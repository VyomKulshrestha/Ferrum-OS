// ============================================================================
// FerrumOS - Agent Runtime Boundary
// ============================================================================
// This is not the AI agent itself. It is the deterministic service boundary
// that a future agent runtime can attach to from userspace. The Python/Tauri
// agent runtime should be ported or hosted above this boundary, never inside the
// kernel core.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec;
use spin::Mutex;

const AGENT_SERVICE: &str = "runtime.agentd";
const AGENT_CHANNEL: &str = "control";
const AGENT_RESOURCE: &str = "agent:command";
const AGENT_CONTROL_CAP: &str = "cap:agent:control";

#[derive(Debug, Clone)]
pub struct AgentStatus {
    pub service_id: Option<u64>,
    pub running: bool,
    pub commands_received: u64,
    pub last_command: String,
    pub last_response: String,
}

struct AgentState {
    service_id: Option<u64>,
    running: bool,
    commands_received: u64,
    last_command: String,
    last_response: String,
}

static AGENT: Mutex<AgentState> = Mutex::new(AgentState {
    service_id: None,
    running: false,
    commands_received: 0,
    last_command: String::new(),
    last_response: String::new(),
});

/// Register the sandboxed agent runtime service.
pub fn init() {
    let service_id = crate::services::register_manifest(crate::services::ServiceManifest::new(
        AGENT_SERVICE,
        "agent runtime boundary",
        crate::services::ServiceLayer::Runtime,
        vec![String::from(AGENT_CONTROL_CAP)],
        crate::services::SandboxProfile::runtime_default(),
    ));

    let mut agent = AGENT.lock();
    agent.service_id = Some(service_id);
    agent.last_response = String::from("agentd registered; waiting for start");
}

/// Start the agent runtime boundary.
pub fn start() -> Result<(), String> {
    let held_capabilities = vec![String::from(AGENT_CONTROL_CAP)];
    start_with_capabilities(&held_capabilities)
}

/// Start the agent runtime boundary with an explicit caller authority set.
pub fn start_with_capabilities(held_capabilities: &[String]) -> Result<(), String> {
    let service_id = AGENT
        .lock()
        .service_id
        .ok_or_else(|| String::from("agentd service not registered"))?;

    crate::services::start_service_authorized(service_id, held_capabilities)?;
    let task_id = crate::scheduler::spawn_with_capabilities(
        String::from("agentd"),
        crate::scheduler::Priority::High,
        &[String::from("cap:ipc:send")],
    )?;

    let mut agent = AGENT.lock();
    agent.running = true;
    agent.last_response = alloc::format!("agentd started as task {}", task_id);
    Ok(())
}

/// Send a command to the agent runtime boundary.
pub fn send_command(command: &str) -> Result<u64, String> {
    let held_capabilities = vec![
        String::from(AGENT_CONTROL_CAP),
        String::from("cap:ipc:send"),
    ];
    send_command_with_capabilities(command, &held_capabilities)
}

/// Send a command after checking the caller's agent-control capability.
pub fn send_command_with_capabilities(
    command: &str,
    held_capabilities: &[String],
) -> Result<u64, String> {
    if !AGENT.lock().running {
        return Err(String::from("agentd is not running"));
    }

    if !crate::security::holds_capability_token(held_capabilities, AGENT_CONTROL_CAP) {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            "agent command denied; caller lacks cap:agent:control",
        );
        return Err(String::from("missing capability cap:agent:control"));
    }

    let message = crate::ipc::Message::new(
        0,
        crate::ipc::Endpoint::new(AGENT_SERVICE, AGENT_CHANNEL),
        crate::ipc::MessageKind::Request,
        AGENT_RESOURCE,
        command.as_bytes(),
    )
    .map_err(|_| String::from("invalid agent command payload"))?;

    let id = crate::ipc::send(message, &held_capabilities)
        .map_err(|err| alloc::format!("agent IPC send failed: {:?}", err))?;

    process_pending();
    Ok(id)
}

/// Process pending agent messages.
///
/// v0.1 only acknowledges commands. Later this will call the planner,
/// orchestrator, verifier, sandbox, and memory services through userspace IPC.
pub fn process_pending() {
    while let Ok(message) = crate::ipc::receive_for_service(AGENT_SERVICE) {
        let command = core::str::from_utf8(message.payload()).unwrap_or("<non-utf8 command>");
        let mut agent = AGENT.lock();
        agent.commands_received += 1;
        agent.last_command = command.to_string();
        agent.last_response = String::from(
            "accepted by agentd boundary; planner/orchestrator not loaded yet",
        );
    }
}

/// Return agent runtime state.
pub fn status() -> AgentStatus {
    let agent = AGENT.lock();
    AgentStatus {
        service_id: agent.service_id,
        running: agent.running,
        commands_received: agent.commands_received,
        last_command: agent.last_command.clone(),
        last_response: agent.last_response.clone(),
    }
}
