// FerrumOS - Shell Commands
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use crate::println;

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
        "mkdir" => cmd_mkdir(args),
        "touch" => cmd_touch(args),
        "write" => cmd_write(args),
        "rm" => cmd_rm(args),
        "caps" => cmd_caps(),
        "services" => cmd_services(args),
        "ipc" => cmd_ipc(),
        "syscalls" => cmd_syscalls(),
        "agent" => cmd_agent(args),
        "log" => cmd_log(),
        "uptime" => cmd_uptime(),
        "uname" => cmd_uname(),
        "whoami" => cmd_whoami(),
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
    println!("  mkdir <d>  Create a directory");
    println!("  touch <f>  Create an empty file");
    println!("  write <f> <text>  Write text to file");
    println!("  rm <path>  Remove file or directory");
    println!("  caps       Show capability tokens");
    println!("  services   List/start/stop registered services");
    println!("  ipc        Show IPC broker statistics");
    println!("  syscalls   Show syscall ABI numbers");
    println!("  agent      Control the agent runtime boundary");
    println!("  log        Show recent audit log");
    println!("  uptime     Show system uptime (ticks)");
    println!("  uname      Show system information");
    println!("  whoami     Show current identity");
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
    if args.is_empty() {
        println!("cat: missing file argument");
        return;
    }
    match crate::fs::read_file(args[0]) {
        Ok(content) => println!("{}", content),
        Err(e) => println!("cat: {}", e),
    }
}

fn cmd_mkdir(args: &[&str]) {
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
    if args.is_empty() {
        println!("rm: missing path");
        return;
    }
    match crate::fs::remove(args[0]) {
        Ok(()) => println!("Removed: {}", args[0]),
        Err(e) => println!("rm: {}", e),
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
                        let held = alloc::vec![String::from("cap:system:all")];
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
                        let held = alloc::vec![String::from("cap:system:all")];
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
    println!("Status: ABI reserved; full userspace dispatch pending");
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
        "start" => match crate::agent::start() {
            Ok(()) => println!("agentd started"),
            Err(err) => println!("agent start: {}", err),
        },
        "send" => {
            if args.len() < 2 {
                println!("agent send: missing command text");
                return;
            }
            let command = args[1..].join(" ");
            match crate::agent::send_command(&command) {
                Ok(id) => println!("agent command queued as IPC message {}", id),
                Err(err) => println!("agent send: {}", err),
            }
        }
        _ => println!("agent: unknown subcommand '{}'", args[0]),
    }
}

fn cmd_log() {
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
    println!("kernel (uid=0, gid=0)");
    println!("Capabilities: cap:system:all");
}

fn cmd_spawn(args: &[&str]) {
    let name = if args.is_empty() { "user_task" } else { args[0] };
    let id = crate::scheduler::spawn(
        String::from(name),
        crate::scheduler::Priority::Normal,
    );
    println!("Spawned task '{}' with PID {}", name, id);
}

fn cmd_kill(args: &[&str]) {
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
