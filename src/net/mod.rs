// ============================================================================
// FerrumOS - Network Subsystem
// ============================================================================
// Provides deterministic network state before physical NIC drivers exist. The
// loopback interface lets runtime services test networking policy safely.
// ============================================================================

extern crate alloc;

pub mod rtl8139;
pub mod stack;

use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use spin::Mutex;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InterfaceState {
    Up,
    Down,
    Planned,
}

#[derive(Debug, Clone)]
pub struct NetworkInterface {
    pub name: String,
    pub address: String,
    pub state: InterfaceState,
    pub driver: String,
    pub packets_sent: u64,
    pub packets_received: u64,
}

#[derive(Debug, Clone)]
pub struct Route {
    pub destination: String,
    pub gateway: String,
    pub interface: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NetworkStats {
    pub interfaces: usize,
    pub routes: usize,
    pub packets_sent: u64,
    pub packets_received: u64,
    pub denied: u64,
}

struct NetworkState {
    interfaces: Vec<NetworkInterface>,
    routes: Vec<Route>,
    denied: u64,
}

static NETWORK: Mutex<NetworkState> = Mutex::new(NetworkState {
    interfaces: Vec::new(),
    routes: Vec::new(),
    denied: 0,
});

pub fn init() {
    // Attempt to initialize the RTL8139 NIC
    match rtl8139::init() {
        Ok(_) => { crate::serial_println!("[  OK  ] RTL8139 initialized successfully"); }
        Err(e) => { crate::serial_println!("[ WARN ] Failed to initialize RTL8139: {}", e); }
    }

    let mut network = NETWORK.lock();
    network.interfaces.clear();
    network.routes.clear();
    network.denied = 0;

    network.interfaces.push(NetworkInterface {
        name: String::from("lo"),
        address: String::from("127.0.0.1/8"),
        state: InterfaceState::Up,
        driver: String::from("loopback"),
        packets_sent: 0,
        packets_received: 0,
    });
    network.interfaces.push(NetworkInterface {
        name: String::from("net0"),
        address: String::from("unassigned"),
        state: InterfaceState::Planned,
        driver: String::from("pending-nic"),
        packets_sent: 0,
        packets_received: 0,
    });

    network.routes.push(Route {
        destination: String::from("127.0.0.0/8"),
        gateway: String::from("local"),
        interface: String::from("lo"),
    });
}

pub fn interfaces() -> Vec<NetworkInterface> {
    NETWORK.lock().interfaces.clone()
}

pub fn routes() -> Vec<Route> {
    NETWORK.lock().routes.clone()
}

pub fn stats() -> NetworkStats {
    let network = NETWORK.lock();
    let packets_sent = network
        .interfaces
        .iter()
        .map(|interface| interface.packets_sent)
        .sum();
    let packets_received = network
        .interfaces
        .iter()
        .map(|interface| interface.packets_received)
        .sum();

    NetworkStats {
        interfaces: network.interfaces.len(),
        routes: network.routes.len(),
        packets_sent,
        packets_received,
        denied: network.denied,
    }
}

pub fn send_loopback(payload: &str, held_capabilities: &[String]) -> Result<(), String> {
    if !crate::security::has_capability(held_capabilities, "net:connect:*") {
        if let Some(mut network) = NETWORK.try_lock() {
            network.denied += 1;
        }
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            "loopback send denied; caller lacks net connect",
        );
        return Err(String::from("missing capability net:connect:*"));
    }

    if payload.len() > 128 {
        return Err(String::from("payload too large"));
    }

    let mut network = NETWORK.lock();
    let interface = network
        .interfaces
        .iter_mut()
        .find(|interface| interface.name == "lo")
        .ok_or_else(|| String::from("loopback interface missing"))?;

    interface.packets_sent += 1;
    interface.packets_received += 1;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        "loopback packet delivered",
    );
    Ok(())
}

pub fn loopback_capabilities() -> Vec<String> {
    vec![String::from("cap:net:connect")]
}
