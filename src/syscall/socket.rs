// ============================================================================
// FerrumOS - Socket Syscalls (wired to smoltcp)
// ============================================================================
// These syscalls bridge userspace socket requests to the kernel's smoltcp
// network stack via the interface manager in `net::iface`.
// ============================================================================

use crate::net::iface;
use crate::syscall::SyscallResult;
use crate::syscall::SyscallStatus;

/// Bound one network copy to a practical TCP chunk. This prevents an
/// untrusted caller from forcing a multi-gigabyte kernel allocation even when
/// the claimed user range is otherwise valid.
const MAX_SOCKET_IO: usize = 1024 * 1024;

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

    let requested = match usize::try_from(len) {
        Ok(value) if value > 0 && value <= MAX_SOCKET_IO => value,
        _ => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    if !super::fs::valid_user_range(buf_ptr, requested) {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    // Receive into kernel-owned memory first. The smoltcp lock and caller's
    // address space are never held at the same time, and no device path gets a
    // mutable pointer into ring-3 memory.
    let mut data = alloc::vec![0u8; requested];

    match iface::socket_recv(fd, &mut data) {
        Ok(n) => {
            let copied = unsafe { super::fs::copy_to_user(buf_ptr, &data[..n], requested) };
            if copied == n {
                SyscallResult::ok(n as u64)
            } else {
                SyscallResult::err(SyscallStatus::InvalidArgument)
            }
        }
        Err("blocked") => SyscallResult::err(SyscallStatus::Blocked),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Send data through a socket.
/// args: fd, buf_ptr (pointer to data), len (data length)
/// Returns number of bytes sent.
pub fn sys_send(fd: u64, buf_ptr: u64, len: u64) -> SyscallResult {
    // Poll before sending to ensure connection state is current
    iface::poll();

    let data = match unsafe { super::fs::read_user_bytes(buf_ptr, len, MAX_SOCKET_IO) } {
        Some(data) => data,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    match iface::socket_send(fd, &data) {
        Ok(n) => {
            // Poll again to flush the TX buffer out through the NIC
            iface::poll();
            SyscallResult::ok(n as u64)
        }
        Err("blocked") => SyscallResult::err(SyscallStatus::Blocked),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}

/// Close a socket.
/// args: fd
pub fn sys_close(fd: u64) -> SyscallResult {
    match iface::socket_close(fd) {
        Ok(()) => SyscallResult::ok(0),
        Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
    }
}
