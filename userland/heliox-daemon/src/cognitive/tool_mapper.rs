// ============================================================================
// Heliox-Daemon - Tool-to-Syscall Mapper (27 tools, 5-tier permissions)
// ============================================================================
// Maps LLM tool call names to FerrumOS kernel syscalls. Each tool has a
// permission tier that determines whether it can execute immediately or
// requires user confirmation via the kernel shell.
//
// Tier 0: Observe  — read-only internal state, always allowed
// Tier 1: Safe     — read-only kernel ops, auto-approved
// Tier 2: Network  — network I/O, auto-approved but rate-limited
// Tier 3: Modify   — disk writes, service control, needs confirmation
// Tier 4: Destructive — process spawn, file delete, needs explicit approval
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::format;
use alloc::vec::Vec;
use core::arch::asm;

use super::json::{JsonValue, ToolCall};
use super::confirmation::{ConfirmationGate, ConfirmationStatus};
use crate::memory::vector_store::MemoryCategory;

// ---- Syscall Numbers (must match kernel src/syscall/mod.rs) ----------------
const SYS_YIELD: u64 = 0;
const SYS_IPC_SEND: u64 = 1;
const SYS_IPC_RECEIVE: u64 = 2;
const SYS_SERVICE_START: u64 = 3;
const SYS_SERVICE_STOP: u64 = 4;
const SYS_CAPABILITY_CHECK: u64 = 5;
const SYS_AUDIT_WRITE: u64 = 6;
const SYS_SOCKET: u64 = 7;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;
const SYS_CONNECT: u64 = 14;
const SYS_READ_FILE: u64 = 15;
const SYS_WRITE_FILE: u64 = 16;
const SYS_READ_DIR: u64 = 17;
const SYS_EXEC: u64 = 18;
const SYS_CREATE_DIR: u64 = 21;
const SYS_DELETE_FILE: u64 = 22;

// ---- Raw Syscall Interface -------------------------------------------------

#[inline(always)]
unsafe fn syscall3(number: u64, arg1: u64, arg2: u64, arg3: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

#[inline(always)]
unsafe fn syscall4(number: u64, arg1: u64, arg2: u64, arg3: u64, arg4: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        in("r10") arg4,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

// ---- Permission Tiers ------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum PermissionTier {
    Observe = 0,
    Safe = 1,
    Network = 2,
    Modify = 3,
    Destructive = 4,
}

fn tool_tier(name: &str) -> PermissionTier {
    match name {
        // Tier 0: Observe
        "query_memory" | "get_config" | "system_info" | "list_processes"
        | "add_subtask" => PermissionTier::Observe,
        // Tier 1: Safe
        "ipc_send" | "audit_write" | "yield_cpu" | "report_status"
        | "capability_check" | "read_file" | "read_dir" | "sleep"
        | "read_screen" | "set_volume" => PermissionTier::Safe,
        // Tier 2: Network
        "net_connect" | "net_send" | "net_recv" | "http_get"
        | "load_memory" | "set_goal" | "record_audio" => PermissionTier::Network,
        // Tier 3: Modify
        "write_file" | "create_directory" | "save_memory"
        | "service_start" | "service_stop" | "play_audio"
        | "keyboard_type" | "mouse_click" | "mouse_move" => PermissionTier::Modify,
        // Tier 4: Destructive
        "exec_process" | "delete_file" => PermissionTier::Destructive,
        _ => PermissionTier::Destructive, // unknown tools default to highest tier
    }
}

// ---- Tool Execution Result -------------------------------------------------

#[derive(Debug, Clone)]
pub struct ToolResult {
    pub tool_name: String,
    pub success: bool,
    pub output: String,
}

// ---- Tool Registry ---------------------------------------------------------

pub const TOOL_DEFINITIONS: &str = r#"You have access to the following tools:

1. `ipc_send` - Send an IPC message to a kernel service.
   Arguments: {"target_pid": <number>, "message": "<string>"}

2. `audit_write` - Write an entry to the kernel audit log.
   Arguments: {"message": "<string>"}

3. `yield_cpu` - Voluntarily yield the CPU to other tasks.
   Arguments: {}

4. `report_status` - Report the agent's current status to the kernel.
   Arguments: {"status": "<string>"}

5. `capability_check` - Check if a capability is held.
   Arguments: {"capability_id": <number>}

6. `read_file` - Read a file from the filesystem.
   Arguments: {"path": "<string>"}

7. `read_dir` - List the contents of a directory.
   Arguments: {"path": "<string>"}

8. `query_memory` - Search the agent's vector memory for relevant context.
   Arguments: {"query": "<string>", "top_k": <number>}

9. `get_config` - Read a runtime configuration value.
   Arguments: {"key": "<string>"}

10. `system_info` - Get system information (uptime, memory, processes).
    Arguments: {}

11. `list_processes` - List all running processes.
    Arguments: {}

12. `net_connect` - Open a TCP connection to a remote host.
    Arguments: {"host": "<ip_address>", "port": <number>}

13. `net_send` - Send data on an open socket.
    Arguments: {"fd": <number>, "data": "<string>"}

14. `net_recv` - Receive data from an open socket.
    Arguments: {"fd": <number>}

15. `http_get` - Make an HTTP GET request to a URL.
    Arguments: {"host": "<hostname>", "port": <number>, "path": "<string>"}

16. `write_file` - Write content to a file (REQUIRES CONFIRMATION).
    Arguments: {"path": "<string>", "content": "<string>"}

17. `create_directory` - Create a new directory (REQUIRES CONFIRMATION).
    Arguments: {"path": "<string>"}

18. `save_memory` - Persist the vector memory to disk (REQUIRES CONFIRMATION).
    Arguments: {}

19. `load_memory` - Load the vector memory from disk.
    Arguments: {}

20. `set_goal` - Change the current agent goal.
    Arguments: {"goal": "<string>"}

21. `sleep` - Sleep for a number of milliseconds.
    Arguments: {"ms": <number>}

22. `service_start` - Start a registered kernel service (REQUIRES CONFIRMATION).
    Arguments: {"service_id": <number>}

23. `service_stop` - Stop a registered kernel service (REQUIRES CONFIRMATION).
    Arguments: {"service_id": <number>}

24. `exec_process` - Spawn a new process from an ELF binary (REQUIRES EXPLICIT APPROVAL).
    Arguments: {"path": "<string>"}

25. `delete_file` - Delete a file from disk (REQUIRES EXPLICIT APPROVAL).
    Arguments: {"path": "<string>"}

26. `read_screen` - Capture the current screen contents as text.
    Arguments: {}

27. `add_subtask` - Add a new subtask to the current plan.
    Arguments: {"description": "<string>", "depends_on": "<comma-separated task IDs>"}

28. `record_audio` - Record audio from the microphone for a given duration.
    Arguments: {"duration_ms": <number>}

29. `play_audio` - Play a notification beep through the speaker (REQUIRES CONFIRMATION).
    Arguments: {}

30. `set_volume` - Set the audio output volume.
    Arguments: {"level": <number 0-127>}

31. `keyboard_type` - Type a string of text as keyboard input (REQUIRES CONFIRMATION).
    Arguments: {"text": "<string>"}

32. `mouse_click` - Click a mouse button (REQUIRES CONFIRMATION).
    Arguments: {"button": <number 0=left, 1=right, 2=middle>}

33. `mouse_move` - Move the mouse cursor by a relative offset (REQUIRES CONFIRMATION).
    Arguments: {"dx": <number>, "dy": <number>}

Respond with a JSON object: {"tool": "<tool_name>", "args": {<arguments>}}
If no tool is needed, respond with plain text.
Tools marked REQUIRES CONFIRMATION need operator approval before executing."#;

// ---- Tool Execution --------------------------------------------------------

/// Check if a tool requires confirmation before execution.
pub fn needs_confirmation(tool_name: &str, auto_approve_tier: u8) -> bool {
    let tier = tool_tier(tool_name) as u8;
    tier > auto_approve_tier
}

/// Execute a parsed tool call by dispatching to the appropriate handler.
/// For tools that require confirmation, returns a pending result.
pub fn execute(tool_call: &ToolCall, confirmation_gate: &mut ConfirmationGate, auto_approve_tier: u8, current_tick: u64) -> ToolResult {
    let tier = tool_tier(&tool_call.name);

    // Check if this tool needs confirmation
    if (tier as u8) > auto_approve_tier {
        // Check if we already have a pending/approved confirmation
        let args_summary = format_args_summary(&tool_call.arguments);
        match confirmation_gate.check_or_request(&tool_call.name, &args_summary, tier, current_tick) {
            ConfirmationStatus::Approved => {
                // Approved — proceed with execution
            }
            ConfirmationStatus::Pending(id) => {
                return ToolResult {
                    tool_name: tool_call.name.clone(),
                    success: false,
                    output: format!("Awaiting confirmation (id={}). Use 'confirm {}' in kernel shell.", id, id),
                };
            }
            ConfirmationStatus::Denied => {
                return ToolResult {
                    tool_name: tool_call.name.clone(),
                    success: false,
                    output: String::from("Action denied by operator."),
                };
            }
            ConfirmationStatus::Expired => {
                return ToolResult {
                    tool_name: tool_call.name.clone(),
                    success: false,
                    output: String::from("Confirmation request expired."),
                };
            }
        }
    }

    // Dispatch to the appropriate handler
    match tool_call.name.as_str() {
        "ipc_send" => execute_ipc_send(&tool_call.arguments),
        "audit_write" => execute_audit_write(&tool_call.arguments),
        "yield_cpu" => execute_yield(),
        "report_status" => execute_report_status(&tool_call.arguments),
        "capability_check" => execute_capability_check(&tool_call.arguments),
        "read_file" => execute_read_file(&tool_call.arguments),
        "read_dir" => execute_read_dir(&tool_call.arguments),
        "query_memory" => execute_query_memory(&tool_call.arguments),
        "get_config" => execute_get_config(&tool_call.arguments),
        "system_info" => execute_system_info(),
        "list_processes" => execute_list_processes(),
        "net_connect" => execute_net_connect(&tool_call.arguments),
        "net_send" => execute_net_send(&tool_call.arguments),
        "net_recv" => execute_net_recv(&tool_call.arguments),
        "http_get" => execute_http_get(&tool_call.arguments),
        "write_file" => execute_write_file(&tool_call.arguments),
        "create_directory" => execute_create_directory(&tool_call.arguments),
        "save_memory" => execute_save_memory(),
        "load_memory" => execute_load_memory(),
        "set_goal" => execute_set_goal(&tool_call.arguments),
        "sleep" => execute_sleep(&tool_call.arguments),
        "service_start" => execute_service_lifecycle(SYS_SERVICE_START, &tool_call.arguments),
        "service_stop" => execute_service_lifecycle(SYS_SERVICE_STOP, &tool_call.arguments),
        "exec_process" => execute_exec_process(&tool_call.arguments),
        "delete_file" => execute_delete_file(&tool_call.arguments),
        "read_screen" => execute_read_screen(),
        "add_subtask" => execute_add_subtask(),
        "record_audio" => execute_record_audio(&tool_call.arguments),
        "play_audio" => execute_play_audio(),
        "set_volume" => execute_set_volume(&tool_call.arguments),
        "keyboard_type" => execute_keyboard_type(&tool_call.arguments),
        "mouse_click" => execute_mouse_click(&tool_call.arguments),
        "mouse_move" => execute_mouse_move(&tool_call.arguments),
        _ => ToolResult {
            tool_name: tool_call.name.clone(),
            success: false,
            output: format!("Unknown tool: {}", tool_call.name),
        },
    }
}

// ---- Tool Implementations --------------------------------------------------

fn execute_ipc_send(args: &[(String, JsonValue)]) -> ToolResult {
    let target_pid = find_arg_number(args, "target_pid").unwrap_or(0.0) as u64;
    let message = find_arg_string(args, "message").unwrap_or_default();
    let result = unsafe {
        syscall3(SYS_IPC_SEND, target_pid, message.as_ptr() as u64, message.len() as u64)
    };
    ToolResult {
        tool_name: String::from("ipc_send"),
        success: result == 0,
        output: format!("IPC sent to PID {} ({} bytes), result={}", target_pid, message.len(), result),
    }
}

fn execute_audit_write(args: &[(String, JsonValue)]) -> ToolResult {
    let message = find_arg_string(args, "message").unwrap_or_default();
    let result = unsafe {
        syscall3(SYS_AUDIT_WRITE, message.as_ptr() as u64, message.len() as u64, 0)
    };
    ToolResult {
        tool_name: String::from("audit_write"),
        success: result == 0,
        output: format!("Audit written ({} bytes), result={}", message.len(), result),
    }
}

fn execute_yield() -> ToolResult {
    unsafe { syscall3(SYS_YIELD, 0, 0, 0) };
    ToolResult {
        tool_name: String::from("yield_cpu"),
        success: true,
        output: String::from("CPU yielded"),
    }
}

fn execute_report_status(args: &[(String, JsonValue)]) -> ToolResult {
    let status = find_arg_string(args, "status").unwrap_or_default();
    let msg = format!("HELIOX_STATUS:{}", status);
    let result = unsafe {
        syscall3(SYS_IPC_SEND, 0, msg.as_ptr() as u64, msg.len() as u64)
    };
    ToolResult {
        tool_name: String::from("report_status"),
        success: result == 0,
        output: format!("Status reported: {}", status),
    }
}

fn execute_capability_check(args: &[(String, JsonValue)]) -> ToolResult {
    let cap_id = find_arg_number(args, "capability_id").unwrap_or(0.0) as u64;
    let result = unsafe { syscall3(SYS_CAPABILITY_CHECK, cap_id, 0, 0) };
    ToolResult {
        tool_name: String::from("capability_check"),
        success: result == 0,
        output: format!("Capability {} check result={}", cap_id, result),
    }
}

fn execute_read_file(args: &[(String, JsonValue)]) -> ToolResult {
    let path = find_arg_string(args, "path").unwrap_or_default();
    if path.is_empty() {
        return ToolResult {
            tool_name: String::from("read_file"),
            success: false,
            output: String::from("Missing 'path' argument"),
        };
    }

    let mut buf = alloc::vec![0u8; 64 * 1024]; // 64KB read buffer
    let bytes_read = unsafe {
        syscall4(SYS_READ_FILE, path.as_ptr() as u64, path.len() as u64,
                 buf.as_mut_ptr() as u64, buf.len() as u64)
    };

    if (bytes_read as i64) < 0 {
        ToolResult {
            tool_name: String::from("read_file"),
            success: false,
            output: format!("Failed to read '{}': error {}", path, bytes_read as i64),
        }
    } else {
        let content = core::str::from_utf8(&buf[..bytes_read as usize]).unwrap_or("<binary>");
        // Truncate for output
        let preview = if content.len() > 512 { &content[..512] } else { content };
        ToolResult {
            tool_name: String::from("read_file"),
            success: true,
            output: format!("Read {} bytes from '{}': {}", bytes_read, path, preview),
        }
    }
}

fn execute_read_dir(args: &[(String, JsonValue)]) -> ToolResult {
    let path = find_arg_string(args, "path").unwrap_or_default();
    if path.is_empty() {
        return ToolResult {
            tool_name: String::from("read_dir"),
            success: false,
            output: String::from("Missing 'path' argument"),
        };
    }

    let mut buf = alloc::vec![0u8; 16 * 1024]; // 16KB buffer for dir listing
    let bytes_read = unsafe {
        syscall4(SYS_READ_DIR, path.as_ptr() as u64, path.len() as u64,
                 buf.as_mut_ptr() as u64, buf.len() as u64)
    };

    if (bytes_read as i64) < 0 {
        ToolResult {
            tool_name: String::from("read_dir"),
            success: false,
            output: format!("Failed to read directory '{}': error {}", path, bytes_read as i64),
        }
    } else {
        let listing = core::str::from_utf8(&buf[..bytes_read as usize]).unwrap_or("");
        ToolResult {
            tool_name: String::from("read_dir"),
            success: true,
            output: format!("Directory '{}' contents:\n{}", path, listing),
        }
    }
}

fn execute_query_memory(_args: &[(String, JsonValue)]) -> ToolResult {
    // This is handled internally by the orchestrator, not via syscall.
    // The tool mapper returns a marker that the orchestrator intercepts.
    ToolResult {
        tool_name: String::from("query_memory"),
        success: true,
        output: String::from("INTERNAL:query_memory"),
    }
}

fn execute_get_config(_args: &[(String, JsonValue)]) -> ToolResult {
    // Handled internally by the orchestrator.
    ToolResult {
        tool_name: String::from("get_config"),
        success: true,
        output: String::from("INTERNAL:get_config"),
    }
}

fn execute_system_info() -> ToolResult {
    // Report basic system info via IPC query
    let msg = b"HELIOX_QUERY:sysinfo";
    let _result = unsafe {
        syscall3(SYS_IPC_SEND, 0, msg.as_ptr() as u64, msg.len() as u64)
    };
    ToolResult {
        tool_name: String::from("system_info"),
        success: true,
        output: String::from("System info requested via IPC"),
    }
}

fn execute_list_processes() -> ToolResult {
    let msg = b"HELIOX_QUERY:processes";
    let _result = unsafe {
        syscall3(SYS_IPC_SEND, 0, msg.as_ptr() as u64, msg.len() as u64)
    };
    ToolResult {
        tool_name: String::from("list_processes"),
        success: true,
        output: String::from("Process list requested via IPC"),
    }
}

fn execute_net_connect(args: &[(String, JsonValue)]) -> ToolResult {
    let host = find_arg_string(args, "host").unwrap_or_default();
    let port = find_arg_number(args, "port").unwrap_or(80.0) as u16;

    let ip = match crate::network::resolve_host(&host) {
        Some(ip) => ip,
        None => {
            return ToolResult {
                tool_name: String::from("net_connect"),
                success: false,
                output: format!("Failed to resolve host: {}", host),
            };
        }
    };

    let fd = match crate::network::tcp_socket() {
        Ok(fd) => fd,
        Err(e) => {
            return ToolResult {
                tool_name: String::from("net_connect"),
                success: false,
                output: format!("Socket creation failed: {}", e),
            };
        }
    };

    match crate::network::tcp_connect(fd, ip, port) {
        Ok(()) => ToolResult {
            tool_name: String::from("net_connect"),
            success: true,
            output: format!("Connected to {}:{} (fd={})", host, port, fd),
        },
        Err(e) => ToolResult {
            tool_name: String::from("net_connect"),
            success: false,
            output: format!("Connect failed: {}", e),
        },
    }
}

fn execute_net_send(args: &[(String, JsonValue)]) -> ToolResult {
    let fd = find_arg_number(args, "fd").unwrap_or(0.0) as u64;
    let data = find_arg_string(args, "data").unwrap_or_default();
    let result = unsafe {
        syscall3(SYS_SEND, fd, data.as_ptr() as u64, data.len() as u64)
    };
    ToolResult {
        tool_name: String::from("net_send"),
        success: (result as i64) >= 0,
        output: format!("Sent {} bytes on fd={}, result={}", data.len(), fd, result),
    }
}

fn execute_net_recv(args: &[(String, JsonValue)]) -> ToolResult {
    let fd = find_arg_number(args, "fd").unwrap_or(0.0) as u64;
    let mut buf = alloc::vec![0u8; 4096];
    let result = unsafe {
        syscall3(SYS_RECV, fd, buf.as_mut_ptr() as u64, buf.len() as u64)
    };
    if (result as i64) < 0 {
        ToolResult {
            tool_name: String::from("net_recv"),
            success: false,
            output: format!("Recv failed on fd={}: error {}", fd, result as i64),
        }
    } else {
        let data = core::str::from_utf8(&buf[..result as usize]).unwrap_or("<binary>");
        let preview = if data.len() > 512 { &data[..512] } else { data };
        ToolResult {
            tool_name: String::from("net_recv"),
            success: true,
            output: format!("Received {} bytes on fd={}: {}", result, fd, preview),
        }
    }
}

fn execute_http_get(args: &[(String, JsonValue)]) -> ToolResult {
    let host = find_arg_string(args, "host").unwrap_or_default();
    let port = find_arg_number(args, "port").unwrap_or(80.0) as u16;
    let path = find_arg_string(args, "path").unwrap_or(String::from("/"));

    // Build and send HTTP GET request
    let request = format!(
        "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
        path, host
    );

    let ip = match crate::network::resolve_host(&host) {
        Some(ip) => ip,
        None => {
            return ToolResult {
                tool_name: String::from("http_get"),
                success: false,
                output: format!("Failed to resolve host: {}", host),
            };
        }
    };

    let fd = match crate::network::tcp_socket() {
        Ok(fd) => fd,
        Err(e) => {
            return ToolResult {
                tool_name: String::from("http_get"),
                success: false,
                output: format!("Socket creation failed: {}", e),
            };
        }
    };

    if let Err(e) = crate::network::tcp_connect(fd, ip, port) {
        return ToolResult {
            tool_name: String::from("http_get"),
            success: false,
            output: format!("Connect failed: {}", e),
        };
    }

    unsafe { syscall3(SYS_SEND, fd, request.as_ptr() as u64, request.len() as u64) };

    let mut buf = alloc::vec![0u8; 8192];
    let result = unsafe {
        syscall3(SYS_RECV, fd, buf.as_mut_ptr() as u64, buf.len() as u64)
    };

    if (result as i64) <= 0 {
        ToolResult {
            tool_name: String::from("http_get"),
            success: false,
            output: format!("No response from {}:{}{}", host, port, path),
        }
    } else {
        let response = core::str::from_utf8(&buf[..result as usize]).unwrap_or("<binary>");
        let preview = if response.len() > 512 { &response[..512] } else { response };
        ToolResult {
            tool_name: String::from("http_get"),
            success: true,
            output: format!("HTTP response ({} bytes): {}", result, preview),
        }
    }
}

fn execute_write_file(args: &[(String, JsonValue)]) -> ToolResult {
    let path = find_arg_string(args, "path").unwrap_or_default();
    let content = find_arg_string(args, "content").unwrap_or_default();
    if path.is_empty() {
        return ToolResult {
            tool_name: String::from("write_file"),
            success: false,
            output: String::from("Missing 'path' argument"),
        };
    }

    let result = unsafe {
        syscall4(SYS_WRITE_FILE, path.as_ptr() as u64, path.len() as u64,
                 content.as_ptr() as u64, content.len() as u64)
    };

    ToolResult {
        tool_name: String::from("write_file"),
        success: result == 0,
        output: format!("Write '{}' ({} bytes): result={}", path, content.len(), result),
    }
}

fn execute_create_directory(args: &[(String, JsonValue)]) -> ToolResult {
    let path = find_arg_string(args, "path").unwrap_or_default();
    if path.is_empty() {
        return ToolResult {
            tool_name: String::from("create_directory"),
            success: false,
            output: String::from("Missing 'path' argument"),
        };
    }
    let result = unsafe {
        crate::syscall4(SYS_CREATE_DIR, path.as_ptr() as u64, path.len() as u64, 0, 0)
    };
    ToolResult {
        tool_name: String::from("create_directory"),
        success: result == 0,
        output: format!("Create directory '{}': result={}", path, result),
    }
}

fn execute_save_memory() -> ToolResult {
    // Handled internally by the orchestrator
    ToolResult {
        tool_name: String::from("save_memory"),
        success: true,
        output: String::from("INTERNAL:save_memory"),
    }
}

fn execute_load_memory() -> ToolResult {
    // Handled internally by the orchestrator
    ToolResult {
        tool_name: String::from("load_memory"),
        success: true,
        output: String::from("INTERNAL:load_memory"),
    }
}

fn execute_set_goal(_args: &[(String, JsonValue)]) -> ToolResult {
    // Handled internally by the orchestrator
    ToolResult {
        tool_name: String::from("set_goal"),
        success: true,
        output: String::from("INTERNAL:set_goal"),
    }
}

fn execute_read_screen() -> ToolResult {
    match crate::cognitive::screen_vision::capture_screen() {
        Ok(capture) => ToolResult {
            tool_name: String::from("read_screen"),
            success: true,
            output: capture.full_text(),
        },
        Err(e) => ToolResult {
            tool_name: String::from("read_screen"),
            success: false,
            output: String::from(e),
        },
    }
}

fn execute_add_subtask() -> ToolResult {
    // Handled internally by the orchestrator
    ToolResult {
        tool_name: String::from("add_subtask"),
        success: true,
        output: String::from("INTERNAL:add_subtask"),
    }
}

fn execute_sleep(args: &[(String, JsonValue)]) -> ToolResult {
    let ms = find_arg_number(args, "ms").unwrap_or(100.0) as u64;
    // Use hlt loop for approximate sleep
    let iterations = ms / 10;
    for _ in 0..iterations {
        unsafe { asm!("hlt", options(nomem, nostack, preserves_flags)); }
    }
    ToolResult {
        tool_name: String::from("sleep"),
        success: true,
        output: format!("Slept for ~{} ms", ms),
    }
}

fn execute_service_lifecycle(syscall: u64, args: &[(String, JsonValue)]) -> ToolResult {
    let service_id = find_arg_number(args, "service_id").unwrap_or(0.0) as u64;
    let name = if syscall == SYS_SERVICE_START { "service_start" } else { "service_stop" };
    let result = unsafe { syscall3(syscall, service_id, 0, 0) };
    ToolResult {
        tool_name: String::from(name),
        success: result == 0,
        output: format!("{} service_id={}, result={}", name, service_id, result),
    }
}

fn execute_exec_process(args: &[(String, JsonValue)]) -> ToolResult {
    let path = find_arg_string(args, "path").unwrap_or_default();
    if path.is_empty() {
        return ToolResult {
            tool_name: String::from("exec_process"),
            success: false,
            output: String::from("Missing 'path' argument"),
        };
    }
    let result = unsafe {
        syscall3(SYS_EXEC, path.as_ptr() as u64, path.len() as u64, 0)
    };
    if (result as i64) > 0 {
        ToolResult {
            tool_name: String::from("exec_process"),
            success: true,
            output: format!("Spawned process '{}' with PID {}", path, result),
        }
    } else {
        ToolResult {
            tool_name: String::from("exec_process"),
            success: false,
            output: format!("Failed to exec '{}': error {}", path, result as i64),
        }
    }
}

fn execute_delete_file(args: &[(String, JsonValue)]) -> ToolResult {
    let path = find_arg_string(args, "path").unwrap_or_default();
    if path.is_empty() {
        return ToolResult {
            tool_name: String::from("delete_file"),
            success: false,
            output: String::from("Missing 'path' argument"),
        };
    }
    let result = unsafe {
        crate::syscall4(SYS_DELETE_FILE, path.as_ptr() as u64, path.len() as u64, 0, 0)
    };
    ToolResult {
        tool_name: String::from("delete_file"),
        success: result == 0,
        output: format!("Delete '{}': result={}", path, result),
    }
}

// ---- Argument Helpers ------------------------------------------------------

fn find_arg_string(args: &[(String, JsonValue)], key: &str) -> Option<String> {
    for (k, v) in args {
        if k == key {
            return v.as_str().map(String::from);
        }
    }
    None
}

fn find_arg_number(args: &[(String, JsonValue)], key: &str) -> Option<f64> {
    for (k, v) in args {
        if k == key {
            return v.as_f64();
        }
    }
    None
}

fn format_args_summary(args: &[(String, JsonValue)]) -> String {
    let mut s = String::new();
    for (i, (k, v)) in args.iter().enumerate() {
        if i > 0 { s.push_str(", "); }
        s.push_str(k);
        s.push('=');
        match v {
            JsonValue::Str(sv) => {
                let preview = if sv.len() > 32 { &sv[..32] } else { sv.as_str() };
                s.push_str(preview);
            }
            JsonValue::Number(n) => s.push_str(&format!("{}", n)),
            _ => s.push_str("..."),
        }
    }
    s
}

// ---- Audio Tools -----------------------------------------------------------

fn execute_record_audio(args: &[(String, JsonValue)]) -> ToolResult {
    let duration_ms = find_arg_number(args, "duration_ms").unwrap_or(2000.0) as u32;
    match crate::cognitive::voice::record_audio(duration_ms) {
        Ok(buf) => {
            let rms = buf.rms_amplitude();
            let has_voice = crate::cognitive::voice::detect_voice_activity(&buf);
            ToolResult {
                tool_name: String::from("record_audio"),
                success: true,
                output: format!(
                    "Recorded {}ms audio ({} bytes). RMS amplitude: {}. Voice detected: {}",
                    duration_ms, buf.data.len(), rms, has_voice
                ),
            }
        }
        Err(e) => ToolResult {
            tool_name: String::from("record_audio"),
            success: false,
            output: format!("Recording failed: {}", e),
        },
    }
}

fn execute_play_audio() -> ToolResult {
    let beep = crate::cognitive::voice::generate_beep();
    match crate::cognitive::voice::play_audio(&beep) {
        Ok(()) => ToolResult {
            tool_name: String::from("play_audio"),
            success: true,
            output: String::from("Played notification beep (440Hz, 200ms)"),
        },
        Err(e) => ToolResult {
            tool_name: String::from("play_audio"),
            success: false,
            output: format!("Playback failed: {}", e),
        },
    }
}

fn execute_set_volume(args: &[(String, JsonValue)]) -> ToolResult {
    let level = find_arg_number(args, "level").unwrap_or(64.0) as u8;
    crate::cognitive::voice::set_volume(level);
    ToolResult {
        tool_name: String::from("set_volume"),
        success: true,
        output: format!("Volume set to {}/127", level),
    }
}

// ---- Input Tools -----------------------------------------------------------

const SYS_INJECT_KEY: u64 = 26;
const SYS_INJECT_MOUSE: u64 = 27;

fn execute_keyboard_type(args: &[(String, JsonValue)]) -> ToolResult {
    let text = find_arg_string(args, "text").unwrap_or_default();
    if text.is_empty() {
        return ToolResult {
            tool_name: String::from("keyboard_type"),
            success: false,
            output: String::from("No text provided"),
        };
    }

    let mut typed = 0u32;
    for ch in text.bytes() {
        unsafe {
            crate::syscall4(SYS_INJECT_KEY, ch as u64, 0, 0, 0);
        }
        typed += 1;
    }

    ToolResult {
        tool_name: String::from("keyboard_type"),
        success: true,
        output: format!("Typed {} characters", typed),
    }
}

fn execute_mouse_click(args: &[(String, JsonValue)]) -> ToolResult {
    let button = find_arg_number(args, "button").unwrap_or(0.0) as u64;
    if button > 2 {
        return ToolResult {
            tool_name: String::from("mouse_click"),
            success: false,
            output: String::from("Invalid button (use 0=left, 1=right, 2=middle)"),
        };
    }

    // event_type=1 (click), button_id, 0
    unsafe {
        crate::syscall4(SYS_INJECT_MOUSE, 1, button, 0, 0);
    }

    let name = match button {
        0 => "left",
        1 => "right",
        _ => "middle",
    };
    ToolResult {
        tool_name: String::from("mouse_click"),
        success: true,
        output: format!("Clicked {} mouse button", name),
    }
}

fn execute_mouse_move(args: &[(String, JsonValue)]) -> ToolResult {
    let dx = find_arg_number(args, "dx").unwrap_or(0.0) as i64;
    let dy = find_arg_number(args, "dy").unwrap_or(0.0) as i64;

    // event_type=0 (move), dx, dy
    unsafe {
        crate::syscall4(SYS_INJECT_MOUSE, 0, dx as u64, dy as u64, 0);
    }

    ToolResult {
        tool_name: String::from("mouse_move"),
        success: true,
        output: format!("Mouse moved by ({}, {})", dx, dy),
    }
}
