// ============================================================================
// FerrumOS - Task Scheduler
// ============================================================================
// Phase 2 of the v0.2 completion roadmap.
//
// Provides a priority-aware, preemptive-capable task scheduler with
// per-task `TaskContext` save/restore. The timer interrupt (`tick`)
// wakes sleeping tasks and (optionally) decrements a per-task time
// slice. The actual cross-task context switch is driven by the
// syscall layer (`sys_yield`, `sys_sleep`, `sys_exit`) so the
// existing one-way `ring3` path keeps its microsecond-fast
// straight-line user code uninterrupted.
//
// Layout
// ------
// - `Task` is the scheduler's bookkeeping record (id, priority,
//   state, ticks, capabilities, time slice, sleep deadline).
// - `TaskContext` is the raw register + iretq-frame image the
//   context-switch assembly uses. It is `#[repr(C)]` so the asm
//   offsets stay stable.
// - `TASKS` holds every `Task` plus a parallel `Vec<TaskContext>`
//   indexed by the same slot. A `current_pid: AtomicU64` points
//   at the slot the CPU is executing (0 = kernel main context).
// - `RUN_QUEUES[priority]` holds the ready pids per priority.
// - `SLEEPERS` is a sorted wake-tick queue.
//
// The kernel main context (the shell) is *not* a `Task`; pid 0 is
// a sentinel that means "kernel main context, do not schedule
// anything else, just return to the syscall handler".
// ============================================================================

extern crate alloc;

use alloc::collections::VecDeque;
use alloc::string::String;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use spin::Mutex;
use x86_64::VirtAddr;

// ============================================================================
// Task State Machine
// ============================================================================

/// Task execution state
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskState {
    /// Ready to be scheduled
    Ready,
    /// Currently executing on a CPU
    Running,
    /// Blocked waiting for a resource
    Blocked,
    /// Terminated - awaiting cleanup
    Dead,
}

/// Task priority levels
///
/// Higher-priority tasks preempt lower-priority ones. The
/// scheduler walks `RUN_QUEUES` from `System` (highest) to `Idle`
/// (lowest) and always picks the head of the first non-empty
/// queue. The kernel main context (pid 0) is implicit priority
/// `System` and is not in the queues.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    Idle = 0,
    Normal = 1,
    High = 2,
    System = 3,
}

impl Priority {
    /// Number of priority levels (used to size `RUN_QUEUES`).
    pub const COUNT: usize = 4;

    /// Index of this priority inside `RUN_QUEUES`.
    pub fn index(self) -> usize {
        self as usize
    }
}

// ============================================================================
// TaskContext
// ============================================================================

/// Raw register + iretq-frame image. The layout matches the
/// offsets used by the inline-asm context switch:
///
/// ```text
///   offset  register / iretq field
///   0x00    r15
///   0x08    r14
///   0x10    r13
///   0x18    r12
///   0x20    r11
///   0x28    r10
///   0x30    r9
///   0x38    r8
///   0x40    rbp
///   0x48    rdi
///   0x50    rsi
///   0x58    rdx
///   0x60    rcx
///   0x68    rbx
///   0x70    rax
///   0x78    rip
///   0x80    cs
///   0x88    rflags
///   0x90    rsp
///   0x98    ss
/// ```
#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct TaskContext {
    pub r15: u64,
    pub r14: u64,
    pub r13: u64,
    pub r12: u64,
    pub r11: u64,
    pub r10: u64,
    pub r9: u64,
    pub r8: u64,
    pub rbp: u64,
    pub rdi: u64,
    pub rsi: u64,
    pub rdx: u64,
    pub rcx: u64,
    pub rbx: u64,
    pub rax: u64,
    /// iretq frame - RIP the CPU will resume at.
    pub rip: u64,
    /// iretq frame - CS (0x08 ring 0, 0x1B ring 3).
    pub cs: u64,
    /// iretq frame - RFLAGS (0x3202 for user with IOPL=3).
    pub rflags: u64,
    /// iretq frame - RSP the CPU will resume at.
    pub rsp: u64,
    /// iretq frame - SS (0x10 ring 0, 0x23 ring 3).
    pub ss: u64,
}

impl TaskContext {
    pub const fn new() -> Self {
        TaskContext {
            r15: 0, r14: 0, r13: 0, r12: 0, r11: 0, r10: 0, r9: 0, r8: 0,
            rbp: 0, rdi: 0, rsi: 0, rdx: 0, rcx: 0, rbx: 0, rax: 0,
            rip: 0, cs: 0, rflags: 0x3202, rsp: 0, ss: 0,
        }
    }

    /// Fill a fresh ring-3 iretq frame (CS=0x1B, SS=0x23, RFLAGS=0x3202).
    pub fn ring3(rip: u64, rsp: u64) -> Self {
        TaskContext {
            r15: 0, r14: 0, r13: 0, r12: 0, r11: 0, r10: 0, r9: 0, r8: 0,
            rbp: 0, rdi: 0, rsi: 0, rdx: 0, rcx: 0, rbx: 0, rax: 0,
            rip,
            cs: crate::gdt::USER_CODE_SELECTOR,
            rflags: 0x3202,
            rsp,
            ss: crate::gdt::USER_DATA_SELECTOR,
        }
    }
}


// ============================================================================
// Task
// ============================================================================

/// Quota tracking for a task.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TaskQuotas {
    pub max_memory_pages: u64,
    pub max_cpu_ticks_continuous: u64,
    pub used_cpu_ticks_continuous: u64,
    pub max_syscalls_per_window: u64,
    pub syscalls_in_window: u64,
    pub syscall_window_start: u64,
}

impl TaskQuotas {
    pub const fn unlimited() -> Self {
        Self {
            max_memory_pages: u64::MAX,
            max_cpu_ticks_continuous: u64::MAX,
            used_cpu_ticks_continuous: 0,
            max_syscalls_per_window: u64::MAX,
            syscalls_in_window: 0,
            syscall_window_start: 0,
        }
    }

    pub const fn default_user() -> Self {
        Self {
            max_memory_pages: 2048, // 8 MiB
            max_cpu_ticks_continuous: 100, // ~5.5 seconds of uninterrupted execution
            used_cpu_ticks_continuous: 0,
            max_syscalls_per_window: 100, // 100 syscalls per window
            syscalls_in_window: 0,
            syscall_window_start: 0,
        }
    }
}

/// A schedulable task in the kernel.
///
/// Each `Task` lives in `TASKS` and is referenced by its `pid`
/// (which is also its index into the parallel `TASK_CONTEXTS`
/// vector). Kernel-thread pids start at 100 to leave room for
/// the user process pids (which start at 1 and are assigned by
/// the process registry).
#[derive(Debug, Clone)]
pub struct Task {
    pub id: u64,
    pub name: String,
    pub state: TaskState,
    pub priority: Priority,
    pub ticks: u64,
    pub capabilities: Vec<String>,
    pub quotas: TaskQuotas,
    /// Time slice remaining in PIT ticks. Reset to
    /// `TIME_SLICE_TICKS` every time the task is picked from a
    /// run-queue. When it reaches 0 the task is preemptible.
    pub time_remaining: u64,
    /// Absolute PIT tick at which a `sys_sleep` task should be
    /// woken. `u64::MAX` means "not sleeping".
    pub wake_at: u64,
    /// Top of this task's kernel stack. The context switch sets
    /// TSS.RSP0 to this value before iretq so the next
    /// ring-0 entry from this task lands on its own stack.
    pub kernel_stack_top: u64,
    /// CR3 (L4 frame physical address) for this task's address
    /// space. The context switch loads this into CR3 before
    /// iretq. The kernel main context keeps the bootloader's
    /// active L4.
    pub cr3: u64,
    pub parent_id: Option<u64>,
    pub waiting_on_pid: Option<u64>,
    pub cpu_affinity: Option<u32>,
}

impl Task {
    pub fn new(name: String, priority: Priority) -> Self {
        // Bookkeeping/kernel-thread tasks start at id 100 so they never
        // collide with user-process pids, which come from the process
        // registry and start at 1. `register_user` builds its Task with
        // `id: pid` directly (bypassing this counter), so a user task always
        // carries its real pid; without the offset, the "kernel"/"shell"
        // stubs created at scheduler init would also claim ids 1 and 2 and
        // shadow the first user processes in every `find(|t| t.id == pid)`.
        static NEXT_ID: AtomicU64 = AtomicU64::new(100);
        Task {
            id: NEXT_ID.fetch_add(1, Ordering::SeqCst),
            name,
            state: TaskState::Ready,
            priority,
            ticks: 0,
            capabilities: Vec::new(),
            quotas: TaskQuotas::unlimited(),
            time_remaining: TIME_SLICE_TICKS,
            wake_at: u64::MAX,
            kernel_stack_top: 0,
            cr3: 0,
            parent_id: None,
            waiting_on_pid: None,
            cpu_affinity: None,
        }
    }
}

/// Default time slice in PIT ticks (~18.2 Hz). 18 ticks is just
/// Default time slice in PIT ticks (~18.2 Hz). 5 ticks is just
/// over 250ms; long enough for basic work, short enough for
/// interactive preemption.
pub const TIME_SLICE_TICKS: u64 = 5;


// ============================================================================
// Scheduler state
// ============================================================================

/// One entry per priority level. `RUN_QUEUES[0]` is `Idle`,
/// `RUN_QUEUES[3]` is `System`. Tasks of the same priority
/// are round-robined within their queue.
type RunQueues = [VecDeque<u64>; Priority::COUNT];

struct Scheduler {
    /// Every `Task` in the system, including dead ones until
    /// `cleanup_dead_tasks` reaps them.
    tasks: Vec<Task>,
    /// Parallel to `tasks`: the saved register context for each
    /// task. Dead tasks' contexts are stale.
    contexts: Vec<TaskContext>,
    /// Pids that are ready to run, bucketed by priority.
    run_queues: RunQueues,
    /// Total PIT ticks since boot.
    total_ticks: u64,
    /// Whether `init` has run.
    initialized: bool,
}

impl Scheduler {
    const fn new() -> Self {
        // `VecDeque::new` is const since Rust 1.61.
        Scheduler {
            tasks: Vec::new(),
            contexts: Vec::new(),
            run_queues: [
                VecDeque::new(), // Idle
                VecDeque::new(), // Normal
                VecDeque::new(), // High
                VecDeque::new(), // System
            ],
            total_ticks: 0,
            initialized: false,
        }
    }
}

static SCHEDULER: Mutex<Scheduler> = Mutex::new(Scheduler::new());

static SCHEDULER_INIT: AtomicBool = AtomicBool::new(false);

/// Pid of the task currently executing on the CPU. 0 means
/// "kernel main context" (the shell). Set by the context switch
/// asm, read by the syscall layer and `tick`.
pub static CURRENT_PID: AtomicU64 = AtomicU64::new(0);

// ============================================================================
// Public API
// ============================================================================

/// Initialize the scheduler. Creates two bookkeeping tasks
/// (`kernel` and `shell`) at `System` and `High` priority. They
/// are never actually scheduled (the kernel main context stays
/// on pid 0); they exist so the sweep's `ps` command and
/// `list_tasks` keep the same surface as Phase 1.
pub fn init() {
    // Capture the boot L4 frame so the idle loop and the kernel return
    // trampoline can restore the kernel address space after the last
    // user process dies (at that point CR3 holds the dead process's L4).
    let (boot_l4, _) = x86_64::registers::control::Cr3::read();
    BOOT_CR3.store(boot_l4.start_address().as_u64(), Ordering::SeqCst);

    let mut sched = SCHEDULER.lock();
    sched.initialized = true;

    let mut kernel_task = Task::new(String::from("kernel"), Priority::System);
    kernel_task.state = TaskState::Running;
    kernel_task.capabilities.push(String::from("cap:system:all"));
    push_task_locked(&mut sched, kernel_task);

    let mut shell_task = Task::new(String::from("shell"), Priority::High);
    shell_task.state = TaskState::Ready;
    shell_task.capabilities.push(String::from("cap:shell:interactive"));
    push_task_locked(&mut sched, shell_task);

    SCHEDULER_INIT.store(true, Ordering::SeqCst);
}

/// Append a task to the scheduler's `tasks` and `contexts`
/// vectors in lock-step. Caller must hold the `SCHEDULER` lock.
fn push_task_locked(sched: &mut Scheduler, task: Task) -> u64 {
    let id = task.id;
    sched.contexts.push(TaskContext::new());
    sched.tasks.push(task);
    id
}

/// Register a freshly-built user process with the scheduler.
/// Returns the scheduler-assigned task id (which is the same as
/// the process pid for user tasks, but kept as a separate type
/// at the API boundary for clarity).
pub fn register_user(
    pid: u64,
    name: &str,
    priority: Priority,
    kernel_stack_top: VirtAddr,
    cr3: u64,
    capabilities: &[String],
) {
    if !SCHEDULER_INIT.load(Ordering::SeqCst) {
        return;
    }
    let caller_pid = CURRENT_PID.load(Ordering::SeqCst);
    let parent_id = if caller_pid == 0 { None } else { Some(caller_pid) };
    
    let mut sched = SCHEDULER.lock();
    let is_exempt = capabilities.iter().any(|c| c == "cap:quota:exempt");
    let quotas = if is_exempt {
        TaskQuotas::unlimited()
    } else {
        TaskQuotas::default_user()
    };
    
    let mut task = Task {
        id: pid,
        name: String::from(name),
        state: TaskState::Ready,
        priority,
        ticks: 0,
        capabilities: capabilities.to_vec(),
        quotas,
        time_remaining: TIME_SLICE_TICKS,
        wake_at: u64::MAX,
        kernel_stack_top: kernel_stack_top.as_u64(),
        cr3,
        parent_id,
        waiting_on_pid: None,
        cpu_affinity: None,
    };
    if !task.capabilities.contains(&String::from("cap:process:user")) {
        task.capabilities.push(String::from("cap:process:user"));
    }
    let ctx = TaskContext::new();
    sched.contexts.push(ctx);
    sched.tasks.push(task);
    let idx = sched.tasks.len() - 1;
    sched.run_queues[priority.index()].push_back(pid);
    // Mark which index in `tasks`/`contexts` the pid lives at so
    // we can do O(1) lookups without scanning.
    debug_assert_eq!(sched.tasks[idx].id, pid);
}


/// Timer tick. Increments tick counters, wakes any sleepers
/// whose deadline has passed, and decrements the current
/// task's time slice. Does *not* preempt; the syscall layer
/// observes `time_remaining == 0` (or the deadline wake) and
/// triggers the actual context switch.
pub fn tick() {
    if !SCHEDULER_INIT.load(Ordering::SeqCst) {
        return;
    }
    if let Some(mut sched) = SCHEDULER.try_lock() {
        sched.total_ticks = sched.total_ticks.wrapping_add(1);
        let now = sched.total_ticks;

        // First pass: decide which tasks to wake and which
        // ticks/time-slice to update, collecting them in
        // plain `Vec`s so we can re-borrow `sched.run_queues`
        // afterwards without an aliasing violation.
        let mut to_wake: Vec<u64> = Vec::new();
        for task in sched.tasks.iter() {
            if task.state == TaskState::Blocked && task.wake_at <= now {
                to_wake.push(task.id);
            }
        }

        // Second pass: apply the state changes. We touch
        // `run_queues` and `tasks` separately, releasing the
        // mutable borrow on each before acquiring the next.
        for pid in &to_wake {
            if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == *pid) {
                task.state = TaskState::Ready;
                task.wake_at = u64::MAX;
                task.time_remaining = TIME_SLICE_TICKS;
            }
            let pri = sched
                .tasks
                .iter()
                .find(|t| t.id == *pid)
                .map(|t| t.priority.index())
                .unwrap_or(0);
            if !sched.run_queues[pri].contains(pid) {
                sched.run_queues[pri].push_back(*pid);
            }
        }

        // Third pass: tick counters and time-slice
        // accounting. Safe because `to_wake` is the only
        // outstanding reference into `sched.tasks`.
        drop(to_wake);
        for task in sched.tasks.iter_mut() {
            if task.state == TaskState::Running || task.state == TaskState::Ready {
                task.ticks = task.ticks.wrapping_add(1);
                if task.state == TaskState::Running {
                    task.quotas.used_cpu_ticks_continuous = task.quotas.used_cpu_ticks_continuous.saturating_add(1);
                    if task.time_remaining > 0 {
                        task.time_remaining -= 1;
                    }
                }
            }
        }
    }
}

/// Put the current task to sleep for `ticks` PIT ticks. Returns
/// true if the task was actually put to sleep (it was running).
pub fn sleep_current(ticks: u64) -> bool {
    let pid = CURRENT_PID.load(Ordering::SeqCst);
    if pid == 0 {
        return false;
    }
    let mut sched = SCHEDULER.lock();
    let now = sched.total_ticks;
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        if task.state == TaskState::Running {
            task.state = TaskState::Blocked;
            task.wake_at = now.saturating_add(ticks);
            task.time_remaining = 0;
            task.quotas.used_cpu_ticks_continuous = 0;
            CURRENT_PID.store(0, Ordering::SeqCst);
            return true;
        }
    }
    false
}

/// Mark the current task as dead. Returns true if a task was
/// actually reaped. The caller is responsible for picking the
/// next task to run (or halting if the run-queues are empty).
pub fn exit_current() -> bool {
    let pid = CURRENT_PID.load(Ordering::SeqCst);
    if pid == 0 {
        return false;
    }
    let mut sched = SCHEDULER.lock();
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        task.state = TaskState::Dead;
        task.time_remaining = 0;
        // Drain from run-queues (it may be there if it yielded
        // and was re-queued; defensive).
        for q in sched.run_queues.iter_mut() {
            q.retain(|p| *p != pid);
        }
        CURRENT_PID.store(0, Ordering::SeqCst);
        return true;
    }
    false
}

/// Get the current local APIC ID using the `cpuid` leaf 1 instruction.
pub fn initial_apic_id() -> u32 {
    let ebx: u32;
    unsafe {
        core::arch::asm!(
            "push rbx",
            "cpuid",
            "mov {ebx_val:e}, ebx",
            "pop rbx",
            ebx_val = out(reg) ebx,
            inout("eax") 1 => _,
            out("ecx") _,
            out("edx") _,
            options(nomem, preserves_flags)
        );
    }
    (ebx >> 24) & 0xFF
}

/// Pick the next runnable pid from the highest-priority
/// non-empty run-queue. Returns `None` if every run-queue is
/// empty.
pub fn schedule_next() -> Option<u64> {
    let mut sched = SCHEDULER.lock();
    let current_apic_id = initial_apic_id();
    for qi in (0..Priority::COUNT).rev() {
        let mut idx = 0;
        while idx < sched.run_queues[qi].len() {
            let pid = sched.run_queues[qi][idx];
            if let Some(task) = sched.tasks.iter().find(|t| t.id == pid) {
                if task.state != TaskState::Ready {
                    // Discard dead/blocked task from the queue
                    sched.run_queues[qi].remove(idx);
                    continue;
                }
                
                // It is Ready. Check CPU affinity
                let affinity_ok = match task.cpu_affinity {
                    None => true,
                    Some(aff) => aff == current_apic_id,
                };
                
                if affinity_ok {
                    // Remove from queue and run it
                    sched.run_queues[qi].remove(idx);
                    
                    // Reset time slice and mark running.
                    if let Some(task_mut) = sched.tasks.iter_mut().find(|t| t.id == pid) {
                        task_mut.state = TaskState::Running;
                        task_mut.time_remaining = TIME_SLICE_TICKS;
                    }
                    
                    drop(sched);
                    CURRENT_PID.store(pid, Ordering::SeqCst);
                    return Some(pid);
                } else {
                    // Task is for another CPU core, leave it in queue
                    idx += 1;
                }
            } else {
                // Task does not exist in the list, discard it
                sched.run_queues[qi].remove(idx);
            }
        }
    }
    None
}

/// Make the current task ready and re-queue it at its
/// priority. Used by `sys_yield`.
pub fn yield_current() -> bool {
    let pid = CURRENT_PID.load(Ordering::SeqCst);
    if pid == 0 {
        return false;
    }
    let mut sched = SCHEDULER.lock();
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        if task.state == TaskState::Running {
            task.state = TaskState::Ready;
            task.time_remaining = TIME_SLICE_TICKS;
            task.quotas.used_cpu_ticks_continuous = 0;
            let pri = task.priority.index();
            if !sched.run_queues[pri].contains(&pid) {
                sched.run_queues[pri].push_back(pid);
            }
            CURRENT_PID.store(0, Ordering::SeqCst);
            return true;
        }
    }
    false
}

/// Look up the saved context for `pid`. Returns `None` if the
/// pid is not registered.
pub fn context_of(pid: u64) -> Option<TaskContext> {
    let sched = SCHEDULER.lock();
    sched
        .tasks
        .iter()
        .position(|t| t.id == pid)
        .map(|idx| sched.contexts[idx])
}

/// Overwrite the saved context for `pid`. Used by the syscall
/// layer to capture the outgoing task's iretq frame before the
/// context switch.
pub fn write_context(pid: u64, ctx: TaskContext) {
    let mut sched = SCHEDULER.lock();
    if let Some(idx) = sched.tasks.iter().position(|t| t.id == pid) {
        sched.contexts[idx] = ctx;
    }
}

/// Return the kernel stack top and CR3 for `pid`. Used by the
/// context switch to set TSS.RSP0 and CR3.
pub fn switch_target(pid: u64) -> Option<(u64, u64)> {
    let sched = SCHEDULER.lock();
    sched
        .tasks
        .iter()
        .find(|t| t.id == pid)
        .map(|t| (t.kernel_stack_top, t.cr3))
}

/// Spawn a new (kernel-side bookkeeping) task. This is the
/// Phase 1 surface kept for backward compat with `ps`/`spawn`.
pub fn spawn(name: String, priority: Priority) -> u64 {
    spawn_internal(name, priority, Vec::new())
}

pub fn spawn_with_capabilities(
    name: String,
    priority: Priority,
    capabilities: &[String],
) -> Result<u64, String> {
    for capability in capabilities {
        if !crate::security::can_delegate(capability) {
            return Err(alloc::format!("capability is not delegatable: {}", capability));
        }
    }
    Ok(spawn_internal(name, priority, capabilities.to_vec()))
}

fn spawn_internal(name: String, priority: Priority, capabilities: Vec<String>) -> u64 {
    let id = {
        let mut sched = SCHEDULER.lock();
        let mut task = Task::new(name, priority);
        task.capabilities = capabilities;
        let id = task.id;
        push_task_locked(&mut sched, task);
        id
    };

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ProcessSpawned,
        "Task spawned",
    );
    id
}

pub fn kill(id: u64) -> bool {
    let killed = {
        let mut sched = SCHEDULER.lock();
        let mut killed = false;
        for task in sched.tasks.iter_mut() {
            if task.id == id {
                task.state = TaskState::Dead;
                task.time_remaining = 0;
                killed = true;
                break;
            }
        }
        if killed {
            // Drain the pid from every run-queue so schedule_next
            // can never hand the CPU to a dead task.
            for q in sched.run_queues.iter_mut() {
                q.retain(|p| *p != id);
            }
        }
        killed
    };

    if killed {
        record_exit(id, 137); // 128 + SIGKILL, by convention
        if CURRENT_PID.load(Ordering::SeqCst) == id {
            CURRENT_PID.store(0, Ordering::SeqCst);
        }
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::ProcessKilled,
            "Task marked dead",
        );
    }

    killed
}

pub fn list_tasks() -> Vec<Task> {
    let sched = SCHEDULER.lock();
    sched.tasks.iter().cloned().collect()
}

/// Capability strings held by the task `pid`, if it exists.
pub fn capabilities_of(pid: u64) -> Option<Vec<String>> {
    let sched = SCHEDULER.lock();
    sched
        .tasks
        .iter()
        .find(|t| t.id == pid)
        .map(|t| t.capabilities.clone())
}

pub fn total_ticks() -> u64 {
    let sched = SCHEDULER.lock();
    sched.total_ticks
}

pub fn active_task_count() -> usize {
    let sched = SCHEDULER.lock();
    sched.tasks.iter().filter(|t| t.state != TaskState::Dead).count()
}

/// Pids of every task currently in the `Dead` state. Used by the
/// process reaper to know which address spaces to free.
pub fn dead_pids() -> Vec<u64> {
    let sched = SCHEDULER.lock();
    sched
        .tasks
        .iter()
        .filter(|t| t.state == TaskState::Dead)
        .map(|t| t.id)
        .collect()
}

pub fn cleanup_dead_tasks() {
    let mut sched = SCHEDULER.lock();
    // Walk both vectors in lock-step and drop dead entries.
    let mut i = 0;
    while i < sched.tasks.len() {
        if sched.tasks[i].state == TaskState::Dead {
            sched.tasks.remove(i);
            sched.contexts.remove(i);
        } else {
            i += 1;
        }
    }
}

// ============================================================================
// Context switch
// ============================================================================

/// Save the *outgoing* task's callee-saved registers into the
/// `TaskContext` whose address is in `rdi`, then load the
/// *incoming* task's callee-saved registers and iretq frame
/// from the `TaskContext` whose address is in `rsi`, and
/// iretq into it. The stack pointer for the incoming task is
/// taken from `rdx` (top of the incoming task's kernel stack).
///
/// This is the only piece of Phase 2 that touches raw
/// registers. It is `noreturn` — it pops the saved frame and
/// jumps to the new task, never returning to the Rust caller.
///
/// # Safety
///
/// Must be called from a context where the CPU is allowed to
/// iretq to the new task's frame (i.e. from the syscall
/// interrupt handler, with interrupts enabled). The caller
/// must have already updated TSS.RSP0 and CR3 for the
/// incoming task. `_out_ctx` must be a valid, non-null
/// pointer to a writable `TaskContext` (it is written to
/// even if the caller does not intend to resume the outgoing
/// task — the write is cheap and keeps the asm branch-free).
#[unsafe(naked)]
pub unsafe extern "C" fn context_switch_to(
    _out_ctx: *mut TaskContext,
    _in_ctx: *const TaskContext,
    _in_kernel_stack_top: u64,
) -> ! {
    // Register usage on entry (set by the Rust ABI for
    // `extern "C" fn`):
    //   rdi = _out_ctx
    //   rsi = _in_ctx
    //   rdx = _in_kernel_stack_top
    core::arch::naked_asm!(
        // Save the outgoing task's GPRs.
        "mov [rdi + 0x00], r15",
        "mov [rdi + 0x08], r14",
        "mov [rdi + 0x10], r13",
        "mov [rdi + 0x18], r12",
        "mov [rdi + 0x20], r11",
        "mov [rdi + 0x28], r10",
        "mov [rdi + 0x30], r9",
        "mov [rdi + 0x38], r8",
        "mov [rdi + 0x40], rbp",
        "mov [rdi + 0x48], rdi",
        "mov [rdi + 0x50], rsi",
        "mov [rdi + 0x58], rdx",
        "mov [rdi + 0x60], rcx",
        "mov [rdi + 0x68], rbx",
        "mov [rdi + 0x70], rax",
        
        // Switch to the incoming task's kernel stack.
        "mov rsp, rdx",
        
        // Push the incoming task's iretq frame on the new stack:
        //   RIP, CS, RFLAGS, RSP, SS
        "sub rsp, 0x28",
        "mov rax, [rsi + 0x78]",   // RIP
        "mov [rsp + 0x00], rax",
        "mov rax, [rsi + 0x80]",   // CS
        "mov [rsp + 0x08], rax",
        "mov rax, [rsi + 0x88]",   // RFLAGS
        "mov [rsp + 0x10], rax",
        "mov rax, [rsi + 0x90]",   // RSP
        "mov [rsp + 0x18], rax",
        "mov rax, [rsi + 0x98]",   // SS
        "mov [rsp + 0x20], rax",
        
        // Load the incoming task's GPRs.
        // We load rsi last to preserve the base pointer.
        "mov r15, [rsi + 0x00]",
        "mov r14, [rsi + 0x08]",
        "mov r13, [rsi + 0x10]",
        "mov r12, [rsi + 0x18]",
        "mov r11, [rsi + 0x20]",
        "mov r10, [rsi + 0x28]",
        "mov r9,  [rsi + 0x30]",
        "mov r8,  [rsi + 0x38]",
        "mov rbp, [rsi + 0x40]",
        "mov rbx, [rsi + 0x68]",
        "mov rcx, [rsi + 0x60]",
        "mov rdx, [rsi + 0x58]",
        "mov rdi, [rsi + 0x48]",
        "mov rax, [rsi + 0x70]",
        "mov rsi, [rsi + 0x50]",
        
        "iretq",
    );
}


/// A process-wide scratch `TaskContext` used by the syscall
/// layer as the "outgoing" slot for `context_switch_to` when
/// the outgoing task is being reaped or re-queued and will
/// never be resumed. Lazily allocated on first use.
pub fn scratch_context() -> &'static mut TaskContext {
    use core::sync::atomic::{AtomicU64, Ordering};
    static SCRATCH: AtomicU64 = AtomicU64::new(0);
    let addr = SCRATCH.load(Ordering::SeqCst);
    if addr == 0 {
        let boxed: alloc::boxed::Box<TaskContext> =
            alloc::boxed::Box::new(TaskContext::new());
        let raw = alloc::boxed::Box::into_raw(boxed) as u64;
        SCRATCH.store(raw, Ordering::SeqCst);
        unsafe { &mut *(raw as *mut TaskContext) }
    } else {
        unsafe { &mut *(addr as *mut TaskContext) }
    }
}

// ============================================================================
// Exit status tracking
// ============================================================================

/// Physical address of the boot L4 frame, captured by `init()`.
/// The idle loop and the kernel return trampoline switch back to
/// this CR3 because the CR3 they are entered on may belong to a
/// process that is about to be reaped.
pub static BOOT_CR3: AtomicU64 = AtomicU64::new(0);

/// Exit codes of finished tasks, kept until `sys_waitpid` or the
/// reaper consumes them. Entries are (pid, parent_pid, code).
static EXIT_CODES: Mutex<Vec<(u64, u64, u32)>> = Mutex::new(Vec::new());

/// Packed (pid << 32 | code) of the most recent exit, displayed by
/// the kernel return trampoline. `u64::MAX` means "none pending".
static LAST_EXIT: AtomicU64 = AtomicU64::new(u64::MAX);

/// Record that `pid` finished with `code`. Idempotent per pid.
pub fn record_exit(pid: u64, code: u32) {
    let parent_id = {
        let sched = SCHEDULER.lock();
        sched.tasks.iter().find(|t| t.id == pid).and_then(|t| t.parent_id).unwrap_or(0)
    };
    
    let mut codes = EXIT_CODES.lock();
    if !codes.iter().any(|(p, _, _)| *p == pid) {
        if codes.len() >= 128 {
            codes.remove(0);
        }
        codes.push((pid, parent_id, code));
    }
    LAST_EXIT.store((pid << 32) | code as u64, Ordering::SeqCst);

    // Wake waiting parent if active
    wake_waiting_parent(pid, parent_id, code);
}

fn wake_waiting_parent(child_pid: u64, parent_pid: u64, code: u32) {
    if parent_pid == 0 {
        return;
    }
    let mut sched = SCHEDULER.lock();
    let mut parent_idx = None;
    for (idx, task) in sched.tasks.iter().enumerate() {
        if task.id == parent_pid && task.state == TaskState::Blocked {
            if task.waiting_on_pid == Some(child_pid) || task.waiting_on_pid == Some(u64::MAX) {
                parent_idx = Some(idx);
                break;
            }
        }
    }
    
    if let Some(idx) = parent_idx {
        sched.tasks[idx].state = TaskState::Ready;
        sched.tasks[idx].waiting_on_pid = None;
        sched.contexts[idx].rax = code as u64;

        let pri = sched.tasks[idx].priority.index();
        let pid = sched.tasks[idx].id;
        if !sched.run_queues[pri].contains(&pid) {
            sched.run_queues[pri].push_back(pid);
        }
    }
}

/// Exit code of `pid` if it has finished.
pub fn exit_status(pid: u64) -> Option<u32> {
    EXIT_CODES
        .lock()
        .iter()
        .find(|(p, _, _)| *p == pid)
        .map(|(_, _, c)| *c)
}

/// Exit status of any finished task, consuming the record.
pub fn take_any_exit_status() -> Option<(u64, u32)> {
    EXIT_CODES.lock().pop().map(|(pid, _, code)| (pid, code))
}

pub fn waitpid_current(target: u64) -> Result<Option<u32>, crate::syscall::SyscallStatus> {
    let current_pid = CURRENT_PID.load(Ordering::SeqCst);
    if current_pid == 0 {
        return Err(crate::syscall::SyscallStatus::InvalidArgument);
    }
    
    let mut codes = EXIT_CODES.lock();
    if target == u64::MAX {
        let found_idx = codes.iter().position(|(_, parent, _)| *parent == current_pid);
        if let Some(idx) = found_idx {
            let (pid, _, code) = codes.remove(idx);
            drop(codes);
            crate::process::drop_by_pid(pid);
            cleanup_dead_tasks();
            return Ok(Some(code));
        }
    } else {
        let found_idx = codes.iter().position(|(pid, parent, _)| *pid == target && *parent == current_pid);
        if let Some(idx) = found_idx {
            let (pid, _, code) = codes.remove(idx);
            drop(codes);
            crate::process::drop_by_pid(pid);
            cleanup_dead_tasks();
            return Ok(Some(code));
        }
    }
    drop(codes);
    
    // Not exited yet. Check if target is alive as a child of current_pid
    let mut sched = SCHEDULER.lock();
    let has_children = if target == u64::MAX {
        sched.tasks.iter().any(|t| t.parent_id == Some(current_pid) && t.state != TaskState::Dead)
    } else {
        sched.tasks.iter().any(|t| t.id == target && t.parent_id == Some(current_pid) && t.state != TaskState::Dead)
    };
    
    if !has_children {
        return Err(crate::syscall::SyscallStatus::InvalidArgument);
    }
    
    // Still running, block caller
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == current_pid) {
        task.state = TaskState::Blocked;
        task.waiting_on_pid = Some(target);
        task.time_remaining = 0;
    }
    
    // Remove from run queues
    for q in sched.run_queues.iter_mut() {
        q.retain(|p| *p != current_pid);
    }
    
    CURRENT_PID.store(0, Ordering::SeqCst);
    Ok(None)
}

/// Take the most recent exit (pid, code) for display, clearing it.
pub fn take_last_exit() -> Option<(u64, u32)> {
    let packed = LAST_EXIT.swap(u64::MAX, Ordering::SeqCst);
    if packed == u64::MAX {
        return None;
    }
    Some((packed >> 32, (packed & 0xFFFF_FFFF) as u32))
}

/// True if any task is Blocked (sleeping). Used by the exit path to
/// decide between idling (a sleeper will wake) and returning to the
/// shell (nothing left to run).
pub fn has_blocked_tasks() -> bool {
    let sched = SCHEDULER.lock();
    sched.tasks.iter().any(|t| t.state == TaskState::Blocked)
}

/// True if the running task `pid` has exhausted its time slice and
/// should be preempted at the next syscall boundary.
pub fn should_preempt(pid: u64) -> bool {
    let sched = SCHEDULER.lock();
    sched
        .tasks
        .iter()
        .find(|t| t.id == pid)
        .map(|t| t.state == TaskState::Running && t.time_remaining == 0)
        .unwrap_or(false)
}

/// Claim the CPU for `pid` outside the normal `schedule_next` path
/// (used by the one-way `ring3` dispatch). Drains the pid from the
/// run-queues so a later `schedule_next` cannot re-enter the task
/// through its stale seeded context while it is already running.
pub fn claim_for_run(pid: u64) {
    let mut sched = SCHEDULER.lock();
    for q in sched.run_queues.iter_mut() {
        q.retain(|p| *p != pid);
    }
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        task.state = TaskState::Running;
        task.time_remaining = TIME_SLICE_TICKS;
    }
    drop(sched);
    CURRENT_PID.store(pid, Ordering::SeqCst);
}

// ============================================================================
// Kernel-side execution targets: resume, idle, return-to-shell
// ============================================================================

const KERNEL_TASK_STACK_SIZE: usize = 32 * 1024;

#[repr(C, align(16))]
struct KernelTaskStack([u8; KERNEL_TASK_STACK_SIZE]);

/// Stack for the idle loop that runs while every task is sleeping.
static mut IDLE_STACK: KernelTaskStack = KernelTaskStack([0; KERNEL_TASK_STACK_SIZE]);

/// Stack for the return-to-shell trampoline that runs after the last
/// user task exits.
static mut RETURN_STACK: KernelTaskStack = KernelTaskStack([0; KERNEL_TASK_STACK_SIZE]);

/// Stable slot for the *incoming* context of `context_switch_to`.
/// Must not alias the scratch (outgoing) slot: the switch asm writes
/// the outgoing registers before it reads the incoming ones, so using
/// one slot for both would corrupt the incoming image.
static mut RESUME_SLOT: TaskContext = TaskContext::new();

fn kernel_stack_top(stack: *mut KernelTaskStack) -> u64 {
    ((stack as u64) + KERNEL_TASK_STACK_SIZE as u64) & !0xF
}

unsafe fn load_cr3(phys: u64) {
    use x86_64::registers::control::Cr3;
    use x86_64::structures::paging::PhysFrame;
    use x86_64::PhysAddr;
    let (_, flags) = Cr3::read();
    let frame = PhysFrame::containing_address(PhysAddr::new(phys));
    Cr3::write(frame, flags);
}

/// Switch the CPU to the saved context of `pid` (which must already
/// be marked Running by `schedule_next`). Sets TSS.RSP0 and CR3 for
/// the target, then performs the iretq switch. Never returns.
///
/// # Safety
/// Must be called with interrupts disabled, from a context that will
/// never be resumed (the caller's stack frame is abandoned).
pub unsafe fn resume_task(pid: u64) -> ! {
    let (kstack, cr3) = switch_target(pid).expect("resume_task: pid not registered");
    let ctx = context_of(pid).expect("resume_task: pid has no saved context");
    crate::gdt::set_kernel_stack(VirtAddr::new(kstack));
    if cr3 != 0 {
        load_cr3(cr3);
    }
    let slot = &raw mut RESUME_SLOT;
    *slot = ctx;
    context_switch_to(scratch_context() as *mut TaskContext, slot, kstack);
}

/// Switch to a fresh ring-0 execution context running `entry` on the
/// given stack, on the boot CR3. Never returns.
unsafe fn switch_to_kernel_entry(entry: extern "C" fn() -> !, stack: *mut KernelTaskStack) -> ! {
    let top = kernel_stack_top(stack);
    let boot_cr3 = BOOT_CR3.load(Ordering::SeqCst);
    if boot_cr3 != 0 {
        load_cr3(boot_cr3);
    }
    crate::gdt::set_kernel_stack(VirtAddr::new(top));
    let slot = &raw mut RESUME_SLOT;
    *slot = TaskContext {
        r15: 0,
        r14: 0,
        r13: 0,
        r12: 0,
        r11: 0,
        r10: 0,
        r9: 0,
        r8: 0,
        rbp: 0,
        rdi: 0,
        rsi: 0,
        rdx: 0,
        rcx: 0,
        rbx: 0,
        rax: 0,
        rip: entry as u64,
        cs: crate::gdt::KERNEL_CODE_SELECTOR,
        rflags: 0x202, // IF=1
        // Mimic post-`call` alignment (rsp % 16 == 8 at fn entry).
        rsp: top - 8,
        ss: crate::gdt::KERNEL_DATA_SELECTOR,
    };
    context_switch_to(scratch_context() as *mut TaskContext, slot, top);
}

/// Park the CPU until a sleeping task wakes. Never returns to the
/// caller; control continues in `idle_entry`.
///
/// # Safety
/// The caller's stack frame is abandoned.
pub unsafe fn enter_idle() -> ! {
    switch_to_kernel_entry(idle_entry, &raw mut IDLE_STACK);
}

/// Hand the CPU back to the shell after the last user task exits.
/// Never returns to the caller; control continues in
/// `kernel_return_entry`.
///
/// # Safety
/// The caller's stack frame is abandoned.
pub unsafe fn enter_kernel_return() -> ! {
    switch_to_kernel_entry(kernel_return_entry, &raw mut RETURN_STACK);
}

/// Idle loop: halt until an interrupt fires, then try to schedule.
/// The PIT tick moves sleeping tasks back to Ready, at which point
/// `schedule_next` finds them and we switch in. If every task dies
/// while we idle (e.g. killed from a fault handler), fall through to
/// the shell trampoline.
extern "C" fn idle_entry() -> ! {
    CURRENT_PID.store(0, Ordering::SeqCst);
    loop {
        x86_64::instructions::interrupts::enable_and_hlt();
        x86_64::instructions::interrupts::disable();
        if let Some(next) = schedule_next() {
            unsafe { resume_task(next) }
        }
        if !has_blocked_tasks() {
            kernel_return_entry();
        }
    }
}

/// Return-to-shell trampoline: reap whatever died, report the exit,
/// and drop into a fresh shell prompt. The original boot-time shell
/// stack frame (abandoned when `ring3` dispatched one-way into user
/// space) is never resumed; this is a fresh re-entry.
extern "C" fn kernel_return_entry() -> ! {
    CURRENT_PID.store(0, Ordering::SeqCst);
    crate::process::reap_dead();
    if let Some((pid, code)) = take_last_exit() {
        crate::println!();
        crate::println!("[kernel] user process {} exited (code {})", pid, code);
    }
    x86_64::instructions::interrupts::enable();
    crate::shell::run()
}

/// Check if the running task has exceeded its CPU continuous execution quota.
/// If it has, mark it as dead, and return true (so it can be context switched away).
pub fn check_and_enforce_quotas(pid: u64) -> bool {
    let mut sched = SCHEDULER.lock();
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        if task.state == TaskState::Running {
            let continuous_exceeded = task.quotas.used_cpu_ticks_continuous > task.quotas.max_cpu_ticks_continuous;
            if continuous_exceeded {
                task.state = TaskState::Dead;
                task.time_remaining = 0;
                CURRENT_PID.store(0, Ordering::SeqCst);
                // Also remove it from run queues
                for q in sched.run_queues.iter_mut() {
                    q.retain(|p| *p != pid);
                }
                drop(sched);
                record_exit(pid, 140); // Exit code 140 for quota exceeded
                crate::logging::audit::log_event(
                    crate::logging::audit::AuditEvent::ProcessKilled,
                    "Task killed: continuous CPU quota exceeded",
                );
                return true;
            }
        }
    }
    false
}

