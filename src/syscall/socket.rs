// ============================================================================
// FerrumOS - Socket Syscalls
// ============================================================================

use crate::syscall::SyscallResult;
use crate::syscall::SyscallStatus;

pub fn sys_socket(_domain: u64, _type_: u64, _protocol: u64) -> SyscallResult {
    // Stub: create a new smoltcp socket and return an FD
    // domain=AF_INET(2), type=SOCK_STREAM(1)
    SyscallResult::ok(100) // Fake FD for now
}

pub fn sys_bind(fd: u64, _port: u64) -> SyscallResult {
    if fd != 100 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    // Stub: bind the socket to port
    SyscallResult::ok(0)
}

pub fn sys_listen(fd: u64, _backlog: u64) -> SyscallResult {
    if fd != 100 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    SyscallResult::ok(0)
}

pub fn sys_accept(fd: u64) -> SyscallResult {
    if fd != 100 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    // Stub: accept connection, return new FD
    SyscallResult::ok(101)
}

pub fn sys_recv(fd: u64, _buf_ptr: u64, _len: u64) -> SyscallResult {
    if fd != 100 && fd != 101 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    // Stub: read from socket
    SyscallResult::ok(0)
}

pub fn sys_send(fd: u64, _buf_ptr: u64, len: u64) -> SyscallResult {
    if fd != 100 && fd != 101 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    // Stub: write to socket
    SyscallResult::ok(len)
}
