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

/// Dispatch a syscall number.
///
/// Real userspace will enter this through a dedicated syscall instruction or
/// software interrupt. For now, this is a typed ABI placeholder used by tests
/// and runtime-service scaffolding.
pub fn dispatch(number: u64, _args: [u64; 6]) -> SyscallResult {
    match number {
        x if x == SyscallNumber::Yield as u64 => SyscallResult::ok(0),
        x if x == SyscallNumber::IpcSend as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        x if x == SyscallNumber::IpcReceive as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        x if x == SyscallNumber::ServiceStart as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        x if x == SyscallNumber::ServiceStop as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        x if x == SyscallNumber::CapabilityCheck as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        x if x == SyscallNumber::AuditWrite as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        _ => SyscallResult::err(SyscallStatus::UnknownSyscall),
    }
}
