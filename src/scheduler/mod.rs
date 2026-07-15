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
    /// Pointer to 16-byte aligned 512-byte buffer for fxsave/fxrstor
    pub simd_state_ptr: u64,
}

impl TaskContext {
    pub const fn new() -> Self {
        TaskContext {
            r15: 0, r14: 0, r13: 0, r12: 0, r11: 0, r10: 0, r9: 0, r8: 0,
            rbp: 0, rdi: 0, rsi: 0, rdx: 0, rcx: 0, rbx: 0, rax: 0,
            rip: 0, cs: 0, rflags: 0x3202, rsp: 0, ss: 0,
            simd_state_ptr: 0,
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
            simd_state_ptr: 0,
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
            // 200-tick window (~11s at the PIT's ~18.2Hz). A normal D1
            // app-window GUI loop (poll_window_input + occasional
            // present + sleep every ~30ms, matching every app built on
            // libferrumgui) makes ~2-3 syscalls per ~0.5-tick iteration,
            // i.e. up to ~1000+ syscalls across one window even at rest -
            // the old value of 100 killed any such app within its first
            // 1-2 seconds of normal operation as "syscall rate quota
            // exceeded", never previously noticed because D3's app tests
            // only interact briefly. Sized with headroom above steady-state
            // polling while still bounding a genuinely pathological
            // syscall-spam loop with no sleep at all.
            max_syscalls_per_window: 5000,
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
    pub blocked_on_confirmation: bool,
    pub confirmation_approved: bool,
    pub confirmation_denied: bool,
    /// True only for `scheduler::init()`'s "kernel" placeholder (pid 100) -
    /// never pushed to any run-queue, never actually dispatched, and its
    /// `state` is set once and never updated again. It still shows up in
    /// `ps`/`users` so those commands have something to say about the
    /// kernel main context, but `cmd_scheduler`'s aggregate counts exclude
    /// it - otherwise its permanently-frozen `Running` state inflated the
    /// "running" tally by one forever (see `work.md` finding 2.4).
    pub is_bookkeeping_stub: bool,
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
            blocked_on_confirmation: false,
            confirmation_approved: false,
            confirmation_denied: false,
            is_bookkeeping_stub: false,
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

pub(crate) struct Scheduler {
    /// Every `Task` in the system, including dead ones until
    /// `cleanup_dead_tasks` reaps them.
    pub(crate) tasks: Vec<Task>,
    /// Parallel to `tasks`: the saved register context for each
    /// task. Dead tasks' contexts are stale.
    pub(crate) contexts: Vec<TaskContext>,
    /// Pids that are ready to run, bucketed by priority.
    pub(crate) run_queues: RunQueues,
    /// Total PIT ticks since boot.
    pub(crate) total_ticks: u64,
    /// Whether `init` has run.
    pub(crate) initialized: bool,
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

pub(crate) static SCHEDULER: Mutex<Scheduler> = Mutex::new(Scheduler::new());

static SCHEDULER_INIT: AtomicBool = AtomicBool::new(false);

/// Pid of the task currently executing on the CPU. 0 means
/// "kernel main context" (the shell). Set by the context switch
/// asm, read by the syscall layer and `tick`.
pub static CURRENT_PID: AtomicU64 = AtomicU64::new(0);

/// Pid of a registered kernel task (see `register_kernel_task`, e.g.
/// the desktop compositor loop) that is *right now* parked at its own
/// designated, known-safe preemption point - immediately before its
/// own `hlt`. 0 the rest of the time, including while that same task
/// is doing real work (rendering, processing input) between one hlt
/// and the next.
///
/// This exists because a long-running ring-0 `loop { ...; hlt; }`
/// (the desktop GUI, originally) was found to completely starve every
/// ring-3 task - including `heliox-daemon` - because the timer
/// interrupt's preemption logic only ever acted when the *interrupted*
/// context was ring-3 (`frame.cs & 3 == 3`); a newly-registered ring-3
/// task (e.g. a Start-menu-launched app) sat Ready in its run-queue
/// forever with no code path ever dispatching it. Arbitrary ring-0
/// code (syscall handlers, boot, anything holding a lock) is never
/// safe to preempt at a random instruction boundary - only a loop that
/// explicitly opts in by calling `enter_kernel_task_safepoint` right
/// before its own `hlt` is.
pub static CURRENT_KERNEL_TASK_PID: AtomicU64 = AtomicU64::new(0);

/// Mark that `pid` (a task registered via `register_kernel_task`) is
/// about to `hlt` at its own designated, known-safe preemption point.
/// Must be paired with `leave_kernel_task_safepoint` immediately after
/// waking, before doing any further (non-reentrant) work.
pub fn enter_kernel_task_safepoint(pid: u64) {
    CURRENT_KERNEL_TASK_PID.store(pid, Ordering::SeqCst);
}

pub fn leave_kernel_task_safepoint() {
    CURRENT_KERNEL_TASK_PID.store(0, Ordering::SeqCst);
}

// ============================================================================
// Public API
// ============================================================================

/// Initialize the scheduler. Creates one bookkeeping task (`kernel`,
/// pid 100) at `System` priority, marked `is_bookkeeping_stub` - it's
/// never actually scheduled (the kernel main context stays on pid 0)
/// or updated again after this, so `ps`/`users` have something to show
/// for the kernel main context and `cmd_scheduler`'s aggregate counts
/// know to exclude it.
///
/// There used to be a second stub here, `shell` at `High` priority, for
/// the same "give `ps` something to show" reason - before D13, the
/// interactive shell prompt was a bare blocking loop with no scheduler
/// presence of its own. Now that `shell::run()` registers the shell as
/// a genuine, live kernel task at boot (see its own doc comment), that
/// stub was retired entirely - it only ever produced a second, confusing,
/// permanently-`Ready` "shell" row alongside the real one in `ps`/`users`
/// (see `work.md` finding 2.3).
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
    kernel_task.is_bookkeeping_stub = true;
    push_task_locked(&mut sched, kernel_task);

    SCHEDULER_INIT.store(true, Ordering::SeqCst);
}

fn allocate_simd_buffer() -> u64 {
    let layout = core::alloc::Layout::from_size_align(512, 16).unwrap();
    let ptr = unsafe { alloc::alloc::alloc_zeroed(layout) };
    unsafe {
        // FPU Control Word (FCW) at offset 0: default 0x037F (all exceptions masked)
        let fcw_ptr = ptr as *mut u16;
        *fcw_ptr = 0x037F;
        // MXCSR at offset 24: default 0x1F80 (all exceptions masked)
        let mxcsr_ptr = ptr.add(24) as *mut u32;
        *mxcsr_ptr = 0x1F80;
    }
    ptr as u64
}

/// Append a task to the scheduler's `tasks` and `contexts`
/// vectors in lock-step. Caller must hold the `SCHEDULER` lock.
fn push_task_locked(sched: &mut Scheduler, task: Task) -> u64 {
    let id = task.id;
    let mut ctx = TaskContext::new();
    ctx.simd_state_ptr = allocate_simd_buffer();
    sched.contexts.push(ctx);
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
    
    if let Some(idx) = sched.tasks.iter().position(|t| t.id == pid) {
        sched.tasks[idx].name = String::from(name);
        sched.tasks[idx].state = TaskState::Ready;
        sched.tasks[idx].priority = priority;
        sched.tasks[idx].ticks = 0;
        sched.tasks[idx].capabilities = capabilities.to_vec();
        if !sched.tasks[idx].capabilities.contains(&String::from("cap:process:user")) {
            sched.tasks[idx].capabilities.push(String::from("cap:process:user"));
        }
        sched.tasks[idx].quotas = quotas;
        sched.tasks[idx].time_remaining = TIME_SLICE_TICKS;
        sched.tasks[idx].wake_at = u64::MAX;
        sched.tasks[idx].kernel_stack_top = kernel_stack_top.as_u64();
        sched.tasks[idx].cr3 = cr3;
        sched.tasks[idx].parent_id = parent_id;
        sched.tasks[idx].waiting_on_pid = None;
        sched.tasks[idx].cpu_affinity = None;
        sched.tasks[idx].blocked_on_confirmation = false;
        sched.tasks[idx].confirmation_approved = false;
        sched.tasks[idx].confirmation_denied = false;

        let old_simd = sched.contexts[idx].simd_state_ptr;
        let mut ctx = TaskContext::new();
        ctx.simd_state_ptr = old_simd;
        if old_simd != 0 {
            unsafe {
                let fcw_ptr = old_simd as *mut u16;
                *fcw_ptr = 0x037F;
                let mxcsr_ptr = (old_simd as *mut u8).add(24) as *mut u32;
                *mxcsr_ptr = 0x1F80;
            }
        }
        sched.contexts[idx] = ctx;

        let pri_idx = priority.index();
        if !sched.run_queues[pri_idx].contains(&pid) {
            sched.run_queues[pri_idx].push_back(pid);
        }
        return;
    }

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
        blocked_on_confirmation: false,
        confirmation_approved: false,
        confirmation_denied: false,
        is_bookkeeping_stub: false,
    };
    if !task.capabilities.contains(&String::from("cap:process:user")) {
        task.capabilities.push(String::from("cap:process:user"));
    }
    let mut ctx = TaskContext::new();
    ctx.simd_state_ptr = allocate_simd_buffer();
    sched.contexts.push(ctx);
    sched.tasks.push(task);
    let idx = sched.tasks.len() - 1;
    sched.run_queues[priority.index()].push_back(pid);
    // Mark which index in `tasks`/`contexts` the pid lives at so
    // we can do O(1) lookups without scanning.
    debug_assert_eq!(sched.tasks[idx].id, pid);
}

/// Register a long-running ring-0 loop (e.g. the desktop compositor)
/// as a genuine schedulable task, so ring-3 tasks actually get CPU
/// time while it runs instead of it monopolizing the CPU the way a
/// bare `loop { ...; hlt; }` does (see `CURRENT_KERNEL_TASK_PID`'s
/// doc for why that happened). Runs on the boot/kernel address space
/// (`cr3: 0` - `resume_task` then leaves CR3 untouched rather than
/// loading a process address space) starting at `entry`, on its own
/// dedicated `stack_top`. Uses the same pid range (>=100) `Task::new`
/// already reserves for kernel-side tasks. The caller is responsible
/// for the *first* dispatch (`claim_kernel_task_for_run` +
/// `resume_task`); subsequent re-entry happens via the timer
/// interrupt's normal round-robin once the task starts calling
/// `enter_kernel_task_safepoint` before its own `hlt`.
pub fn register_kernel_task(name: &str, priority: Priority, stack_top: u64, entry: u64) -> u64 {
    let mut sched = SCHEDULER.lock();
    let mut task = Task::new(String::from(name), priority);
    task.state = TaskState::Ready;
    task.kernel_stack_top = stack_top;
    task.cr3 = 0;
    task.capabilities.push(String::from("cap:system:all"));
    let id = push_task_locked(&mut sched, task);
    let idx = sched.contexts.len() - 1;
    let simd_state_ptr = sched.contexts[idx].simd_state_ptr;
    sched.contexts[idx] = kernel_task_entry_context(stack_top, entry, simd_state_ptr);
    sched.run_queues[priority.index()].push_back(id);
    id
}

/// Reset an already-registered kernel task (see `register_kernel_task`)
/// back to a clean entry-point context. Used when re-launching a
/// kernel task (e.g. reopening the desktop) rather than resuming
/// whatever mid-loop point it last happened to be preempted at - all
/// of a kernel task's real state lives in its own globals, so
/// restarting its local loop variables from scratch is safe, the same
/// abandon-and-fresh-re-enter pattern `kernel_return_entry` already
/// uses for the shell.
pub fn reset_kernel_task_entry(pid: u64, stack_top: u64, entry: u64) {
    let simd_state_ptr = context_of(pid).map(|c| c.simd_state_ptr).unwrap_or(0);
    write_context(pid, kernel_task_entry_context(stack_top, entry, simd_state_ptr));
}

fn kernel_task_entry_context(stack_top: u64, entry: u64, simd_state_ptr: u64) -> TaskContext {
    TaskContext {
        r15: 0, r14: 0, r13: 0, r12: 0, r11: 0, r10: 0, r9: 0, r8: 0,
        rbp: 0, rdi: 0, rsi: 0, rdx: 0, rcx: 0, rbx: 0, rax: 0,
        rip: entry,
        cs: crate::gdt::KERNEL_CODE_SELECTOR,
        rflags: 0x202, // IF=1
        rsp: stack_top - 8,
        ss: crate::gdt::KERNEL_DATA_SELECTOR,
        simd_state_ptr,
    }
}

/// Re-queue a currently-executing kernel task (registered via
/// `register_kernel_task`) as Ready. Mirrors `yield_current`'s
/// bookkeeping but keys off the task's own pid rather than
/// `CURRENT_PID` - a kernel task is never "the current ring-3
/// process", so `yield_current` itself is a no-op for it. Called by
/// the timer interrupt when preempting a kernel task at its own
/// `enter_kernel_task_safepoint` point.
pub fn yield_current_kernel_task(pid: u64) -> bool {
    let mut sched = SCHEDULER.lock();
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        if task.state == TaskState::Running {
            task.state = TaskState::Ready;
            task.time_remaining = TIME_SLICE_TICKS;
            let pri = task.priority.index();
            if !sched.run_queues[pri].contains(&pid) {
                sched.run_queues[pri].push_back(pid);
            }
            return true;
        }
    }
    false
}

/// Claim a registered kernel task for its first dispatch, mirroring
/// `claim_for_run`'s bookkeeping (drain from run-queues, mark
/// Running) without touching `CURRENT_PID` - that stays 0 the whole
/// time a kernel task runs, since it correctly means "no ring-3
/// process currently owns the CPU". Follow with `resume_task(pid)`.
pub fn claim_kernel_task_for_run(pid: u64) {
    let mut sched = SCHEDULER.lock();
    for q in sched.run_queues.iter_mut() {
        q.retain(|p| *p != pid);
    }
    if let Some(task) = sched.tasks.iter_mut().find(|t| t.id == pid) {
        task.state = TaskState::Running;
        task.time_remaining = TIME_SLICE_TICKS;
    }
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

        if now % 100 == 0 {
            crate::logging::audit::FLUSH_PENDING.store(true, Ordering::SeqCst);
        }

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
                if task.blocked_on_confirmation {
                    task.blocked_on_confirmation = false;
                    task.confirmation_denied = true;
                }
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
pub fn write_context(pid: u64, mut ctx: TaskContext) {
    let mut sched = SCHEDULER.lock();
    if let Some(idx) = sched.tasks.iter().position(|t| t.id == pid) {
        let old_simd = sched.contexts[idx].simd_state_ptr;
        ctx.simd_state_ptr = old_simd;
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
            let ctx = sched.contexts.remove(i);
            if ctx.simd_state_ptr != 0 {
                let layout = core::alloc::Layout::from_size_align(512, 16).unwrap();
                unsafe { alloc::alloc::dealloc(ctx.simd_state_ptr as *mut u8, layout) };
            }
            sched.tasks.remove(i);
        } else {
            i += 1;
        }
    }
}

pub fn save_simd_state(pid: u64) {
    let sched = SCHEDULER.lock();
    if let Some(idx) = sched.tasks.iter().position(|t| t.id == pid) {
        let ptr = sched.contexts[idx].simd_state_ptr;
        if ptr != 0 {
            unsafe {
                core::arch::asm!(
                    "fxsave64 [{}]",
                    in(reg) ptr
                );
            }
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
        
        // Restore SIMD/SSE state for the incoming task.
        "mov rax, [rsi + 0xA0]",
        "test rax, rax",
        "jz 9f",
        "fxrstor64 [rax]",
        "9:",
        
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
        crate::serial_println!("[WAKE_PARENT] Waking parent pid={}, name={}, rip={:#x}, state={:?}, child_pid={}, exit_code={}", 
                               parent_pid, sched.tasks[idx].name, sched.contexts[idx].rip, sched.tasks[idx].state, child_pid, code);
        sched.tasks[idx].state = TaskState::Ready;
        sched.tasks[idx].waiting_on_pid = None;
        sched.contexts[idx].rax = code as u64;

        let pri = sched.tasks[idx].priority.index();
        let pid = sched.tasks[idx].id;
        if !sched.run_queues[pri].contains(&pid) {
            sched.run_queues[pri].push_back(pid);
        }
    } else {
        crate::serial_println!("[WAKE_PARENT] Parent pid={} not found or not Blocked waiting for child_pid={}", parent_pid, child_pid);
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
    crate::serial_println!("[RESUME_TASK] Resuming pid={}, name={}, rip={:#x}, rsp={:#x}, rax={:#x}", pid, {
        let sched = SCHEDULER.lock();
        sched.tasks.iter().find(|t| t.id == pid).map(|t| t.name.clone()).unwrap_or_else(|| String::from("unknown"))
    }, ctx.rip, ctx.rsp, ctx.rax);
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
        rsp: top - 8,
        ss: crate::gdt::KERNEL_DATA_SELECTOR,
        simd_state_ptr: 0,
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

/// Return-to-shell fallback: reap whatever died, report the exit, and
/// hand control back to the shell. `shell::run()` now resumes the
/// shell's own registered kernel task (see `register_kernel_task`) from
/// wherever it was last parked, rather than starting fresh - the shell
/// is a normal, always-in-the-run-queue-when-idle participant these
/// days, so in practice `schedule_next()` above usually finds and
/// resumes it directly the moment it becomes Ready, without ever
/// reaching this trampoline; this stays as a safety net for the
/// remaining edge case (death happening before the shell has reached
/// its own first safepoint).
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

/// Wake any task blocked on confirmation.
pub fn wake_confirmation_waiters(key: u8) -> bool {
    let mut sched = SCHEDULER.lock();
    let mut woken_any = false;
    let mut task_idx = None;
    for (idx, task) in sched.tasks.iter().enumerate() {
        if task.state == TaskState::Blocked && task.blocked_on_confirmation {
            task_idx = Some(idx);
            break;
        }
    }
    
    if let Some(idx) = task_idx {
        let task = &mut sched.tasks[idx];
        task.state = TaskState::Ready;
        task.blocked_on_confirmation = false;
        task.wake_at = u64::MAX;
        
        let approved = key == b'y' || key == b'Y';
        if approved {
            task.confirmation_approved = true;
        } else {
            task.confirmation_denied = true;
        }
        
        let pri = task.priority.index();
        let pid = task.id;
        if !sched.run_queues[pri].contains(&pid) {
            sched.run_queues[pri].push_back(pid);
        }
        woken_any = true;
    }
    woken_any
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

