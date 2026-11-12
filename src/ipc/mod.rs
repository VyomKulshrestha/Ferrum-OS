// ============================================================================
// FerrumOS - Inter-Process Communication Contracts
// ============================================================================
// The v0.1 kernel does not run AI systems, semantic memory, or vector search.
// This module defines deterministic IPC metadata that future runtime services
// can use without coupling probabilistic components into kernel space.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::collections::VecDeque;
use alloc::vec::Vec;
use core::sync::atomic::{AtomicU64, Ordering};
use spin::Mutex;

/// Maximum inline payload size for early kernel IPC messages.
///
/// Large buffers should later be transferred through shared memory handles
/// guarded by capabilities, not by copying through the kernel message path.
/// Bumped from the original 256 bytes to fit a real chat-style agent
/// response (e.g. a generated story) in one message instead of chunking -
/// Per-service and broker-wide quotas below keep copied payload memory bounded
/// while preserving fair progress between independent mailboxes.
pub const MAX_PAYLOAD_BYTES: usize = 4096;

/// Stable service endpoint identifier.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Endpoint {
    pub service: String,
    pub channel: String,
}

impl Endpoint {
    pub fn new(service: &str, channel: &str) -> Self {
        Self {
            service: service.to_string(),
            channel: channel.to_string(),
        }
    }
}

/// IPC operation class.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageKind {
    Request,
    Response,
    Event,
}

/// Sender flag: the message was posted by the kernel shell on the operator's
/// behalf (`heliox confirm`, `heliox deny`, `heliox voice event`,
/// `heliox neural`). Only kernel code sets it; IpcSend never does.
pub const SENDER_KERNEL_SHELL: u64 = 1 << 0;
/// Sender flag: the message was posted by an assistant panel the kernel
/// itself launched for the operator (desktop launcher clicked with a physical
/// pointer, the boot-time setup launch, or the shell's `run`). A panel spawned
/// through Exec or AppLaunch by any process never carries it.
pub const SENDER_ASSISTANT_PANEL: u64 = 1 << 1;

/// Deterministic IPC envelope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Message {
    pub id: u64,
    pub source_pid: u64,
    /// `SENDER_*` bits established by the kernel, never by the sender.
    pub sender_flags: u64,
    pub target: Endpoint,
    pub kind: MessageKind,
    pub required_capability: String,
    payload: Vec<u8>,
    /// The mailbox owner this message was queued for (set by `send`). Only
    /// that pid receives it; it is dropped when that pid is reaped.
    target_pid: u64,
}

impl Message {
    /// Create a bounded IPC message.
    pub fn new(
        source_pid: u64,
        target: Endpoint,
        kind: MessageKind,
        required_capability: &str,
        payload: &[u8],
    ) -> Result<Self, IpcError> {
        if payload.len() > MAX_PAYLOAD_BYTES {
            return Err(IpcError::PayloadTooLarge);
        }

        static NEXT_MESSAGE_ID: AtomicU64 = AtomicU64::new(1);

        Ok(Self {
            id: NEXT_MESSAGE_ID.fetch_add(1, Ordering::SeqCst),
            source_pid,
            sender_flags: 0,
            target,
            kind,
            required_capability: required_capability.to_string(),
            payload: payload.to_vec(),
            target_pid: 0,
        })
    }

    /// Kernel-only: record how the kernel knows who sent this message.
    pub fn with_sender_flags(mut self, flags: u64) -> Self {
        self.sender_flags = flags;
        self
    }

    pub fn payload(&self) -> &[u8] {
        &self.payload
    }
}

/// Pids of assistant panels the kernel launched for the operator. Pids are
/// never reused (`process::create`), so a later process cannot inherit an
/// entry; `forget_pid` drops it when the panel is reaped.
static OPERATOR_PANEL_PIDS: Mutex<alloc::collections::BTreeSet<u64>> =
    Mutex::new(alloc::collections::BTreeSet::new());

/// Record that the kernel launched `pid` as the operator's assistant panel.
/// Call only from kernel launch paths that act on operator input.
pub fn mark_operator_panel(pid: u64) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        OPERATOR_PANEL_PIDS.lock().insert(pid);
    });
}

/// Drop any sender record for a reaped process, release the mailbox it owned
/// and drop the messages queued for it (they must not reach a later owner).
pub fn forget_pid(pid: u64) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        OPERATOR_PANEL_PIDS.lock().remove(&pid);
        MAILBOX_OWNERS.lock().retain(|_, owner| *owner != pid);
        BROKER.lock().queue.retain(|message| message.target_pid != pid);
    });
}

/// Mailboxes owned by ring-3 processes: process name -> pid.
///
/// Ownership used to be recomputed on every call as "the first live task
/// with this name", so a second instance of a program (an Exec of
/// `/bin/heliox-daemon`, a second AppLaunch of the panel) became the owner
/// of the first instance's mailbox, with its queued messages, the moment
/// the first died. A mailbox is now bound to the process that registered
/// under the name while it was free, and only that pid receives from it.
static MAILBOX_OWNERS: Mutex<alloc::collections::BTreeMap<String, u64>> =
    Mutex::new(alloc::collections::BTreeMap::new());

/// The process name a service name belongs to (stable aliases resolved).
fn mailbox_name(service: &str) -> &str {
    match service {
        "runtime.agentd" => "agentd",
        "heliox" => "heliox-daemon",
        "assistant" => "heliox-assistant-panel",
        other => other,
    }
}

/// A pid is alive while its scheduler task is not Dead, or, before it has a
/// task, while its process record exists.
fn pid_alive(pid: u64) -> bool {
    match crate::scheduler::task_state(pid) {
        Some(state) => state != crate::scheduler::TaskState::Dead,
        None => crate::process::is_registered(pid),
    }
}

/// Called when a ring-3 process is registered: it becomes the owner of the
/// mailbox named after it unless a live process already owns that mailbox.
/// A process that registered while another owner was live never owns it,
/// even after that owner dies.
pub fn claim_mailbox(pid: u64, process_name: &str) {
    let current = x86_64::instructions::interrupts::without_interrupts(|| {
        MAILBOX_OWNERS.lock().get(process_name).copied()
    });
    if let Some(owner) = current {
        if owner != pid && pid_alive(owner) {
            return;
        }
    }
    x86_64::instructions::interrupts::without_interrupts(|| {
        MAILBOX_OWNERS
            .lock()
            .insert(String::from(process_name), pid);
    });
}

/// The `SENDER_*` flags the kernel attaches to an IpcSend from `pid`.
pub fn process_sender_flags(pid: u64) -> u64 {
    let is_panel = x86_64::instructions::interrupts::without_interrupts(|| {
        OPERATOR_PANEL_PIDS.lock().contains(&pid)
    });
    if is_panel {
        SENDER_ASSISTANT_PANEL
    } else {
        0
    }
}

/// Names a VFS file must not take as its process name when it is Exec'd:
/// every program compiled into the kernel image and every mailbox alias.
/// The process name chooses the program's manifest capabilities and the
/// mailbox it owns, so an Exec'd file called `heliox-assistant-panel` used
/// to receive the panel's capabilities and its `assistant` mailbox.
pub fn is_reserved_program_name(name: &str) -> bool {
    matches!(
        name,
        "init"
            | "heliox-daemon"
            | "heliox"
            | "heliox-assistant-panel"
            | "assistant"
            | "agentd"
            | "runtime.agentd"
            | "agent-bridge"
            | "audit-exporter"
            | "gui-smoke-test"
            | "text-editor"
            | "calculator"
            | "file-manager"
            | "settings"
            | "browser"
            | "app-store"
            | "notification-center"
            | "task-manager"
            | "ipc-owner-test"
            | "ipc-forge-test"
    ) || crate::userspace::is_compiled_program(name)
}

/// IPC validation failures.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IpcError {
    PayloadTooLarge,
    PermissionDenied,
    QueueFull,
    NoMessage,
    NoService,
}

/// Validate message send permission against the caller's held capabilities.
pub fn authorize_message(message: &Message, held_capabilities: &[String]) -> Result<(), IpcError> {
    if crate::security::has_capability(held_capabilities, &message.required_capability) {
        Ok(())
    } else {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            "IPC message denied by capability policy",
        );
        Err(IpcError::PermissionDenied)
    }
}

/// Broker-wide memory bound. Per-service quotas below ensure one stalled
/// consumer cannot monopolize this capacity and starve unrelated agents.
const MAX_QUEUED_MESSAGES: usize = 256;
const MAX_QUEUED_MESSAGES_PER_SERVICE: usize = 16;
/// Slots of each mailbox (and of the broker) that only messages the kernel
/// marked as the operator's (`SENDER_KERNEL_SHELL`, `SENDER_ASSISTANT_PANEL`)
/// may take. Without them, any holder of `ipc:send:*` could fill the
/// daemon's mailbox and make the operator's next DENY or disarm fail.
pub const OPERATOR_RESERVED_SLOTS: usize = 4;
const OPERATOR_SENDERS: u64 = SENDER_KERNEL_SHELL | SENDER_ASSISTANT_PANEL;

struct IpcBroker {
    queue: VecDeque<Message>,
    sent: u64,
    received: u64,
    denied: u64,
}

static BROKER: Mutex<IpcBroker> = Mutex::new(IpcBroker {
    queue: VecDeque::new(),
    sent: 0,
    received: 0,
    denied: 0,
});

/// Snapshot of deterministic IPC broker counters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IpcStats {
    pub queued: usize,
    pub sent: u64,
    pub received: u64,
    pub denied: u64,
}

/// Send a message through the kernel IPC broker.
pub fn send(message: Message, held_capabilities: &[String]) -> Result<u64, IpcError> {
    // Audit capability
    if !crate::security::has_capability(held_capabilities, &message.required_capability) {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::SecurityViolation,
            "IPC send denied - missing capability",
        );
        x86_64::instructions::interrupts::without_interrupts(|| {
            BROKER.lock().denied += 1;
        });
        return Err(IpcError::PermissionDenied);
    }

    // A mailbox belongs to a live ring-3 task. Rejecting unknown targets
    // prevents absent/crashed services from filling the broker and applying
    // global backpressure to unrelated control channels.
    let Some(owner) = service_owner_pid(&message.target.service) else {
        return Err(IpcError::NoService);
    };
    let mut message = message;
    message.target_pid = owner;

    let id = message.id;
    let operator = message.sender_flags & OPERATOR_SENDERS != 0;
    let mailbox = String::from(mailbox_name(&message.target.service));

    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut broker = BROKER.lock();
        // Messages left for an earlier owner of this mailbox are never
        // delivered; do not let them hold its slots.
        broker.queue.retain(|queued| {
            mailbox_name(&queued.target.service) != mailbox || queued.target_pid == owner
        });
        let service_depth = broker
            .queue
            .iter()
            .filter(|queued| mailbox_name(&queued.target.service) == mailbox)
            .count();
        let (per_service, total) = if operator {
            (MAX_QUEUED_MESSAGES_PER_SERVICE, MAX_QUEUED_MESSAGES)
        } else {
            (
                MAX_QUEUED_MESSAGES_PER_SERVICE - OPERATOR_RESERVED_SLOTS,
                MAX_QUEUED_MESSAGES - MAX_QUEUED_MESSAGES_PER_SERVICE,
            )
        };
        if service_depth >= per_service {
            return Err(IpcError::QueueFull);
        }
        if broker.queue.len() >= total {
            return Err(IpcError::QueueFull);
        }
        broker.queue.push_back(message);
        broker.sent += 1;
        Ok(id)
    })
}

/// Receive the next message for a target service.
pub fn receive_for_service(service: &str) -> Result<Message, IpcError> {
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut broker = BROKER.lock();
        let Some(index) = broker
            .queue
            .iter()
            .position(|message| message.target.service == service)
        else {
            return Err(IpcError::NoMessage);
        };

        let message = broker.queue.remove(index).ok_or(IpcError::NoMessage)?;
        broker.received += 1;
        Ok(message)
    })
}

/// Receive the next message queued for `owner` in the mailbox `service`.
/// The syscall path: a message is delivered only to the pid it was queued for.
pub fn receive_for_owner(service: &str, owner: u64) -> Result<Message, IpcError> {
    let mailbox = mailbox_name(service);
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut broker = BROKER.lock();
        let Some(index) = broker.queue.iter().position(|message| {
            mailbox_name(&message.target.service) == mailbox && message.target_pid == owner
        }) else {
            return Err(IpcError::NoMessage);
        };
        let message = broker.queue.remove(index).ok_or(IpcError::NoMessage)?;
        broker.received += 1;
        Ok(message)
    })
}

/// Return whether a ring-3 task owns the named mailbox.  IPC receive is
/// intentionally stricter than send: knowing a service name must never be
/// enough to consume another process's messages.  Ordinary programs own a
/// mailbox matching their executable name; stable runtime aliases retain
/// their public service contracts.
pub fn task_owns_service(pid: u64, service: &str) -> bool {
    service_owner_pid(service) == Some(pid)
}

/// Resolve a mailbox to its live task owner. Executable names are the default
/// service names; stable Heliox aliases preserve the existing wire contract.
pub fn service_owner_pid(service: &str) -> Option<u64> {
    let mailbox = mailbox_name(service);
    let bound = x86_64::instructions::interrupts::without_interrupts(|| {
        MAILBOX_OWNERS.lock().get(mailbox).copied()
    });
    if let Some(owner) = bound {
        // A dead owner's mailbox stays closed until a new process registers
        // under the name; it never passes to another live instance.
        return pid_alive(owner).then_some(owner);
    }

    // No ring-3 owner: kernel tasks that serve a mailbox by name (the agentd
    // boundary task). Ring-3 processes own mailboxes only through a claim.
    crate::scheduler::list_tasks()
        .into_iter()
        .find(|task| {
            task.state != crate::scheduler::TaskState::Dead
                && task.name == mailbox
                && !crate::process::is_registered(task.id)
        })
        .map(|task| task.id)
}

/// Return IPC queue counters.
pub fn stats() -> IpcStats {
    x86_64::instructions::interrupts::without_interrupts(|| {
        let broker = BROKER.lock();
        IpcStats {
            queued: broker.queue.len(),
            sent: broker.sent,
            received: broker.received,
            denied: broker.denied,
        }
    })
}
