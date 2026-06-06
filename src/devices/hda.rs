// ============================================================================
// FerrumOS - Intel High Definition Audio (HDA) Controller Driver
// ============================================================================
// Hardware driver for the Intel HDA controller as emulated by QEMU
// (`-device intel-hda -device hda-duplex`).
//
// Implements:
//   - PCI discovery (vendor 0x8086 device 0x2668 / class 04:03 fallback)
//   - MMIO register access via volatile reads/writes
//   - CORB / RIRB command ring buffers for codec verb transport
//   - Codec widget tree discovery (DAC, ADC, pin widgets)
//   - Output & input stream setup with Buffer Descriptor Lists (BDL)
//   - Public API: play_buffer, stop_playback, record_buffer, stop_recording,
//     set_volume, is_available
// ============================================================================

#[allow(dead_code)]
extern crate alloc;

use spin::Mutex;
use x86_64::{PhysAddr, VirtAddr};

use crate::devices::pci;
use crate::devices::pci::PciDevice;

// ============================================================================
// PCI Constants
// ============================================================================

/// Intel HDA PCI class code (Multimedia controller / Audio device).
const HDA_PCI_CLASS: u8 = 0x04;
const HDA_PCI_SUBCLASS: u8 = 0x03;

/// QEMU ICH6 Intel HDA identifiers.
const QEMU_HDA_VENDOR: u16 = 0x8086;
const QEMU_HDA_DEVICE: u16 = 0x2668;

/// PCI configuration space offsets.
const PCI_COMMAND: u8 = 0x04;
const PCI_BAR0: u8 = 0x10;

// ============================================================================
// HDA Controller Register Offsets (from BAR0)
// ============================================================================

const REG_GCAP: u32 = 0x00;    // Global Capabilities (16-bit)
const REG_VMIN: u32 = 0x02;    // Minor Version (8-bit)
const REG_VMAJ: u32 = 0x03;    // Major Version (8-bit)
const REG_OUTPAY: u32 = 0x04;  // Output Payload Capability (16-bit)
const REG_INPAY: u32 = 0x06;   // Input Payload Capability (16-bit)
const REG_GCTL: u32 = 0x08;    // Global Control (32-bit)
const REG_WAKEEN: u32 = 0x0C;  // Wake Enable (16-bit)
const REG_STATESTS: u32 = 0x0E; // State Change Status (16-bit)
const REG_GSTS: u32 = 0x10;    // Global Status (16-bit)
const REG_INTCTL: u32 = 0x20;  // Interrupt Control (32-bit)
const REG_INTSTS: u32 = 0x24;  // Interrupt Status (32-bit)

// CORB registers
const REG_CORBLBASE: u32 = 0x40; // CORB Lower Base Address (32-bit)
const REG_CORBUBASE: u32 = 0x44; // CORB Upper Base Address (32-bit)
const REG_CORBWP: u32 = 0x48;    // CORB Write Pointer (16-bit)
const REG_CORBRP: u32 = 0x4A;    // CORB Read Pointer (16-bit)
const REG_CORBCTL: u32 = 0x4C;   // CORB Control (8-bit)
const REG_CORBSTS: u32 = 0x4D;   // CORB Status (8-bit)
const REG_CORBSIZE: u32 = 0x4E;  // CORB Size (8-bit)

// RIRB registers
const REG_RIRBLBASE: u32 = 0x50; // RIRB Lower Base Address (32-bit)
const REG_RIRBUBASE: u32 = 0x54; // RIRB Upper Base Address (32-bit)
const REG_RIRBWP: u32 = 0x58;    // RIRB Write Pointer (16-bit)
const REG_RINTCNT: u32 = 0x5A;   // Response Interrupt Count (16-bit)
const REG_RIRBCTL: u32 = 0x5C;   // RIRB Control (8-bit)
const REG_RIRBSTS: u32 = 0x5D;   // RIRB Status (8-bit)
const REG_RIRBSIZE: u32 = 0x5E;  // RIRB Size (8-bit)

// Stream Descriptor base offset (output stream 0 at 0x80)
const SD_BASE: u32 = 0x80;
const SD_STRIDE: u32 = 0x20; // 32 bytes per stream descriptor

// Stream Descriptor register offsets (relative to stream base)
const SD_CTL: u32 = 0x00;    // Stream Descriptor Control (24-bit over 3 bytes)
const SD_STS: u32 = 0x03;    // Stream Descriptor Status (8-bit)
const SD_LPIB: u32 = 0x04;   // Link Position in Buffer (32-bit)
const SD_CBL: u32 = 0x08;    // Cyclic Buffer Length (32-bit)
const SD_LVI: u32 = 0x0C;    // Last Valid Index (16-bit)
const SD_FIFOW: u32 = 0x0E;  // FIFO Watermark (16-bit)
const SD_FIFOS: u32 = 0x10;  // FIFO Size (16-bit)
const SD_FMT: u32 = 0x12;    // Stream Format (16-bit)
const SD_BDLPL: u32 = 0x18;  // BDL Pointer Lower (32-bit)
const SD_BDLPU: u32 = 0x1C;  // BDL Pointer Upper (32-bit)

// ============================================================================
// HDA Codec Verb Constants
// ============================================================================

/// GET_PARAMETER verb (verb ID 0xF00, 12-bit payload).
const VERB_GET_PARAMETER: u32 = 0xF0000;
const PARAM_VENDOR_ID: u32 = 0x00;
const PARAM_REVISION_ID: u32 = 0x02;
const PARAM_SUBNODE_COUNT: u32 = 0x04;
const PARAM_FUNC_GROUP_TYPE: u32 = 0x05;
const PARAM_AUDIO_WIDGET_CAP: u32 = 0x09;
const PARAM_CONN_LIST_LEN: u32 = 0x0E;

/// SET_STREAM_FORMAT verb (verb ID 0x200, 16-bit payload).
const VERB_SET_STREAM_FORMAT: u32 = 0x20000;

/// SET_CHANNEL_STREAM_ID (verb ID 0x706, 8-bit payload).
const VERB_SET_CHANNEL_STREAM: u32 = 0x70600;

/// SET_PIN_WIDGET_CONTROL (verb ID 0x707, 8-bit payload).
const VERB_SET_PIN_CONTROL: u32 = 0x70700;

/// GET_PIN_WIDGET_CONTROL (verb ID 0xF07).
const VERB_GET_PIN_CONTROL: u32 = 0xF0700;

/// SET_AMP_GAIN_MUTE (verb ID 0x300, 16-bit payload).
const VERB_SET_AMP_GAIN_MUTE: u32 = 0x30000;

/// SET_POWER_STATE (verb ID 0x705, 8-bit payload).
const VERB_SET_POWER_STATE: u32 = 0x70500;

/// SET_EAPD/BTL Enable (verb ID 0x70C, 8-bit payload).
const VERB_SET_EAPD: u32 = 0x70C00;

/// SET_CONVERTER_CONTROL (verb ID 0x70D for digital converters).
const VERB_SET_DIGI_CONVERT_1: u32 = 0x70D00;

/// GET_CONFIGURATION_DEFAULT (verb ID 0xF1C).
const VERB_GET_CONFIG_DEFAULT: u32 = 0xF1C00;

// Widget type constants (bits [23:20] of widget capabilities).
const WIDGET_TYPE_OUTPUT: u8 = 0; // Audio Output (DAC)
const WIDGET_TYPE_INPUT: u8 = 1;  // Audio Input  (ADC)
const WIDGET_TYPE_MIXER: u8 = 2;  // Mixer
const WIDGET_TYPE_SELECTOR: u8 = 3; // Selector
const WIDGET_TYPE_PIN: u8 = 4;    // Pin Complex
const WIDGET_TYPE_POWER: u8 = 5;  // Power Widget
const WIDGET_TYPE_VOLUME: u8 = 6; // Volume Knob

// Stream format: 48 kHz, 16-bit, stereo
// Bits [14]:    Base rate 0=48kHz
// Bits [13:11]: Multiplier 000=x1
// Bits [10:8]:  Divisor    000=/1
// Bits [7:4]:   Bits/sample 0001=16-bit
// Bits [3:0]:   Channels-1  0001=2ch (stereo)
const STREAM_FORMAT_48K_16B_STEREO: u16 = 0x0011;

// Number of BDL entries per stream
const BDL_ENTRY_COUNT: usize = 4;
// Size of each audio buffer chunk (4 KiB)
const AUDIO_BUF_CHUNK: usize = 4096;
// Total audio buffer size (4 chunks Ã— 4 KiB = 16 KiB)
const AUDIO_BUF_TOTAL: usize = BDL_ENTRY_COUNT * AUDIO_BUF_CHUNK;

// Timeout for polling loops (iterations)
const POLL_TIMEOUT: u32 = 50_000;

// ============================================================================
// BDL Entry (Buffer Descriptor List)
// ============================================================================

/// A single Buffer Descriptor List entry (16 bytes, naturally aligned).
#[repr(C, packed)]
#[derive(Clone, Copy)]
struct BdlEntry {
    /// Physical address of the buffer.
    address: u64,
    /// Length of the buffer in bytes.
    length: u32,
    /// Bit 0 = Interrupt On Completion (IOC).
    ioc: u32,
}

// ============================================================================
// MMIO Register Access
// ============================================================================

/// Wrapper around a base MMIO pointer for volatile register I/O.
struct HdaRegs {
    base: *mut u8,
}

impl HdaRegs {
    /// Read a 32-bit MMIO register at `offset` bytes from base.
    #[inline]
    fn read32(&self, offset: u32) -> u32 {
        // Safety: `base + offset` is within the HDA controller's MMIO
        // region mapped from BAR0.  Volatile ensures the read is not
        // elided or reordered by the compiler.
        unsafe { core::ptr::read_volatile(self.base.add(offset as usize) as *const u32) }
    }

    /// Write a 32-bit value to the MMIO register at `offset`.
    #[inline]
    fn write32(&self, offset: u32, value: u32) {
        // Safety: same as read32.
        unsafe { core::ptr::write_volatile(self.base.add(offset as usize) as *mut u32, value) }
    }

    /// Read a 16-bit MMIO register at `offset`.
    #[inline]
    fn read16(&self, offset: u32) -> u16 {
        // Safety: within MMIO region from BAR0.
        unsafe { core::ptr::read_volatile(self.base.add(offset as usize) as *const u16) }
    }

    /// Write a 16-bit value to the MMIO register at `offset`.
    #[inline]
    fn write16(&self, offset: u32, value: u16) {
        // Safety: within MMIO region from BAR0.
        unsafe { core::ptr::write_volatile(self.base.add(offset as usize) as *mut u16, value) }
    }

    /// Read an 8-bit MMIO register at `offset`.
    #[inline]
    fn read8(&self, offset: u32) -> u8 {
        // Safety: within MMIO region from BAR0.
        unsafe { core::ptr::read_volatile(self.base.add(offset as usize) as *const u8) }
    }

    /// Write an 8-bit value to the MMIO register at `offset`.
    #[inline]
    fn write8(&self, offset: u32, value: u8) {
        // Safety: within MMIO region from BAR0.
        unsafe { core::ptr::write_volatile(self.base.add(offset as usize) as *mut u8, value) }
    }
}

// ============================================================================
// Global State
// ============================================================================

/// Global Intel HDA controller instance, protected by a spinlock.
pub static HDA: Mutex<Option<HdaController>> = Mutex::new(None);

// ============================================================================
// HdaController
// ============================================================================

/// Represents a fully initialised Intel HDA controller.
pub struct HdaController {
    regs: HdaRegs,

    // CORB (Command Output Ring Buffer)
    corb_virt: VirtAddr,
    corb_phys: PhysAddr,
    // RIRB (Response Input Ring Buffer)
    rirb_virt: VirtAddr,
    rirb_phys: PhysAddr,

    corb_wp: u16,  // our write pointer into CORB
    rirb_rp: u16,  // our read pointer into RIRB

    // Output stream (playback)
    out_bdl_virt: VirtAddr,
    out_bdl_phys: PhysAddr,
    out_buf_virt: VirtAddr,
    out_buf_phys: PhysAddr,
    out_buf_size: u32,
    out_stream_base: u32, // SD register base for the output stream

    // Input stream (recording)
    in_bdl_virt: VirtAddr,
    in_bdl_phys: PhysAddr,
    in_buf_virt: VirtAddr,
    in_buf_phys: PhysAddr,
    in_buf_size: u32,
    in_stream_base: u32, // SD register base for the input stream

    // Codec topology discovered during init
    output_dac_nid: u8,
    output_pin_nid: u8,
    input_adc_nid: u8,
    input_pin_nid: u8,

    // Stream counts from GCAP
    num_input_streams: u8,
    num_output_streams: u8,
}

// Safety: The HdaController contains raw pointers to MMIO memory and DMA
// buffers.  All accesses go through volatile operations, and the entire
// struct is behind a spin::Mutex, so only one core accesses it at a time.
unsafe impl Send for HdaController {}
unsafe impl Sync for HdaController {}

// ============================================================================
// PCI Discovery
// ============================================================================

/// Attempt to locate the HDA controller on the PCI bus.
///
/// First tries the well-known QEMU ICH6 vendor/device pair, then falls
/// back to scanning for any device with class 04 subclass 03.
fn find_hda_pci() -> Option<PciDevice> {
    // Fast path: try the known QEMU ICH6 HDA device.
    if let Some(dev) = pci::find_device(QEMU_HDA_VENDOR, QEMU_HDA_DEVICE) {
        return Some(dev);
    }

    // Slow path: scan all buses/slots for class 04:03.
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

                if class == HDA_PCI_CLASS && subclass == HDA_PCI_SUBCLASS {
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
// Tiny busy-wait helper
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

/// Initialise the Intel HDA controller.
///
/// Discovers the device on PCI, resets the controller, sets up CORB/RIRB,
/// walks the codec widget tree, and prepares output & input streams.
pub fn init() -> Result<(), &'static str> {
    // 1. Find the HDA device on PCI.
    let pci_dev = find_hda_pci().ok_or("HDA: PCI device not found")?;

    crate::serial_println!(
        "HDA: found PCI device at bus={} slot={} func={}",
        pci_dev.bus,
        pci_dev.slot,
        pci_dev.func
    );

    // 2. Read BAR0 and map into kernel virtual address space.
    let bar0_lo = pci::read_config_u32(pci_dev.bus, pci_dev.slot, pci_dev.func, PCI_BAR0);
    let is_64bit = (bar0_lo & 0x06) == 0x04;
    let bar0_hi = if is_64bit {
        pci::read_config_u32(pci_dev.bus, pci_dev.slot, pci_dev.func, PCI_BAR0 + 4)
    } else {
        0
    };

    let bar0_phys = ((bar0_hi as u64) << 32) | ((bar0_lo & !0xF) as u64);
    if bar0_phys == 0 {
        return Err("HDA: BAR0 is zero");
    }

    let bar0_virt = crate::memory::phys_to_virt(PhysAddr::new(bar0_phys));
    let regs = HdaRegs {
        base: bar0_virt.as_u64() as *mut u8,
    };

    crate::serial_println!(
        "HDA: BAR0 phys={:#X} virt={:#X}",
        bar0_phys,
        bar0_virt.as_u64()
    );

    // 3. Enable PCI bus mastering (set bit 2 of the command register).
    let cmd = pci::read_config_u16(pci_dev.bus, pci_dev.slot, pci_dev.func, PCI_COMMAND);
    let new_cmd = cmd | 0x06; // Bus Master + Memory Space enable
    pci::write_config_u32(
        pci_dev.bus,
        pci_dev.slot,
        pci_dev.func,
        PCI_COMMAND,
        new_cmd as u32,
    );

    // 4. Controller reset: clear CRST, wait, then set CRST, wait.
    let gctl = regs.read32(REG_GCTL);
    regs.write32(REG_GCTL, gctl & !1); // Clear CRST
    spin_wait(1000);

    // Wait for CRST to read 0 (controller in reset).
    for _ in 0..POLL_TIMEOUT {
        if (regs.read32(REG_GCTL) & 1) == 0 {
            break;
        }
        core::hint::spin_loop();
    }

    // Bring controller out of reset.
    let gctl = regs.read32(REG_GCTL);
    regs.write32(REG_GCTL, gctl | 1); // Set CRST
    spin_wait(1000);

    // Wait for CRST to read 1 (controller running).
    let mut running = false;
    for _ in 0..POLL_TIMEOUT {
        if (regs.read32(REG_GCTL) & 1) != 0 {
            running = true;
            break;
        }
        core::hint::spin_loop();
    }
    if !running {
        return Err("HDA: controller failed to exit reset");
    }

    // 5. Wait for at least one codec to report presence via STATESTS.
    spin_wait(10_000); // give codecs time to enumerate
    let mut codec_detected = false;
    for _ in 0..POLL_TIMEOUT {
        let sts = regs.read16(REG_STATESTS);
        if sts != 0 {
            crate::serial_println!("HDA: STATESTS={:#06X} — codec(s) detected", sts);
            regs.write16(REG_STATESTS, sts); // write-1-to-clear
            codec_detected = true;
            break;
        }
        core::hint::spin_loop();
    }
    if !codec_detected {
        return Err("HDA: no codecs detected (STATESTS timeout)");
    }

    // 6. Read GCAP for stream counts.
    let gcap = regs.read16(REG_GCAP);
    let num_output_streams = ((gcap >> 12) & 0x0F) as u8;
    let num_input_streams = ((gcap >> 8) & 0x0F) as u8;
    let num_bidir_streams = ((gcap >> 3) & 0x1F) as u8;
    crate::serial_println!(
        "HDA: GCAP={:#06X} oss={} iss={} bss={}",
        gcap,
        num_output_streams,
        num_input_streams,
        num_bidir_streams
    );

    // Compute stream descriptor register bases.
    // Input streams come first starting at SD_BASE, then output streams.
    let out_stream_base = SD_BASE + (num_input_streams as u32) * SD_STRIDE;
    let in_stream_base = SD_BASE; // Input stream 0 is the first SD

    // 7. Setup CORB.
    let corb_frame =
        crate::memory::allocate_frame().ok_or("HDA: failed to allocate CORB frame")?;
    let corb_phys = corb_frame.start_address();
    let corb_virt = crate::memory::phys_to_virt(corb_phys);

    // Zero the CORB page.
    // Safety: corb_virt is a valid kernel-mapped 4 KiB page.
    unsafe {
        core::ptr::write_bytes(corb_virt.as_u64() as *mut u8, 0, 4096);
    }

    // Stop CORB before configuring.
    regs.write8(REG_CORBCTL, 0);
    spin_wait(500);

    // Set CORB base address.
    regs.write32(REG_CORBLBASE, corb_phys.as_u64() as u32);
    regs.write32(REG_CORBUBASE, (corb_phys.as_u64() >> 32) as u32);

    // Set CORB size to 256 entries (bits [1:0] = 0b10).
    regs.write8(REG_CORBSIZE, 0x02);

    // Reset CORB read pointer: set bit 15, wait, clear it.
    regs.write16(REG_CORBRP, 0x8000);
    spin_wait(1000);
    // Some controllers require waiting for bit 15 to read back as 1
    for _ in 0..POLL_TIMEOUT {
        if (regs.read16(REG_CORBRP) & 0x8000) != 0 {
            break;
        }
        core::hint::spin_loop();
    }
    regs.write16(REG_CORBRP, 0x0000);
    spin_wait(500);

    // Reset CORB write pointer.
    regs.write16(REG_CORBWP, 0);

    // Start CORB (DMA run bit 1).
    regs.write8(REG_CORBCTL, 0x02);
    spin_wait(500);

    // 8. Setup RIRB.
    let rirb_frame =
        crate::memory::allocate_frame().ok_or("HDA: failed to allocate RIRB frame")?;
    let rirb_phys = rirb_frame.start_address();
    let rirb_virt = crate::memory::phys_to_virt(rirb_phys);

    // Zero the RIRB page.
    // Safety: rirb_virt is a valid kernel-mapped 4 KiB page.
    unsafe {
        core::ptr::write_bytes(rirb_virt.as_u64() as *mut u8, 0, 4096);
    }

    // Stop RIRB before configuring.
    regs.write8(REG_RIRBCTL, 0);
    spin_wait(500);

    // Set RIRB base address.
    regs.write32(REG_RIRBLBASE, rirb_phys.as_u64() as u32);
    regs.write32(REG_RIRBUBASE, (rirb_phys.as_u64() >> 32) as u32);

    // Set RIRB size to 256 entries (bits [1:0] = 0b10).
    regs.write8(REG_RIRBSIZE, 0x02);

    // Reset RIRB write pointer (set bit 15).
    regs.write16(REG_RIRBWP, 0x8000);
    spin_wait(500);

    // Set response interrupt count.
    regs.write16(REG_RINTCNT, 1);

    // Start RIRB (DMA run bit 1 + interrupt bit 0).
    regs.write8(REG_RIRBCTL, 0x02);
    spin_wait(500);

    // ---- Allocate output stream buffers ----
    let out_bdl_frame =
        crate::memory::allocate_frame().ok_or("HDA: failed to allocate output BDL frame")?;
    let out_bdl_phys = out_bdl_frame.start_address();
    let out_bdl_virt = crate::memory::phys_to_virt(out_bdl_phys);
    // Safety: out_bdl_virt is a valid 4 KiB page.
    unsafe {
        core::ptr::write_bytes(out_bdl_virt.as_u64() as *mut u8, 0, 4096);
    }

    let out_buf_first = crate::memory::allocate_contiguous_frames(BDL_ENTRY_COUNT)
        .ok_or("HDA: failed to allocate output audio buffer")?;
    let out_buf_phys = out_buf_first.start_address();
    let out_buf_virt = crate::memory::phys_to_virt(out_buf_phys);
    // Safety: out_buf_virt spans BDL_ENTRY_COUNT contiguous 4 KiB pages.
    unsafe {
        core::ptr::write_bytes(out_buf_virt.as_u64() as *mut u8, 0, AUDIO_BUF_TOTAL);
    }

    // ---- Allocate input stream buffers ----
    let in_bdl_frame =
        crate::memory::allocate_frame().ok_or("HDA: failed to allocate input BDL frame")?;
    let in_bdl_phys = in_bdl_frame.start_address();
    let in_bdl_virt = crate::memory::phys_to_virt(in_bdl_phys);
    // Safety: in_bdl_virt is a valid 4 KiB page.
    unsafe {
        core::ptr::write_bytes(in_bdl_virt.as_u64() as *mut u8, 0, 4096);
    }

    let in_buf_first = crate::memory::allocate_contiguous_frames(BDL_ENTRY_COUNT)
        .ok_or("HDA: failed to allocate input audio buffer")?;
    let in_buf_phys = in_buf_first.start_address();
    let in_buf_virt = crate::memory::phys_to_virt(in_buf_phys);
    // Safety: in_buf_virt spans BDL_ENTRY_COUNT contiguous 4 KiB pages.
    unsafe {
        core::ptr::write_bytes(in_buf_virt.as_u64() as *mut u8, 0, AUDIO_BUF_TOTAL);
    }

    // Build the controller struct.
    let mut ctrl = HdaController {
        regs,
        corb_virt,
        corb_phys,
        rirb_virt,
        rirb_phys,
        corb_wp: 0,
        rirb_rp: 0,
        out_bdl_virt,
        out_bdl_phys,
        out_buf_virt,
        out_buf_phys,
        out_buf_size: AUDIO_BUF_TOTAL as u32,
        out_stream_base,
        in_bdl_virt,
        in_bdl_phys,
        in_buf_virt,
        in_buf_phys,
        in_buf_size: AUDIO_BUF_TOTAL as u32,
        in_stream_base,
        output_dac_nid: 0,
        output_pin_nid: 0,
        input_adc_nid: 0,
        input_pin_nid: 0,
        num_input_streams,
        num_output_streams,
    };

    // 9. Discover codec widgets.
    ctrl.discover_codec()?;

    // 10. Setup output stream BDL.
    ctrl.setup_output_stream()?;

    // 11. Setup input stream BDL.
    ctrl.setup_input_stream()?;

    // 12. Configure output path (DAC â†’ Pin).
    ctrl.configure_output_path()?;

    // 13. Configure input path (Pin â†’ ADC).
    ctrl.configure_input_path()?;

    crate::serial_println!("HDA: initialisation complete");

    // Store in global state.
    *HDA.lock() = Some(ctrl);
    Ok(())
}

// ============================================================================
// HdaController Implementation
// ============================================================================

impl HdaController {
    // ========================================================================
    // Codec Verb Transport
    // ========================================================================

    /// Send a codec verb via CORB and wait for the response in RIRB.
    ///
    /// The verb is encoded as:
    ///   `(codec_id << 28) | (nid << 20) | verb`
    ///
    /// Returns the 32-bit response word, or an error on timeout.
    fn send_verb(
        &mut self,
        codec_id: u8,
        nid: u8,
        verb: u32,
    ) -> Result<u32, &'static str> {
        let command: u32 =
            ((codec_id as u32) << 28) | ((nid as u32) << 20) | (verb & 0x000F_FFFF);

        // Advance the CORB write pointer (wraps at 255 for 256-entry ring).
        self.corb_wp = (self.corb_wp + 1) & 0xFF;

        // Write the command into the CORB ring buffer.
        let corb_slot = self.corb_virt.as_u64() + (self.corb_wp as u64) * 4;
        // Safety: corb_slot is within the CORB page, each entry is 4 bytes.
        unsafe {
            core::ptr::write_volatile(corb_slot as *mut u32, command);
        }

        // Poke the CORBWP register so the controller fetches the command.
        self.regs.write16(REG_CORBWP, self.corb_wp);

        // Poll RIRBWP until the controller has written a response.
        let mut timeout = POLL_TIMEOUT;
        loop {
            let hw_wp = self.regs.read16(REG_RIRBWP) & 0xFF;
            if hw_wp != self.rirb_rp {
                break;
            }
            timeout -= 1;
            if timeout == 0 {
                return Err("HDA: RIRB timeout waiting for response");
            }
            core::hint::spin_loop();
        }

        // Advance our software read pointer.
        self.rirb_rp = (self.rirb_rp + 1) & 0xFF;

        // Each RIRB entry is 8 bytes: [response: u32][response_ex: u32].
        let rirb_slot = self.rirb_virt.as_u64() + (self.rirb_rp as u64) * 8;
        // Safety: rirb_slot is within the RIRB page.
        let response = unsafe { core::ptr::read_volatile(rirb_slot as *const u32) };

        // Clear RIRB Interrupt Status (bit 0 = Response Interrupt, bit 2 = RIRB Overrun).
        // This is a write-1-to-clear register.
        self.regs.write8(REG_RIRBSTS, 0x05);

        Ok(response)
    }

    // ========================================================================
    // Codec Discovery
    // ========================================================================

    /// Walk the codec widget tree and populate DAC / ADC / pin NIDs.
    fn discover_codec(&mut self) -> Result<(), &'static str> {
        // Read root node (NID 0) subordinate count.
        let sub = self.send_verb(0, 0, VERB_GET_PARAMETER | PARAM_SUBNODE_COUNT)?;
        let start_nid = ((sub >> 16) & 0xFF) as u8;
        let num_nodes = (sub & 0xFF) as u8;

        crate::serial_println!(
            "HDA: root node: start_nid={} num_nodes={}",
            start_nid,
            num_nodes
        );

        // Iterate function groups (usually just one: Audio Function Group).
        for fg in start_nid..(start_nid + num_nodes) {
            let fg_type = self.send_verb(0, fg, VERB_GET_PARAMETER | PARAM_FUNC_GROUP_TYPE)?;
            let is_audio_fg = (fg_type & 0xFF) == 0x01;

            if !is_audio_fg {
                continue;
            }

            crate::serial_println!("HDA: Audio Function Group at NID {}", fg);

            // Power on the function group.
            let _ = self.send_verb(0, fg, VERB_SET_POWER_STATE | 0x00);

            // Read subordinate widgets of this function group.
            let wid_sub =
                self.send_verb(0, fg, VERB_GET_PARAMETER | PARAM_SUBNODE_COUNT)?;
            let w_start = ((wid_sub >> 16) & 0xFF) as u8;
            let w_count = (wid_sub & 0xFF) as u8;

            crate::serial_println!(
                "HDA: FG{}: widget start={} count={}",
                fg,
                w_start,
                w_count
            );

            for w in w_start..(w_start.saturating_add(w_count)) {
                let cap =
                    self.send_verb(0, w, VERB_GET_PARAMETER | PARAM_AUDIO_WIDGET_CAP)?;
                let wtype = ((cap >> 20) & 0x0F) as u8;

                match wtype {
                    WIDGET_TYPE_OUTPUT => {
                        if self.output_dac_nid == 0 {
                            self.output_dac_nid = w;
                            crate::serial_println!("HDA: found DAC at NID {}", w);
                        }
                    }
                    WIDGET_TYPE_INPUT => {
                        if self.input_adc_nid == 0 {
                            self.input_adc_nid = w;
                            crate::serial_println!("HDA: found ADC at NID {}", w);
                        }
                    }
                    WIDGET_TYPE_PIN => {
                        // Read default configuration to determine direction.
                        let cfg_default =
                            self.send_verb(0, w, VERB_GET_CONFIG_DEFAULT)?;
                        let default_device = (cfg_default >> 20) & 0x0F;

                        // Device types: 0=Line Out, 1=Speaker, 2=HP Out,
                        // 8=Line In, 0xA=Mic In
                        if self.output_pin_nid == 0
                            && (default_device == 0x0
                                || default_device == 0x1
                                || default_device == 0x2)
                        {
                            self.output_pin_nid = w;
                            crate::serial_println!(
                                "HDA: found output pin at NID {} (dev={:#X})",
                                w,
                                default_device
                            );
                        }

                        if self.input_pin_nid == 0
                            && (default_device == 0x8 || default_device == 0xA)
                        {
                            self.input_pin_nid = w;
                            crate::serial_println!(
                                "HDA: found input pin at NID {} (dev={:#X})",
                                w,
                                default_device
                            );
                        }

                        // If both are still 0 after checking device type,
                        // read pin capabilities to decide.
                        if self.output_pin_nid == 0 || self.input_pin_nid == 0 {
                            let pin_ctl =
                                self.send_verb(0, w, VERB_GET_PIN_CONTROL)?;
                            if self.output_pin_nid == 0 && (pin_ctl & 0x40) != 0 {
                                self.output_pin_nid = w;
                            }
                            if self.input_pin_nid == 0 && (pin_ctl & 0x20) != 0 {
                                self.input_pin_nid = w;
                            }
                        }
                    }
                    _ => {}
                }
            }
        }

        // QEMU hda-duplex defaults if discovery came up empty.
        if self.output_dac_nid == 0 {
            self.output_dac_nid = 2;
            crate::serial_println!("HDA: using default DAC NID 2");
        }
        if self.output_pin_nid == 0 {
            self.output_pin_nid = 3;
            crate::serial_println!("HDA: using default output pin NID 3");
        }
        if self.input_adc_nid == 0 {
            self.input_adc_nid = 4;
            crate::serial_println!("HDA: using default ADC NID 4");
        }
        if self.input_pin_nid == 0 {
            self.input_pin_nid = 5;
            crate::serial_println!("HDA: using default input pin NID 5");
        }

        crate::serial_println!(
            "HDA: codec topology â€” DAC={} pin_out={} ADC={} pin_in={}",
            self.output_dac_nid,
            self.output_pin_nid,
            self.input_adc_nid,
            self.input_pin_nid
        );

        Ok(())
    }

    // ========================================================================
    // Output Stream Setup
    // ========================================================================

    /// Populate the output BDL and program the output stream descriptor.
    fn setup_output_stream(&mut self) -> Result<(), &'static str> {
        // Stop the stream first (clear RUN bit).
        self.stop_stream(self.out_stream_base);

        // Fill BDL entries.
        let bdl_ptr = self.out_bdl_virt.as_u64() as *mut BdlEntry;
        for i in 0..BDL_ENTRY_COUNT {
            let entry = BdlEntry {
                address: self.out_buf_phys.as_u64() + (i as u64) * (AUDIO_BUF_CHUNK as u64),
                length: AUDIO_BUF_CHUNK as u32,
                ioc: if i == BDL_ENTRY_COUNT - 1 { 1 } else { 0 },
            };
            // Safety: bdl_ptr + i is within the allocated BDL page, and each
            // BdlEntry is 16 bytes.  4 entries = 64 bytes << 4096.
            unsafe {
                core::ptr::write_volatile(bdl_ptr.add(i), entry);
            }
        }

        let base = self.out_stream_base;

        // Set Cyclic Buffer Length (total bytes across all BDL entries).
        self.regs.write32(base + SD_CBL, self.out_buf_size);

        // Set Last Valid Index (number of BDL entries minus 1).
        self.regs
            .write16(base + SD_LVI, (BDL_ENTRY_COUNT - 1) as u16);

        // Set stream format (48 kHz / 16-bit / stereo).
        self.regs
            .write16(base + SD_FMT, STREAM_FORMAT_48K_16B_STEREO);

        // Set BDL lower and upper physical addresses.
        self.regs
            .write32(base + SD_BDLPL, self.out_bdl_phys.as_u64() as u32);
        self.regs
            .write32(base + SD_BDLPU, (self.out_bdl_phys.as_u64() >> 32) as u32);

        // Set stream number / channel in CTL bits [23:20] and [3:0].
        // Use stream tag 1 for the output stream, channel 0.
        let ctl_upper = 0x10u8; // stream tag 1 in bits [7:4] of byte 2
        self.regs.write8(base + SD_CTL + 2, ctl_upper);

        crate::serial_println!("HDA: output stream configured at SD base {:#X}", base);
        Ok(())
    }

    // ========================================================================
    // Input Stream Setup
    // ========================================================================

    /// Populate the input BDL and program the input stream descriptor.
    fn setup_input_stream(&mut self) -> Result<(), &'static str> {
        // Stop the stream first.
        self.stop_stream(self.in_stream_base);

        // Fill BDL entries.
        let bdl_ptr = self.in_bdl_virt.as_u64() as *mut BdlEntry;
        for i in 0..BDL_ENTRY_COUNT {
            let entry = BdlEntry {
                address: self.in_buf_phys.as_u64() + (i as u64) * (AUDIO_BUF_CHUNK as u64),
                length: AUDIO_BUF_CHUNK as u32,
                ioc: if i == BDL_ENTRY_COUNT - 1 { 1 } else { 0 },
            };
            // Safety: within BDL page bounds.
            unsafe {
                core::ptr::write_volatile(bdl_ptr.add(i), entry);
            }
        }

        let base = self.in_stream_base;

        self.regs.write32(base + SD_CBL, self.in_buf_size);
        self.regs
            .write16(base + SD_LVI, (BDL_ENTRY_COUNT - 1) as u16);
        self.regs
            .write16(base + SD_FMT, STREAM_FORMAT_48K_16B_STEREO);
        self.regs
            .write32(base + SD_BDLPL, self.in_bdl_phys.as_u64() as u32);
        self.regs
            .write32(base + SD_BDLPU, (self.in_bdl_phys.as_u64() >> 32) as u32);

        // Use stream tag 2 for the input stream.
        let ctl_upper = 0x20u8; // stream tag 2
        self.regs.write8(base + SD_CTL + 2, ctl_upper);

        crate::serial_println!("HDA: input stream configured at SD base {:#X}", base);
        Ok(())
    }

    // ========================================================================
    // Output Path Configuration
    // ========================================================================

    /// Configure the output path: DAC â†’ output pin.
    ///
    /// Sets stream format, stream/channel ID, enables the pin for output,
    /// and unmutes amplifiers along the path.
    fn configure_output_path(&mut self) -> Result<(), &'static str> {
        let dac = self.output_dac_nid;
        let pin = self.output_pin_nid;

        // Power on the DAC and output pin.
        let _ = self.send_verb(0, dac, VERB_SET_POWER_STATE | 0x00);
        let _ = self.send_verb(0, pin, VERB_SET_POWER_STATE | 0x00);

        // Set converter stream format on the DAC.
        let _ = self.send_verb(
            0,
            dac,
            VERB_SET_STREAM_FORMAT | (STREAM_FORMAT_48K_16B_STEREO as u32),
        );

        // Set converter stream/channel: stream tag 1, channel 0.
        // Bits [7:4] = stream tag, bits [3:0] = channel.
        let _ = self.send_verb(0, dac, VERB_SET_CHANNEL_STREAM | 0x10);

        // Unmute DAC output amplifier, set maximum gain.
        // SET_AMP_GAIN_MUTE: bit 15=output, bit 13=left, bit 12=right,
        // bits [6:0]=gain (0x7F = max).
        let _ = self.send_verb(0, dac, VERB_SET_AMP_GAIN_MUTE | 0xB07F);

        // Enable the output pin (bit 6=OUT enable).
        let _ = self.send_verb(0, pin, VERB_SET_PIN_CONTROL | 0x40);

        // Unmute the pin's output amplifier.
        let _ = self.send_verb(0, pin, VERB_SET_AMP_GAIN_MUTE | 0xB07F);

        // Try to set EAPD if supported (silently ignore errors).
        let _ = self.send_verb(0, pin, VERB_SET_EAPD | 0x02);

        crate::serial_println!(
            "HDA: output path configured (DAC {} â†’ pin {})",
            dac,
            pin
        );
        Ok(())
    }

    // ========================================================================
    // Input Path Configuration
    // ========================================================================

    /// Configure the input path: input pin â†’ ADC.
    fn configure_input_path(&mut self) -> Result<(), &'static str> {
        let adc = self.input_adc_nid;
        let pin = self.input_pin_nid;

        // Power on the ADC and input pin.
        let _ = self.send_verb(0, adc, VERB_SET_POWER_STATE | 0x00);
        let _ = self.send_verb(0, pin, VERB_SET_POWER_STATE | 0x00);

        // Set converter stream format on the ADC.
        let _ = self.send_verb(
            0,
            adc,
            VERB_SET_STREAM_FORMAT | (STREAM_FORMAT_48K_16B_STEREO as u32),
        );

        // Set converter stream/channel: stream tag 2, channel 0.
        let _ = self.send_verb(0, adc, VERB_SET_CHANNEL_STREAM | 0x20);

        // Unmute ADC input amplifier, set max gain.
        // bit 14=input, bit 13=left, bit 12=right, gain=0x7F.
        let _ = self.send_verb(0, adc, VERB_SET_AMP_GAIN_MUTE | 0x707F);

        // Enable the input pin (bit 5=IN enable).
        let _ = self.send_verb(0, pin, VERB_SET_PIN_CONTROL | 0x20);

        // Unmute pin input amplifier.
        let _ = self.send_verb(0, pin, VERB_SET_AMP_GAIN_MUTE | 0x707F);

        crate::serial_println!(
            "HDA: input path configured (pin {} â†’ ADC {})",
            pin,
            adc
        );
        Ok(())
    }

    // ========================================================================
    // Stream Start / Stop Helpers
    // ========================================================================

    /// Start the stream at the given SD base (set RUN bit 1 in SD_CTL).
    fn start_stream(&self, sd_base: u32) {
        // Clear status bits first.
        self.regs.write8(sd_base + SD_STS, 0x1C);

        // Read the existing CTL value (3 bytes, but we use the low 2).
        let ctl = self.regs.read8(sd_base + SD_CTL);
        // Set bit 1 (RUN) and bit 2 (IRQ enable).
        self.regs.write8(sd_base + SD_CTL, ctl | 0x06);
        // Also ensure the DMA enable is set.
        let ctl_lo = self.regs.read8(sd_base + SD_CTL);
        self.regs.write8(sd_base + SD_CTL, ctl_lo | 0x02);
    }

    /// Stop the stream at the given SD base (clear RUN bit).
    fn stop_stream(&self, sd_base: u32) {
        let ctl = self.regs.read8(sd_base + SD_CTL);
        self.regs.write8(sd_base + SD_CTL, ctl & !0x02);

        // Wait for the stream to actually stop (bit 1 cleared in STS is
        // not guaranteed, so just spin briefly).
        spin_wait(1000);
    }

    /// Reset the stream descriptor (set SRST, wait, clear SRST).
    fn reset_stream(&self, sd_base: u32) {
        // Set stream reset bit (bit 0 of SD_CTL).
        self.regs.write8(sd_base + SD_CTL, 0x01);
        spin_wait(1000);
        for _ in 0..POLL_TIMEOUT {
            if (self.regs.read8(sd_base + SD_CTL) & 0x01) != 0 {
                break;
            }
            core::hint::spin_loop();
        }

        // Clear stream reset.
        self.regs.write8(sd_base + SD_CTL, 0x00);
        spin_wait(1000);
        for _ in 0..POLL_TIMEOUT {
            if (self.regs.read8(sd_base + SD_CTL) & 0x01) == 0 {
                break;
            }
            core::hint::spin_loop();
        }
    }

    // ========================================================================
    // Playback
    // ========================================================================

    /// Copy `data` into the output DMA buffers and start the output stream.
    ///
    /// If `data` is larger than the total buffer (16 KiB), only the first
    /// 16 KiB is used.  If smaller, the remaining buffer is zero-filled
    /// (silence).
    fn play(&mut self, data: &[u8]) -> Result<(), &'static str> {
        // Stop any running playback first.
        self.stop_stream(self.out_stream_base);

        let copy_len = core::cmp::min(data.len(), self.out_buf_size as usize);
        let buf_ptr = self.out_buf_virt.as_u64() as *mut u8;

        // Safety: buf_ptr is within the contiguous DMA buffer we allocated.
        unsafe {
            core::ptr::copy_nonoverlapping(data.as_ptr(), buf_ptr, copy_len);
            // Zero-fill remainder.
            if copy_len < self.out_buf_size as usize {
                core::ptr::write_bytes(
                    buf_ptr.add(copy_len),
                    0,
                    self.out_buf_size as usize - copy_len,
                );
            }
        }

        // Ensure the stream is properly reset before starting.
        self.reset_stream(self.out_stream_base);

        // Re-program stream descriptor after reset.
        self.setup_output_stream()?;

        // Re-configure the converter to point at our stream tag.
        let _ = self.send_verb(
            0,
            self.output_dac_nid,
            VERB_SET_CHANNEL_STREAM | 0x10,
        );
        let _ = self.send_verb(
            0,
            self.output_dac_nid,
            VERB_SET_STREAM_FORMAT | (STREAM_FORMAT_48K_16B_STEREO as u32),
        );

        // Start the stream.
        self.start_stream(self.out_stream_base);

        crate::serial_println!("HDA: playback started ({} bytes)", copy_len);
        Ok(())
    }

    // ========================================================================
    // Recording
    // ========================================================================

    /// Start recording into the input DMA buffers and copy captured data
    /// into `buf`.
    ///
    /// Returns the number of bytes actually captured (capped at buffer
    /// size and `buf.len()`).
    fn record(&mut self, buf: &mut [u8]) -> Result<usize, &'static str> {
        // Stop any running capture.
        self.stop_stream(self.in_stream_base);

        // Zero the input buffer.
        let in_ptr = self.in_buf_virt.as_u64() as *mut u8;
        // Safety: in_ptr spans our contiguous DMA buffer.
        unsafe {
            core::ptr::write_bytes(in_ptr, 0, self.in_buf_size as usize);
        }

        // Reset and re-program the input stream.
        self.reset_stream(self.in_stream_base);
        self.setup_input_stream()?;

        // Re-configure the ADC converter.
        let _ = self.send_verb(
            0,
            self.input_adc_nid,
            VERB_SET_CHANNEL_STREAM | 0x20,
        );
        let _ = self.send_verb(
            0,
            self.input_adc_nid,
            VERB_SET_STREAM_FORMAT | (STREAM_FORMAT_48K_16B_STEREO as u32),
        );

        // Start recording.
        self.start_stream(self.in_stream_base);

        // Wait for the stream to run through the buffer once.
        // Poll LPIB until it reaches the end or we time out.
        let target = self.in_buf_size;
        for _ in 0..POLL_TIMEOUT {
            let lpib = self.regs.read32(self.in_stream_base + SD_LPIB);
            if lpib >= target {
                break;
            }
            // Also check if the buffer completed status is set (bit 2).
            let sts = self.regs.read8(self.in_stream_base + SD_STS);
            if (sts & 0x04) != 0 {
                break;
            }
            core::hint::spin_loop();
        }

        // Stop the stream.
        self.stop_stream(self.in_stream_base);

        // Copy captured data to the caller's buffer.
        let copy_len = core::cmp::min(buf.len(), self.in_buf_size as usize);
        // Safety: in_ptr + copy_len is within DMA buffer bounds.
        unsafe {
            core::ptr::copy_nonoverlapping(in_ptr, buf.as_mut_ptr(), copy_len);
        }

        crate::serial_println!("HDA: recorded {} bytes", copy_len);
        Ok(copy_len)
    }

    // ========================================================================
    // Volume Control
    // ========================================================================

    /// Set the output volume (0â€“127) via the DAC's output amplifier gain.
    fn set_vol(&mut self, level: u8) {
        let gain = (level & 0x7F) as u32;
        // SET_AMP_GAIN_MUTE: output amp, left+right, gain value.
        let _ = self.send_verb(
            0,
            self.output_dac_nid,
            VERB_SET_AMP_GAIN_MUTE | 0xB000 | gain,
        );
        // Also set on the pin for good measure.
        let _ = self.send_verb(
            0,
            self.output_pin_nid,
            VERB_SET_AMP_GAIN_MUTE | 0xB000 | gain,
        );
    }
}

// ============================================================================
// Public API (free functions operating on the global HDA mutex)
// ============================================================================

/// Copy `data` into the output audio buffers and start playback.
///
/// The data should be raw PCM: 48 kHz, 16-bit signed, stereo (interleaved
/// L/R).  Up to 16 KiB is accepted per call.
pub fn play_buffer(data: &[u8]) -> Result<(), &'static str> {
    let mut guard = HDA.lock();
    let ctrl = guard.as_mut().ok_or("HDA: not initialised")?;
    ctrl.play(data)
}

/// Stop playback on the output stream.
pub fn stop_playback() {
    let guard = HDA.lock();
    if let Some(ref ctrl) = *guard {
        ctrl.stop_stream(ctrl.out_stream_base);
    }
}

/// Start recording and copy captured PCM data into `buf`.
///
/// Returns the number of bytes captured.
pub fn record_buffer(buf: &mut [u8]) -> Result<usize, &'static str> {
    let mut guard = HDA.lock();
    let ctrl = guard.as_mut().ok_or("HDA: not initialised")?;
    ctrl.record(buf)
}

/// Stop recording on the input stream.
pub fn stop_recording() {
    let guard = HDA.lock();
    if let Some(ref ctrl) = *guard {
        ctrl.stop_stream(ctrl.in_stream_base);
    }
}

/// Set the output volume level (0 = silent, 127 = maximum).
pub fn set_volume(level: u8) {
    let mut guard = HDA.lock();
    if let Some(ref mut ctrl) = *guard {
        ctrl.set_vol(level);
    }
}

/// Returns `true` if the HDA controller was successfully initialised.
pub fn is_available() -> bool {
    HDA.lock().is_some()
}
