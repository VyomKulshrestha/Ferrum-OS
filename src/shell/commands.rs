// FerrumOS - Shell Commands
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use crate::println;
use crate::print;
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
        "mount" => cmd_mounts(),
        "sync" => cmd_sync(),
        "mkdir" => cmd_mkdir(args),
        "touch" => cmd_touch(args),
        "write" => cmd_write(args),
        "rm" => cmd_rm(args),
        "devices" => cmd_devices(),
        "net" => cmd_net(args),
        "caps" => cmd_caps(),
        "services" => cmd_services(args),
        "ipc" => cmd_ipc(),
        "syscalls" => cmd_syscalls(),
        "programs" => cmd_programs(),
        "users" => cmd_users(),
        "run" => cmd_run(args),
        "syscall" => cmd_syscall(args),
        "agent" => cmd_agent(args),
        "heliox" => cmd_heliox(args),
        "desktop" => {
            if crate::gui::is_active() {
                println!("Desktop is already running.");
            } else {
                crate::gui::run_desktop();
            }
        }
        "elf" => cmd_elf(args),
        "process" => cmd_process(args),
        "ring3" => cmd_ring3(args),
        "log" => cmd_log(),
        "uptime" => cmd_uptime(),
        "scheduler" => cmd_scheduler(args),
        "test-syscall" => cmd_test_syscall(args),
        "uname" => cmd_uname(),
        "whoami" => cmd_whoami(),
        "session" => cmd_session(args),
        "spawn" => cmd_spawn(args),
        "kill" => cmd_kill(args),
        "security" => cmd_security(),
        "about" => cmd_about(),
        "disk" => cmd_disk(args),
        "dashboard" => super::dashboard::run_dashboard(),
        _ => println!("FerrumOS: command not found: {}", command),
    }
}

fn cmd_help() {
    println!("FerrumOS Shell Commands:");
    println!("  help       Show this help message");
    println!("  clear      Clear the screen");
    println!("  desktop    Launch GUI Desktop Environment");
    println!("  echo       Print arguments to screen");
    println!("  ps         List running tasks");
    println!("  mem        Show memory usage");
    println!("  ls [path]  List directory contents");
    println!("  cat <file> Display file contents");
    println!("  stat <p>   Show filesystem metadata");
    println!("  mounts     Show mounted filesystems");
    println!("  sync       Synchronize dirty filesystem data to disk");
    println!("  mkdir <d>  Create a directory");
    println!("  touch <f>  Create an empty file");
    println!("  write <f> <text>  Write text to file");
    println!("  rm <path>  Remove file or directory");
    println!("  devices    List kernel-visible device surfaces");
    println!("  net        Show network interfaces and loopback state");
    println!("  caps       Show capability tokens");
    println!("  services   List/start/stop/restart service registry");
    println!("  ipc        Show IPC broker statistics");
    println!("  syscalls   Show syscall ABI numbers");
    println!("  programs   List userspace program manifests");
    println!("  users      List userspace process table");
    println!("  run <p>    Launch a userspace program");
    println!("  syscall <pid> <num> [arg0]  Dispatch a userspace syscall");
    println!("  agent      Control the agent runtime boundary");
    println!("  heliox     Heliox-OS JSON-RPC bridge surface");
    println!("  elf        Inspect the embedded userspace init ELF");
    println!("  process    List per-process address spaces");
    println!("  ring3 <pid|init>  Enter ring-3 in the given process");
    println!("  log        Show recent audit log");
    println!("  uptime     Show system uptime (ticks)");
    println!("  scheduler  Show Phase 2 scheduler state");
    println!("  test-syscall <yield|sleep|wait|priority>  Exercise Phase 2 syscalls");
    println!("  uname      Show system information");
    println!("  whoami     Show current identity");
    println!("  session    Switch debug shell capability profile");
    println!("  spawn <n>  Spawn a new task");
    println!("  kill <id>  Kill a task by ID");
    println!("  security   Show security status");
    println!("  about      About FerrumOS");
    println!("  disk       List ATA drives or read sectors");
    println!("  dashboard  Full-screen system status dashboard");
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

fn cmd_sync() {
    if require_resource("fs:write:*").is_err() {
        return;
    }

    println!("Syncing filesystems...");
    match crate::fs::sync() {
        Ok(()) => println!("Filesystems synchronized successfully."),
        Err(err) => println!("sync error: {}", err),
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

fn cmd_net(args: &[&str]) {
    if args.first() == Some(&"send") {
        let Ok(held) = require_resource("net:connect:*") else {
            return;
        };
        let payload = if args.len() > 1 {
            args[1..].join(" ")
        } else {
            String::from("ping")
        };
        match crate::net::send_loopback(&payload, &held) {
            Ok(()) => println!("loopback packet delivered"),
            Err(err) => println!("net send: {}", err),
        }
        return;
    }

    let stats = crate::net::stats();
    println!("Network:");
    println!("  Interfaces: {}", stats.interfaces);
    println!("  Routes:     {}", stats.routes);
    println!("  Sent:       {}", stats.packets_sent);
    println!("  Received:   {}", stats.packets_received);
    println!("  Denied:     {}", stats.denied);
    println!("Interfaces:");
    for interface in crate::net::interfaces() {
        let state = match interface.state {
            crate::net::InterfaceState::Up => "UP     ",
            crate::net::InterfaceState::Down => "DOWN   ",
            crate::net::InterfaceState::Planned => "PLANNED",
        };
        println!(
            "  {} {} {} {}",
            interface.name,
            state,
            interface.address,
            interface.driver
        );
    }
    println!("Routes:");
    for route in crate::net::routes() {
        println!(
            "  {} via {} dev {}",
            route.destination,
            route.gateway,
            route.interface
        );
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
            "health" => {
                let report = crate::services::health_report();
                println!("Service Health:");
                println!("  Total:     {}", report.total);
                println!("  Running:   {}", report.running);
                println!("  Stopped:   {}", report.stopped);
                println!("  Failed:    {}", report.failed);
                println!("  Sandboxed: {}", report.sandboxed);
                println!("  Restarts:  {}", report.restarts);
            }
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
            "restart" => {
                if args.len() < 2 {
                    println!("services restart: missing service id");
                    return;
                }
                match args[1].parse::<u64>() {
                    Ok(id) => {
                        let Ok(held) = require_token("cap:service:register") else {
                            return;
                        };
                        match crate::services::restart_service_authorized(id, &held) {
                            Ok(()) => println!("service {} restarted", id),
                            Err(err) => println!("services restart: {}", err),
                        }
                    }
                    Err(_) => println!("services restart: invalid service id"),
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
            _ => println!("services: usage: services [health|start|stop|restart] <id>"),
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
            println!(
                "       health checks: {} restarts: {}",
                svc.health_checks,
                svc.restart_count
            );
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
    let tasks = crate::scheduler::list_tasks();
    println!("Active Scheduler Tasks:");
    if tasks.is_empty() {
        println!("  (none)");
        return;
    }

    println!("  PID  STATE    AFFINITY  PARENT  NAME");
    println!("  ---  -----    --------  ------  ----");
    for task in &tasks {
        let state = match task.state {
            crate::scheduler::TaskState::Ready => "READY  ",
            crate::scheduler::TaskState::Running => "RUNNING",
            crate::scheduler::TaskState::Blocked => "BLOCKED",
            crate::scheduler::TaskState::Dead => "DEAD   ",
        };
        let affinity = match task.cpu_affinity {
            Some(aff) => alloc::format!("{}", aff),
            None => alloc::string::String::from("any"),
        };
        let parent = match task.parent_id {
            Some(p) => alloc::format!("{}", p),
            None => alloc::string::String::from("none"),
        };
        println!(
            "  {:>3}  {}  {:>8}  {:>6}  {}",
            task.id,
            state,
            affinity,
            parent,
            task.name
        );
        if !task.capabilities.is_empty() {
            println!("       caps: {}", task.capabilities.join(", "));
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

fn cmd_heliox(args: &[&str]) {
    if args.is_empty() {
        println!("heliox: usage: heliox <status|methods|tiers|actions|services|send|notif|persona|screen|voice|confirm|execute>");
        return;
    }

    match args[0] {
        "status" => cmd_heliox_status(),
        "methods" => cmd_heliox_methods(),
        "tiers" => cmd_heliox_tiers(),
        "actions" => cmd_heliox_actions(),
        "services" => cmd_heliox_services(),
        "send" => cmd_heliox_send(&args[1..]),
        "notif" => cmd_heliox_notif(&args[1..]),
        "persona" => cmd_heliox_persona(&args[1..]),
        "screen" => cmd_heliox_screen(&args[1..]),
        "voice" => cmd_heliox_voice(&args[1..]),
        "confirm" => cmd_heliox_confirm(&args[1..]),
        "execute" => cmd_heliox_execute(&args[1..]),
        _ => println!(
            "heliox: unknown subcommand '{}' (try status, methods, tiers, actions, services, send, notif, persona, screen, voice, confirm, execute)",
            args[0]
        ),
    }
}

fn cmd_heliox_status() {
    use crate::heliox;
    let status = heliox::status();
    println!("Heliox-OS Integration Bridge:");
    println!("  Transport:    {}", status.transport);
    println!("  Protocol:     {}", status.protocol);
    println!("  Version:      {}", status.version);
    println!("  Services:     {}", status.services_registered);
    println!("  Methods:      {} (JSON-RPC 2.0 over WebSocket)", status.methods);
    println!("  Actions:      {} (5-tier permission model)", status.actions);
    println!("  Envelopes:    {} (invoked {}, denied {})",
        status.envelopes_seen, status.methods_invoked, status.methods_denied);
    println!("  Voice listener: {} (events={}, commands={})",
        status.voice_listener.name(), status.voice_events, status.voice_commands);
    println!("  Gesture events: {}", status.gesture_events);
    println!("  Multimodal intents: {}", status.multimodal_intents);
    println!("  Screen vision: {:?}", status.screen_vision);
    println!("  Screen frames: {}", status.screen_frames);
    println!("  Persona rules: {}", status.persona_rules);
    println!("  Pending confirmations: {}", status.pending_confirmations);
    if let Some(phase) = status.last_pipeline_phase {
        println!("  Last pipeline phase: {}", phase.name());
    }
}

fn cmd_heliox_methods() {
    use crate::heliox;
    let methods = heliox::list_methods();
    let request_count = heliox::method_count_by_class(crate::heliox::MethodClass::Request);
    let notif_count = heliox::method_count_by_class(crate::heliox::MethodClass::Notification);
    println!("Heliox JSON-RPC Methods ({}):", methods.len());
    println!("  requests:     {}", request_count);
    println!("  notifications:{}", notif_count);
    println!("  NAME                              CLASS         CAPABILITY");
    println!("  ----                              -----         ----------");
    for method in &methods {
        let class = match method.class {
            crate::heliox::MethodClass::Request => "request",
            crate::heliox::MethodClass::Notification => "notif",
        };
        println!("  {:<32}  {:<11}  {}", method.name, class, method.required_capability);
    }
}

fn cmd_heliox_tiers() {
    use crate::heliox;
    let categories = heliox::list_action_categories();
    println!("Heliox Permission Tiers:");
    for category in &categories {
        println!(
            "  {} (auto-exec={}): {} actions",
            category.tier.name(),
            !category.tier.requires_confirmation(),
            category.actions.len()
        );
    }
    println!("  Total action types: {}", heliox::action_count());
}

fn cmd_heliox_actions() {
    use crate::heliox;
    let categories = heliox::list_action_categories();
    println!("Heliox Action Catalog:");
    for category in &categories {
        println!("[{}] {} ({} actions)",
            category.tier.index(),
            category.tier.name(),
            category.actions.len());
        for action in category.actions {
            println!("  {}", action);
        }
    }
}

fn cmd_heliox_services() {
    use crate::heliox;
    let slots = heliox::runtime_slots();
    println!("Heliox Runtime Service Slots:");
    for slot in &slots {
        match crate::services::find_service(slot.name) {
            Some(svc) => {
                let state = match svc.state {
                    crate::services::ServiceState::Running => "RUNNING",
                    crate::services::ServiceState::Stopped => "STOPPED",
                    crate::services::ServiceState::Failed => "FAILED ",
                };
                println!("  [{}] {} {} - {}", svc.id, state, slot.name, slot.description);
            }
            None => {
                println!("  [?] (not registered) {} - {}", slot.name, slot.description);
            }
        }
    }
}

fn cmd_heliox_send(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        println!("heliox send: usage: heliox send <method> [input]");
        return;
    }
    let method = args[0];
    let input = if args.len() > 1 { args[1..].join(" ") } else { String::new() };
    let Ok(held) = require_token("cap:heliox:bridge") else {
        return;
    };
    match heliox::submit_request(method, &input, &held) {
        Ok(envelope) => println!(
            "heliox envelope dispatched: {} kind={} id={}",
            envelope.method,
            envelope.kind_name(),
            envelope.id
        ),
        Err(err) => println!("heliox send: {}", err),
    }
}

fn cmd_heliox_notif(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        println!("heliox notif: usage: heliox notif <method>");
        return;
    }
    let method = args[0];
    if require_token("cap:heliox:bridge").is_err() {
        return;
    }
    match heliox::submit_notification(method) {
        Ok(envelope) => println!(
            "heliox notification prepared: {} (id={})",
            envelope.method, envelope.id
        ),
        Err(err) => println!("heliox notif: {}", err),
    }
}

fn cmd_heliox_persona(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        let rules = heliox::persona_rules();
        println!("Heliox Persona Rules ({}):", rules.len());
        for rule in &rules {
            println!(
                "  [{:?}] {} = {} (confidence {}%)",
                rule.category, rule.key, rule.value, rule.confidence
            );
        }
        return;
    }
    match args[0] {
        "add" => {
            let payload = if args.len() > 1 { args[1..].join(" ") } else { String::new() };
            if payload.is_empty() {
                println!("heliox persona add: usage: heliox persona add <key>=<value>");
                return;
            }
            let Ok(held) = require_token("cap:heliox:persona") else {
                return;
            };
            match heliox::submit_request("persona_add_preference", &payload, &held) {
                Ok(envelope) => println!("persona rule recorded (envelope id={})", envelope.id),
                Err(err) => println!("heliox persona add: {}", err),
            }
        }
        _ => println!("heliox persona: usage: heliox persona [add <key>=<value>]"),
    }
}

fn cmd_heliox_screen(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        let status = heliox::status();
        println!("Heliox Screen Vision: {:?}", status.screen_vision);
        println!("  Frames captured: {}", status.screen_frames);
        return;
    }
    match args[0] {
        "on" => {
            let Ok(held) = require_token("cap:heliox:screen") else {
                return;
            };
            let result = heliox::submit_request("screen_vision_toggle", "on", &held);
            match result {
                Ok(_) => println!("heliox screen vision enabled"),
                Err(err) => println!("heliox screen on: {}", err),
            }
        }
        "off" => {
            let Ok(held) = require_token("cap:heliox:screen") else {
                return;
            };
            let result = heliox::submit_request("screen_vision_toggle", "off", &held);
            match result {
                Ok(_) => println!("heliox screen vision disabled"),
                Err(err) => println!("heliox screen off: {}", err),
            }
        }
        "context" => {
            let Ok(held) = require_token("cap:heliox:screen") else {
                return;
            };
            let result = heliox::submit_request("screen_context", "active window", &held);
            match result {
                Ok(envelope) => println!("screen_context envelope id={}", envelope.id),
                Err(err) => println!("heliox screen context: {}", err),
            }
        }
        _ => println!("heliox screen: usage: heliox screen [on|off|context]"),
    }
}

fn cmd_heliox_voice(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        let status = heliox::status();
        println!("Heliox Voice Listener: {}", status.voice_listener.name());
        println!("  Events: {}", status.voice_events);
        println!("  Commands: {}", status.voice_commands);
        return;
    }
    match args[0] {
        "start" => {
            let Ok(held) = require_token("cap:heliox:voice") else {
                return;
            };
            match heliox::submit_request("voice_listener_start", "hey heliox", &held) {
                Ok(_) => println!("heliox voice listener started"),
                Err(err) => println!("heliox voice start: {}", err),
            }
        }
        "stop" => {
            let Ok(held) = require_token("cap:heliox:voice") else {
                return;
            };
            match heliox::submit_request("voice_listener_stop", "", &held) {
                Ok(_) => println!("heliox voice listener stopped"),
                Err(err) => println!("heliox voice stop: {}", err),
            }
        }
        "event" => {
            if args.len() < 2 {
                println!("heliox voice event: usage: heliox voice event <transcript>");
                return;
            }
            let Ok(held) = require_token("cap:heliox:voice") else {
                return;
            };
            let transcript = args[1..].join(" ");
            match heliox::submit_request("voice_event", &transcript, &held) {
                Ok(envelope) => println!("voice_event envelope id={}", envelope.id),
                Err(err) => println!("heliox voice event: {}", err),
            }
        }
        _ => println!("heliox voice: usage: heliox voice [start|stop|event <text>]"),
    }
}

fn cmd_heliox_confirm(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        let pending = heliox::pending_confirmations();
        println!("Pending Heliox Confirmations ({}):", pending.len());
        for gate in &pending {
            println!("  plan_id={} actions={}", gate.plan_id, gate.actions.len());
            for action in &gate.actions {
                println!("    - {}", action);
            }
        }
        return;
    }
    let plan_id = args[0];
    let Ok(held) = require_token("cap:heliox:bridge") else {
        return;
    };
    match heliox::submit_request("confirm", plan_id, &held) {
        Ok(_) => println!("confirmation gate resolved: {}", plan_id),
        Err(err) => println!("heliox confirm: {}", err),
    }
}

fn cmd_heliox_execute(args: &[&str]) {
    use crate::heliox;
    if args.is_empty() {
        println!("heliox execute: usage: heliox execute <input text>");
        return;
    }
    let input = args.join(" ");
    let Ok(held) = require_token("cap:heliox:execute") else {
        return;
    };
    match heliox::submit_request("execute", &input, &held) {
        Ok(envelope) => println!(
            "heliox execute dispatched: id={} method={}",
            envelope.id, envelope.method
        ),
        Err(err) => println!("heliox execute: {}", err),
    }
}

fn cmd_elf(_args: &[&str]) {
    let raw = crate::userspace::INIT_ELF;
    println!("Embedded init ELF:");
    println!("  size:  {} bytes", raw.len());

    match crate::elf::parse(raw) {
        Ok(parsed) => {
            let header = parsed.header();
            let type_name: &str = match header.e_type {
                2 => "ET_EXEC",
                3 => "ET_DYN",
                _ => "ET_OTHER",
            };
            println!("  type:       {}", type_name);
            println!("  machine:    EM_X86_64");
            println!("  entry:      {:#x}", parsed.entry());
            println!(
                "  phoff:      {} ({} entries of {} bytes)",
                header.e_phoff, header.e_phnum, header.e_phentsize
            );

            println!("  PT_LOAD segments:");
            for ph in parsed.load_segments() {
                let flags = alloc::format!(
                    "{}{}{}",
                    if ph.is_readable() { 'R' } else { '-' },
                    if ph.is_writable() { 'W' } else { '-' },
                    if ph.is_executable() { 'X' } else { '-' },
                );
                println!(
                    "    vaddr={:#x} filesz={:#x} memsz={:#x} off={:#x} align={:#x} flags={}",
                    ph.p_vaddr, ph.p_filesz, ph.p_memsz, ph.p_offset, ph.p_align, flags
                );
            }

            if let (Some(min), Some(max)) = (parsed.load_vaddr_min(), parsed.load_vaddr_max()) {
                println!("  range:      [{:#x}, {:#x})  ({} bytes)", min, max, max - min);
            }
        }
        Err(err) => println!("  parse:      FAILED ({})", err),
    }
}

fn cmd_process(_args: &[&str]) {
    let procs = crate::process::list();
    println!("Per-process Address Spaces ({}):", procs.len());
    if procs.is_empty() {
        println!("  (none; Phase 1.4 will create one per loaded userspace process)");
        return;
    }
    println!("  PID  USER_FRAMES  NAME");
    println!("  ---  -----------  ----");
    for (pid, name, frames) in &procs {
        println!("  {:>3}  {:>11}  {}", pid, frames, name);
    }
}

/// Enter ring-3 in a previously-registered process. The process
/// must have been loaded with `load_elf` already (i.e. it appears
/// in the `process` table with USER_FRAMES > 0). This is a
/// one-way trip: the iretq never returns to the shell, so
/// callers should treat the kernel as effectively single-shot
/// after issuing this command.
fn cmd_ring3(args: &[&str]) {
    let target = args.first().copied().unwrap_or("init");

    // Locate the process by name or pid.
    let procs = crate::process::list();
    let candidate = if let Ok(pid_num) = target.parse::<u64>() {
        procs.iter().find(|(pid, _, _)| *pid == pid_num).cloned()
    } else {
        procs
            .iter()
            .find(|(_, name, _)| name == target)
            .cloned()
    };

    let Some((pid, name, frames)) = candidate else {
        println!(
            "ring3: no such process '{}' (try `process` to list)",
            target
        );
        return;
    };

    if frames == 0 {
        println!(
            "ring3: process {} ({}) has no mapped user frames; load an ELF first",
            pid, name
        );
        return;
    }

    println!(
        "[  OK  ] Dispatching ring-3 init: pid={} name={} user_frames={}",
        pid, name, frames
    );
    let held = current_capabilities();
    crate::process::enter_registered(pid, &held);
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

fn cmd_scheduler(_args: &[&str]) {
    // Phase 2 summary. The `ps` command already shows the
    // per-task table; this command shows the global state
    // the sweep asserts on (current pid, tick, time slice).
    let tasks = crate::scheduler::list_tasks();
    let current = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    let total = crate::scheduler::total_ticks();
    let active = tasks
        .iter()
        .filter(|t| !matches!(t.state, crate::scheduler::TaskState::Dead))
        .count();
    let ready = tasks
        .iter()
        .filter(|t| matches!(t.state, crate::scheduler::TaskState::Ready))
        .count();
    let running = tasks
        .iter()
        .filter(|t| matches!(t.state, crate::scheduler::TaskState::Running))
        .count();
    let blocked = tasks
        .iter()
        .filter(|t| matches!(t.state, crate::scheduler::TaskState::Blocked))
        .count();
    println!("Scheduler State:");
    println!("  current_pid:    {}", current);
    println!("  total_ticks:    {}", total);
    println!("  active tasks:   {}", active);
    println!("    running:      {}", running);
    println!("    ready:        {}", ready);
    println!("    blocked:      {}", blocked);
    println!(
        "  time slice:     {} PIT ticks (~{} ms)",
        crate::scheduler::TIME_SLICE_TICKS,
        crate::scheduler::TIME_SLICE_TICKS * 55
    );
}

fn cmd_test_syscall(args: &[&str]) {
    // Phase 2 self-test: exercises the new syscalls from the
    // kernel main context (no ring-3 process required). The
    // scheduler's `run-queue` is empty in the shell context, so
    // `schedule_next()` returns `None` and the yield/sleep
    // paths fall through to their no-op returns. This
    // command exists so the sweep can assert the syscall
    // numbers, the priority logic, and the run-queue shape
    // without needing a second user process.
    if args.is_empty() {
        println!("test-syscall: usage: test-syscall <yield|sleep|wait|priority>");
        return;
    }
    match args[0] {
        "yield" => {
            // The kernel main context (pid 0) is not in the
            // scheduler, so `yield_current` returns false.
            // The shell keeps running.
            let ran = crate::scheduler::yield_current();
            println!("yield: ran={}", ran);
        }
        "sleep" => {
            // Same: the kernel main context cannot sleep. The
            // call is a no-op for the shell.
            let ran = crate::scheduler::sleep_current(2);
            println!("sleep(2): ran={}", ran);
        }
        "wait" => {
            // `wait(-1)` with no dead children returns -ECHILD.
            let sched = crate::scheduler::list_tasks();
            let any_dead = sched
                .iter()
                .any(|t| matches!(t.state, crate::scheduler::TaskState::Dead));
            println!("wait(-1): any_dead={}", any_dead);
        }
        "priority" => {
            // Verify the priority index math the scheduler
            // uses to pick the next run-queue.
            for p in &[
                crate::scheduler::Priority::Idle,
                crate::scheduler::Priority::Normal,
                crate::scheduler::Priority::High,
                crate::scheduler::Priority::System,
            ] {
                println!("priority {:?} -> index {}", p, p.index());
            }
        }
        _ => println!("test-syscall: unknown subcommand '{}'", args[0]),
    }
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

fn cmd_disk(args: &[&str]) {
    if args.first() == Some(&"read") {
        // disk read <sector>
        if args.len() < 2 {
            println!("disk read: usage: disk read <sector_number>");
            return;
        }
        let Ok(lba) = args[1].parse::<u64>() else {
            println!("disk read: invalid sector number");
            return;
        };
        let mut buf = [0u8; 512];
        match crate::ata::read_sectors(
            crate::ata::AtaBus::Primary,
            0,
            lba,
            1,
            &mut buf,
        ) {
            Ok(()) => {
                println!("Sector {} (512 bytes):", lba);
                // Print hexdump (first 256 bytes to avoid flooding VGA)
                for row in 0..16 {
                    let offset = row * 16;
                    print!("  {:04x}: ", offset);
                    for col in 0..16 {
                        print!("{:02x} ", buf[offset + col]);
                    }
                    print!(" ");
                    for col in 0..16 {
                        let ch = buf[offset + col];
                        if ch >= 0x20 && ch < 0x7F {
                            print!("{}", ch as char);
                        } else {
                            print!(".");
                        }
                    }
                    println!();
                }
            }
            Err(e) => println!("disk read: {}", e),
        }
        return;
    }

    // Default: list all ATA drives
    let drives = crate::ata::list_drives();
    if drives.is_empty() {
        println!("No ATA drives detected.");
        println!("  (attach a disk image with QEMU -drive file=disk.img,format=raw,if=ide)");
        return;
    }
    println!("ATA Drives:");
    println!("  BUS        DRIVE   SECTORS       SIZE   MODEL");
    println!("  ---        -----   -------       ----   -----");
    for drive in &drives {
        let pos = if drive.drive == 0 { "master" } else { "slave" };
        println!(
            "  {:<8}  {:<6}  {:>10}  {:>5} MiB  {}",
            drive.bus.name(),
            pos,
            drive.sectors,
            drive.size_mb,
            drive.model,
        );
        println!(
            "             serial: {}  LBA48: {}",
            drive.serial, drive.lba48,
        );
    }
}
