// ============================================================================
// FerrumOS - RTL8139 Network Driver
// ============================================================================
// Driver for the Realtek RTL8139 PCI Fast Ethernet Controller.
// Handles packet transmission and ring-buffer reception via DMA. The driver is
// polled (smoltcp's `iface::poll`); the device's interrupts stay masked.
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use core::slice;
use core::sync::atomic::{AtomicU64, Ordering};
use spin::Mutex;
use x86_64::{
    instructions::port::{Port, PortReadOnly, PortWriteOnly},
    PhysAddr, VirtAddr,
};

use crate::devices::pci;
use crate::memory;

/// TSD bit 13: the driver owns the descriptor again (DMA to the FIFO is done).
const TSD_OWN: u32 = 1 << 13;
/// Sends refused because the next TX descriptor was still the device's.
pub static TX_BUSY_DROPS: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

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

/// Receive ring length programmed in RCR (RBLEN = 0: 8 KiB + 16 bytes).
pub const RX_RING_LEN: usize = 8192;
/// RCR: accept broadcast, multicast, physical match and all physical (0x0F),
/// WRAP (0x80): the device writes a frame that runs past the end of the ring
/// linearly after it instead of splitting it.
const RCR_VALUE: u32 = 0x0F | 0x80;
/// Largest frame (with its 4-byte CRC) the stack accepts: 1514 + 4, plus room
/// for a VLAN tag.
pub const MAX_RX_FRAME_LEN: usize = 1522;
/// Smallest plausible frame length field (an Ethernet header plus CRC).
pub const MIN_RX_FRAME_LEN: usize = 18;
/// Bytes of RX memory after the ring. With WRAP set the device writes past the
/// end of the ring, and in ring mode it checks a frame's size only against the
/// free space of a non-empty ring (QEMU `rtl8139_receive`: `avail != 0 &&
/// RX_ALIGN(size + 8) >= avail`), so a frame arriving at an empty ring is
/// written whole whatever its size. QEMU's net layer passes frames up to
/// 4096 + 65536 bytes. The slack covers the ring's last offset, the 4-byte
/// header and such a frame.
const RX_SLACK: usize = 16 + 4 + 4096 + 65536 + 4096;
/// Frames of RX memory (ring + slack), allocated physically contiguous.
pub const RX_FRAMES: usize = (RX_RING_LEN + RX_SLACK + 4095) / 4096;
const TX_FRAMES: usize = 4;
/// The RTL8139's RBSTART and TSAD registers hold 32-bit bus addresses.
const DMA_LIMIT: u64 = 1 << 32;

/// Receive-path counters (read by `test-syscall net-k2`).
pub static RX_DELIVERED: AtomicU64 = AtomicU64::new(0);
pub static RX_DROPPED_OVERSIZE: AtomicU64 = AtomicU64::new(0);
pub static RX_RESETS: AtomicU64 = AtomicU64::new(0);
/// Largest frame length handed to the network stack since boot.
pub static RX_MAX_DELIVERED_LEN: AtomicU64 = AtomicU64::new(0);

pub struct Rtl8139 {
    io_base: u16,
    rx_buffer_virt: VirtAddr,
    rx_buffer_phys: PhysAddr,
    tx_buffers: [PhysAddr; TX_FRAMES],
    tx_curr: u8,
    rx_curr: u16,
    mac_address: [u8; 6],
}

pub static RTL8139_NIC: Mutex<Option<Rtl8139>> = Mutex::new(None);

/// Decision for one receive-ring header.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RxHeader {
    /// A good frame of this many bytes (CRC excluded) follows the header.
    Deliver(usize),
    /// A good header for a frame the stack does not accept; skip it.
    Skip,
    /// The header is not a good-frame header (or its length is impossible):
    /// the ring position can no longer be trusted.
    Reset,
}

/// Classify a receive header. `length` is the device-written length field
/// (frame plus CRC). Every length is bounded here before the driver reads
/// the frame out of the ring.
pub fn classify_rx_header(status: u16, length: usize) -> RxHeader {
    // ROK set and none of FAE/CRC/LONG/RUNT/ISE (bits 1..5).
    if status & 0x01 == 0 || status & 0x3E != 0 {
        return RxHeader::Reset;
    }
    // The device writes frame length + 4, so a good header never has a
    // length below 4; such a header means the ring position is lost.
    if length < 4 || length > RX_SLACK - 16 - 4 {
        return RxHeader::Reset;
    }
    // A good header for a frame the stack will not take (a runt, or longer
    // than any Ethernet frame): consume it and move on.
    if length < MIN_RX_FRAME_LEN || length > MAX_RX_FRAME_LEN {
        return RxHeader::Skip;
    }
    RxHeader::Deliver(length - 4)
}

pub fn init() -> Result<(), &'static str> {
    let device = pci::find_device(RTL8139_VENDOR_ID, RTL8139_DEVICE_ID)
        .ok_or("RTL8139 not found on PCI bus")?;

    // Read BAR0 (I/O base)
    let bar0 = pci::read_config_u32(device.bus, device.slot, device.func, 0x10);
    if (bar0 & 1) == 0 {
        return Err("RTL8139 BAR0 is not an I/O port");
    }
    let io_base = (bar0 & !3) as u16;

    // One contiguous block for the RX ring with its slack and the four TX
    // buffers, entirely below 4 GiB: the device's address registers are 32
    // bits wide, and a truncated address makes it read or write some other
    // physical page (TX: kernel memory sent on the wire).
    let first = memory::allocate_contiguous_frames(RX_FRAMES + TX_FRAMES)
        .ok_or("Failed to allocate contiguous RX/TX frames")?;
    let rx_buffer_phys = first.start_address();
    let end = rx_buffer_phys.as_u64() + ((RX_FRAMES + TX_FRAMES) as u64) * 4096;
    if end > DMA_LIMIT {
        return Err("RX/TX buffers are above the 4 GiB DMA limit");
    }
    let rx_buffer_virt = memory::phys_to_virt(rx_buffer_phys);
    let mut tx_buffers = [PhysAddr::new(0); TX_FRAMES];
    for (i, slot) in tx_buffers.iter_mut().enumerate() {
        *slot = rx_buffer_phys + ((RX_FRAMES + i) as u64) * 4096;
    }

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
    }

    let mut nic = Rtl8139 {
        io_base,
        rx_buffer_phys,
        rx_buffer_virt,
        tx_buffers,
        tx_curr: 0,
        rx_curr: 0,
        mac_address,
    };
    nic.reset_and_start();
    *RTL8139_NIC.lock() = Some(nic);

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

    /// Software reset, then program the ring, mask every interrupt (the
    /// driver is polled and installs no IRQ handler) and enable RX/TX. Also
    /// used to resynchronise after a bad receive header: the reset returns the
    /// device's ring and TX pointers to 0.
    fn reset_and_start(&mut self) {
        unsafe {
            let mut cr_port = Port::<u8>::new(self.io_base + CR);
            cr_port.write(0x10); // Reset
            let mut spins = 0u32;
            while (cr_port.read() & 0x10) != 0 && spins < 1_000_000 {
                spins += 1;
            }
            PortWriteOnly::<u32>::new(self.io_base + RBSTART).write(self.rx_buffer_phys.as_u64() as u32);
            PortWriteOnly::<u16>::new(self.io_base + IMR).write(0x0000);
            Port::<u16>::new(self.io_base + ISR).write(0xFFFF);
            PortWriteOnly::<u32>::new(self.io_base + RCR).write(RCR_VALUE);
            PortWriteOnly::<u8>::new(self.io_base + CR).write(0x0C); // RE=0x08, TE=0x04
        }
        self.rx_curr = 0;
        self.tx_curr = 0;
    }

    pub fn send_packet(&mut self, data: &[u8]) -> Result<(), &'static str> {
        if data.len() > 1518 {
            return Err("Packet too large");
        }

        let tx_phys = self.tx_buffers[self.tx_curr as usize];
        let tx_virt = memory::phys_to_virt(tx_phys);

        // The descriptor (and its buffer) may be reused only once the device
        // has handed it back (TSD.OWN, bit 13). The driver used to overwrite
        // the buffer and rewrite TSAD/TSD whatever the state, which corrupts
        // a frame still being read by DMA on hardware that completes later.
        let tsd_port = self.io_base + TSD0 + (self.tx_curr as u16 * 4);
        let mut owned = false;
        for _ in 0..100_000 {
            if unsafe { PortReadOnly::<u32>::new(tsd_port).read() } & TSD_OWN != 0 {
                owned = true;
                break;
            }
            core::hint::spin_loop();
        }
        if !owned {
            TX_BUSY_DROPS.fetch_add(1, core::sync::atomic::Ordering::Relaxed);
            return Err("TX descriptor still owned by the device");
        }

        unsafe {
            let tx_slice = slice::from_raw_parts_mut(tx_virt.as_mut_ptr::<u8>(), data.len());
            tx_slice.copy_from_slice(data);

            let tsad_port = self.io_base + TSAD0 + (self.tx_curr as u16 * 4);

            PortWriteOnly::<u32>::new(tsad_port).write(tx_phys.as_u64() as u32);
            PortWriteOnly::<u32>::new(tsd_port).write(data.len() as u32);
        }

        self.tx_curr = (self.tx_curr + 1) % TX_FRAMES as u8;

        Ok(())
    }

    pub fn receive_packet(&mut self) -> Option<Vec<u8>> {
        // A skipped (oversized) frame is consumed and the next one tried, so
        // a run of them cannot stall reception.
        for _ in 0..64 {
            unsafe {
                let mut cr_port = PortReadOnly::<u8>::new(self.io_base + CR);
                if (cr_port.read() & 0x01) != 0 {
                    return None; // RX buffer empty
                }

                let rx_ptr = self.rx_buffer_virt.as_u64() as *const u8;
                let offset = self.rx_curr as usize % RX_RING_LEN;

                let header = core::ptr::read_unaligned(rx_ptr.add(offset) as *const u16);
                let length = core::ptr::read_unaligned(rx_ptr.add(offset + 2) as *const u16) as usize;

                let packet_len = match classify_rx_header(header, length) {
                    RxHeader::Reset => {
                        // A header the device would not write: the ring
                        // position is lost. Leaving it there stalled reception
                        // for good; reading on would trust a garbage length.
                        RX_RESETS.fetch_add(1, Ordering::Relaxed);
                        crate::serial_println!(
                            "[rtl8139] bad receive header status={:#x} len={} at {}: resetting the receiver",
                            header,
                            length,
                            offset
                        );
                        self.reset_and_start();
                        return None;
                    }
                    RxHeader::Skip => {
                        RX_DROPPED_OVERSIZE.fetch_add(1, Ordering::Relaxed);
                        crate::serial_println!("[rtl8139] dropped oversized frame len={}", length);
                        None
                    }
                    RxHeader::Deliver(len) => Some(len),
                };

                let vec = packet_len.map(|len| {
                    // offset < RX_RING_LEN and len <= MAX_RX_FRAME_LEN, so the
                    // read stays inside the ring and its slack.
                    let packet_data = slice::from_raw_parts(rx_ptr.add(offset + 4), len);
                    let mut vec = Vec::with_capacity(len);
                    vec.extend_from_slice(packet_data);
                    vec
                });

                // Advance exactly as the device does (header + length,
                // 4-byte aligned, modulo the ring).
                let total_length = (length + 4 + 3) & !3;
                self.rx_curr = ((offset + total_length) % RX_RING_LEN) as u16;

                // Update CAPR (subtract 16 per RTL8139 spec)
                PortWriteOnly::<u16>::new(self.io_base + CAPR).write(self.rx_curr.wrapping_sub(16));

                if let Some(vec) = vec {
                    RX_DELIVERED.fetch_add(1, Ordering::Relaxed);
                    RX_MAX_DELIVERED_LEN.fetch_max(vec.len() as u64, Ordering::Relaxed);
                    return Some(vec);
                }
            }
        }
        None
    }

    pub fn handle_interrupt(&mut self) {
        unsafe {
            let mut isr_port = Port::<u16>::new(self.io_base + ISR);
            let status = isr_port.read();
            isr_port.write(status); // Acknowledge
        }
    }
}
