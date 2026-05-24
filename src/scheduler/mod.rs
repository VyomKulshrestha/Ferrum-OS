// ============================================================================
// FerrumOS - Task Scheduler
// ============================================================================
// Cooperative round-robin task scheduler.
//
// Each task has a unique ID, state, and priority level.
// The scheduler is designed to be extended with:
//   - Preemptive scheduling (via timer interrupt)
//   - Priority-based scheduling
//   - CPU affinity (for multi-core)
//   - Real-time task support
//
// Tasks are the future foundation for:
//   - AI runtime service processes
//   - Sandboxed agent execution
//   - System service lifecycle management
// ============================================================================

extern crate alloc;

use alloc::collections::VecDeque;
use alloc::string::String;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use spin::Mutex;

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
/// Higher priority tasks are scheduled more frequently.
/// System tasks always run before user tasks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    /// Lowest priority - background maintenance
    Idle = 0,
    /// Normal user tasks
    Normal = 1,
    /// Elevated priority for interactive tasks
    High = 2,
    /// Highest priority - kernel and system services
    System = 3,
}

// ============================================================================
// Task
// ============================================================================

/// A schedulable task in the kernel
/// 
/// Each task represents an independent unit of execution.
/// In the current cooperative model, tasks yield voluntarily.
/// Future versions will support preemption via the timer interrupt.
#[derive(Debug, Clone)]
pub struct Task {
    /// Unique task identifier
    pub id: u64,
    /// Human-readable task name
    pub name: String,
    /// Current execution state
    pub state: TaskState,
    /// Scheduling priority
    pub priority: Priority,
    /// Number of timer ticks this task has been alive
    pub ticks: u64,
    /// Security capabilities assigned to this task
    pub capabilities: Vec<String>,
}

impl Task {
    /// Create a new task with the given name and priority
    pub fn new(name: String, priority: Priority) -> Self {
        static NEXT_ID: AtomicU64 = AtomicU64::new(1);
        
        Task {
            id: NEXT_ID.fetch_add(1, Ordering::SeqCst),
            name,
            state: TaskState::Ready,
            priority,
            ticks: 0,
            capabilities: Vec::new(),
        }
    }
}

// ============================================================================
// Scheduler
// ============================================================================

/// The global task scheduler
/// 
/// Manages a queue of tasks and provides round-robin scheduling.
/// Protected by a spinlock for interrupt safety.
struct Scheduler {
    /// Task ready queue
    tasks: VecDeque<Task>,
    /// Total timer ticks since boot
    total_ticks: u64,
    /// Whether the scheduler has been initialized
    initialized: bool,
}

impl Scheduler {
    const fn new() -> Self {
        Scheduler {
            tasks: VecDeque::new(),
            total_ticks: 0,
            initialized: false,
        }
    }
}

/// Global scheduler instance
static SCHEDULER: Mutex<Scheduler> = Mutex::new(Scheduler::new());

/// Whether the scheduler has been initialized
static SCHEDULER_INIT: AtomicBool = AtomicBool::new(false);

// ============================================================================
// Public API
// ============================================================================

/// Initialize the scheduler
/// 
/// Creates the initial kernel task and marks the scheduler as ready.
pub fn init() {
    let mut sched = SCHEDULER.lock();
    sched.initialized = true;
    
    // Create the kernel idle task
    let mut kernel_task = Task::new(
        String::from("kernel"),
        Priority::System,
    );
    kernel_task.state = TaskState::Running;
    kernel_task.capabilities.push(String::from("cap:system:all"));
    sched.tasks.push_back(kernel_task);
    
    // Create the shell task
    let mut shell_task = Task::new(
        String::from("shell"),
        Priority::High,
    );
    shell_task.state = TaskState::Ready;
    shell_task.capabilities.push(String::from("cap:shell:interactive"));
    sched.tasks.push_back(shell_task);
    
    SCHEDULER_INIT.store(true, Ordering::SeqCst);
}

/// Timer tick handler - called from the timer interrupt
/// 
/// Increments tick counters for all active tasks.
/// In a preemptive scheduler, this would trigger context switches.
pub fn tick() {
    if !SCHEDULER_INIT.load(Ordering::SeqCst) {
        return;
    }
    
    // Try to lock without blocking (we're in an interrupt handler)
    if let Some(mut sched) = SCHEDULER.try_lock() {
        sched.total_ticks += 1;
        for task in sched.tasks.iter_mut() {
            if task.state == TaskState::Running || task.state == TaskState::Ready {
                task.ticks += 1;
            }
        }
    }
}

/// Spawn a new task
/// 
/// Adds a task to the ready queue with the specified name and priority.
/// Returns the task ID.
pub fn spawn(name: String, priority: Priority) -> u64 {
    spawn_internal(name, priority, Vec::new())
}

/// Spawn a new task with a checked capability set.
///
/// Non-delegatable capabilities may not be assigned through this path unless
/// the caller uses `cap:system:all` through a future privileged broker.
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
        sched.tasks.push_back(task);
        id
    };

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ProcessSpawned,
        "Task spawned",
    );
    id
}

/// Kill a task by ID
/// 
/// Marks the task as Dead for cleanup.
/// Returns true if the task was found and killed.
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

/// Get a snapshot of all tasks
/// 
/// Returns a copy of the task list for display purposes.
pub fn list_tasks() -> Vec<Task> {
    let sched = SCHEDULER.lock();
    sched.tasks.iter().cloned().collect()
}

/// Get the total number of timer ticks since boot
pub fn total_ticks() -> u64 {
    let sched = SCHEDULER.lock();
    sched.total_ticks
}

/// Get the number of active (non-dead) tasks
pub fn active_task_count() -> usize {
    let sched = SCHEDULER.lock();
    sched.tasks.iter().filter(|t| t.state != TaskState::Dead).count()
}

/// Clean up dead tasks
/// 
/// Removes all tasks in the Dead state from the scheduler.
pub fn cleanup_dead_tasks() {
    let mut sched = SCHEDULER.lock();
    sched.tasks.retain(|t| t.state != TaskState::Dead);
}
