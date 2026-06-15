// ============================================================================
// FerrumOS - Userspace Process Registry
// ============================================================================
// This module models loadable userspace programs before FerrumOS has true
// ring-3 execution. It gives the kernel a concrete process/capability table
// that syscalls can authorize against.
// ============================================================================

/// Embedded `init` userspace ELF built by the workspace's `userland/init`
/// crate. Phase 1.4 will parse this binary, allocate a ring-3 address space,
/// and dispatch into its `_start` entry point. For now the bytes are kept
/// here so the build pipeline is in place and the kernel can sanity-check
/// the embedded blob.
pub const INIT_ELF: &[u8] = include_bytes!("../../userland/init/target/x86_64-unknown-none/release/init");

/// Return the size of the embedded `init` ELF in bytes. Useful for
/// boot-time sanity checks (`init_size > 0` after the userland build has
/// run at least once).
pub fn init_elf_size() -> usize {
    INIT_ELF.len()
}

pub const HELIOX_DAEMON_ELF: &[u8] = include_bytes!("../../userland/heliox-daemon/target/x86_64-unknown-none/release/heliox-daemon");

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;
use spin::Mutex;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessState {
    Ready,
    Running,
    Exited,
}

#[derive(Debug, Clone)]
pub struct ProgramManifest {
    pub name: String,
    pub description: String,
    pub entry: String,
    pub requested_capabilities: Vec<String>,
}

impl ProgramManifest {
    fn new(name: &str, description: &str, entry: &str, requested_capabilities: Vec<String>) -> Self {
        Self {
            name: name.to_string(),
            description: description.to_string(),
            entry: entry.to_string(),
            requested_capabilities,
        }
    }
}

#[derive(Debug, Clone)]
pub struct UserProcess {
    pub pid: u64,
    pub program: String,
    pub entry: String,
    pub state: ProcessState,
    pub capabilities: Vec<String>,
    pub syscall_count: u64,
}

struct UserspaceState {
    programs: Vec<ProgramManifest>,
    processes: Vec<UserProcess>,
}

static USERSPACE: Mutex<UserspaceState> = Mutex::new(UserspaceState {
    programs: Vec::new(),
    processes: Vec::new(),
});

pub fn init() {
    let mut state = USERSPACE.lock();
    state.programs.clear();
    state.processes.clear();

    state.programs.push(ProgramManifest::new(
        "init",
        "first userspace service supervisor",
        "/bin/init",
        vec![String::from("cap:system:all")],
    ));
    state.programs.push(ProgramManifest::new(
        "agent-bridge",
        "Heliox-compatible agent runtime bridge",
        "/srv/agent-bridge",
        vec![String::from("cap:ipc:send"), String::from("cap:net:connect")],
    ));
    state.programs.push(ProgramManifest::new(
        "audit-exporter",
        "exports audit events to runtime services",
        "/srv/audit-exporter",
        vec![String::from("cap:ipc:send")],
    ));
    state.programs.push(ProgramManifest::new(
        "heliox-daemon",
        "Heliox-OS native cognitive daemon",
        "/bin/heliox-daemon",
        vec![
            String::from("cap:ipc:send"),
            String::from("cap:net:connect"),
            String::from("cap:fs:read"),
            String::from("cap:fs:write"),
            String::from("cap:audio:play"),
            String::from("cap:audio:record"),
            String::from("cap:input:inject"),
            String::from("cap:camera:read"),
            String::from("cap:quota:exempt"),
        ],
    ));
}

pub fn list_programs() -> Vec<ProgramManifest> {
    USERSPACE.lock().programs.clone()
}

pub fn capabilities_for_program(name: &str) -> Vec<String> {
    let state = USERSPACE.lock();
    state.programs
        .iter()
        .find(|program| program.name == name)
        .map(|program| program.requested_capabilities.clone())
        .unwrap_or_else(Vec::new)
}


pub fn list_processes() -> Vec<UserProcess> {
    USERSPACE.lock().processes.clone()
}

pub fn bootstrap_init() -> Result<u64, String> {
    if let Some(pid) = pid_for_program("init") {
        return Ok(pid);
    }

    let held_capabilities = alloc::vec![String::from("cap:system:all")];
    let pid = launch("init", &held_capabilities)?;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ProcessSpawned,
        "userspace init bootstrapped",
    );
    Ok(pid)
}

pub fn launch(program_name: &str, caller_capabilities: &[String]) -> Result<u64, String> {
    if !crate::security::has_capability(caller_capabilities, "process:spawn") {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            "userspace launch denied; caller lacks process spawn",
        );
        return Err(String::from("missing capability process:spawn"));
    }

    let manifest = USERSPACE
        .lock()
        .programs
        .iter()
        .find(|program| program.name == program_name)
        .cloned()
        .ok_or_else(|| alloc::format!("program not found: {}", program_name))?;

    for capability in &manifest.requested_capabilities {
        if !crate::security::can_delegate(capability) {
            return Err(alloc::format!("program requests non-delegatable {}", capability));
        }
    }

    let pid = crate::scheduler::spawn_with_capabilities(
        manifest.name.clone(),
        crate::scheduler::Priority::Normal,
        &manifest.requested_capabilities,
    )?;

    USERSPACE.lock().processes.push(UserProcess {
        pid,
        program: manifest.name,
        entry: manifest.entry,
        state: ProcessState::Ready,
        capabilities: manifest.requested_capabilities,
        syscall_count: 0,
    });

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::ProcessSpawned,
        "userspace process launched",
    );

    Ok(pid)
}

pub fn pid_for_program(program_name: &str) -> Option<u64> {
    USERSPACE
        .lock()
        .processes
        .iter()
        .find(|process| process.program == program_name && process.state != ProcessState::Exited)
        .map(|process| process.pid)
}

pub fn capabilities_for(pid: u64) -> Option<Vec<String>> {
    USERSPACE
        .lock()
        .processes
        .iter()
        .find(|process| process.pid == pid)
        .map(|process| process.capabilities.clone())
}

pub fn record_syscall(pid: u64) -> Result<(), String> {
    let mut state = USERSPACE.lock();
    let process = state
        .processes
        .iter_mut()
        .find(|process| process.pid == pid)
        .ok_or_else(|| alloc::format!("unknown userspace pid {}", pid))?;

    process.syscall_count += 1;
    if process.state == ProcessState::Ready {
        process.state = ProcessState::Running;
    }
    Ok(())
}
