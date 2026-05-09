// ============================================================================
// FerrumOS — Modular Service Manager
// ============================================================================
// Manages lifecycle of kernel and userspace services.
// Designed as the integration point for future AI runtime services.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

/// Service execution state
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServiceState {
    Stopped,
    Running,
    Failed,
}

/// A registered system service
#[derive(Debug, Clone)]
pub struct Service {
    pub id: u64,
    pub name: String,
    pub description: String,
    pub state: ServiceState,
    /// Required capabilities for this service
    pub required_capabilities: Vec<String>,
    /// Whether this service runs in a sandbox
    pub sandboxed: bool,
}

struct ServiceManager {
    services: Vec<Service>,
    next_id: u64,
}

static MANAGER: Mutex<ServiceManager> = Mutex::new(ServiceManager {
    services: Vec::new(),
    next_id: 1,
});

/// Initialize the service manager with core system services
pub fn init() {
    let mut mgr = MANAGER.lock();
    
    // Register core system services
    let core_services = [
        ("kernel.memory", "Memory Management Service", false),
        ("kernel.scheduler", "Task Scheduler Service", false),
        ("kernel.security", "Security Enforcement Service", false),
        ("kernel.logging", "Audit Logging Service", false),
        ("kernel.fs", "Filesystem Service", false),
        ("runtime.ipc", "Inter-Process Communication", true),
    ];
    
    for (name, desc, sandboxed) in &core_services {
        let id = mgr.next_id;
        mgr.next_id += 1;
        mgr.services.push(Service {
            id,
            name: name.to_string(),
            description: desc.to_string(),
            state: ServiceState::Running,
            required_capabilities: Vec::new(),
            sandboxed: *sandboxed,
        });
    }
}

/// List all registered services
pub fn list_services() -> Vec<Service> {
    MANAGER.lock().services.clone()
}

/// Find a service by name.
pub fn find_service(name: &str) -> Option<Service> {
    MANAGER
        .lock()
        .services
        .iter()
        .find(|service| service.name == name)
        .cloned()
}

/// Register a new service
pub fn register_service(name: &str, description: &str, sandboxed: bool) -> u64 {
    let mut mgr = MANAGER.lock();
    let id = mgr.next_id;
    mgr.next_id += 1;
    mgr.services.push(Service {
        id,
        name: name.to_string(),
        description: description.to_string(),
        state: ServiceState::Stopped,
        required_capabilities: Vec::new(),
        sandboxed,
    });
    
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ServiceRegistered,
        &alloc::format!("Service registered: {}", name),
    );
    
    id
}

/// Start a service by ID
pub fn start_service(id: u64) -> Result<(), String> {
    let started = {
        let mut mgr = MANAGER.lock();
        let mut started = false;
        for svc in mgr.services.iter_mut() {
            if svc.id == id {
                svc.state = ServiceState::Running;
                started = true;
                break;
            }
        }
        started
    };

    if started {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::ServiceStarted,
            "Service started",
        );
        Ok(())
    } else {
        Err(String::from("service not found"))
    }
}

/// Stop a service by ID
pub fn stop_service(id: u64) -> Result<(), String> {
    let stopped = {
        let mut mgr = MANAGER.lock();
        let mut stopped = false;
        for svc in mgr.services.iter_mut() {
            if svc.id == id {
                svc.state = ServiceState::Stopped;
                stopped = true;
                break;
            }
        }
        stopped
    };

    if stopped {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::ServiceStopped,
            "Service stopped",
        );
        Ok(())
    } else {
        Err(String::from("service not found"))
    }
}
