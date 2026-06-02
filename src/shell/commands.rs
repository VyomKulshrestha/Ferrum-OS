// FerrumOS - Shell Commands
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use crate::println;
use spin::Mutex;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SessionProfile {
    Root,
    Guest,
}

static SESSION: Mutex<SessionProfile> = Mutex::new(SessionProfile::Root);

fn current_session() -> SessionProfile {
    *SESSION.lock()
}

fn current_capabilities() -> Vec<String> {
    match current_session() {
        SessionProfile::Root => alloc::vec![String::from("cap:system:all")],
        SessionProfile::Guest => alloc::vec![String::from("cap:fs:read")],
    }
}

fn require_resource(resource: &str) -> Result<Vec<String>, ()> {
    let held = current_capabilities();
    if crate::security::has_capability(&held, resource) {
        Ok(held)
    } else {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("shell denied resource {}", resource),
        );
        println!("permission denied: {}", resource);
        Err(())
    }
}

fn require_token(capability: &str) -> Result<Vec<String>, ()> {
    let held = current_capabilities();
    if crate::security::holds_capability_token(&held, capability) {
        Ok(held)
    } else {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!("shell missing capability {}", capability),
        );
        println!("permission denied: {}", capability);
        Err(())
    }
}

/// Execute a shell command
pub fn execute(input: &str) {
    let parts: Vec<&str> = input.split_whitespace().collect();
    if parts.is_empty() {
        return;
    }
    
    let command = parts[0];
    let args = &parts[1..];
    
    match command {
        "help" => cmd_help(),
        "clear" => cmd_clear(),
        "echo" => cmd_echo(args),
        "ps" => cmd_ps(),
        "mem" => cmd_mem(),
        "ls" => cmd_ls(args),
        "cat" => cmd_cat(args),
        "stat" => cmd_stat(args),
        "mounts" => cmd_mounts(),
        "mkdir" => cmd_mkdir(args),
        "touch" => cmd_touch(args),
        "write" => cmd_write(args),
        "rm" => cmd_rm(args),
        "devices" => cmd_devices(),
        "caps" => cmd_caps(),
        "services" => cmd_services(args),
        "ipc" => cmd_ipc(),
        "syscalls" => cmd_syscalls(),
        "programs" => cmd_programs(),
        "users" => cmd_users(),
        "run" => cmd_run(args),
        "syscall" => cmd_syscall(args),
        "agent" => cmd_agent(args),
        "log" => cmd_log(),
        "uptime" => cmd_uptime(),
        "uname" => cmd_uname(),
        "whoami" => cmd_whoami(),
        "session" => cmd_session(args),
        "spawn" => cmd_spawn(args),
        "kill" => cmd_kill(args),
        "security" => cmd_security(),
        "about" => cmd_about(),
        _ => println!("FerrumOS: command not found: {}", command),
    }
}

fn cmd_help() {
    println!("FerrumOS Shell Commands:");
    println!("  help       Show this help message");
    println!("  clear      Clear the screen");
    println!("  echo       Print arguments to screen");
    println!("  ps         List running tasks");
    println!("  mem        Show memory usage");
    println!("  ls [path]  List directory contents");
    println!("  cat <file> Display file contents");
    println!("  stat <p>   Show filesystem metadata");
    println!("  mounts     Show mounted filesystems");
    println!("  mkdir <d>  Create a directory");
    println!("  touch <f>  Create an empty file");
    println!("  write <f> <text>  Write text to file");
    println!("  rm <path>  Remove file or directory");
    println!("  devices    List kernel-visible device surfaces");
    println!("  caps       Show capability tokens");
    println!("  services   List/start/stop registered services");
    println!("  ipc        Show IPC broker statistics");
    println!("  syscalls   Show syscall ABI numbers");
    println!("  programs   List userspace program manifests");
    println!("  users      List userspace process table");
    println!("  run <p>    Launch a userspace program");
    println!("  syscall <pid> <num> [arg0]  Dispatch a userspace syscall");
    println!("  agent      Control the agent runtime boundary");
    println!("  log        Show recent audit log");
    println!("  uptime     Show system uptime (ticks)");
    println!("  uname      Show system information");
    println!("  whoami     Show current identity");
    println!("  session    Switch debug shell capability profile");
    println!("  spawn <n>  Spawn a new task");
    println!("  kill <id>  Kill a task by ID");
    println!("  security   Show security status");
    println!("  about      About FerrumOS");
}

fn cmd_clear() {
    crate::vga::WRITER.lock().clear_screen();
}

fn cmd_echo(args: &[&str]) {
    println!("{}", args.join(" "));
}

fn cmd_ps() {
    let tasks = crate::scheduler::list_tasks();
    println!("  PID  STATE    PRIO     TICKS  NAME");
    println!("  ---  -----    ----     -----  ----");
    for task in &tasks {
        let state = match task.state {
            crate::scheduler::TaskState::Ready => "READY  ",
            crate::scheduler::TaskState::Running => "RUNNING",
            crate::scheduler::TaskState::Blocked => "BLOCKED",
            crate::scheduler::TaskState::Dead => "DEAD   ",
        };
        let prio = match task.priority {
            crate::scheduler::Priority::Idle => "idle  ",
            crate::scheduler::Priority::Normal => "normal",
            crate::scheduler::Priority::High => "high  ",
            crate::scheduler::Priority::System => "system",
        };
        println!("  {:>3}  {}  {}  {:>7}  {}", task.id, state, prio, task.ticks, task.name);
    }
    println!("\nTotal tasks: {}", tasks.len());
}

fn cmd_mem() {
    let (used, free) = crate::memory::heap::heap_stats();
    let total = crate::memory::heap::HEAP_SIZE;
    let pct = (used * 100) / total;
    println!("Kernel Heap Memory:");
    println!("  Total:  {} bytes ({} KiB)", total, total / 1024);
    println!("  Used:   {} bytes ({} KiB) [{}%]", used, used / 1024, pct);
    println!("  Free:   {} bytes ({} KiB)", free, free / 1024);
}

fn cmd_ls(args: &[&str]) {
    if require_resource("fs:read:*").is_err() {
        return;
    }

    let path = if args.is_empty() { "/" } else { args[0] };
    match crate::fs::list_dir(path) {
        Ok(entries) => {
            if entries.is_empty() {
                println!("(empty directory)");
            } else {
                for entry in entries {
                    let type_str = if entry.is_dir { "DIR " } else { "FILE" };
                    println!("  {} {:>6}  {}", type_str, entry.size, entry.name);
                }
            }
        }
        Err(e) => println!("ls: {}", e),
    }
}

fn cmd_cat(args: &[&str]) {
    if require_resource("fs:read:*").is_err() {
        return;
    }

    if args.is_empty() {
        println!("cat: missing file argument");
        return;
    }
    match crate::fs::read_file(args[0]) {
        Ok(content) => println!("{}", content),
        Err(e) => println!("cat: {}", e),
    }
}

fn cmd_stat(args: &[&str]) {
    if require_resource("fs:read:*").is_err() {
        return;
    }

    let path = if args.is_empty() { "/" } else { args[0] };
    match crate::fs::stat(path) {
        Ok(stat) => {
            let kind = if stat.is_dir { "directory" } else { "file" };
            println!("Filesystem Stat:");
            println!("  Path:     {}", stat.path);
            println!("  Type:     {}", kind);
            println!("  Size:     {} bytes", stat.size);
            println!("  Children: {}", stat.children);
        }
        Err(err) => println!("stat: {}", err),
    }
}

fn cmd_mounts() {
    if require_resource("fs:read:*").is_err() {
        return;
    }

    match crate::fs::usage() {
        Ok(usage) => {
            println!("Mount Table:");
            for mount in crate::fs::mounts() {
                println!(
                    "  {} on {} type {} ({})",
                    mount.device,
                    mount.path,
                    mount.fs_type,
                    mount.flags
                );
            }
            println!(
                "Usage: {} files, {} directories, {} bytes",
                usage.files,
                usage.directories,
                usage.bytes
            );
        }
        Err(err) => println!("mounts: {}", err),
    }
}

fn cmd_mkdir(args: &[&str]) {
    if require_resource("fs:write:*").is_err() {
        return;
    }

    if args.is_empty() {
        println!("mkdir: missing directory name");
        return;
    }
    match crate::fs::create_dir(args[0]) {
        Ok(()) => println!("Directory created: {}", args[0]),
        Err(e) => println!("mkdir: {}", e),
    }
}

fn cmd_touch(args: &[&str]) {
    if require_resource("fs:write:*").is_err() {
        return;
    }

    if args.is_empty() {
        println!("touch: missing file name");
        return;
    }
    match crate::fs::create_file(args[0], "") {
        Ok(()) => {},
        Err(e) => println!("touch: {}", e),
    }
}

fn cmd_write(args: &[&str]) {
    if require_resource("fs:write:*").is_err() {
        return;
    }

    if args.len() < 2 {
        println!("write: usage: write <file> <text>");
        return;
    }
    let content = args[1..].join(" ");
    match crate::fs::create_file(args[0], &content) {
        Ok(()) => println!("Written to {}", args[0]),
        Err(e) => println!("write: {}", e),
    }
}

fn cmd_rm(args: &[&str]) {
    if require_resource("fs:write:*").is_err() {
        return;
    }

    if args.is_empty() {
        println!("rm: missing path");
        return;
    }
    match crate::fs::remove(args[0]) {
        Ok(()) => println!("Removed: {}", args[0]),
        Err(e) => println!("rm: {}", e),
    }
}

fn cmd_devices() {
    let devices = crate::devices::list_devices();
    let online = crate::devices::device_count_by_state(crate::devices::DeviceState::Online);
    let planned = crate::devices::device_count_by_state(crate::devices::DeviceState::Planned);

    println!("Device Registry:");
    println!("  Online:  {}", online);
    println!("  Planned: {}", planned);
    println!("  ID  STATE    CLASS    DRIVER        NAME");
    println!("  --  -----    -----    ------        ----");
    for device in &devices {
        let state = match device.state {
            crate::devices::DeviceState::Online => "ONLINE ",
            crate::devices::DeviceState::Planned => "PLANNED",
            crate::devices::DeviceState::Disabled => "DISABLE",
        };
        let class = match device.class {
            crate::devices::DeviceClass::Display => "display",
            crate::devices::DeviceClass::Serial => "serial ",
            crate::devices::DeviceClass::Input => "input  ",
            crate::devices::DeviceClass::Timer => "timer  ",
            crate::devices::DeviceClass::Storage => "storage",
            crate::devices::DeviceClass::Network => "network",
            crate::devices::DeviceClass::Audio => "audio  ",
            crate::devices::DeviceClass::Camera => "camera ",
        };
        println!(
            "  {:>2}  {}  {}  {:<12}  {}",
            device.id,
            state,
            class,
            device.driver,
            device.name
        );
        println!("      cap: {}", device.capability);
    }
}

fn cmd_caps() {
    let caps = crate::security::list_capabilities();
    println!("Registered Capabilities:");
    for cap in &caps {
        println!("  [{}] {} - {}", cap.id, cap.name, cap.description);
    }
}

fn cmd_services(args: &[&str]) {
    if !args.is_empty() {
        match args[0] {
            "start" => {
                if args.len() < 2 {
                    println!("services start: missing service id");
                    return;
                }
                match args[1].parse::<u64>() {
                    Ok(id) => {
                        let Ok(held) = require_token("cap:service:register") else {
                            return;
                        };
                        match crate::services::start_service_authorized(id, &held) {
                            Ok(()) => println!("service {} started", id),
                            Err(err) => println!("services start: {}", err),
                        }
                    }
                    Err(_) => println!("services start: invalid service id"),
                }
            }
            "stop" => {
                if args.len() < 2 {
                    println!("services stop: missing service id");
                    return;
                }
                match args[1].parse::<u64>() {
                    Ok(id) => {
                        let Ok(held) = require_token("cap:service:register") else {
                            return;
                        };
                        match crate::services::stop_service_authorized(id, &held) {
                            Ok(()) => println!("service {} stopped", id),
                            Err(err) => println!("services stop: {}", err),
                        }
                    }
                    Err(_) => println!("services stop: invalid service id"),
                }
            }
            _ => println!("services: usage: services [start|stop] <id>"),
        }
        return;
    }

    let services = crate::services::list_services();
    println!("Registered Services:");
    if services.is_empty() {
        println!("  (no services registered)");
    } else {
        for svc in &services {
            let state = match svc.state {
                crate::services::ServiceState::Stopped => "STOPPED",
                crate::services::ServiceState::Running => "RUNNING",
                crate::services::ServiceState::Failed => "FAILED ",
            };
            let layer = match svc.layer {
                crate::services::ServiceLayer::Kernel => "kernel",
                crate::services::ServiceLayer::Runtime => "runtime",
                crate::services::ServiceLayer::Cognitive => "cognitive",
                crate::services::ServiceLayer::Agent => "agent",
            };
            let sandbox = if svc.sandboxed { "sandbox" } else { "trusted" };
            println!(
                "  [{}] {} {:>9} {:>7} - {} ({})",
                svc.id,
                state,
                layer,
                sandbox,
                svc.name,
                svc.description
            );
            if !svc.required_capabilities.is_empty() {
                println!("       caps: {}", svc.required_capabilities.join(", "));
            }
        }
    }
}

fn cmd_ipc() {
    let stats = crate::ipc::stats();
    println!("IPC Broker:");
    println!("  Queued:   {}", stats.queued);
    println!("  Sent:     {}", stats.sent);
    println!("  Received: {}", stats.received);
    println!("  Denied:   {}", stats.denied);
}

fn cmd_syscalls() {
    println!("Syscall ABI:");
    println!("  0  yield");
    println!("  1  ipc_send");
    println!("  2  ipc_receive");
    println!("  3  service_start");
    println!("  4  service_stop");
    println!("  5  capability_check");
    println!("  6  audit_write");
    println!("Capability resources:");
    println!("  1  ipc:send:*");
    println!("  2  service:register");
    println!("  3  audit:read");
    println!("  4  process:spawn");
    println!("Status: process capability dispatch active");
}

fn cmd_programs() {
    let programs = crate::userspace::list_programs();
    println!("Userspace Programs:");
    for program in &programs {
        println!("  {} - {} ({})", program.name, program.description, program.entry);
        if !program.requested_capabilities.is_empty() {
            println!("       caps: {}", program.requested_capabilities.join(", "));
        }
    }
}

fn cmd_users() {
    let processes = crate::userspace::list_processes();
    println!("Userspace Processes:");
    if processes.is_empty() {
        println!("  (none)");
        return;
    }

    println!("  PID  STATE    SYSCALLS  PROGRAM");
    println!("  ---  -----    --------  -------");
    for process in &processes {
        let state = match process.state {
            crate::userspace::ProcessState::Ready => "READY  ",
            crate::userspace::ProcessState::Running => "RUNNING",
            crate::userspace::ProcessState::Exited => "EXITED ",
        };
        println!(
            "  {:>3}  {}  {:>8}  {}",
            process.pid,
            state,
            process.syscall_count,
            process.program
        );
        if !process.capabilities.is_empty() {
            println!("       caps: {}", process.capabilities.join(", "));
        }
    }
}

fn cmd_run(args: &[&str]) {
    if args.is_empty() {
        println!("run: missing program name");
        return;
    }

    let Ok(held) = require_resource("process:spawn") else {
        return;
    };

    match crate::userspace::launch(args[0], &held) {
        Ok(pid) => println!("launched {} as userspace pid {}", args[0], pid),
        Err(err) => println!("run: {}", err),
    }
}

fn cmd_syscall(args: &[&str]) {
    if args.len() < 2 {
        println!("syscall: usage: syscall <pid> <number> [arg0]");
        return;
    }

    let Ok(pid) = args[0].parse::<u64>() else {
        println!("syscall: invalid pid");
        return;
    };
    let Ok(number) = args[1].parse::<u64>() else {
        println!("syscall: invalid number");
        return;
    };
    let arg0 = args
        .get(2)
        .and_then(|arg| arg.parse::<u64>().ok())
        .unwrap_or(0);

    let result = crate::syscall::dispatch_for_process(pid, number, [arg0, 0, 0, 0, 0, 0]);
    println!("syscall result: {:?} value={}", result.status, result.value);
}

fn cmd_agent(args: &[&str]) {
    if args.is_empty() {
        println!("agent: usage: agent <status|start|send>");
        return;
    }

    match args[0] {
        "status" => {
            let status = crate::agent::status();
            println!("Agent Runtime Boundary:");
            match status.service_id {
                Some(id) => println!("  Service ID: {}", id),
                None => println!("  Service ID: none"),
            }
            println!("  Running:    {}", status.running);
            println!("  Commands:   {}", status.commands_received);
            if !status.last_command.is_empty() {
                println!("  Last command:  {}", status.last_command);
            }
            if !status.last_response.is_empty() {
                println!("  Last response: {}", status.last_response);
            }
        }
        "start" => {
            let Ok(held) = require_token("cap:agent:control") else {
                return;
            };
            match crate::agent::start_with_capabilities(&held) {
                Ok(()) => println!("agentd started"),
                Err(err) => println!("agent start: {}", err),
            }
        }
        "send" => {
            let Ok(mut held) = require_token("cap:agent:control") else {
                return;
            };
            if !held.iter().any(|cap| cap == "cap:system:all") {
                held.push(String::from("cap:ipc:send"));
            }
            if args.len() < 2 {
                println!("agent send: missing command text");
                return;
            }
            let command = args[1..].join(" ");
            match crate::agent::send_command_with_capabilities(&command, &held) {
                Ok(id) => println!("agent command queued as IPC message {}", id),
                Err(err) => println!("agent send: {}", err),
            }
        }
        _ => println!("agent: unknown subcommand '{}'", args[0]),
    }
}

fn cmd_log() {
    if require_resource("audit:read").is_err() {
        return;
    }

    let entries = crate::logging::audit::recent_entries(10);
    println!("Recent Audit Log ({} entries):", entries.len());
    for entry in &entries {
        println!("  [{}] {:?}: {}", entry.tick, entry.event, entry.message);
    }
}

fn cmd_uptime() {
    let ticks = crate::scheduler::total_ticks();
    // PIT fires ~18.2 times per second
    let seconds = ticks / 18;
    let minutes = seconds / 60;
    println!("Uptime: {} ticks (~{}m {}s)", ticks, minutes, seconds % 60);
}

fn cmd_uname() {
    println!("FerrumOS v0.1.0 x86_64 (Rust nightly)");
    println!("AI-Native Autonomous OS Foundation");
    println!("Kernel: microkernel-inspired, capability-based");
}

fn cmd_whoami() {
    match current_session() {
        SessionProfile::Root => println!("kernel (uid=0, gid=0)"),
        SessionProfile::Guest => println!("guest (uid=1000, gid=1000)"),
    }
    println!("Capabilities: {}", current_capabilities().join(", "));
}

fn cmd_session(args: &[&str]) {
    if args.is_empty() {
        let name = match current_session() {
            SessionProfile::Root => "root",
            SessionProfile::Guest => "guest",
        };
        println!("Current session: {}", name);
        println!("Profiles: root, guest");
        return;
    }

    match args[0] {
        "root" => {
            *SESSION.lock() = SessionProfile::Root;
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::CapabilityGranted,
                "debug shell switched to root profile",
            );
            println!("session switched to root");
        }
        "guest" => {
            *SESSION.lock() = SessionProfile::Guest;
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::CapabilityRevoked,
                "debug shell switched to guest profile",
            );
            println!("session switched to guest");
        }
        _ => println!("session: usage: session [root|guest]"),
    }
}

fn cmd_spawn(args: &[&str]) {
    if require_resource("process:spawn").is_err() {
        return;
    }

    let name = if args.is_empty() { "user_task" } else { args[0] };
    let id = crate::scheduler::spawn(
        String::from(name),
        crate::scheduler::Priority::Normal,
    );
    println!("Spawned task '{}' with PID {}", name, id);
}

fn cmd_kill(args: &[&str]) {
    if require_resource("process:kill:*").is_err() {
        return;
    }

    if args.is_empty() {
        println!("kill: missing PID");
        return;
    }
    if let Ok(id) = args[0].parse::<u64>() {
        if crate::scheduler::kill(id) {
            println!("Killed task {}", id);
        } else {
            println!("kill: no task with PID {}", id);
        }
    } else {
        println!("kill: invalid PID");
    }
}

fn cmd_security() {
    println!("Security Status:");
    println!("  Model:      Capability-based");
    println!("  Default:    Deny-all");
    println!("  Sandbox:    Enabled");
    println!("  Audit Log:  Active");
    let caps = crate::security::list_capabilities();
    println!("  Capabilities: {} registered", caps.len());
    let entries = crate::logging::audit::recent_entries(100);
    println!("  Audit Events: {} recorded", entries.len());
    let session = match current_session() {
        SessionProfile::Root => "root",
        SessionProfile::Guest => "guest",
    };
    println!("  Shell Session: {}", session);
}

fn cmd_about() {
    println!("FerrumOS v0.1.0");
    println!("A minimal modular Rust-based operating system designed as");
    println!("the foundation for an AI-native autonomous computing environment.");
    println!();
    println!("Architecture Layers:");
    println!("  [Kernel]    Scheduling, Memory, Isolation, HAL");
    println!("  [Runtime]   Services, Permissions, IPC");
    println!("  [Cognitive] Semantic Memory, Vector Search (future)");
    println!("  [Agent]     Autonomous Workflows, Planning (future)");
    println!();
    println!("Built with Rust for safety, performance, and fearless concurrency.");
}
