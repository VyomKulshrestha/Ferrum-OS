// ============================================================================
// FerrumOS - smoltcp Interface Manager
// ============================================================================
// Creates and manages the global smoltcp Interface, socket set, and the
// kernel file descriptor table that maps userspace FDs to smoltcp
// SocketHandles.
// ============================================================================

extern crate alloc;

use alloc::vec;
use smoltcp::iface::{Config, Interface, SocketHandle, SocketSet};
use smoltcp::socket::tcp;
use smoltcp::time::Instant;
use smoltcp::wire::{EthernetAddress, HardwareAddress, IpAddress, Ipv4Address};
use spin::Mutex;

use crate::net::rtl8139::RTL8139_NIC;
use crate::net::stack::Rtl8139Device;

// ---- File Descriptor Table -------------------------------------------------

/// Maps kernel FDs to smoltcp socket handles.
#[derive(Debug, Clone, Copy)]
pub struct SocketEntry {
    pub handle: SocketHandle,
    pub socket_type: SocketType,
    pub in_use: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SocketType {
    Tcp,
}

const MAX_SOCKETS: usize = 64;
const FD_BASE: u64 = 100; // FDs start at 100 to avoid collision with stdio

/// The interface state is split into individual Mutex-wrapped fields so that
/// Rust's borrow checker allows us to mutably borrow the interface, device,
/// and socket set simultaneously (which smoltcp's `poll()` requires).
static IFACE: Mutex<Option<Interface>> = Mutex::new(None);
static SOCKETS: Mutex<Option<SocketSet<'static>>> = Mutex::new(None);
static DEVICE: Mutex<Rtl8139Device> = Mutex::new(Rtl8139Device);
static FD_TABLE: Mutex<[Option<SocketEntry>; MAX_SOCKETS]> = Mutex::new([None; MAX_SOCKETS]);
static INITIALIZED: spin::Once = spin::Once::new();

fn is_initialized() -> bool {
    INITIALIZED.is_completed()
}

// ---- Initialization --------------------------------------------------------

/// Initialize the smoltcp interface using the RTL8139 NIC.
/// Called from `net::init()` after the RTL8139 driver is ready.
pub fn init() {
    let mac = {
        let nic = RTL8139_NIC.lock();
        match nic.as_ref() {
            Some(n) => n.mac_address(),
            None => {
                crate::serial_println!("[ WARN ] No NIC available for smoltcp interface");
                return;
            }
        }
    };

    // Build the smoltcp config with the real hardware MAC
    let hw_addr = HardwareAddress::Ethernet(EthernetAddress(mac));
    let config = Config::new(hw_addr);

    let mut device = DEVICE.lock();
    let mut iface = Interface::new(config, &mut *device, Instant::from_millis(0));

    // Configure the interface IP address
    // QEMU user-mode networking gives the guest 10.0.2.15/24 by default
    iface.update_ip_addrs(|ip_addrs| {
        ip_addrs
            .push(smoltcp::wire::IpCidr::new(IpAddress::v4(10, 0, 2, 15), 24))
            .ok();
    });

    // Set the default gateway (QEMU user-mode default is 10.0.2.2)
    iface
        .routes_mut()
        .add_default_ipv4_route(Ipv4Address::new(10, 0, 2, 2))
        .ok();

    *IFACE.lock() = Some(iface);
    *SOCKETS.lock() = Some(SocketSet::new(vec![]));

    INITIALIZED.call_once(|| ());

    crate::serial_println!("[  OK  ] smoltcp interface initialized (10.0.2.15/24, gw 10.0.2.2)");
}

// ---- Socket Operations (called from syscall/socket.rs) ---------------------

/// Create a new TCP socket and return its kernel FD.
pub fn socket_create_tcp() -> Result<u64, &'static str> {
    if !is_initialized() {
        return Err("network interface not initialized");
    }

    // Create TCP socket with buffers large enough for a TLS 1.3 handshake
    // flight (ServerHello + Certificate + CertVerify + Finished can exceed
    // 4 KiB). 16 KiB matches the daemon's embedded-tls record buffers and
    // avoids handshake stalls/resets from receive-window starvation.
    let rx_buffer = tcp::SocketBuffer::new(vec![0u8; 16384]);
    let tx_buffer = tcp::SocketBuffer::new(vec![0u8; 16384]);
    let socket = tcp::Socket::new(rx_buffer, tx_buffer);

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;
    let handle = sockets.add(socket);

    // Find a free FD slot
    let mut fd_table = FD_TABLE.lock();
    for i in 0..MAX_SOCKETS {
        if fd_table[i].is_none() {
            fd_table[i] = Some(SocketEntry {
                handle,
                socket_type: SocketType::Tcp,
                in_use: true,
            });
            return Ok(FD_BASE + i as u64);
        }
    }

    Err("no free file descriptors")
}

/// Connect a TCP socket to a remote address.
/// `fd`: kernel FD, `ip_packed`: IPv4 as u32 (network byte order), `port`: destination port
pub fn socket_connect(fd: u64, ip_packed: u64, port: u64) -> Result<(), &'static str> {
    if !is_initialized() {
        return Err("network interface not initialized");
    }

    let entry = lookup_fd(fd)?;
    let handle = entry.handle;

    let ip_bytes = (ip_packed as u32).to_be_bytes();
    let remote_addr = Ipv4Address::new(ip_bytes[0], ip_bytes[1], ip_bytes[2], ip_bytes[3]);
    let remote_port = port as u16;

    // We need a local (ephemeral) port. Pick one based on the FD to avoid collisions.
    let local_port = 49152 + ((fd - FD_BASE) as u16);

    let mut iface = IFACE.lock();
    let iface = iface.as_mut().ok_or("interface not ready")?;

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;

    let socket = sockets.get_mut::<tcp::Socket>(handle);
    socket
        .connect(
            iface.context(),
            (IpAddress::Ipv4(remote_addr), remote_port),
            local_port,
        )
        .map_err(|_| "TCP connect failed")?;

    Ok(())
}

/// Bind a TCP socket to a local port and start listening.
pub fn socket_bind(fd: u64, port: u64) -> Result<(), &'static str> {
    if !is_initialized() {
        return Err("network interface not initialized");
    }

    let entry = lookup_fd(fd)?;
    let handle = entry.handle;

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;

    let socket = sockets.get_mut::<tcp::Socket>(handle);
    socket
        .listen(port as u16)
        .map_err(|_| "TCP bind/listen failed")?;

    Ok(())
}

/// Send data through a TCP socket. Returns bytes written.
pub fn socket_send(fd: u64, data: &[u8]) -> Result<usize, &'static str> {
    if !is_initialized() {
        return Err("network interface not initialized");
    }

    let entry = lookup_fd(fd)?;
    let handle = entry.handle;

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;

    let socket = sockets.get_mut::<tcp::Socket>(handle);
    if !socket.can_send() {
        use smoltcp::socket::tcp::State;
        match socket.state() {
            // Still completing the TCP handshake (the window right after
            // connect): not sendable *yet*, but will be — tell userspace to
            // retry rather than failing. Previously this was misclassified as
            // a hard error, which aborted the TLS ClientHello send.
            State::SynSent | State::SynReceived | State::Listen => return Err("blocked"),
            // Established but TX buffer full → retry; anything terminal/closing
            // → genuine "cannot send".
            _ => {
                if socket.may_send() {
                    return Err("blocked");
                } else {
                    return Err("socket not ready to send");
                }
            }
        }
    }

    socket.send_slice(data).map_err(|_| "TCP send failed")
}

/// Receive data from a TCP socket. Returns bytes read.
pub fn socket_recv(fd: u64, buf: &mut [u8]) -> Result<usize, &'static str> {
    if !is_initialized() {
        return Err("network interface not initialized");
    }

    let entry = lookup_fd(fd)?;
    let handle = entry.handle;

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;

    let socket = sockets.get_mut::<tcp::Socket>(handle);
    if !socket.can_recv() {
        use smoltcp::socket::tcp::State;
        match socket.state() {
            // Still completing the TCP handshake: no data yet, NOT EOF — retry.
            // (SYN-SENT has may_recv()==false, which previously returned Ok(0)
            // and was misread by embedded-tls as a premature connection close.)
            State::SynSent | State::SynReceived | State::Listen => return Err("blocked"),
            // Established with no buffered data → retry; a peer that has closed
            // its write side → genuine EOF.
            _ => {
                if socket.may_recv() {
                    return Err("blocked");
                } else {
                    return Ok(0);
                }
            }
        }
    }

    socket.recv_slice(buf).map_err(|_| "TCP recv failed")
}

/// Close a socket and free its FD.
pub fn socket_close(fd: u64) -> Result<(), &'static str> {
    let idx = fd_to_index(fd)?;

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;

    let mut fd_table = FD_TABLE.lock();
    if let Some(entry) = fd_table[idx] {
        let socket = sockets.get_mut::<tcp::Socket>(entry.handle);
        socket.close();
        fd_table[idx] = None;
        Ok(())
    } else {
        Err("invalid file descriptor")
    }
}

/// Check if a TCP socket is connected and ready.
pub fn socket_is_active(fd: u64) -> Result<bool, &'static str> {
    let entry = lookup_fd(fd)?;

    let mut sockets = SOCKETS.lock();
    let sockets = sockets.as_mut().ok_or("socket set not initialized")?;

    let socket = sockets.get::<tcp::Socket>(entry.handle);
    Ok(socket.is_active())
}

// ---- Polling ---------------------------------------------------------------

/// Poll the smoltcp interface. Should be called periodically (e.g. from
/// the PIT timer interrupt or a dedicated polling loop).
pub fn poll() {
    if !is_initialized() {
        return;
    }

    let mut iface_guard = IFACE.lock();
    let mut sockets_guard = SOCKETS.lock();
    let mut device_guard = DEVICE.lock();

    if let (Some(iface), Some(sockets)) = (iface_guard.as_mut(), sockets_guard.as_mut()) {
        // PIT fires ~18.2 times/sec; convert ticks to approximate milliseconds
        let ticks = crate::scheduler::total_ticks();
        let timestamp = Instant::from_millis((ticks * 55) as i64); // ~55ms per tick
        iface.poll(timestamp, &mut *device_guard, sockets);
    }
}

// ---- Helpers ---------------------------------------------------------------

fn fd_to_index(fd: u64) -> Result<usize, &'static str> {
    if fd < FD_BASE || fd >= FD_BASE + MAX_SOCKETS as u64 {
        return Err("invalid file descriptor");
    }
    Ok((fd - FD_BASE) as usize)
}

fn lookup_fd(fd: u64) -> Result<SocketEntry, &'static str> {
    let idx = fd_to_index(fd)?;
    let fd_table = FD_TABLE.lock();
    fd_table[idx].ok_or("file descriptor not in use")
}
