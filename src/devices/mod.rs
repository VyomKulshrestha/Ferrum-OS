// ============================================================================
// FerrumOS - Device Registry
// ============================================================================
// Tracks kernel-visible devices and future driver surfaces. This is the first
// step toward a real HAL without pretending unavailable hardware is online.
// ============================================================================

extern crate alloc;

pub mod hda;
pub mod pci;
pub mod vga_fb;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceClass {
    Display,
    Serial,
    Input,
    Timer,
    Storage,
    Network,
    Audio,
    Camera,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceState {
    Online,
    Planned,
    Disabled,
}

#[derive(Debug, Clone)]
pub struct Device {
    pub id: u64,
    pub name: String,
    pub class: DeviceClass,
    pub state: DeviceState,
    pub driver: String,
    pub capability: String,
}

struct DeviceRegistry {
    devices: Vec<Device>,
    next_id: u64,
}

static REGISTRY: Mutex<DeviceRegistry> = Mutex::new(DeviceRegistry {
    devices: Vec::new(),
    next_id: 1,
});

pub fn init() {
    let mut registry = REGISTRY.lock();
    registry.devices.clear();
    registry.next_id = 1;

    registry.register("vga.text", DeviceClass::Display, DeviceState::Online, "vga", "display:write");
    registry.register("uart.com1", DeviceClass::Serial, DeviceState::Online, "uart_16550", "serial:write");
    registry.register("pit.timer", DeviceClass::Timer, DeviceState::Online, "pic8259-pit", "timer:read");
    registry.register("ps2.keyboard", DeviceClass::Input, DeviceState::Online, "ps2-set1", "input:read");
    registry.register("ramfs.root", DeviceClass::Storage, DeviceState::Online, "ramfs", "fs:*");

    registry.register("net.primary", DeviceClass::Network, DeviceState::Planned, "pending", "net:*");
    registry.register("audio.primary", DeviceClass::Audio, DeviceState::Planned, "pending", "audio:*");
    registry.register("camera.primary", DeviceClass::Camera, DeviceState::Planned, "pending", "camera:*");
}

impl DeviceRegistry {
    fn register(
        &mut self,
        name: &str,
        class: DeviceClass,
        state: DeviceState,
        driver: &str,
        capability: &str,
    ) {
        let id = self.next_id;
        self.next_id += 1;
        self.devices.push(Device {
            id,
            name: name.to_string(),
            class,
            state,
            driver: driver.to_string(),
            capability: capability.to_string(),
        });
    }
}

pub fn list_devices() -> Vec<Device> {
    REGISTRY.lock().devices.clone()
}

/// Register a new device at runtime.
///
/// Used by subsystem drivers (e.g. ATA) to register hardware
/// discovered after boot-time `init()`.
pub fn register_device(
    name: &str,
    class: DeviceClass,
    state: DeviceState,
    driver: &str,
    capability: &str,
) {
    REGISTRY.lock().register(name, class, state, driver, capability);
}

pub fn device_count_by_state(state: DeviceState) -> usize {
    REGISTRY
        .lock()
        .devices
        .iter()
        .filter(|device| device.state == state)
        .count()
}
