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
///   0x20    rbp
///   0x28    rbx
///   0x30    rip
///   0x38    cs
///   0x40    rflags
///   0x48    rsp
///   0x50    ss
/// ```
///
/// The caller-saved registers (rax, rcx, rdx, rsi, rdi, r8-r11)
/// are saved into the *old* context by the syscall handler before
/// the switch and are not loaded by the switch itself (the switch
/// target re-reads them on its next return-to-user). Keeping them
/// out of the struct keeps the hot path small and the asm simple.
#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct TaskContext {
    pub r15: u64,
    pub r14: u64,
    pub r13: u64,
    pub r12: u64,
    pub rbp: u64,
    pub rbx: u64,
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
            r15: 0, r14: 0, r13: 0, r12: 0, rbp: 0, rbx: 0,
            rip: 0, cs: 0, rflags: 0x3202, rsp: 0, ss: 0,
        }
    }

    /// Fill a fresh ring-3 iretq frame (CS=0x1B, SS=0x23, RFLAGS=0x3202).
    pub fn ring3(rip: u64, rsp: u64) -> Self {
        TaskContext {
            r15: 0, r14: 0, r13: 0, r12: 0, rbp: 0, rbx: 0,
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
}

impl Task {
    pub fn new(name: String, priority: Priority) -> Self {
        static NEXT_ID: AtomicU64 = AtomicU64::new(1);
        Task {
            id: NEXT_ID.fetch_add(1, Ordering::SeqCst),
            name,
            state: TaskState::Ready,
            priority,
            ticks: 0,
            capabilities: Vec::new(),
            time_remaining: TIME_SLICE_TICKS,
            wake_at: u64::MAX,
            kernel_stack_top: 0,
            cr3: 0,
        }
    }
}

/// Default time slice in PIT ticks (~18.2 Hz). 18 ticks is just
/// under one second; long enough that the straight-line
/// `ring3 init` user code prints "ABC" long before the slice
/// can expire, short enough that a misbehaving loop is still
/// preempted within a second.
pub const TIME_SLICE_TICKS: u64 = 18;

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
) {
    if !SCHEDULER_INIT.load(Ordering::SeqCst) {
        return;
    }
    let mut sched = SCHEDULER.lock();
    let mut task = Task {
        id: pid,
        name: String::from(name),
        state: TaskState::Ready,
        priority,
        ticks: 0,
        capabilities: Vec::new(),
        time_remaining: TIME_SLICE_TICKS,
        wake_at: u64::MAX,
        kernel_stack_top: kernel_stack_top.as_u64(),
        cr3,
    };
    task.capabilities.push(String::from("cap:process:user"));
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
                if task.state == TaskState::Running && task.time_remaining > 0 {
                    task.time_remaining -= 1;
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

/// Pick the next runnable pid from the highest-priority
/// non-empty run-queue. Returns `None` if every run-queue is
/// empty.
pub fn schedule_next() -> Option<u64> {
    let mut sched = SCHEDULER.lock();
    for q in sched.run_queues.iter_mut().rev() {
        if let Some(pid) = q.pop_front() {
            // Reset time slice and mark running.
            if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
                task.state = TaskState::Running;
                task.time_remaining = TIME_SLICE_TICKS;
            }
            // Drop the lock before touching CURRENT_PID.
            drop(sched);
            CURRENT_PID.store(pid, Ordering::SeqCst);
            return Some(pid);
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
                killed = true;
                break;
            }
        }
        killed
    };

    if killed {
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

pub fn total_ticks() -> u64 {
    let sched = SCHEDULER.lock();
    sched.total_ticks
}

pub fn active_task_count() -> usize {
    let sched = SCHEDULER.lock();
    sched.tasks.iter().filter(|t| t.state != TaskState::Dead).count()
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
        // Save the outgoing task's callee-saved GPRs.
        "mov [rdi + 0x00], r15",
        "mov [rdi + 0x08], r14",
        "mov [rdi + 0x10], r13",
        "mov [rdi + 0x18], r12",
        "mov [rdi + 0x20], rbp",
        "mov [rdi + 0x28], rbx",
        // Switch to the incoming task's kernel stack.
        "mov rsp, rdx",
        // Push the incoming task's iretq frame on the new
        // stack in the order iretq expects (low→high):
        //   RIP, CS, RFLAGS, RSP, SS
        "sub rsp, 0x28",
        "mov rax, [rsi + 0x30]",   // RIP
        "mov [rsp + 0x00], rax",
        "mov rax, [rsi + 0x38]",   // CS
        "mov [rsp + 0x08], rax",
        "mov rax, [rsi + 0x40]",   // RFLAGS
        "mov [rsp + 0x10], rax",
        "mov rax, [rsi + 0x48]",   // RSP
        "mov [rsp + 0x18], rax",
        "mov rax, [rsi + 0x50]",   // SS
        "mov [rsp + 0x20], rax",
        // Load the incoming task's callee-saved GPRs.
        "mov r15, [rsi + 0x00]",
        "mov r14, [rsi + 0x08]",
        "mov r13, [rsi + 0x10]",
        "mov r12, [rsi + 0x18]",
        "mov rbp, [rsi + 0x20]",
        "mov rbx, [rsi + 0x28]",
        // iretq into the incoming task.
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
