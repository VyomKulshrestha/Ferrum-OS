// ============================================================================
// FerrumOS - Socket Syscalls (wired to smoltcp)
// ============================================================================
// These syscalls bridge userspace socket requests to the kernel's smoltcp
// network stack via the interface manager in `net::iface`.
// ============================================================================

use crate::syscall::SyscallResult;
use crate::syscall::SyscallStatus;
use crate::net::iface;

/// Create a new socket. Returns a kernel file descriptor.
/// args: domain (AF_INET=2), type (SOCK_STREAM=1, SOCK_DGRAM=2), protocol (0)
pub fn sys_socket(_domain: u64, type_: u64, _protocol: u64) -> SyscallResult {
    // Currently only TCP (SOCK_STREAM=1) is supported
    match type_ {
        1 => {
            // SOCK_STREAM → TCP
            match iface::socket_create_tcp() {
                Ok(fd) => SyscallResult::ok(fd),
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        _ => SyscallResult::err(SyscallStatus::NotImplemented),
    }
}

/// Connect a socket to a remote address.
/// args: fd, ip_packed (IPv4 as u32 big-endian), port
pub fn sys_connect(fd: u64, ip_packed: u64, port: u64) -> SyscallResult {
    // Poll once before connecting to process any pending events
    iface::poll();

    match iface::socket_connect(fd, ip_packed, port) {
        Ok(()) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Bind a socket to a local port and start listening.
/// For TCP this puts the socket into the LISTEN state.
pub fn sys_bind(fd: u64, port: u64) -> SyscallResult {
    match iface::socket_bind(fd, port) {
        Ok(()) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Listen on a bound socket (TCP listen is handled in bind for smoltcp).
pub fn sys_listen(fd: u64, _backlog: u64) -> SyscallResult {
    // smoltcp combines bind+listen into socket.listen(), which we do in sys_bind.
    // Validate the FD is real.
    match iface::socket_is_active(fd) {
        Ok(_) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Accept an incoming connection (stub — smoltcp handles this differently).
pub fn sys_accept(fd: u64) -> SyscallResult {
    // In smoltcp, a listening socket automatically transitions to established
    // when a SYN arrives. For now, we poll and check if the socket is active.
    iface::poll();

    match iface::socket_is_active(fd) {
        Ok(true) => SyscallResult::ok(fd), // Return same FD (smoltcp model)
        Ok(false) => SyscallResult::err(SyscallStatus::NotImplemented), // No connection yet
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Receive data from a socket.
/// args: fd, buf_ptr (userspace pointer), len (buffer size)
/// Returns number of bytes read.
pub fn sys_recv(fd: u64, buf_ptr: u64, len: u64) -> SyscallResult {
    // Poll the interface to process any incoming packets
    iface::poll();

    if buf_ptr == 0 || len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Safety: we trust the kernel-side caller for now. In a real OS we would
    // validate that buf_ptr falls within the calling process's address space.
    let buf = unsafe { core::slice::from_raw_parts_mut(buf_ptr as *mut u8, len as usize) };

    match iface::socket_recv(fd, buf) {
        Ok(n) => SyscallResult::ok(n as u64),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Send data through a socket.
/// args: fd, buf_ptr (pointer to data), len (data length)
/// Returns number of bytes sent.
pub fn sys_send(fd: u64, buf_ptr: u64, len: u64) -> SyscallResult {
    // Poll before sending to ensure connection state is current
    iface::poll();

    if buf_ptr == 0 || len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Safety: same trust model as sys_recv
    let data = unsafe { core::slice::from_raw_parts(buf_ptr as *const u8, len as usize) };

    match iface::socket_send(fd, data) {
        Ok(n) => {
            // Poll again to flush the TX buffer out through the NIC
            iface::poll();
            SyscallResult::ok(n as u64)
        }
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
