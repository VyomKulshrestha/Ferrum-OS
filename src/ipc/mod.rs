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

/// Drop any sender record for a reaped process.
pub fn forget_pid(pid: u64) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        OPERATOR_PANEL_PIDS.lock().remove(&pid);
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
    if service_owner_pid(&message.target.service).is_none() {
        return Err(IpcError::NoService);
    }

    let id = message.id;

    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut broker = BROKER.lock();
        let service_depth = broker
            .queue
            .iter()
            .filter(|queued| queued.target.service == message.target.service)
            .count();
        if service_depth >= MAX_QUEUED_MESSAGES_PER_SERVICE {
            return Err(IpcError::QueueFull);
        }
        if broker.queue.len() >= MAX_QUEUED_MESSAGES {
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
    let matches_service = |name: &str| {
        service == name
            || (name == "agentd" && service == "runtime.agentd")
            || (name == "heliox-daemon" && service == "heliox")
            || (name == "heliox-assistant-panel" && service == "assistant")
    };

    if let Some(owner) = crate::scheduler::list_tasks()
        .into_iter()
        .find(|task| {
            task.state != crate::scheduler::TaskState::Dead
                && matches_service(&task.name)
        })
        .map(|task| task.id)
    {
        return Some(owner);
    }

    // Boot services are valid IPC owners as soon as their ring-3 image is
    // registered, even before the operator dispatches init. This permits a
    // bounded control message to be queued during boot without reopening
    // arbitrary/unknown service names.
    crate::process::list()
        .into_iter()
        .find(|(_, name, _)| matches_service(name))
        .map(|(pid, _, _)| pid)
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
