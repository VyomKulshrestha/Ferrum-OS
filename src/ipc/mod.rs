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

/// Deterministic IPC envelope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Message {
    pub id: u64,
    pub source_pid: u64,
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
            target,
            kind,
            required_capability: required_capability.to_string(),
            payload: payload.to_vec(),
        })
    }

    pub fn payload(&self) -> &[u8] {
        &self.payload
    }
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
/// mailbox matching their executable name; the two historical Heliox
/// channels retain their stable public names.
pub fn task_owns_service(pid: u64, service: &str) -> bool {
    service_owner_pid(service) == Some(pid)
}

/// Resolve a mailbox to its live task owner. Executable names are the default
/// service names; stable Heliox aliases preserve the existing wire contract.
pub fn service_owner_pid(service: &str) -> Option<u64> {
    crate::scheduler::list_tasks()
        .into_iter()
        .find(|task| {
            task.state != crate::scheduler::TaskState::Dead
                && (service == task.name
                    || (task.name == "heliox-daemon" && service == "heliox")
                    || (task.name == "heliox-assistant-panel" && service == "assistant"))
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
