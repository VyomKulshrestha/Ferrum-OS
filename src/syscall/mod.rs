// ============================================================================
// FerrumOS - Syscall ABI Skeleton
// ============================================================================
// This module defines the stable kernel/userspace boundary before true
// userspace execution exists. Handlers are intentionally minimal in v0.1:
// they document the ABI and provide a deterministic dispatch point for future
// ring-3 process support.
// ============================================================================

/// Stable syscall numbers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub enum SyscallNumber {
    Yield = 0,
    IpcSend = 1,
    IpcReceive = 2,
    ServiceStart = 3,
    ServiceStop = 4,
    CapabilityCheck = 5,
    AuditWrite = 6,
    Socket = 7,
    Bind = 8,
    Listen = 9,
    Accept = 10,
    Recv = 11,
    Send = 12,
    Wait = 13,
    Connect = 14,
    ReadFile = 15,
    WriteFile = 16,
    ReadDir = 17,
    Exec = 18,
}

/// Syscall return status.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i64)]
pub enum SyscallStatus {
    Ok = 0,
    UnknownSyscall = -1,
    PermissionDenied = -2,
    InvalidArgument = -3,
    NotImplemented = -4,
}

/// Raw syscall result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SyscallResult {
    pub status: SyscallStatus,
    pub value: u64,
}

impl SyscallResult {
    pub const fn ok(value: u64) -> Self {
        Self {
            status: SyscallStatus::Ok,
            value,
        }
    }

    pub const fn err(status: SyscallStatus) -> Self {
        Self { status, value: 0 }
    }
}

extern crate alloc;

pub mod socket;
pub mod fs;
pub mod process;

use alloc::string::String;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub enum CapabilityResource {
    IpcSend = 1,
    ServiceRegister = 2,
    AuditRead = 3,
    ProcessSpawn = 4,
}

impl CapabilityResource {
    fn resource(self) -> &'static str {
        match self {
            Self::IpcSend => "ipc:send:*",
            Self::ServiceRegister => "service:register",
            Self::AuditRead => "audit:read",
            Self::ProcessSpawn => "process:spawn",
        }
    }

    fn from_raw(raw: u64) -> Option<Self> {
        match raw {
            1 => Some(Self::IpcSend),
            2 => Some(Self::ServiceRegister),
            3 => Some(Self::AuditRead),
            4 => Some(Self::ProcessSpawn),
            _ => None,
        }
    }
}

pub fn dispatch(number: u64, args: [u64; 6]) -> SyscallResult {
    let held_capabilities = alloc::vec![String::from("cap:system:all")];
    dispatch_with_capabilities(number, args, &held_capabilities)
}

pub fn dispatch_for_process(pid: u64, number: u64, args: [u64; 6]) -> SyscallResult {
    let Some(held_capabilities) = crate::userspace::capabilities_for(pid) else {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    };

    if crate::userspace::record_syscall(pid).is_err() {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    dispatch_with_capabilities(number, args, &held_capabilities)
}

pub fn dispatch_with_capabilities(
    number: u64,
    args: [u64; 6],
    held_capabilities: &[String],
) -> SyscallResult {
    match number {
        x if x == SyscallNumber::Yield as u64 => SyscallResult::ok(0),
        x if x == SyscallNumber::IpcSend as u64 => {
            let message = match crate::ipc::Message::new(
                0,
                crate::ipc::Endpoint::new("runtime.ipc", "syscall"),
                crate::ipc::MessageKind::Event,
                "ipc:send:*",
                b"userspace ipc_send",
            ) {
                Ok(message) => message,
                Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
            };
            match crate::ipc::send(message, held_capabilities) {
                Ok(id) => SyscallResult::ok(id),
                Err(crate::ipc::IpcError::PermissionDenied) => {
                    SyscallResult::err(SyscallStatus::PermissionDenied)
                }
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::IpcReceive as u64 => {
            match crate::ipc::receive_for_service("runtime.ipc") {
                Ok(message) => SyscallResult::ok(message.id),
                Err(crate::ipc::IpcError::NoMessage) => SyscallResult::ok(0),
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::ServiceStart as u64 => {
            match crate::services::start_service_authorized(args[0], held_capabilities) {
                Ok(()) => SyscallResult::ok(args[0]),
                Err(err) if err.starts_with("missing capability") => {
                    SyscallResult::err(SyscallStatus::PermissionDenied)
                }
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::ServiceStop as u64 => {
            match crate::services::stop_service_authorized(args[0], held_capabilities) {
                Ok(()) => SyscallResult::ok(args[0]),
                Err(err) if err.starts_with("missing capability") => {
                    SyscallResult::err(SyscallStatus::PermissionDenied)
                }
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::CapabilityCheck as u64 => {
            let Some(resource) = CapabilityResource::from_raw(args[0]) else {
                return SyscallResult::err(SyscallStatus::InvalidArgument);
            };
            if crate::security::has_capability(held_capabilities, resource.resource()) {
                SyscallResult::ok(1)
            } else {
                SyscallResult::ok(0)
            }
        }
        x if x == SyscallNumber::AuditWrite as u64 => {
            if !crate::security::has_capability(held_capabilities, "ipc:send:*") {
                return SyscallResult::err(SyscallStatus::PermissionDenied);
            }
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::FileAccess,
                "userspace audit_write syscall",
            );
            SyscallResult::ok(0)
        }
        x if x == SyscallNumber::Socket as u64 => {
            socket::sys_socket(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::Bind as u64 => {
            socket::sys_bind(args[0], args[1])
        }
        x if x == SyscallNumber::Listen as u64 => {
            socket::sys_listen(args[0], args[1])
        }
        x if x == SyscallNumber::Accept as u64 => {
            socket::sys_accept(args[0])
        }
        x if x == SyscallNumber::Recv as u64 => {
            socket::sys_recv(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::Send as u64 => {
            socket::sys_send(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::Wait as u64 => {
            SyscallResult::ok(0)
        }
        x if x == SyscallNumber::Connect as u64 => {
            socket::sys_connect(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::ReadFile as u64 => {
            fs::sys_read_file(args)
        }
        x if x == SyscallNumber::WriteFile as u64 => {
            fs::sys_write_file(args)
        }
        x if x == SyscallNumber::ReadDir as u64 => {
            fs::sys_read_dir(args)
        }
        x if x == SyscallNumber::Exec as u64 => {
            process::sys_exec(args)
        }
        _ => SyscallResult::err(SyscallStatus::UnknownSyscall),
    }
}
