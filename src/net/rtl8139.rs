// ============================================================================
// FerrumOS - RTL8139 Network Driver
// ============================================================================
// Driver for the Realtek RTL8139 PCI Fast Ethernet Controller.
// Handles packet transmission and ring-buffer reception via DMA.
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use core::slice;
use spin::Mutex;
use x86_64::{
    instructions::port::{Port, PortReadOnly, PortWriteOnly},
    PhysAddr, VirtAddr,
};

use crate::devices::pci;
use crate::memory;

const RTL8139_VENDOR_ID: u16 = 0x10EC;
const RTL8139_DEVICE_ID: u16 = 0x8139;

// Ports offset from I/O base
const MAC05: u16 = 0x00;
const TSD0: u16 = 0x10;
const TSAD0: u16 = 0x20;
const RBSTART: u16 = 0x30;
const CR: u16 = 0x37;
const CAPR: u16 = 0x38;
#[allow(dead_code)]
const CBR: u16 = 0x3A;
const IMR: u16 = 0x3C;
const ISR: u16 = 0x3E;
const RCR: u16 = 0x44;
const CONFIG1: u16 = 0x52;

pub struct Rtl8139 {
    io_base: u16,
    rx_buffer_virt: VirtAddr,
    _rx_buffer_phys: PhysAddr,
    tx_curr: u8,
    rx_curr: u16,
    mac_address: [u8; 6],
}

pub static RTL8139_NIC: Mutex<Option<Rtl8139>> = Mutex::new(None);

pub fn init() -> Result<(), &'static str> {
    let device = pci::find_device(RTL8139_VENDOR_ID, RTL8139_DEVICE_ID)
        .ok_or("RTL8139 not found on PCI bus")?;

    // Read BAR0 (I/O base)
    let bar0 = pci::read_config_u32(device.bus, device.slot, device.func, 0x10);
    if (bar0 & 1) == 0 {
        return Err("RTL8139 BAR0 is not an I/O port");
    }
    let io_base = (bar0 & !3) as u16;

    // Enable PCI Bus Mastering
    let command_reg = pci::read_config_u32(device.bus, device.slot, device.func, 0x04);
    pci::write_config_u32(
        device.bus,
        device.slot,
        device.func,
        0x04,
        command_reg | 0x07, // I/O, Mem, Bus Master
    );

    // Power on (Config1)
    unsafe {
        PortWriteOnly::<u8>::new(io_base + CONFIG1).write(0x00);
    }

    // Software Reset
    unsafe {
        let mut cr_port = Port::<u8>::new(io_base + CR);
        cr_port.write(0x10); // Reset
        while (cr_port.read() & 0x10) != 0 {}
    }

    // Allocate 3 physically contiguous frames for the RX buffer (12 KiB)
    let frame1 = memory::allocate_frame().ok_or("Failed to allocate RX frame 1")?;
    let frame2 = memory::allocate_frame().ok_or("Failed to allocate RX frame 2")?;
    let frame3 = memory::allocate_frame().ok_or("Failed to allocate RX frame 3")?;

    if frame2.start_address().as_u64() != frame1.start_address().as_u64() + 4096
        || frame3.start_address().as_u64() != frame2.start_address().as_u64() + 4096
    {
        return Err("Allocated RX frames are not physically contiguous");
    }

    let rx_buffer_phys = frame1.start_address();
    let rx_buffer_virt = memory::phys_to_virt(rx_buffer_phys);

    let mut mac_address = [0u8; 6];
    unsafe {
        let mac_low = PortReadOnly::<u32>::new(io_base + MAC05).read();
        let mac_high = PortReadOnly::<u16>::new(io_base + MAC05 + 4).read();
        mac_address[0] = (mac_low & 0xFF) as u8;
        mac_address[1] = ((mac_low >> 8) & 0xFF) as u8;
        mac_address[2] = ((mac_low >> 16) & 0xFF) as u8;
        mac_address[3] = ((mac_low >> 24) & 0xFF) as u8;
        mac_address[4] = (mac_high & 0xFF) as u8;
        mac_address[5] = ((mac_high >> 8) & 0xFF) as u8;

        // Set RX buffer start address
        PortWriteOnly::<u32>::new(io_base + RBSTART).write(rx_buffer_phys.as_u64() as u32);

        // Set IMR (Interrupt Mask Register) to TOK and ROK
        PortWriteOnly::<u16>::new(io_base + IMR).write(0x0005); // TOK=0x04, ROK=0x01

        // Set RCR (Receive Configuration Register) to accept AB, AM, AP, AAP + WRAP
        PortWriteOnly::<u32>::new(io_base + RCR).write(0x8F | 0x80);

        // Enable RX and TX
        PortWriteOnly::<u8>::new(io_base + CR).write(0x0C); // RE=0x08, TE=0x04
    }

    *RTL8139_NIC.lock() = Some(Rtl8139 {
        io_base,
        _rx_buffer_phys: rx_buffer_phys,
        rx_buffer_virt,
        tx_curr: 0,
        rx_curr: 0,
        mac_address,
    });

    crate::devices::register_device(
        "net.rtl8139",
        crate::devices::DeviceClass::Network,
        crate::devices::DeviceState::Online,
        "rtl8139",
        "net:eth",
    );

    Ok(())
}

impl Rtl8139 {
    pub fn mac_address(&self) -> [u8; 6] {
        self.mac_address
    }

    pub fn send_packet(&mut self, data: &[u8]) -> Result<(), &'static str> {
        if data.len() > 1518 {
            return Err("Packet too large");
        }

        // We need a physically contiguous buffer for TX data.
        // We can allocate one frame for TX buffers and reuse it.
        // For simplicity, let's copy to a statically allocated physical buffer,
        // or just allocate a frame if not already done.
        // Wait, for this minimal driver, let's lazily allocate a TX buffer.
        // Actually, we can use a static global for TX buffer if needed, but since we are locked, we can just allocate it once inside the struct.
        // Let's assume we implement a tx_buffer per transmit slot later. For now, allocate one frame.
        // Since we are in no_std and memory::allocate_frame gives us physical memory, let's keep it simple.
        
        let tx_frame = memory::allocate_frame().ok_or("Failed to allocate TX frame")?;
        let tx_virt = memory::phys_to_virt(tx_frame.start_address());

        unsafe {
            let tx_slice = slice::from_raw_parts_mut(tx_virt.as_mut_ptr::<u8>(), data.len());
            tx_slice.copy_from_slice(data);
            
            let tsad_port = self.io_base + TSAD0 + (self.tx_curr as u16 * 4);
            let tsd_port = self.io_base + TSD0 + (self.tx_curr as u16 * 4);

            PortWriteOnly::<u32>::new(tsad_port).write(tx_frame.start_address().as_u64() as u32);
            PortWriteOnly::<u32>::new(tsd_port).write(data.len() as u32);
        }

        self.tx_curr = (self.tx_curr + 1) % 4;

        Ok(())
    }

    pub fn receive_packet(&mut self) -> Option<Vec<u8>> {
        unsafe {
            let mut cr_port = PortReadOnly::<u8>::new(self.io_base + CR);
            if (cr_port.read() & 0x01) != 0 {
                return None; // RX buffer empty
            }

            let rx_ptr = self.rx_buffer_virt.as_u64() as *const u8;
            let offset = self.rx_curr as usize;
            
            let header = core::ptr::read_unaligned(rx_ptr.add(offset) as *const u16);
            let length = core::ptr::read_unaligned(rx_ptr.add(offset + 2) as *const u16) as usize;

            if header & 0x01 == 0 {
                // Invalid packet or error
                return None;
            }

            let packet_len = length.saturating_sub(4); // Subtract 4 bytes CRC
            let packet_data = slice::from_raw_parts(rx_ptr.add(offset + 4), packet_len);
            
            let mut vec = Vec::with_capacity(packet_len);
            vec.extend_from_slice(packet_data);

            // Update rx_curr
            let total_length = (length + 4 + 3) & !3; // Align to 4 bytes
            self.rx_curr = (self.rx_curr + total_length as u16) % 8192;

            // Update CAPR (subtract 16 per RTL8139 spec)
            PortWriteOnly::<u16>::new(self.io_base + CAPR).write(self.rx_curr.wrapping_sub(16));

            Some(vec)
        }
    }
    
    pub fn handle_interrupt(&mut self) {
        unsafe {
            let mut isr_port = Port::<u16>::new(self.io_base + ISR);
            let status = isr_port.read();
            isr_port.write(status); // Acknowledge
        }
    }
}
