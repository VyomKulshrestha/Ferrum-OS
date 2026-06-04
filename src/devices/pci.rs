// ============================================================================
// FerrumOS - PCI Bus Scanner
// ============================================================================
// Minimal PCI configuration space access for discovering hardware like NICs.
// ============================================================================

use x86_64::instructions::port::Port;

const CONFIG_ADDRESS: u16 = 0xCF8;
const CONFIG_DATA: u16 = 0xCFC;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PciDevice {
    pub bus: u8,
    pub slot: u8,
    pub func: u8,
}

/// Read a 32-bit register from PCI configuration space
pub fn read_config_u32(bus: u8, slot: u8, func: u8, offset: u8) -> u32 {
    let address = 0x80000000
        | ((bus as u32) << 16)
        | ((slot as u32) << 11)
        | ((func as u32) << 8)
        | (offset as u32 & 0xFC);
    unsafe {
        let mut addr_port = Port::<u32>::new(CONFIG_ADDRESS);
        let mut data_port = Port::<u32>::new(CONFIG_DATA);
        addr_port.write(address);
        data_port.read()
    }
}

/// Write a 32-bit register to PCI configuration space
pub fn write_config_u32(bus: u8, slot: u8, func: u8, offset: u8, value: u32) {
    let address = 0x80000000
        | ((bus as u32) << 16)
        | ((slot as u32) << 11)
        | ((func as u32) << 8)
        | (offset as u32 & 0xFC);
    unsafe {
        let mut addr_port = Port::<u32>::new(CONFIG_ADDRESS);
        let mut data_port = Port::<u32>::new(CONFIG_DATA);
        addr_port.write(address);
        data_port.write(value);
    }
}

/// Read a 16-bit register from PCI configuration space
pub fn read_config_u16(bus: u8, slot: u8, func: u8, offset: u8) -> u16 {
    let val = read_config_u32(bus, slot, func, offset);
    ((val >> ((offset & 2) * 8)) & 0xFFFF) as u16
}

/// Read an 8-bit register from PCI configuration space
pub fn read_config_u8(bus: u8, slot: u8, func: u8, offset: u8) -> u8 {
    let val = read_config_u32(bus, slot, func, offset);
    ((val >> ((offset & 3) * 8)) & 0xFF) as u8
}

/// Discover a device on the PCI bus by Vendor ID and Device ID
pub fn find_device(vendor_id: u16, device_id: u16) -> Option<PciDevice> {
    for bus in 0..=255 {
        for slot in 0..32 {
            let vendor = read_config_u16(bus, slot, 0, 0);
            if vendor == 0xFFFF {
                continue;
            }

            for func in 0..8 {
                let current_vendor = read_config_u16(bus, slot, func, 0);
                if current_vendor == 0xFFFF {
                    continue;
                }

                let current_device = read_config_u16(bus, slot, func, 2);
                if current_vendor == vendor_id && current_device == device_id {
                    return Some(PciDevice { bus, slot, func });
                }

                if func == 0 {
                    let header_type = read_config_u8(bus, slot, 0, 0x0E);
                    if (header_type & 0x80) == 0 {
                        break;
                    }
                }
            }
        }
    }
    None
}
