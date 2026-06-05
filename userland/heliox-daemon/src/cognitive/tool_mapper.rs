// ============================================================================
// Heliox-Daemon - Tool-to-Syscall Mapper
// ============================================================================
// Maps LLM tool call names to FerrumOS kernel syscalls. When the LLM
// decides to execute a tool (e.g. "list_directory"), this module translates
// that intent into the appropriate syscall sequence.
// ============================================================================

use alloc::string::String;
use alloc::format;
use alloc::vec::Vec;
use core::arch::asm;

use super::json::{JsonValue, ToolCall};

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

// ---- Tool Execution Result -------------------------------------------------

/// The result of executing a tool call.
#[derive(Debug, Clone)]
pub struct ToolResult {
    pub tool_name: String,
    pub success: bool,
    pub output: String,
}

// ---- Tool Registry ---------------------------------------------------------

/// Available tools that the LLM can invoke.
/// These are advertised in the system prompt so the LLM knows what it can do.
pub const TOOL_DEFINITIONS: &str = r#"You have access to the following tools:

1. `ipc_send` - Send an IPC message to a kernel service.
   Arguments: {"target_pid": <number>, "message": "<string>"}

2. `service_start` - Start a registered kernel service.
   Arguments: {"service_id": <number>}

3. `service_stop` - Stop a registered kernel service.
   Arguments: {"service_id": <number>}

4. `audit_write` - Write an entry to the kernel audit log.
   Arguments: {"message": "<string>"}

5. `capability_check` - Check if a capability is held.
   Arguments: {"capability_id": <number>}

6. `yield_cpu` - Voluntarily yield the CPU to other tasks.
   Arguments: {}

7. `net_connect` - Open a TCP connection to a remote host.
   Arguments: {"host": "<ip_address>", "port": <number>}

8. `report_status` - Report the agent's current status to the kernel.
   Arguments: {"status": "<string>"}

Respond with a JSON object: {"tool": "<tool_name>", "args": {<arguments>}}
If no tool is needed, respond with plain text."#;

// ---- Tool Execution --------------------------------------------------------

/// Execute a parsed tool call by dispatching to the appropriate syscall.
pub fn execute(tool_call: &ToolCall) -> ToolResult {
    match tool_call.name.as_str() {
        "ipc_send" => execute_ipc_send(&tool_call.arguments),
        "service_start" => execute_service_lifecycle(SYS_SERVICE_START, &tool_call.arguments),
        "service_stop" => execute_service_lifecycle(SYS_SERVICE_STOP, &tool_call.arguments),
        "audit_write" => execute_audit_write(&tool_call.arguments),
        "capability_check" => execute_capability_check(&tool_call.arguments),
        "yield_cpu" => execute_yield(),
        "net_connect" => execute_net_connect(&tool_call.arguments),
        "report_status" => execute_report_status(&tool_call.arguments),
        _ => ToolResult {
            tool_name: tool_call.name.clone(),
            success: false,
            output: format!("Unknown tool: {}", tool_call.name),
        },
    }
}

/// Send an IPC message to a kernel service.
fn execute_ipc_send(args: &[(String, JsonValue)]) -> ToolResult {
    let target_pid = find_arg_number(args, "target_pid").unwrap_or(0.0) as u64;
    let message = find_arg_string(args, "message").unwrap_or_default();

    let result = unsafe {
        syscall3(
            SYS_IPC_SEND,
            target_pid,
            message.as_ptr() as u64,
            message.len() as u64,
        )
    };

    ToolResult {
        tool_name: String::from("ipc_send"),
        success: result == 0,
        output: format!("IPC sent to PID {} ({} bytes), result={}", target_pid, message.len(), result),
    }
}

/// Start or stop a service.
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

/// Write to the kernel audit log.
fn execute_audit_write(args: &[(String, JsonValue)]) -> ToolResult {
    let message = find_arg_string(args, "message").unwrap_or_default();

    let result = unsafe {
        syscall3(
            SYS_AUDIT_WRITE,
            message.as_ptr() as u64,
            message.len() as u64,
            0,
        )
    };

    ToolResult {
        tool_name: String::from("audit_write"),
        success: result == 0,
        output: format!("Audit written ({} bytes), result={}", message.len(), result),
    }
}

/// Check a capability.
fn execute_capability_check(args: &[(String, JsonValue)]) -> ToolResult {
    let cap_id = find_arg_number(args, "capability_id").unwrap_or(0.0) as u64;

    let result = unsafe { syscall3(SYS_CAPABILITY_CHECK, cap_id, 0, 0) };

    ToolResult {
        tool_name: String::from("capability_check"),
        success: result == 0,
        output: format!("Capability {} check result={}", cap_id, result),
    }
}

/// Yield the CPU.
fn execute_yield() -> ToolResult {
    unsafe { syscall3(SYS_YIELD, 0, 0, 0) };

    ToolResult {
        tool_name: String::from("yield_cpu"),
        success: true,
        output: String::from("CPU yielded"),
    }
}

/// Open a TCP connection.
fn execute_net_connect(args: &[(String, JsonValue)]) -> ToolResult {
    let host = find_arg_string(args, "host").unwrap_or_default();
    let port = find_arg_number(args, "port").unwrap_or(80.0) as u16;

    // Resolve host via our DNS resolver
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

    // Create socket
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

    // Connect
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

/// Report the agent's status back to the kernel via IPC.
fn execute_report_status(args: &[(String, JsonValue)]) -> ToolResult {
    let status = find_arg_string(args, "status").unwrap_or_default();
    let msg = format!("HELIOX_STATUS:{}", status);

    let result = unsafe {
        syscall3(
            SYS_IPC_SEND,
            0, // PID 0 = kernel
            msg.as_ptr() as u64,
            msg.len() as u64,
        )
    };

    ToolResult {
        tool_name: String::from("report_status"),
        success: result == 0,
        output: format!("Status reported: {}", status),
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
