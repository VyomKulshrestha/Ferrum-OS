// ============================================================================
// FerrumOS - Capability-Based Security Subsystem
// ============================================================================
// Implements a deny-by-default capability-based permission model.
// Every action requires an explicit capability token.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

/// A capability token representing a specific permission
#[derive(Debug, Clone)]
pub struct Capability {
    pub id: u64,
    pub name: String,
    pub description: String,
    /// Resource pattern this capability grants access to
    pub resource: String,
    /// Whether this capability can be delegated to child processes
    pub delegatable: bool,
}

/// Security policy enforcement state
struct SecurityState {
    capabilities: Vec<Capability>,
    next_id: u64,
    sandbox_enabled: bool,
}

static SECURITY: Mutex<SecurityState> = Mutex::new(SecurityState {
    capabilities: Vec::new(),
    next_id: 1,
    sandbox_enabled: false,
});

/// Initialize the security subsystem with default capabilities
pub fn init() {
    let mut state = SECURITY.lock();
    state.sandbox_enabled = true;
    
    // Register system-level capabilities
    let default_caps = [
        ("cap:system:all", "Full System Access", "system:*", true),
        ("cap:fs:read", "Filesystem Read", "fs:read:*", true),
        ("cap:fs:write", "Filesystem Write", "fs:write:*", true),
        ("cap:process:spawn", "Process Spawn", "process:spawn", true),
        ("cap:process:kill", "Process Kill", "process:kill:*", false),
        ("cap:net:listen", "Network Listen", "net:listen:*", false),
        ("cap:net:connect", "Network Connect", "net:connect:*", true),
        ("cap:service:register", "Service Registration", "service:register", false),
        ("cap:audit:read", "Audit Log Read", "audit:read", false),
        ("cap:memory:alloc", "Memory Allocation", "memory:alloc:*", true),
        ("cap:ipc:send", "IPC Send", "ipc:send:*", true),
        ("cap:agent:control", "Agent Runtime Control", "agent:*", false),
        ("cap:audio:play", "Audio Playback", "audio:play", true),
        ("cap:audio:record", "Audio Recording", "audio:record", true),
        ("cap:input:inject", "Input Injection", "input:inject:*", true),
        ("cap:camera:read", "Camera Frame Access", "camera:read:*", true),
        ("cap:quota:exempt", "Quota Exemption", "quota:exempt:*", true),
        ("cap:confirmation:bypass", "Confirmation Gating Bypass", "confirmation:bypass:*", true),
    ];
    
    for (name, desc, resource, delegatable) in &default_caps {
        let id = state.next_id;
        state.next_id += 1;
        state.capabilities.push(Capability {
            id,
            name: name.to_string(),
            description: desc.to_string(),
            resource: resource.to_string(),
            delegatable: *delegatable,
        });
    }
}

/// List all registered capabilities
pub fn list_capabilities() -> Vec<Capability> {
    SECURITY.lock().capabilities.clone()
}

/// Check if any registered capability covers a resource pattern.
///
/// This validates the policy registry only. Use `has_capability` to verify
/// that a task or service actually holds a token granting the requested access.
pub fn check_capability(resource: &str) -> bool {
    let state = SECURITY.lock();
    state.capabilities.iter().any(|c| {
        resource.starts_with(c.resource.trim_end_matches('*'))
    })
}

/// Check whether a caller's held capability tokens grant access to a resource.
pub fn has_capability(held_capabilities: &[String], resource: &str) -> bool {
    if held_capabilities.iter().any(|held| held == "cap:system:all") {
        return true;
    }

    let state = SECURITY.lock();

    held_capabilities.iter().any(|held| {
        state.capabilities.iter().any(|registered| {
            registered.name == *held
                && resource.starts_with(registered.resource.trim_end_matches('*'))
        })
    })
}

/// Check whether a caller directly holds a named capability token.
///
/// This is used for service lifecycle policy, where manifests name the exact
/// capabilities required to control a service. Resource checks should continue
/// to use `has_capability`.
pub fn holds_capability_token(held_capabilities: &[String], capability_name: &str) -> bool {
    if held_capabilities.iter().any(|held| held == "cap:system:all") {
        return true;
    }

    let state = SECURITY.lock();
    state
        .capabilities
        .iter()
        .any(|registered| registered.name == capability_name)
        && held_capabilities
            .iter()
            .any(|held| held == capability_name)
}

/// Check whether a capability token is delegatable to a child task or service.
pub fn can_delegate(capability_name: &str) -> bool {
    SECURITY
        .lock()
        .capabilities
        .iter()
        .find(|cap| cap.name == capability_name)
        .map(|cap| cap.delegatable)
        .unwrap_or(false)
}

/// Register a new capability
pub fn register_capability(name: &str, description: &str, resource: &str, delegatable: bool) -> u64 {
    let mut state = SECURITY.lock();
    let id = state.next_id;
    state.next_id += 1;
    state.capabilities.push(Capability {
        id,
        name: name.to_string(),
        description: description.to_string(),
        resource: resource.to_string(),
        delegatable,
    });
    
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::CapabilityGranted,
        &alloc::format!("Registered capability: {} ({})", name, resource),
    );
    
    id
}

/// Whether sandbox enforcement is enabled
pub fn is_sandbox_enabled() -> bool {
    SECURITY.lock().sandbox_enabled
}

/// Filter requested capabilities against delegatable ones and caller's held capabilities.
pub fn filter_delegatable(requested: &[String], caller: &[String]) -> Vec<String> {
    requested
        .iter()
        .filter(|cap| can_delegate(cap) && holds_capability_token(caller, cap))
        .cloned()
        .collect()
}

