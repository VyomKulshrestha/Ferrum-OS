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

/// D1 app-window framework smoke test — creates a window, presents a known
/// fill color, and echoes received input events to serial so
/// `scripts/verify_app_window.mjs` can assert the whole path end to end.
pub const GUI_SMOKE_TEST_ELF: &[u8] = include_bytes!("../../userland/gui-smoke-test/target/x86_64-unknown-none/release/gui-smoke-test");

/// Real installed apps, built on the app-window framework + libferrumgui SDK.
pub const TEXT_EDITOR_ELF: &[u8] = include_bytes!("../../userland/text-editor/target/x86_64-unknown-none/release/text-editor");
pub const CALCULATOR_ELF: &[u8] = include_bytes!("../../userland/calculator/target/x86_64-unknown-none/release/calculator");
pub const FILE_MANAGER_ELF: &[u8] = include_bytes!("../../userland/file-manager/target/x86_64-unknown-none/release/file-manager");
/// Replaces the kernel-hardcoded `WindowType::AgentHud`: setup wizard +
/// chat UI as a real app, talking to heliox-daemon over IPC instead of the
/// kernel appending telemetry text into a window it draws itself.
pub const HELIOX_ASSISTANT_PANEL_ELF: &[u8] = include_bytes!("../../userland/heliox-assistant-panel/target/x86_64-unknown-none/release/heliox-assistant-panel");
pub const SETTINGS_ELF: &[u8] = include_bytes!("../../userland/settings/target/x86_64-unknown-none/release/settings");
pub const BROWSER_ELF: &[u8] = include_bytes!("../../userland/browser/target/x86_64-unknown-none/release/browser");
pub const APP_STORE_ELF: &[u8] = include_bytes!("../../userland/app-store/target/x86_64-unknown-none/release/app-store");

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
            String::from("cap:confirmation:bypass"),
            String::from("cap:system:kexec"),
            String::from("cap:hud:overlay"),
            String::from("cap:mem:mmap"),
            String::from("cap:crypto:rng"),
            String::from("cap:net:tls"),
        ],
    ));
    state.programs.push(ProgramManifest::new(
        "gui-smoke-test",
        "D1 app-window framework smoke test",
        "/bin/gui-smoke-test",
        vec![String::from("cap:gui:window")],
    ));
    state.programs.push(ProgramManifest::new(
        "text-editor",
        "Read/write text files in a GUI window",
        "/bin/text-editor",
        vec![String::from("cap:gui:window"), String::from("cap:fs:read"), String::from("cap:fs:write")],
    ));
    state.programs.push(ProgramManifest::new(
        "calculator",
        "Basic arithmetic calculator",
        "/bin/calculator",
        vec![String::from("cap:gui:window")],
    ));
    state.programs.push(ProgramManifest::new(
        "file-manager",
        "Browse the filesystem and preview file contents",
        "/bin/file-manager",
        // Read-only: there's no argv mechanism to tell a spawned
        // text-editor which file to open, so file-manager previews
        // content in its own window instead of launching another process.
        vec![String::from("cap:gui:window"), String::from("cap:fs:read")],
    ));
    state.programs.push(ProgramManifest::new(
        "heliox-assistant-panel",
        "Chat with the Heliox agent and run its first-run setup wizard",
        "/bin/heliox-assistant-panel",
        vec![
            String::from("cap:gui:window"),
            String::from("cap:fs:read"),
            String::from("cap:fs:write"),
            String::from("cap:ipc:send"),
        ],
    ));
    state.programs.push(ProgramManifest::new(
        "settings",
        "View hardware tier and the Heliox agent's active configuration",
        "/bin/settings",
        vec![String::from("cap:gui:window"), String::from("cap:fs:read")],
    ));
    state.programs.push(ProgramManifest::new(
        "browser",
        "Minimal HTTP text browser",
        "/bin/browser",
        vec![String::from("cap:gui:window"), String::from("cap:net:connect")],
    ));
    state.programs.push(ProgramManifest::new(
        "app-store",
        "Browse and launch every app built into this image",
        "/bin/app-store",
        vec![String::from("cap:gui:window")],
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

/// Registers (or updates) a manifest entry at runtime, so a package
/// installed by ferrumpkg (src/pkg/mod.rs) can go through the same
/// `enter_registered` first-ring3-entry path every compiled-in program
/// already uses - `enter_registered` re-derives capabilities from this
/// same table via `capabilities_for_program`, which would otherwise
/// silently return empty for any name it wasn't compiled with.
pub fn register_dynamic_program(name: &str, description: &str, entry: &str, capabilities: Vec<String>) {
    let mut state = USERSPACE.lock();
    if let Some(existing) = state.programs.iter_mut().find(|p| p.name == name) {
        existing.requested_capabilities = capabilities;
    } else {
        state.programs.push(ProgramManifest::new(name, description, entry, capabilities));
    }
}

/// Un-registers a manifest entry previously added by
/// `register_dynamic_program` - called from `pkg remove` (see `cmd_pkg`
/// in `src/shell/commands.rs`) so that plain `run <name>` (`launch`,
/// below) stops finding a package after it's been removed. `pkg remove`
/// itself only ever touched ferrumpkg's own install registry, never this
/// table, which is why `run` (unlike `pkg run`) kept launching removed
/// packages (see `work.md` finding 2.2).
///
/// Only removes the entry if its `entry` path still matches
/// `expected_entry` - a guard against ever deleting a compiled-in
/// program's manifest row in the edge case where a package happens to
/// share a name with one (that program would have a different `entry`
/// path than the package's own `pkg::bin_path`, so it's left alone).
pub fn unregister_dynamic_program(name: &str, expected_entry: &str) {
    let mut state = USERSPACE.lock();
    state.programs.retain(|p| !(p.name == name && p.entry == expected_entry));
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
