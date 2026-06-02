// ============================================================================
// FerrumOS - Modular Service Manager
// ============================================================================
// Manages lifecycle of kernel and userspace services.
// Designed as the integration point for future AI runtime services.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

/// Service placement in the FerrumOS layered architecture.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServiceLayer {
    Kernel,
    Runtime,
    Cognitive,
    Agent,
}

/// Service execution state
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServiceState {
    Stopped,
    Running,
    Failed,
}

/// Sandboxing constraints attached to a runtime service.
#[derive(Debug, Clone)]
pub struct SandboxProfile {
    pub ipc_only: bool,
    pub isolated_address_space: bool,
    pub max_memory_bytes: usize,
    pub audit_syscalls: bool,
}

impl SandboxProfile {
    pub const fn kernel_trusted() -> Self {
        Self {
            ipc_only: false,
            isolated_address_space: false,
            max_memory_bytes: 0,
            audit_syscalls: true,
        }
    }

    pub const fn runtime_default() -> Self {
        Self {
            ipc_only: true,
            isolated_address_space: true,
            max_memory_bytes: 64 * 1024,
            audit_syscalls: true,
        }
    }
}

/// Immutable service registration metadata.
#[derive(Debug, Clone)]
pub struct ServiceManifest {
    pub name: String,
    pub description: String,
    pub layer: ServiceLayer,
    pub required_capabilities: Vec<String>,
    pub sandbox: SandboxProfile,
}

impl ServiceManifest {
    pub fn new(
        name: &str,
        description: &str,
        layer: ServiceLayer,
        required_capabilities: Vec<String>,
        sandbox: SandboxProfile,
    ) -> Self {
        Self {
            name: name.to_string(),
            description: description.to_string(),
            layer,
            required_capabilities,
            sandbox,
        }
    }
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
    /// Layer placement for keeping AI/cognitive systems out of the kernel.
    pub layer: ServiceLayer,
    /// Runtime isolation limits.
    pub sandbox: SandboxProfile,
    /// Number of health checks performed by the supervisor.
    pub health_checks: u64,
    /// Number of restart operations requested by policy or operator action.
    pub restart_count: u64,
}

#[derive(Debug, Clone)]
pub struct ServiceHealth {
    pub total: usize,
    pub running: usize,
    pub stopped: usize,
    pub failed: usize,
    pub sandboxed: usize,
    pub restarts: u64,
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
        ("kernel.memory", "Memory Management Service", ServiceLayer::Kernel),
        ("kernel.scheduler", "Task Scheduler Service", ServiceLayer::Kernel),
        ("kernel.security", "Security Enforcement Service", ServiceLayer::Kernel),
        ("kernel.logging", "Audit Logging Service", ServiceLayer::Kernel),
        ("kernel.fs", "Filesystem Service", ServiceLayer::Kernel),
        ("runtime.ipc", "Inter-Process Communication", ServiceLayer::Runtime),
    ];

    for (name, desc, layer) in &core_services {
        let id = mgr.next_id;
        mgr.next_id += 1;
        let sandbox = if *layer == ServiceLayer::Kernel {
            SandboxProfile::kernel_trusted()
        } else {
            SandboxProfile::runtime_default()
        };
        mgr.services.push(Service {
            id,
            name: name.to_string(),
            description: desc.to_string(),
            state: ServiceState::Running,
            required_capabilities: Vec::new(),
            sandboxed: *layer != ServiceLayer::Kernel,
            layer: *layer,
            sandbox,
            health_checks: 0,
            restart_count: 0,
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

pub fn health_report() -> ServiceHealth {
    let mut mgr = MANAGER.lock();
    let mut report = ServiceHealth {
        total: mgr.services.len(),
        running: 0,
        stopped: 0,
        failed: 0,
        sandboxed: 0,
        restarts: 0,
    };

    for service in mgr.services.iter_mut() {
        service.health_checks += 1;
        match service.state {
            ServiceState::Running => report.running += 1,
            ServiceState::Stopped => report.stopped += 1,
            ServiceState::Failed => report.failed += 1,
        }
        if service.sandboxed {
            report.sandboxed += 1;
        }
        report.restarts += service.restart_count;
    }

    report
}

/// Register a new service
pub fn register_service(name: &str, description: &str, sandboxed: bool) -> u64 {
    let layer = if sandboxed {
        ServiceLayer::Runtime
    } else {
        ServiceLayer::Kernel
    };
    let sandbox = if sandboxed {
        SandboxProfile::runtime_default()
    } else {
        SandboxProfile::kernel_trusted()
    };
    register_manifest(ServiceManifest::new(
        name,
        description,
        layer,
        Vec::new(),
        sandbox,
    ))
}

/// Register a new service from an explicit manifest.
pub fn register_manifest(manifest: ServiceManifest) -> u64 {
    let mut mgr = MANAGER.lock();
    let id = mgr.next_id;
    mgr.next_id += 1;
    mgr.services.push(Service {
        id,
        name: manifest.name.clone(),
        description: manifest.description.clone(),
        state: ServiceState::Stopped,
        required_capabilities: manifest.required_capabilities.clone(),
        sandboxed: manifest.layer != ServiceLayer::Kernel,
        layer: manifest.layer,
        sandbox: manifest.sandbox,
        health_checks: 0,
        restart_count: 0,
    });

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ServiceRegistered,
        &alloc::format!("Service registered: {}", manifest.name),
    );

    id
}

/// Start a service by ID
pub fn start_service(id: u64) -> Result<(), String> {
    let held_capabilities = alloc::vec![String::from("cap:system:all")];
    start_service_authorized(id, &held_capabilities)
}

/// Start a service after checking the caller's lifecycle capabilities.
pub fn start_service_authorized(id: u64, held_capabilities: &[String]) -> Result<(), String> {
    let missing_capability = {
        let mgr = MANAGER.lock();
        let service = mgr
            .services
            .iter()
            .find(|svc| svc.id == id)
            .ok_or_else(|| String::from("service not found"))?;

        service
            .required_capabilities
            .iter()
            .find(|required| !crate::security::holds_capability_token(held_capabilities, required))
            .cloned()
    };

    if let Some(required) = missing_capability {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("Service start denied; missing {}", required),
        );
        return Err(alloc::format!("missing capability {}", required));
    }

    let started = {
        let mut mgr = MANAGER.lock();
        let mut started = false;
        for svc in mgr.services.iter_mut() {
            if svc.id == id {
                svc.state = ServiceState::Running;
                svc.health_checks += 1;
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
    let held_capabilities = alloc::vec![String::from("cap:system:all")];
    stop_service_authorized(id, &held_capabilities)
}

/// Stop a service after checking the caller's lifecycle capabilities.
pub fn stop_service_authorized(id: u64, held_capabilities: &[String]) -> Result<(), String> {
    let missing_capability = {
        let mgr = MANAGER.lock();
        let service = mgr
            .services
            .iter()
            .find(|svc| svc.id == id)
            .ok_or_else(|| String::from("service not found"))?;

        service
            .required_capabilities
            .iter()
            .find(|required| !crate::security::holds_capability_token(held_capabilities, required))
            .cloned()
    };

    if let Some(required) = missing_capability {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("Service stop denied; missing {}", required),
        );
        return Err(alloc::format!("missing capability {}", required));
    }

    let stopped = {
        let mut mgr = MANAGER.lock();
        let mut stopped = false;
        for svc in mgr.services.iter_mut() {
            if svc.id == id {
                svc.state = ServiceState::Stopped;
                svc.health_checks += 1;
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

pub fn restart_service(id: u64) -> Result<(), String> {
    let held_capabilities = alloc::vec![String::from("cap:system:all")];
    restart_service_authorized(id, &held_capabilities)
}

pub fn restart_service_authorized(id: u64, held_capabilities: &[String]) -> Result<(), String> {
    let missing_capability = {
        let mgr = MANAGER.lock();
        let service = mgr
            .services
            .iter()
            .find(|svc| svc.id == id)
            .ok_or_else(|| String::from("service not found"))?;

        service
            .required_capabilities
            .iter()
            .find(|required| !crate::security::holds_capability_token(held_capabilities, required))
            .cloned()
    };

    if let Some(required) = missing_capability {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("Service restart denied; missing {}", required),
        );
        return Err(alloc::format!("missing capability {}", required));
    }

    let restarted = {
        let mut mgr = MANAGER.lock();
        let mut restarted = false;
        for svc in mgr.services.iter_mut() {
            if svc.id == id {
                svc.state = ServiceState::Running;
                svc.restart_count += 1;
                svc.health_checks += 1;
                restarted = true;
                break;
            }
        }
        restarted
    };

    if restarted {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::ServiceStarted,
            "Service restarted",
        );
        Ok(())
    } else {
        Err(String::from("service not found"))
    }
}
