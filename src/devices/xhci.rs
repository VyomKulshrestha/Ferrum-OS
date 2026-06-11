// ============================================================================
// FerrumOS - XHCI USB 3.0 Host Controller Driver
// ============================================================================
// Hardware driver for the XHCI controller as emulated by QEMU
// (`-device qemu-xhci`).
//
// Implements:
//   - PCI discovery (vendor 0x1B36 device 0x000D / class 0C:03:30 fallback)
//   - MMIO register access via volatile reads/writes
//   - TRB ring buffer management (command, event, transfer rings)
//   - Device Context Base Address Array (DCBAA)
//   - Scratchpad buffer allocation
//   - Port reset and device enumeration (Enable Slot, Address Device)
//   - Control transfers (GET_DESCRIPTOR for USB device descriptor)
//   - Interrupt transfers (HID polling)
//   - Endpoint configuration (Configure Endpoint for HID interrupt EPs)
//   - Event ring polling (Command Completion, Transfer Event, Port Status)
// ============================================================================

#![allow(dead_code)]

extern crate alloc;

use spin::Mutex;
use x86_64::{PhysAddr, VirtAddr};

use crate::devices::pci;
use crate::devices::pci::PciDevice;

// ============================================================================
// PCI Constants
// ============================================================================

/// XHCI PCI class code (Serial Bus Controller / USB / XHCI).
#[allow(dead_code)]
const XHCI_PCI_CLASS: u8 = 0x0C;
#[allow(dead_code)]
const XHCI_PCI_SUBCLASS: u8 = 0x03;
#[allow(dead_code)]
const XHCI_PCI_PROG_IF: u8 = 0x30;

/// QEMU XHCI identifiers.
const QEMU_XHCI_VENDOR: u16 = 0x1B36;
const QEMU_XHCI_DEVICE: u16 = 0x000D;

/// PCI configuration space offsets.
const PCI_COMMAND: u8 = 0x04;
const PCI_BAR0: u8 = 0x10;

// ============================================================================
// Capability Register Offsets (from BAR0)
// ============================================================================

const CAP_CAPLENGTH: u32 = 0x00;   // u8: Capability Register Length
const CAP_HCIVERSION: u32 = 0x02;  // u16: Interface Version Number
const CAP_HCSPARAMS1: u32 = 0x04;  // u32: Structural Parameters 1
const CAP_HCSPARAMS2: u32 = 0x08;  // u32: Structural Parameters 2
#[allow(dead_code)]
const CAP_HCSPARAMS3: u32 = 0x0C;  // u32: Structural Parameters 3
const CAP_HCCPARAMS1: u32 = 0x10;  // u32: Capability Parameters 1
const CAP_DBOFF: u32 = 0x14;       // u32: Doorbell Offset
const CAP_RTSOFF: u32 = 0x18;      // u32: Runtime Register Space Offset
#[allow(dead_code)]
const CAP_HCCPARAMS2: u32 = 0x1C;  // u32: Capability Parameters 2

// ============================================================================
// Operational Register Offsets (from BAR0 + cap_length)
// ============================================================================

const OP_USBCMD: u32 = 0x00;       // USB Command
const OP_USBSTS: u32 = 0x04;       // USB Status
#[allow(dead_code)]
const OP_PAGESIZE: u32 = 0x08;     // Page Size
#[allow(dead_code)]
const OP_DNCTRL: u32 = 0x14;       // Device Notification Control
const OP_CRCR: u32 = 0x18;         // Command Ring Control Register (u64)
const OP_DCBAAP: u32 = 0x30;       // Device Context Base Address Array Pointer (u64)
const OP_CONFIG: u32 = 0x38;       // Configure
const OP_PORTSC_BASE: u32 = 0x400; // Port Status and Control base

// ============================================================================
// Interrupter Register Offsets (from rt_base + 0x20 for interrupter 0)
// ============================================================================

const INTR_IMAN: u32 = 0x00;       // Interrupter Management
const INTR_IMOD: u32 = 0x04;       // Interrupter Moderation
const INTR_ERSTSZ: u32 = 0x08;     // Event Ring Segment Table Size
const INTR_ERSTBA: u32 = 0x10;     // Event Ring Segment Table Base Address (u64)
const INTR_ERDP: u32 = 0x18;       // Event Ring Dequeue Pointer (u64)

/// Offset of interrupter 0 within the runtime register space.
const INTR0_OFFSET: u32 = 0x20;

// ============================================================================
// USBCMD / USBSTS bit definitions
// ============================================================================

const USBCMD_RS: u32 = 1 << 0;     // Run/Stop
const USBCMD_HCRST: u32 = 1 << 1;  // Host Controller Reset
const USBCMD_INTE: u32 = 1 << 2;   // Interrupter Enable

const USBSTS_HCH: u32 = 1 << 0;    // HC Halted
const USBSTS_CNR: u32 = 1 << 11;   // Controller Not Ready

// ============================================================================
// PORTSC bit definitions
// ============================================================================

const PORTSC_CCS: u32 = 1 << 0;    // Current Connect Status
#[allow(dead_code)]
const PORTSC_PED: u32 = 1 << 1;    // Port Enabled/Disabled
const PORTSC_PR: u32 = 1 << 4;     // Port Reset
const PORTSC_PRC: u32 = 1 << 21;   // Port Reset Change
#[allow(dead_code)]
const PORTSC_CSC: u32 = 1 << 17;   // Connect Status Change

// ============================================================================
// TRB Type Constants
// ============================================================================

#[allow(dead_code)]
const TRB_NORMAL: u32 = 1;
const TRB_SETUP_STAGE: u32 = 2;
const TRB_DATA_STAGE: u32 = 3;
const TRB_STATUS_STAGE: u32 = 4;
const TRB_LINK: u32 = 6;
const TRB_ENABLE_SLOT: u32 = 9;
#[allow(dead_code)]
const TRB_DISABLE_SLOT: u32 = 10;
const TRB_ADDRESS_DEVICE: u32 = 11;
const TRB_CONFIGURE_ENDPOINT: u32 = 12;
#[allow(dead_code)]
const TRB_EVALUATE_CONTEXT: u32 = 13;
const TRB_NOOP: u32 = 23;
#[allow(dead_code)]
const TRB_TRANSFER_EVENT: u32 = 32;
const TRB_COMMAND_COMPLETION: u32 = 33;
const TRB_PORT_STATUS_CHANGE: u32 = 34;

// ============================================================================
// TRB Completion Codes
// ============================================================================

const TRB_COMP_SUCCESS: u32 = 1;
#[allow(dead_code)]
const TRB_COMP_SHORT_PACKET: u32 = 13;

// ============================================================================
// Port Speed Constants (PORTSC bits [13:10])
// ============================================================================

#[allow(dead_code)]
const PORT_SPEED_FULL: u32 = 1;
const PORT_SPEED_LOW: u32 = 2;
#[allow(dead_code)]
const PORT_SPEED_HIGH: u32 = 3;
const PORT_SPEED_SUPER: u32 = 4;

// ============================================================================
// Endpoint Type Constants (for Endpoint Context)
// ============================================================================

#[allow(dead_code)]
const EP_TYPE_NOT_VALID: u8 = 0;
#[allow(dead_code)]
const EP_TYPE_ISOCH_OUT: u8 = 1;
#[allow(dead_code)]
const EP_TYPE_BULK_OUT: u8 = 2;
#[allow(dead_code)]
const EP_TYPE_INTERRUPT_OUT: u8 = 3;
const EP_TYPE_CONTROL: u8 = 4;
#[allow(dead_code)]
const EP_TYPE_ISOCH_IN: u8 = 5;
#[allow(dead_code)]
const EP_TYPE_BULK_IN: u8 = 6;
const EP_TYPE_INTERRUPT_IN: u8 = 7;

// ============================================================================
// Ring and Buffer Sizes
// ============================================================================

/// Number of TRBs in command and event rings.
const RING_SIZE: usize = 256;

/// Maximum number of device slots we support.
const MAX_SLOTS: usize = 32;

/// Maximum number of transfer ring TRBs per endpoint.
const TRANSFER_RING_SIZE: usize = 64;

/// Polling timeout (iterations).
const POLL_TIMEOUT: u32 = 100_000;

// ============================================================================
// TRB (Transfer Request Block) — 16 bytes
// ============================================================================

/// A single Transfer Request Block (TRB), the fundamental data structure
/// used by the XHCI controller for all command, event, and transfer
/// communication.
#[repr(C, packed)]
#[derive(Clone, Copy, Default)]
struct Trb {
    /// Parameter field — address, data pointer, or inline data.
    param: u64,
    /// Status field — transfer length, completion code, etc.
    status: u32,
    /// Control field — TRB type, cycle bit, flags.
    control: u32,
}

impl Trb {
    /// Create a TRB with the given type and cycle bit.
    fn new(trb_type: u32, cycle: u32) -> Self {
        Trb {
            param: 0,
            status: 0,
            control: (trb_type << 10) | (cycle & 1),
        }
    }

    /// Extract the TRB type from the control field.
    fn trb_type(&self) -> u32 {
        (self.control >> 10) & 0x3F
    }

    /// Extract the completion code from the status field (bits [31:24]).
    fn completion_code(&self) -> u32 {
        (self.status >> 24) & 0xFF
    }

    /// Extract the slot ID from the control field (bits [31:24]).
    fn slot_id(&self) -> u8 {
        (self.control >> 24) as u8
    }

    /// Get the cycle bit from the control field.
    fn cycle_bit(&self) -> u32 {
        self.control & 1
    }
}

// ============================================================================
// MMIO Register Access
// ============================================================================

/// Wrapper around XHCI MMIO register base pointers for volatile I/O.
struct XhciRegs {
    /// Capability registers base (BAR0).
    cap_base: *mut u8,
    /// Operational registers base (BAR0 + cap_length).
    op_base: *mut u8,
    /// Runtime registers base (BAR0 + RTSOFF).
    rt_base: *mut u8,
    /// Doorbell registers base (BAR0 + DBOFF).
    db_base: *mut u8,
}

impl XhciRegs {
    // --- Capability register helpers ---

    /// Read a capability register (u8) at `offset` from cap_base.
    #[inline]
    fn cap_read8(&self, offset: u32) -> u8 {
        // Safety: offset is within the XHCI capability register space
        // mapped from BAR0. Volatile ensures the read is not elided.
        unsafe { core::ptr::read_volatile(self.cap_base.add(offset as usize) as *const u8) }
    }

    /// Read a capability register (u16) at `offset` from cap_base.
    #[inline]
    fn cap_read16(&self, offset: u32) -> u16 {
        // Safety: within XHCI capability MMIO region from BAR0.
        unsafe { core::ptr::read_volatile(self.cap_base.add(offset as usize) as *const u16) }
    }

    /// Read a capability register (u32) at `offset` from cap_base.
    #[inline]
    fn cap_read32(&self, offset: u32) -> u32 {
        // Safety: within XHCI capability MMIO region from BAR0.
        unsafe { core::ptr::read_volatile(self.cap_base.add(offset as usize) as *const u32) }
    }

    // --- Operational register helpers ---

    /// Read an operational register (u32) at `offset` from op_base.
    #[inline]
    fn op_read32(&self, offset: u32) -> u32 {
        // Safety: offset is within the XHCI operational register space.
        unsafe { core::ptr::read_volatile(self.op_base.add(offset as usize) as *const u32) }
    }

    /// Write a u32 to an operational register at `offset` from op_base.
    #[inline]
    fn op_write32(&self, offset: u32, value: u32) {
        // Safety: within XHCI operational MMIO region.
        unsafe { core::ptr::write_volatile(self.op_base.add(offset as usize) as *mut u32, value) }
    }

    /// Write a u64 to an operational register pair at `offset` from op_base.
    /// Writes low 32 bits first, then high 32 bits at offset+4.
    #[inline]
    fn op_write64(&self, offset: u32, value: u64) {
        self.op_write32(offset, value as u32);
        self.op_write32(offset + 4, (value >> 32) as u32);
    }

    // --- Runtime register helpers ---

    /// Read a runtime register (u32) at `offset` from rt_base.
    #[inline]
    fn rt_read32(&self, offset: u32) -> u32 {
        // Safety: within XHCI runtime MMIO region.
        unsafe { core::ptr::read_volatile(self.rt_base.add(offset as usize) as *const u32) }
    }

    /// Write a u32 to a runtime register at `offset` from rt_base.
    #[inline]
    fn rt_write32(&self, offset: u32, value: u32) {
        // Safety: within XHCI runtime MMIO region.
        unsafe { core::ptr::write_volatile(self.rt_base.add(offset as usize) as *mut u32, value) }
    }

    /// Write a u64 to a runtime register pair at `offset` from rt_base.
    #[inline]
    fn rt_write64(&self, offset: u32, value: u64) {
        self.rt_write32(offset, value as u32);
        self.rt_write32(offset + 4, (value >> 32) as u32);
    }

    // --- Doorbell register helpers ---

    /// Write a u32 to doorbell register `index` (each doorbell is 4 bytes).
    #[inline]
    fn ring_doorbell(&self, index: u32, value: u32) {
        let offset = index * 4;
        // Safety: within XHCI doorbell register array.
        unsafe {
            core::ptr::write_volatile(self.db_base.add(offset as usize) as *mut u32, value)
        }
    }

    // --- Port register helpers ---

    /// Read PORTSC for a given 1-based port number.
    #[inline]
    fn portsc_read(&self, port: u8) -> u32 {
        let offset = OP_PORTSC_BASE + ((port as u32 - 1) * 0x10);
        self.op_read32(offset)
    }

    /// Write PORTSC for a given 1-based port number.
    #[inline]
    fn portsc_write(&self, port: u8, value: u32) {
        let offset = OP_PORTSC_BASE + ((port as u32 - 1) * 0x10);
        self.op_write32(offset, value);
    }
}

// ============================================================================
// TRB Ring Buffer
// ============================================================================

/// A producer ring buffer of TRBs, used for command and transfer rings.
///
/// The last TRB slot is reserved for a Link TRB that wraps the ring back
/// to the beginning and toggles the cycle bit.
struct TrbRing {
    /// Kernel-virtual base address of the TRB array.
    base_virt: VirtAddr,
    /// Physical base address of the TRB array.
    base_phys: PhysAddr,
    /// Total number of usable TRB slots (excluding the Link TRB).
    size: usize,
    /// Current enqueue index.
    enqueue: usize,
    /// Producer Cycle State (PCS): 1 or 0.
    cycle_bit: u32,
}

impl TrbRing {
    /// Create a new TRB ring at the given physical/virtual addresses.
    ///
    /// `size` is the total number of TRB slots in the ring including the
    /// Link TRB slot. The last slot is reserved for the Link TRB.
    fn new(phys: PhysAddr, virt: VirtAddr, size: usize) -> Self {
        // Zero the ring memory.
        // Safety: virt points to a valid kernel-mapped region of at least
        // `size * 16` bytes allocated from the frame allocator.
        unsafe {
            core::ptr::write_bytes(virt.as_u64() as *mut u8, 0, size * 16);
        }

        // Write the Link TRB at the last slot, pointing back to the start.
        // The Link TRB has the Toggle Cycle (TC) bit set (bit 1 of control).
        let link_offset = (size - 1) * 16;
        let link_ptr = (virt.as_u64() + link_offset as u64) as *mut Trb;
        let link_trb = Trb {
            param: phys.as_u64(),
            status: 0,
            // TRB type = LINK (6), TC bit (bit 1) set, cycle bit 0 initially
            // (will be set when we actually reach this slot).
            control: (TRB_LINK << 10) | (1 << 1),
        };
        // Safety: link_ptr is within the ring buffer allocation.
        unsafe {
            core::ptr::write_volatile(link_ptr, link_trb);
        }

        TrbRing {
            base_virt: virt,
            base_phys: phys,
            size: size - 1, // usable slots (excluding Link)
            enqueue: 0,
            cycle_bit: 1,
        }
    }

    /// Enqueue a TRB into the ring. Returns the physical address of the
    /// enqueued TRB.
    ///
    /// The caller's TRB is modified to include the correct cycle bit.
    /// When the enqueue pointer reaches the Link TRB, it wraps around
    /// and toggles the cycle bit.
    fn enqueue_trb(&mut self, mut trb: Trb) -> PhysAddr {
        // Set the cycle bit on the TRB.
        trb.control = (trb.control & !1) | (self.cycle_bit & 1);

        let offset = self.enqueue * 16;
        let trb_ptr = (self.base_virt.as_u64() + offset as u64) as *mut Trb;
        let trb_phys = PhysAddr::new(self.base_phys.as_u64() + offset as u64);

        // Safety: trb_ptr is within the ring buffer allocation, and
        // enqueue < self.size so we never overwrite the Link TRB.
        unsafe {
            core::ptr::write_volatile(trb_ptr, trb);
        }

        self.enqueue += 1;

        // If we've reached the Link TRB slot, update its cycle bit
        // and wrap around.
        if self.enqueue >= self.size {
            let link_offset = self.size * 16;
            let link_ptr = (self.base_virt.as_u64() + link_offset as u64) as *mut Trb;

            // Safety: link_ptr points to the Link TRB at the end of the ring.
            unsafe {
                let mut link = core::ptr::read_volatile(link_ptr);
                // Set cycle bit on the Link TRB so the controller processes it.
                link.control = (link.control & !1) | (self.cycle_bit & 1);
                core::ptr::write_volatile(link_ptr, link);
            }

            // Toggle cycle bit and reset enqueue pointer.
            self.cycle_bit ^= 1;
            self.enqueue = 0;
        }

        trb_phys
    }

    /// Get the physical address of the ring base (for writing to registers).
    fn phys(&self) -> PhysAddr {
        self.base_phys
    }
}

// ============================================================================
// Device Context Structures (32-byte aligned)
// ============================================================================

/// Slot Context — 32 bytes, describes the device slot.
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct SlotContext {
    /// Dword 0: Route String [19:0], Speed [23:20], MTT [25],
    /// Hub [26], Context Entries [31:27].
    dword0: u32,
    /// Dword 1: Max Exit Latency [15:0], Root Hub Port Number [23:16],
    /// Number of Ports [31:24].
    dword1: u32,
    /// Dword 2: Parent Hub Slot ID [7:0], Parent Port Number [15:8],
    /// TT Think Time [17:16], Interrupter Target [31:22].
    dword2: u32,
    /// Dword 3: USB Device Address [7:0], Slot State [31:27].
    dword3: u32,
    /// Dwords 4-7: Reserved.
    _reserved: [u32; 4],
}

/// Endpoint Context — 32 bytes, describes one endpoint.
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct EndpointContext {
    /// Dword 0: EP State [2:0], Mult [9:8], MaxPStreams [14:10],
    /// LSA [15], Interval [23:16], MaxESITPayloadHi [31:24].
    dword0: u32,
    /// Dword 1: CErr [2:1], EP Type [5:3], HID [7],
    /// Max Burst Size [15:8], Max Packet Size [31:16].
    dword1: u32,
    /// Dword 2: Dequeue Cycle State [0], TR Dequeue Pointer [63:4].
    dequeue_lo: u32,
    /// Dword 3: TR Dequeue Pointer high 32 bits.
    dequeue_hi: u32,
    /// Dword 4: Average TRB Length [15:0], Max ESIT Payload Lo [31:16].
    dword4: u32,
    /// Dwords 5-7: Reserved.
    _reserved: [u32; 3],
}

/// Device Context — slot context + 31 endpoint contexts.
#[repr(C)]
#[derive(Clone, Copy)]
struct DeviceContext {
    slot: SlotContext,
    endpoints: [EndpointContext; 31],
}

impl Default for DeviceContext {
    fn default() -> Self {
        DeviceContext {
            slot: SlotContext::default(),
            endpoints: [EndpointContext::default(); 31],
        }
    }
}

/// Input Context — drop/add flags + slot context + 31 endpoint contexts.
/// The input control context occupies the first 32 bytes.
#[repr(C)]
#[derive(Clone, Copy)]
struct InputContext {
    /// Drop Context flags — bit N means drop endpoint context N.
    drop_flags: u32,
    /// Add Context flags — bit N means add endpoint context N.
    add_flags: u32,
    /// Reserved padding to fill 32 bytes for the input control context.
    _reserved: [u32; 6],
    /// Slot Context.
    slot: SlotContext,
    /// Endpoint Contexts (EP0 at index 0, then 30 non-default endpoints).
    endpoints: [EndpointContext; 31],
}

impl Default for InputContext {
    fn default() -> Self {
        InputContext {
            drop_flags: 0,
            add_flags: 0,
            _reserved: [0; 6],
            slot: SlotContext::default(),
            endpoints: [EndpointContext::default(); 31],
        }
    }
}

/// Event Ring Segment Table Entry — 16 bytes.
#[repr(C, packed)]
#[derive(Clone, Copy, Default)]
struct ErstEntry {
    /// Physical base address of the event ring segment.
    base_addr: u64,
    /// Number of TRBs in the segment.
    ring_size: u16,
    /// Reserved.
    _reserved: u16,
    /// Reserved.
    _reserved2: u32,
}

// ============================================================================
// USB Device Descriptor
// ============================================================================

/// Standard USB Device Descriptor (18 bytes).
#[repr(C, packed)]
#[derive(Clone, Copy, Default, Debug)]
pub struct UsbDeviceDescriptor {
    pub length: u8,
    pub descriptor_type: u8,
    pub usb_version: u16,
    pub device_class: u8,
    pub device_subclass: u8,
    pub device_protocol: u8,
    pub max_packet_size0: u8,
    pub vendor_id: u16,
    pub product_id: u16,
    pub device_version: u16,
    pub manufacturer_idx: u8,
    pub product_idx: u8,
    pub serial_idx: u8,
    pub num_configurations: u8,
}

// ============================================================================
// XhciController
// ============================================================================

/// Represents a fully initialised XHCI USB 3.0 host controller.
pub struct XhciController {
    regs: XhciRegs,
    max_slots: u8,
    max_ports: u8,
    /// Whether the controller supports 64-bit addressing (AC64).
    #[allow(dead_code)]
    ac64: bool,

    // DCBAA
    dcbaa_virt: VirtAddr,
    dcbaa_phys: PhysAddr,

    // Command Ring
    cmd_ring: TrbRing,

    // Event Ring
    event_ring_virt: VirtAddr,
    event_ring_phys: PhysAddr,
    event_ring_size: usize,
    event_dequeue: usize,
    event_cycle_bit: u32,

    // Event Ring Segment Table
    #[allow(dead_code)]
    erst_virt: VirtAddr,
    erst_phys: PhysAddr,

    // Scratchpad
    #[allow(dead_code)]
    scratchpad_buf_array_phys: PhysAddr,

    // Per-slot tracking
    slot_enabled: [bool; MAX_SLOTS],
    device_ctx_phys: [PhysAddr; MAX_SLOTS],

    // Per-slot transfer rings for EP0 (index = slot_id).
    // Each entry is (virt, phys, enqueue_idx, cycle_bit).
    ep0_rings: [Option<TrbRing>; MAX_SLOTS],
}

// Safety: XhciController contains raw pointers to MMIO memory and DMA
// buffers. All accesses go through volatile operations, and the entire
// struct is behind a spin::Mutex, so only one core accesses it at a time.
unsafe impl Send for XhciController {}
unsafe impl Sync for XhciController {}

// ============================================================================
// Global State
// ============================================================================

/// Global XHCI controller instance, protected by a spinlock.
pub static XHCI: Mutex<Option<XhciController>> = Mutex::new(None);

// ============================================================================
// PCI Discovery
// ============================================================================

/// Attempt to locate the XHCI controller on the PCI bus.
///
/// First tries the well-known QEMU xhci vendor/device pair, then falls
/// back to scanning for any device with class 0C:03:30.
fn find_xhci_pci() -> Option<PciDevice> {
    // Fast path: try the known QEMU XHCI device.
    if let Some(dev) = pci::find_device(QEMU_XHCI_VENDOR, QEMU_XHCI_DEVICE) {
        return Some(dev);
    }

    // Slow path: scan all buses/slots for class 0C:03, prog_if 30.
    for bus in 0u8..=255 {
        for slot in 0u8..32 {
            let vendor = pci::read_config_u16(bus, slot, 0, 0);
            if vendor == 0xFFFF {
                continue;
            }

            for func in 0u8..8 {
                let v = pci::read_config_u16(bus, slot, func, 0);
                if v == 0xFFFF {
                    continue;
                }

                let class = pci::read_config_u8(bus, slot, func, 0x0B);
                let subclass = pci::read_config_u8(bus, slot, func, 0x0A);
                let prog_if = pci::read_config_u8(bus, slot, func, 0x09);

                if class == XHCI_PCI_CLASS
                    && subclass == XHCI_PCI_SUBCLASS
                    && prog_if == XHCI_PCI_PROG_IF
                {
                    return Some(PciDevice { bus, slot, func });
                }

                // If function 0 is not multi-function, skip remaining funcs.
                if func == 0 {
                    let header_type = pci::read_config_u8(bus, slot, 0, 0x0E);
                    if (header_type & 0x80) == 0 {
                        break;
                    }
                }
            }
        }
    }
    None
}

// ============================================================================
// Busy-wait helper
// ============================================================================

/// Spin for approximately `n` iterations (used for small post-write delays).
#[inline(never)]
fn spin_wait(n: u32) {
    for _ in 0..n {
        core::hint::spin_loop();
    }
}

// ============================================================================
// Controller Initialisation
// ============================================================================

/// Initialise the XHCI USB 3.0 host controller.
///
/// Discovers the device on PCI, resets the controller, sets up the DCBAA,
/// command ring, event ring, scratchpad buffers, and starts the controller.
/// Scans ports for connected devices and performs basic enumeration.
pub fn init() -> Result<(), &'static str> {
    // 1. Find the XHCI device on PCI.
    let pci_dev = find_xhci_pci().ok_or("XHCI: PCI device not found")?;

    crate::serial_println!(
        "XHCI: found PCI device at bus={} slot={} func={}",
        pci_dev.bus,
        pci_dev.slot,
        pci_dev.func
    );

    // 2. Read BAR0 (may be 64-bit) and map into kernel virtual address space.
    let bar0_lo = pci::read_config_u32(pci_dev.bus, pci_dev.slot, pci_dev.func, PCI_BAR0);
    let is_64bit = (bar0_lo & 0x06) == 0x04;
    let bar0_hi = if is_64bit {
        pci::read_config_u32(pci_dev.bus, pci_dev.slot, pci_dev.func, PCI_BAR0 + 4)
    } else {
        0
    };

    let bar0_phys = ((bar0_hi as u64) << 32) | ((bar0_lo & !0xF) as u64);
    if bar0_phys == 0 {
        return Err("XHCI: BAR0 is zero");
    }

    let bar0_virt = crate::memory::phys_to_virt(PhysAddr::new(bar0_phys));
    let cap_base = bar0_virt.as_u64() as *mut u8;

    crate::serial_println!(
        "XHCI: BAR0 phys={:#X} virt={:#X}",
        bar0_phys,
        bar0_virt.as_u64()
    );

    // 3. Enable PCI bus mastering and memory space (bits 1 and 2 of command).
    let cmd = pci::read_config_u16(pci_dev.bus, pci_dev.slot, pci_dev.func, PCI_COMMAND);
    let new_cmd = cmd | 0x06; // Bus Master + Memory Space enable
    pci::write_config_u32(
        pci_dev.bus,
        pci_dev.slot,
        pci_dev.func,
        PCI_COMMAND,
        new_cmd as u32,
    );

    // 4. Read capability length to compute operational register base.
    // Safety: cap_base is a valid pointer to BAR0 MMIO region.
    let cap_length = unsafe {
        core::ptr::read_volatile(cap_base.add(CAP_CAPLENGTH as usize) as *const u8)
    };
    let hci_version = unsafe {
        core::ptr::read_volatile(cap_base.add(CAP_HCIVERSION as usize) as *const u16)
    };

    crate::serial_println!(
        "XHCI: cap_length={} hci_version={:#06X}",
        cap_length,
        hci_version
    );

    // Temporary regs for reading capability registers.
    let temp_regs = XhciRegs {
        cap_base,
        op_base: unsafe { cap_base.add(cap_length as usize) },
        rt_base: core::ptr::null_mut(),
        db_base: core::ptr::null_mut(),
    };

    // 5. Read HCSPARAMS1 for max_slots, max_ports.
    let hcsparams1 = temp_regs.cap_read32(CAP_HCSPARAMS1);
    let max_slots_hw = (hcsparams1 & 0xFF) as u8;
    let max_ports = ((hcsparams1 >> 24) & 0xFF) as u8;

    crate::serial_println!(
        "XHCI: HCSPARAMS1={:#010X} max_slots={} max_ports={}",
        hcsparams1,
        max_slots_hw,
        max_ports
    );

    // Read HCSPARAMS2 for scratchpad buffer count.
    let hcsparams2 = temp_regs.cap_read32(CAP_HCSPARAMS2);
    let scratchpad_hi = ((hcsparams2 >> 21) & 0x1F) as usize;
    let scratchpad_lo = ((hcsparams2 >> 27) & 0x1F) as usize;
    let scratchpad_count = (scratchpad_hi << 5) | scratchpad_lo;

    // Read HCCPARAMS1 for 64-bit addressing capability.
    let hccparams1 = temp_regs.cap_read32(CAP_HCCPARAMS1);
    let ac64 = (hccparams1 & 1) != 0;

    crate::serial_println!(
        "XHCI: HCCPARAMS1={:#010X} AC64={} scratchpad_count={}",
        hccparams1,
        ac64,
        scratchpad_count
    );

    // 6. Read DBOFF and RTSOFF for doorbell and runtime bases.
    let dboff = temp_regs.cap_read32(CAP_DBOFF) & !0x3;
    let rtsoff = temp_regs.cap_read32(CAP_RTSOFF) & !0x1F;

    let op_base = unsafe { cap_base.add(cap_length as usize) };
    let rt_base = unsafe { cap_base.add(rtsoff as usize) };
    let db_base = unsafe { cap_base.add(dboff as usize) };

    let regs = XhciRegs {
        cap_base,
        op_base,
        rt_base,
        db_base,
    };

    crate::serial_println!(
        "XHCI: DBOFF={:#X} RTSOFF={:#X}",
        dboff,
        rtsoff
    );

    // 7. Halt: Clear USBCMD.R/S (bit 0), wait for USBSTS.HCH (bit 0).
    let usbcmd = regs.op_read32(OP_USBCMD);
    regs.op_write32(OP_USBCMD, usbcmd & !USBCMD_RS);

    let mut halted = false;
    for _ in 0..POLL_TIMEOUT {
        if (regs.op_read32(OP_USBSTS) & USBSTS_HCH) != 0 {
            halted = true;
            break;
        }
        core::hint::spin_loop();
    }
    if !halted {
        return Err("XHCI: controller failed to halt");
    }

    crate::serial_println!("XHCI: controller halted");

    // 8. Reset: Set USBCMD.HCRST (bit 1), wait for clear; also wait CNR.
    regs.op_write32(OP_USBCMD, USBCMD_HCRST);

    let mut reset_done = false;
    for _ in 0..POLL_TIMEOUT {
        if (regs.op_read32(OP_USBCMD) & USBCMD_HCRST) == 0 {
            reset_done = true;
            break;
        }
        core::hint::spin_loop();
    }
    if !reset_done {
        return Err("XHCI: controller reset timeout");
    }

    // Wait for Controller Not Ready (CNR) to clear.
    let mut ready = false;
    for _ in 0..POLL_TIMEOUT {
        if (regs.op_read32(OP_USBSTS) & USBSTS_CNR) == 0 {
            ready = true;
            break;
        }
        core::hint::spin_loop();
    }
    if !ready {
        return Err("XHCI: controller not ready after reset");
    }

    crate::serial_println!("XHCI: controller reset complete");

    // 9. Set CONFIG.MaxSlotsEn = min(max_slots_hw, MAX_SLOTS).
    let enabled_slots = core::cmp::min(max_slots_hw as usize, MAX_SLOTS) as u32;
    regs.op_write32(OP_CONFIG, enabled_slots);

    crate::serial_println!("XHCI: MaxSlotsEn set to {}", enabled_slots);

    // 10. Allocate DCBAA: 256 entries × 8 bytes = 2048 bytes.
    // Must be 64-byte aligned; a 4K page provides that.
    let dcbaa_frame =
        crate::memory::allocate_frame().ok_or("XHCI: failed to allocate DCBAA frame")?;
    let dcbaa_phys = dcbaa_frame.start_address();
    let dcbaa_virt = crate::memory::phys_to_virt(dcbaa_phys);

    // Zero the DCBAA page.
    // Safety: dcbaa_virt is a valid kernel-mapped 4 KiB page.
    unsafe {
        core::ptr::write_bytes(dcbaa_virt.as_u64() as *mut u8, 0, 4096);
    }

    // Write DCBAA physical address to DCBAAP register.
    regs.op_write64(OP_DCBAAP, dcbaa_phys.as_u64());

    crate::serial_println!(
        "XHCI: DCBAA at phys={:#X} virt={:#X}",
        dcbaa_phys.as_u64(),
        dcbaa_virt.as_u64()
    );

    // 11. Handle scratchpad buffers.
    let mut scratchpad_buf_array_phys = PhysAddr::new(0);
    if scratchpad_count > 0 {
        crate::serial_println!(
            "XHCI: allocating {} scratchpad buffers",
            scratchpad_count
        );

        // Allocate scratchpad buffer array (array of u64 physical addresses).
        let sp_array_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate scratchpad array frame")?;
        let sp_array_phys = sp_array_frame.start_address();
        let sp_array_virt = crate::memory::phys_to_virt(sp_array_phys);

        // Safety: sp_array_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(sp_array_virt.as_u64() as *mut u8, 0, 4096);
        }

        // Allocate individual scratchpad pages and fill the array.
        for i in 0..scratchpad_count {
            let sp_frame = crate::memory::allocate_frame()
                .ok_or("XHCI: failed to allocate scratchpad page")?;
            let sp_page_phys = sp_frame.start_address();

            // Zero the scratchpad page.
            let sp_page_virt = crate::memory::phys_to_virt(sp_page_phys);
            // Safety: sp_page_virt is a valid 4 KiB page.
            unsafe {
                core::ptr::write_bytes(sp_page_virt.as_u64() as *mut u8, 0, 4096);
            }

            // Write the physical address into the scratchpad array.
            let entry_ptr = (sp_array_virt.as_u64() + (i as u64) * 8) as *mut u64;
            // Safety: entry_ptr is within the scratchpad array page.
            unsafe {
                core::ptr::write_volatile(entry_ptr, sp_page_phys.as_u64());
            }
        }

        // Set DCBAA[0] to the scratchpad buffer array physical address.
        let dcbaa_entry0 = dcbaa_virt.as_u64() as *mut u64;
        // Safety: dcbaa_entry0 is at the start of the DCBAA page.
        unsafe {
            core::ptr::write_volatile(dcbaa_entry0, sp_array_phys.as_u64());
        }

        scratchpad_buf_array_phys = sp_array_phys;
    }

    // 12. Allocate Command Ring: RING_SIZE TRBs × 16 bytes.
    // Need ceil(RING_SIZE * 16 / 4096) pages = 1 page for 256 TRBs.
    let cmd_ring_pages = (RING_SIZE * 16 + 4095) / 4096;
    let cmd_ring_frame = if cmd_ring_pages > 1 {
        crate::memory::allocate_contiguous_frames(cmd_ring_pages)
            .ok_or("XHCI: failed to allocate command ring")?
    } else {
        crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate command ring")?
    };
    let cmd_ring_phys = cmd_ring_frame.start_address();
    let cmd_ring_virt = crate::memory::phys_to_virt(cmd_ring_phys);

    let cmd_ring = TrbRing::new(cmd_ring_phys, cmd_ring_virt, RING_SIZE);

    // Write Command Ring Control Register: physical base | cycle bit 1.
    regs.op_write64(OP_CRCR, cmd_ring_phys.as_u64() | 1);

    crate::serial_println!(
        "XHCI: command ring at phys={:#X}",
        cmd_ring_phys.as_u64()
    );

    // 13. Allocate Event Ring: RING_SIZE TRBs × 16 bytes.
    let evt_ring_pages = (RING_SIZE * 16 + 4095) / 4096;
    let evt_ring_frame = if evt_ring_pages > 1 {
        crate::memory::allocate_contiguous_frames(evt_ring_pages)
            .ok_or("XHCI: failed to allocate event ring")?
    } else {
        crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate event ring")?
    };
    let event_ring_phys = evt_ring_frame.start_address();
    let event_ring_virt = crate::memory::phys_to_virt(event_ring_phys);

    // Zero the event ring.
    // Safety: event_ring_virt is a valid kernel-mapped region.
    unsafe {
        core::ptr::write_bytes(
            event_ring_virt.as_u64() as *mut u8,
            0,
            RING_SIZE * 16,
        );
    }

    // Allocate Event Ring Segment Table (ERST): 1 entry, 16 bytes.
    let erst_frame =
        crate::memory::allocate_frame().ok_or("XHCI: failed to allocate ERST frame")?;
    let erst_phys = erst_frame.start_address();
    let erst_virt = crate::memory::phys_to_virt(erst_phys);

    // Safety: erst_virt is a valid 4 KiB page.
    unsafe {
        core::ptr::write_bytes(erst_virt.as_u64() as *mut u8, 0, 4096);
    }

    // Fill ERST entry 0: base address and size.
    let erst_entry = ErstEntry {
        base_addr: event_ring_phys.as_u64(),
        ring_size: RING_SIZE as u16,
        _reserved: 0,
        _reserved2: 0,
    };
    let erst_ptr = erst_virt.as_u64() as *mut ErstEntry;
    // Safety: erst_ptr is at the start of the ERST page.
    unsafe {
        core::ptr::write_volatile(erst_ptr, erst_entry);
    }

    // Write to interrupter 0 registers.
    let intr0_base = INTR0_OFFSET;

    // Set Event Ring Segment Table Size = 1.
    regs.rt_write32(intr0_base + INTR_ERSTSZ, 1);

    // Set Event Ring Dequeue Pointer = event ring physical base.
    // Bit 3 (EHB - Event Handler Busy) should be cleared by writing 1.
    regs.rt_write64(
        intr0_base + INTR_ERDP,
        event_ring_phys.as_u64() | (1 << 3),
    );

    // Set Event Ring Segment Table Base Address.
    regs.rt_write64(intr0_base + INTR_ERSTBA, erst_phys.as_u64());

    // Set Interrupt Moderation (IMOD) — 0 for minimal latency.
    regs.rt_write32(intr0_base + INTR_IMOD, 0);

    // Enable interrupter 0: set IE (bit 1) and IP clear (bit 0) in IMAN.
    regs.rt_write32(intr0_base + INTR_IMAN, 0x03);

    crate::serial_println!(
        "XHCI: event ring at phys={:#X}, ERST at phys={:#X}",
        event_ring_phys.as_u64(),
        erst_phys.as_u64()
    );

    // 14. Start the controller: set USBCMD R/S=1, INTE=1.
    let usbcmd = regs.op_read32(OP_USBCMD);
    regs.op_write32(OP_USBCMD, usbcmd | USBCMD_RS | USBCMD_INTE);

    // Verify controller is running.
    spin_wait(1000);
    let usbsts = regs.op_read32(OP_USBSTS);
    if (usbsts & USBSTS_HCH) != 0 {
        return Err("XHCI: controller did not start (still halted)");
    }

    crate::serial_println!("XHCI: controller running, USBSTS={:#010X}", usbsts);

    // Build the controller struct.
    let mut ctrl = XhciController {
        regs,
        max_slots: max_slots_hw,
        max_ports,
        ac64,
        dcbaa_virt,
        dcbaa_phys,
        cmd_ring,
        event_ring_virt,
        event_ring_phys,
        event_ring_size: RING_SIZE,
        event_dequeue: 0,
        event_cycle_bit: 1,
        erst_virt,
        erst_phys,
        scratchpad_buf_array_phys,
        slot_enabled: [false; MAX_SLOTS],
        device_ctx_phys: [PhysAddr::new(0); MAX_SLOTS],
        ep0_rings: Default::default(),
    };

    // 15. Scan ports: for each port, read PORTSC; if CCS set, reset port.
    for port in 1..=max_ports {
        let portsc = ctrl.regs.portsc_read(port);
        let speed = (portsc >> 10) & 0xF;
        crate::serial_println!(
            "XHCI: port {} PORTSC={:#010X} CCS={} speed={}",
            port,
            portsc,
            portsc & PORTSC_CCS,
            speed
        );

        if (portsc & PORTSC_CCS) != 0 {
            match ctrl.port_reset(port) {
                Ok(slot_id) => {
                    crate::serial_println!(
                        "XHCI: port {} enumerated as slot {}",
                        port,
                        slot_id
                    );
                }
                Err(e) => {
                    crate::serial_println!(
                        "XHCI: port {} reset/enumerate failed: {}",
                        port,
                        e
                    );
                }
            }
        }
    }

    crate::serial_println!("XHCI: initialisation complete");

    // Store in global state.
    *XHCI.lock() = Some(ctrl);
    Ok(())
}

// ============================================================================
// XhciController Implementation
// ============================================================================

impl XhciController {
    // ========================================================================
    // Event Ring Polling
    // ========================================================================

    /// Wait for a specific event TRB type on the event ring.
    /// Returns the event TRB if found, or an error on timeout.
    fn wait_for_event(&mut self, expected_type: u32) -> Result<Trb, &'static str> {
        for _ in 0..POLL_TIMEOUT {
            let offset = self.event_dequeue * 16;
            let trb_ptr =
                (self.event_ring_virt.as_u64() + offset as u64) as *const Trb;

            // Safety: trb_ptr is within the event ring allocation.
            let trb = unsafe { core::ptr::read_volatile(trb_ptr) };

            // Check if this TRB's cycle bit matches our expected consumer
            // cycle state.
            if trb.cycle_bit() == self.event_cycle_bit {
                // Advance dequeue.
                self.event_dequeue += 1;
                if self.event_dequeue >= self.event_ring_size {
                    self.event_dequeue = 0;
                    self.event_cycle_bit ^= 1;
                }

                // Update ERDP to tell the controller we consumed this event.
                let new_erdp = self.event_ring_phys.as_u64()
                    + (self.event_dequeue as u64) * 16;
                let intr0_base = INTR0_OFFSET;
                // Set EHB (bit 3) to clear Event Handler Busy.
                self.regs
                    .rt_write64(intr0_base + INTR_ERDP, new_erdp | (1 << 3));

                let trb_type = trb.trb_type();
                if trb_type == expected_type {
                    return Ok(trb);
                }

                // If it's a different event type, log and continue.
                crate::serial_println!(
                    "XHCI: unexpected event TRB type {} (expected {}), cc={}",
                    trb_type,
                    expected_type,
                    trb.completion_code()
                );

                // If it's a port status change, we handle it but keep looking.
                if trb_type == TRB_PORT_STATUS_CHANGE {
                    let port_id = (trb.param >> 24) as u8;
                    crate::serial_println!(
                        "XHCI: port status change event for port {}",
                        port_id
                    );
                }

                continue;
            }

            core::hint::spin_loop();
        }

        Err("XHCI: event ring timeout")
    }

    /// Send a command on the command ring and wait for completion.
    /// Returns the Command Completion event TRB.
    fn send_command(&mut self, trb: Trb) -> Result<Trb, &'static str> {
        // Enqueue the command TRB.
        self.cmd_ring.enqueue_trb(trb);

        // Ring doorbell 0 (host controller command doorbell).
        self.regs.ring_doorbell(0, 0);

        // Wait for Command Completion event.
        let event = self.wait_for_event(TRB_COMMAND_COMPLETION)?;

        let cc = event.completion_code();
        if cc != TRB_COMP_SUCCESS {
            crate::serial_println!(
                "XHCI: command failed with completion code {}",
                cc
            );
            return Err("XHCI: command completion error");
        }

        Ok(event)
    }

    // ========================================================================
    // Port Reset & Device Enumeration
    // ========================================================================

    /// Reset a USB port and enumerate the connected device.
    ///
    /// Returns the assigned slot ID on success.
    fn port_reset(&mut self, port: u8) -> Result<u8, &'static str> {
        crate::serial_println!("XHCI: resetting port {}", port);

        // 1. Read PORTSC, set Port Reset (PR, bit 4).
        // Preserve RW bits, clear RW1C status bits to avoid accidental clears.
        let portsc = self.regs.portsc_read(port);
        // Mask out RW1C bits (CSC=17, PEC=18, WRC=19, OCC=20, PRC=21,
        // PLC=22, CEC=23) to avoid clearing them, then set PR.
        let preserve_mask: u32 = !(PORTSC_CSC | (1 << 18) | (1 << 19)
            | (1 << 20) | PORTSC_PRC | (1 << 22) | (1 << 23));
        self.regs
            .portsc_write(port, (portsc & preserve_mask) | PORTSC_PR);

        // 2. Wait for Port Reset Change (PRC, bit 21) to be set.
        let mut reset_complete = false;
        for _ in 0..POLL_TIMEOUT {
            let ps = self.regs.portsc_read(port);
            if (ps & PORTSC_PRC) != 0 {
                reset_complete = true;
                break;
            }
            core::hint::spin_loop();
        }
        if !reset_complete {
            return Err("XHCI: port reset timeout (PRC not set)");
        }

        // Clear PRC by writing 1 to it.
        let portsc = self.regs.portsc_read(port);
        self.regs
            .portsc_write(port, (portsc & preserve_mask) | PORTSC_PRC);

        // Read port speed from PORTSC bits [13:10].
        let portsc = self.regs.portsc_read(port);
        let speed = (portsc >> 10) & 0xF;
        crate::serial_println!(
            "XHCI: port {} reset complete, speed={}, PORTSC={:#010X}",
            port,
            speed,
            portsc
        );

        // 3. Send Enable Slot command.
        let enable_slot_trb = Trb::new(TRB_ENABLE_SLOT, 0);
        let event = self.send_command(enable_slot_trb)?;

        let slot_id = event.slot_id();
        if slot_id == 0 || slot_id as usize >= MAX_SLOTS {
            return Err("XHCI: invalid slot ID from Enable Slot");
        }

        crate::serial_println!("XHCI: enabled slot {}", slot_id);

        // 4. Allocate Output Device Context.
        let out_ctx_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate output device context")?;
        let out_ctx_phys = out_ctx_frame.start_address();
        let out_ctx_virt = crate::memory::phys_to_virt(out_ctx_phys);

        // Zero the output context.
        // Safety: out_ctx_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(out_ctx_virt.as_u64() as *mut u8, 0, 4096);
        }

        // Set DCBAA[slot_id] to point to the output device context.
        let dcbaa_entry =
            (self.dcbaa_virt.as_u64() + (slot_id as u64) * 8) as *mut u64;
        // Safety: dcbaa_entry is within the DCBAA page, slot_id < MAX_SLOTS.
        unsafe {
            core::ptr::write_volatile(dcbaa_entry, out_ctx_phys.as_u64());
        }

        self.device_ctx_phys[slot_id as usize] = out_ctx_phys;

        // 5. Allocate Input Context.
        let in_ctx_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate input context")?;
        let in_ctx_phys = in_ctx_frame.start_address();
        let in_ctx_virt = crate::memory::phys_to_virt(in_ctx_phys);

        // Zero the input context.
        // Safety: in_ctx_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(in_ctx_virt.as_u64() as *mut u8, 0, 4096);
        }

        // 6. Allocate EP0 Transfer Ring.
        let ep0_ring_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate EP0 transfer ring")?;
        let ep0_ring_phys = ep0_ring_frame.start_address();
        let ep0_ring_virt = crate::memory::phys_to_virt(ep0_ring_phys);

        let ep0_ring = TrbRing::new(ep0_ring_phys, ep0_ring_virt, TRANSFER_RING_SIZE);

        // 7. Configure Input Context.
        let input_ctx = in_ctx_virt.as_u64() as *mut InputContext;

        // Determine max packet size based on speed.
        let max_packet_size: u16 = match speed {
            PORT_SPEED_LOW => 8,
            PORT_SPEED_SUPER => 512,
            _ => 64, // Full speed and High speed default
        };

        // Safety: input_ctx is within the input context page.
        unsafe {
            let ctx = &mut *input_ctx;

            // Add flags: bit 0 (Slot Context) + bit 1 (EP0 Context).
            ctx.add_flags = (1 << 0) | (1 << 1);
            ctx.drop_flags = 0;

            // Slot Context:
            // - Route String = 0 (directly attached to root hub)
            // - Speed in bits [23:20]
            // - Context Entries = 1 (only EP0) in bits [31:27]
            ctx.slot.dword0 = (1u32 << 27) | (speed << 20);

            // - Root Hub Port Number in bits [23:16]
            ctx.slot.dword1 = (port as u32) << 16;

            // EP0 Context (index 0 in endpoints array):
            // - EP Type = Control (4) in bits [5:3] of dword1
            // - CErr = 3 (retry 3 times) in bits [2:1] of dword1
            // - Max Packet Size in bits [31:16] of dword1
            ctx.endpoints[0].dword1 = ((max_packet_size as u32) << 16)
                | ((EP_TYPE_CONTROL as u32) << 3)
                | (3 << 1);

            // - TR Dequeue Pointer: physical address of EP0 ring | DCS (bit 0 = 1)
            ctx.endpoints[0].dequeue_lo =
                (ep0_ring_phys.as_u64() as u32) | 1; // DCS = 1
            ctx.endpoints[0].dequeue_hi =
                (ep0_ring_phys.as_u64() >> 32) as u32;

            // - Average TRB Length = 8 (for control transfers)
            ctx.endpoints[0].dword4 = 8;
        }

        // 8. Send Address Device command.
        let mut addr_trb = Trb::new(TRB_ADDRESS_DEVICE, 0);
        addr_trb.param = in_ctx_phys.as_u64();
        // Slot ID goes in bits [31:24] of the control field.
        addr_trb.control |= (slot_id as u32) << 24;

        let event = self.send_command(addr_trb)?;
        let cc = event.completion_code();
        if cc != TRB_COMP_SUCCESS {
            crate::serial_println!(
                "XHCI: Address Device failed for slot {}, cc={}",
                slot_id,
                cc
            );
            return Err("XHCI: Address Device command failed");
        }

        crate::serial_println!("XHCI: slot {} addressed successfully", slot_id);

        // Store EP0 ring and mark slot as enabled.
        self.ep0_rings[slot_id as usize] = Some(ep0_ring);
        self.slot_enabled[slot_id as usize] = true;

        Ok(slot_id)
    }

    // ========================================================================
    // Control Transfer — Get Device Descriptor
    // ========================================================================

    /// Perform a GET_DESCRIPTOR control transfer to read the USB device
    /// descriptor from the device in the given slot.
    fn get_descriptor(
        &mut self,
        slot: u8,
    ) -> Result<UsbDeviceDescriptor, &'static str> {
        if slot == 0 || slot as usize >= MAX_SLOTS || !self.slot_enabled[slot as usize] {
            return Err("XHCI: invalid or disabled slot");
        }

        // Allocate a DMA buffer for the descriptor (18 bytes, in a 4K page).
        let data_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate descriptor buffer")?;
        let data_phys = data_frame.start_address();
        let data_virt = crate::memory::phys_to_virt(data_phys);

        // Zero the buffer.
        // Safety: data_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(data_virt.as_u64() as *mut u8, 0, 4096);
        }

        let ep0_ring = self.ep0_rings[slot as usize]
            .as_mut()
            .ok_or("XHCI: EP0 ring not allocated for slot")?;

        // Build the 3-TRB control transfer on EP0's transfer ring.

        // Setup Stage TRB:
        // bmRequestType=0x80 (Device-to-Host, Standard, Device)
        // bRequest=0x06 (GET_DESCRIPTOR)
        // wValue=0x0100 (Device Descriptor, index 0)
        // wIndex=0x0000
        // wLength=18
        let setup_data: u64 = 0x80           // bmRequestType
            | (0x06u64 << 8)                  // bRequest
            | (0x0100u64 << 16)               // wValue
            | (0x0000u64 << 32)               // wIndex
            | (18u64 << 48);                  // wLength

        let mut setup_trb = Trb {
            param: setup_data,
            status: 8, // TRB Transfer Length = 8 (setup packet size)
            // TRB Type = Setup Stage (2), IDT (bit 6) = 1, TRT = IN (3 << 16)
            control: (TRB_SETUP_STAGE << 10) | (1 << 6) | (3 << 16),
        };
        // Cycle bit will be set by enqueue_trb.
        setup_trb.control &= !1;
        ep0_ring.enqueue_trb(setup_trb);

        // Data Stage TRB:
        let mut data_trb = Trb {
            param: data_phys.as_u64(),
            status: 18, // Transfer Length = 18 bytes
            // TRB Type = Data Stage (3), DIR = IN (bit 16 = 1)
            control: (TRB_DATA_STAGE << 10) | (1 << 16),
        };
        data_trb.control &= !1;
        ep0_ring.enqueue_trb(data_trb);

        // Status Stage TRB:
        let mut status_trb = Trb {
            param: 0,
            status: 0,
            // TRB Type = Status Stage (4), IOC = 1 (bit 5), DIR = OUT (bit 16 = 0)
            control: (TRB_STATUS_STAGE << 10) | (1 << 5),
        };
        status_trb.control &= !1;
        ep0_ring.enqueue_trb(status_trb);

        // Ring doorbell for slot / EP0 (doorbell target = 1 for EP0 IN).
        // Doorbell register index = slot_id, doorbell target = 1 (EP 0).
        self.regs.ring_doorbell(slot as u32, 1);

        // Wait for Transfer Event.
        // We may get multiple transfer events (one per TRB with IOC).
        let event = self.wait_for_event(TRB_TRANSFER_EVENT)?;
        let cc = event.completion_code();
        if cc != TRB_COMP_SUCCESS && cc != TRB_COMP_SHORT_PACKET {
            crate::serial_println!(
                "XHCI: GET_DESCRIPTOR transfer failed, cc={}",
                cc
            );
            return Err("XHCI: GET_DESCRIPTOR transfer failed");
        }

        // Parse the 18-byte USB device descriptor from the DMA buffer.
        let desc_ptr = data_virt.as_u64() as *const UsbDeviceDescriptor;
        // Safety: desc_ptr points to a valid 18-byte region in the DMA buffer,
        // and UsbDeviceDescriptor is packed to match the USB descriptor layout.
        let descriptor = unsafe { core::ptr::read_volatile(desc_ptr) };

        // Copy fields out of the packed struct to avoid unaligned references.
        let vid = descriptor.vendor_id;
        let pid = descriptor.product_id;
        let dcls = descriptor.device_class;
        let uver = descriptor.usb_version;
        crate::serial_println!(
            "XHCI: device descriptor: vendor={:#06X} product={:#06X} class={:#04X} usb_ver={:#06X}",
            vid,
            pid,
            dcls,
            uver
        );

        Ok(descriptor)
    }

    // ========================================================================
    // Interrupt Transfer (for HID polling)
    // ========================================================================

    /// Perform an interrupt IN transfer on the given endpoint.
    ///
    /// `slot` is the device slot ID, `endpoint` is the endpoint DCI
    /// (Doorbell target). The caller provides a buffer to receive data.
    /// Returns the number of bytes actually transferred.
    fn interrupt_xfer(
        &mut self,
        slot: u8,
        endpoint: u8,
        buf: &mut [u8],
    ) -> Result<usize, &'static str> {
        if slot == 0 || slot as usize >= MAX_SLOTS || !self.slot_enabled[slot as usize] {
            return Err("XHCI: invalid or disabled slot for interrupt transfer");
        }

        // Allocate a DMA buffer for the transfer.
        let data_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate interrupt transfer buffer")?;
        let data_phys = data_frame.start_address();
        let data_virt = crate::memory::phys_to_virt(data_phys);

        // Safety: data_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(data_virt.as_u64() as *mut u8, 0, 4096);
        }

        let transfer_len = core::cmp::min(buf.len(), 4096) as u32;

        // For interrupt transfers we use EP0's ring if no dedicated ring exists.
        // In a full implementation, each endpoint would have its own ring.
        let ep0_ring = self.ep0_rings[slot as usize]
            .as_mut()
            .ok_or("XHCI: no transfer ring for slot")?;

        // Build a Normal TRB for the interrupt transfer.
        let mut normal_trb = Trb {
            param: data_phys.as_u64(),
            status: transfer_len,
            // TRB Type = Normal (1), IOC (bit 5) = 1, ISP (bit 2) = 1
            control: (TRB_NORMAL << 10) | (1 << 5) | (1 << 2),
        };
        normal_trb.control &= !1; // cycle bit set by enqueue
        ep0_ring.enqueue_trb(normal_trb);

        // Ring doorbell for the target endpoint.
        // Doorbell value = endpoint DCI.
        self.regs.ring_doorbell(slot as u32, endpoint as u32);

        // Wait for Transfer Event.
        let event = self.wait_for_event(TRB_TRANSFER_EVENT)?;
        let cc = event.completion_code();
        if cc != TRB_COMP_SUCCESS && cc != TRB_COMP_SHORT_PACKET {
            crate::serial_println!(
                "XHCI: interrupt transfer failed, cc={}",
                cc
            );
            return Err("XHCI: interrupt transfer failed");
        }

        // Calculate bytes transferred: transfer_len - residual.
        let residual = event.status & 0x00FFFFFF;
        let transferred = (transfer_len - residual) as usize;
        let copy_len = core::cmp::min(transferred, buf.len());

        // Copy data from DMA buffer to caller's buffer.
        // Safety: both pointers are valid for copy_len bytes.
        unsafe {
            core::ptr::copy_nonoverlapping(
                data_virt.as_u64() as *const u8,
                buf.as_mut_ptr(),
                copy_len,
            );
        }

        Ok(copy_len)
    }

    // ========================================================================
    // Configure Endpoint for HID
    // ========================================================================

    /// Configure an interrupt IN endpoint for HID polling.
    ///
    /// `slot` is the device slot ID, `ep_addr` is the USB endpoint address
    /// (e.g., 0x81 for EP1 IN), `max_packet` is the maximum packet size,
    /// and `interval` is the polling interval.
    fn configure_hid_ep(
        &mut self,
        slot: u8,
        ep_addr: u8,
        max_packet: u16,
        interval: u8,
    ) -> Result<(), &'static str> {
        if slot == 0 || slot as usize >= MAX_SLOTS || !self.slot_enabled[slot as usize] {
            return Err("XHCI: invalid or disabled slot for configure endpoint");
        }

        // Calculate the Device Context Index (DCI) for this endpoint.
        // DCI = (endpoint_number * 2) + direction.
        // For IN endpoints (bit 7 set): DCI = ep_num * 2 + 1
        // For OUT endpoints: DCI = ep_num * 2
        let ep_num = ep_addr & 0x0F;
        let is_in = (ep_addr & 0x80) != 0;
        let dci = (ep_num as u32) * 2 + if is_in { 1 } else { 0 };

        if dci == 0 || dci > 31 {
            return Err("XHCI: invalid endpoint DCI");
        }

        crate::serial_println!(
            "XHCI: configuring HID endpoint slot={} ep_addr={:#04X} DCI={} max_pkt={} interval={}",
            slot,
            ep_addr,
            dci,
            max_packet,
            interval
        );

        // Allocate a transfer ring for this endpoint.
        let ep_ring_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate endpoint transfer ring")?;
        let ep_ring_phys = ep_ring_frame.start_address();
        let ep_ring_virt = crate::memory::phys_to_virt(ep_ring_phys);

        // Zero the ring.
        // Safety: ep_ring_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(ep_ring_virt.as_u64() as *mut u8, 0, 4096);
        }

        // Write Link TRB at the end.
        let link_offset = (TRANSFER_RING_SIZE - 1) * 16;
        let link_ptr = (ep_ring_virt.as_u64() + link_offset as u64) as *mut Trb;
        let link_trb = Trb {
            param: ep_ring_phys.as_u64(),
            status: 0,
            control: (TRB_LINK << 10) | (1 << 1), // TC bit set
        };
        // Safety: link_ptr is within the ring allocation.
        unsafe {
            core::ptr::write_volatile(link_ptr, link_trb);
        }

        // Allocate Input Context for the Configure Endpoint command.
        let in_ctx_frame = crate::memory::allocate_frame()
            .ok_or("XHCI: failed to allocate input context for configure")?;
        let in_ctx_phys = in_ctx_frame.start_address();
        let in_ctx_virt = crate::memory::phys_to_virt(in_ctx_phys);

        // Safety: in_ctx_virt is a valid 4 KiB page.
        unsafe {
            core::ptr::write_bytes(in_ctx_virt.as_u64() as *mut u8, 0, 4096);
        }

        let input_ctx = in_ctx_virt.as_u64() as *mut InputContext;

        // Safety: input_ctx is within the input context page.
        unsafe {
            let ctx = &mut *input_ctx;

            // Add flags: bit 0 (Slot) + bit for the endpoint DCI.
            ctx.add_flags = (1 << 0) | (1 << dci);
            ctx.drop_flags = 0;

            // Update Slot Context: set Context Entries to include this EP.
            // Context Entries must be >= DCI.
            let context_entries = dci;
            ctx.slot.dword0 = context_entries << 27;

            // Read the current slot context speed from the output context
            // so we preserve it.
            let out_ctx_virt = crate::memory::phys_to_virt(
                self.device_ctx_phys[slot as usize],
            );
            let out_slot = &*(out_ctx_virt.as_u64() as *const SlotContext);
            ctx.slot.dword0 |= out_slot.dword0 & 0x07FFFFFF; // keep lower bits
            ctx.slot.dword0 = (context_entries << 27) | (out_slot.dword0 & 0x00FFFFFF);
            ctx.slot.dword1 = out_slot.dword1;
            ctx.slot.dword2 = out_slot.dword2;

            // Configure the endpoint context at (dci - 1) index.
            let ep_idx = (dci - 1) as usize;
            let ep_type = if is_in {
                EP_TYPE_INTERRUPT_IN
            } else {
                EP_TYPE_INTERRUPT_OUT
            };

            // Interval: for xHCI, the interval is expressed as
            // 2^(Interval-1) * 125 µs. Convert USB interval to xHCI format.
            let xhci_interval = if interval == 0 { 1u32 } else { interval as u32 };

            // Dword 0: Interval [23:16], EP State = 0
            ctx.endpoints[ep_idx].dword0 = xhci_interval << 16;

            // Dword 1: CErr=3 [2:1], EP Type [5:3], Max Packet Size [31:16]
            ctx.endpoints[ep_idx].dword1 = ((max_packet as u32) << 16)
                | ((ep_type as u32) << 3)
                | (3 << 1);

            // TR Dequeue Pointer with DCS=1.
            ctx.endpoints[ep_idx].dequeue_lo =
                (ep_ring_phys.as_u64() as u32) | 1;
            ctx.endpoints[ep_idx].dequeue_hi =
                (ep_ring_phys.as_u64() >> 32) as u32;

            // Average TRB Length = max_packet (good estimate for interrupt).
            ctx.endpoints[ep_idx].dword4 = max_packet as u32;
        }

        // Send Configure Endpoint command.
        let mut cfg_trb = Trb::new(TRB_CONFIGURE_ENDPOINT, 0);
        cfg_trb.param = in_ctx_phys.as_u64();
        cfg_trb.control |= (slot as u32) << 24;

        let event = self.send_command(cfg_trb)?;
        let cc = event.completion_code();
        if cc != TRB_COMP_SUCCESS {
            crate::serial_println!(
                "XHCI: Configure Endpoint failed for slot {}, cc={}",
                slot,
                cc
            );
            return Err("XHCI: Configure Endpoint command failed");
        }

        crate::serial_println!(
            "XHCI: HID endpoint configured for slot {} DCI {}",
            slot,
            dci
        );

        Ok(())
    }

    // ========================================================================
    // Event Processing (poll)
    // ========================================================================

    /// Poll the event ring for pending events and process them.
    ///
    /// Handles Command Completion, Transfer Event, and Port Status Change
    /// event types. This should be called from a timer IRQ or periodically.
    fn process_events(&mut self) {
        loop {
            let offset = self.event_dequeue * 16;
            let trb_ptr =
                (self.event_ring_virt.as_u64() + offset as u64) as *const Trb;

            // Safety: trb_ptr is within the event ring allocation.
            let trb = unsafe { core::ptr::read_volatile(trb_ptr) };

            // Check cycle bit.
            if trb.cycle_bit() != self.event_cycle_bit {
                break; // No more pending events.
            }

            let trb_type = trb.trb_type();

            match trb_type {
                TRB_COMMAND_COMPLETION => {
                    crate::serial_println!(
                        "XHCI: [event] command completion, cc={}, slot={}",
                        trb.completion_code(),
                        trb.slot_id()
                    );
                }
                TRB_TRANSFER_EVENT => {
                    crate::serial_println!(
                        "XHCI: [event] transfer event, cc={}, slot={}",
                        trb.completion_code(),
                        trb.slot_id()
                    );
                }
                TRB_PORT_STATUS_CHANGE => {
                    let port_id = (trb.param >> 24) as u8;
                    crate::serial_println!(
                        "XHCI: [event] port status change, port={}",
                        port_id
                    );

                    // Check if a new device is connected.
                    if port_id > 0 && port_id <= self.max_ports {
                        let portsc = self.regs.portsc_read(port_id);
                        if (portsc & PORTSC_CCS) != 0 {
                            crate::serial_println!(
                                "XHCI: new device connected on port {}",
                                port_id
                            );
                            // Attempt enumeration (best-effort in poll context).
                            match self.port_reset(port_id) {
                                Ok(sid) => {
                                    crate::serial_println!(
                                        "XHCI: hot-plug enumerated slot {}",
                                        sid
                                    );
                                }
                                Err(e) => {
                                    crate::serial_println!(
                                        "XHCI: hot-plug enumerate failed: {}",
                                        e
                                    );
                                }
                            }
                        }
                    }
                }
                _ => {
                    crate::serial_println!(
                        "XHCI: [event] unknown type={}, cc={}",
                        trb_type,
                        trb.completion_code()
                    );
                }
            }

            // Advance dequeue pointer.
            self.event_dequeue += 1;
            if self.event_dequeue >= self.event_ring_size {
                self.event_dequeue = 0;
                self.event_cycle_bit ^= 1;
            }

            // Update ERDP.
            let new_erdp = self.event_ring_phys.as_u64()
                + (self.event_dequeue as u64) * 16;
            let intr0_base = INTR0_OFFSET;
            self.regs
                .rt_write64(intr0_base + INTR_ERDP, new_erdp | (1 << 3));
        }
    }
}

// ============================================================================
// Public API (free functions operating on the global XHCI mutex)
// ============================================================================

/// Poll for and process pending XHCI events.
///
/// Should be called periodically from a timer interrupt or polling loop.
pub fn poll_events() {
    let mut guard = XHCI.lock();
    if let Some(ref mut ctrl) = *guard {
        ctrl.process_events();
    }
}

/// Perform a GET_DESCRIPTOR control transfer to read the USB device
/// descriptor from the device in the given slot.
pub fn get_device_descriptor(slot: u8) -> Result<UsbDeviceDescriptor, &'static str> {
    let mut guard = XHCI.lock();
    let ctrl = guard.as_mut().ok_or("XHCI: not initialised")?;
    ctrl.get_descriptor(slot)
}

/// Perform an interrupt IN transfer on the given endpoint.
///
/// Returns the number of bytes transferred into `buf`.
pub fn interrupt_transfer(
    slot: u8,
    endpoint: u8,
    buf: &mut [u8],
) -> Result<usize, &'static str> {
    let mut guard = XHCI.lock();
    let ctrl = guard.as_mut().ok_or("XHCI: not initialised")?;
    ctrl.interrupt_xfer(slot, endpoint, buf)
}

/// Configure an interrupt endpoint for HID polling.
pub fn configure_hid_endpoint(
    slot: u8,
    ep_addr: u8,
    max_packet: u16,
    interval: u8,
) -> Result<(), &'static str> {
    let mut guard = XHCI.lock();
    let ctrl = guard.as_mut().ok_or("XHCI: not initialised")?;
    ctrl.configure_hid_ep(slot, ep_addr, max_packet, interval)
}

/// Returns `true` if the XHCI controller was successfully initialised.
pub fn is_available() -> bool {
    XHCI.lock().is_some()
}

/// Returns the number of USB ports on the root hub.
pub fn port_count() -> u8 {
    let guard = XHCI.lock();
    match *guard {
        Some(ref ctrl) => ctrl.max_ports,
        None => 0,
    }
}

/// Returns the number of device slots currently enabled (connected devices).
pub fn connected_devices() -> u8 {
    let guard = XHCI.lock();
    match *guard {
        Some(ref ctrl) => ctrl
            .slot_enabled
            .iter()
            .filter(|&&e| e)
            .count() as u8,
        None => 0,
    }
}
