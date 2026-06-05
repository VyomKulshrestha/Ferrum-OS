// ============================================================================
// FerrumOS - Bochs VBE Framebuffer Driver
// ============================================================================
// Controls the Bochs/QEMU VBE display adapter via I/O port registers.
// Provides a linear framebuffer (LFB) for pixel-level screen access.
//
// The Bochs VBE interface uses two I/O ports:
//   - Index register at 0x01CE (selects which VBE register to access)
//   - Data  register at 0x01CF (reads/writes the selected register)
//
// After mode-set the physical framebuffer is located via PCI BAR0 of
// the Bochs VGA device (vendor 0x1234, device 0x1111) and mapped into
// the kernel's virtual address space through the bootloader's identity
// mapping of physical memory.
// ============================================================================

extern crate alloc;

#[allow(dead_code)]

use spin::Mutex;
use x86_64::instructions::port::Port;
use x86_64::PhysAddr;

// ============================================================================
// VBE I/O Port Constants
// ============================================================================

const VBE_DISPI_IOPORT_INDEX: u16 = 0x01CE;
const VBE_DISPI_IOPORT_DATA: u16 = 0x01CF;

// VBE register indices
const VBE_DISPI_INDEX_ID: u16 = 0;
const VBE_DISPI_INDEX_XRES: u16 = 1;
const VBE_DISPI_INDEX_YRES: u16 = 2;
const VBE_DISPI_INDEX_BPP: u16 = 3;
const VBE_DISPI_INDEX_ENABLE: u16 = 4;

// VBE enable flags
const VBE_DISPI_DISABLED: u16 = 0x00;
const VBE_DISPI_ENABLED_LFB: u16 = 0x41; // bit 0 = enable, bit 6 = LFB

// Bochs VGA PCI identifiers
const BOCHS_VGA_VENDOR_ID: u16 = 0x1234;
const BOCHS_VGA_DEVICE_ID: u16 = 0x1111;

// PCI BAR0 config space offset
const PCI_BAR0_OFFSET: u8 = 0x10;

// ============================================================================
// Global Framebuffer
// ============================================================================

/// Global framebuffer instance, accessible from other kernel subsystems.
pub static FRAMEBUFFER: Mutex<Option<Framebuffer>> = Mutex::new(None);

// ============================================================================
// Framebuffer Struct
// ============================================================================

/// Represents a mapped linear framebuffer in 32-bit XRGB pixel format.
///
/// Each pixel is a `u32` laid out as `0x00RRGGBB`. The `base` pointer
/// refers to the start of the MMIO region mapped from the VGA adapter's
/// BAR0 into the kernel's virtual address space.
pub struct Framebuffer {
    /// Pointer to the first pixel (virtual address of the mapped LFB)
    pub base: *mut u32,
    /// Horizontal resolution in pixels
    pub width: u32,
    /// Vertical resolution in pixels
    pub height: u32,
    /// Pitch in pixels (pixels per scanline, equal to width for 32bpp)
    pub pitch: u32,
}

// Safety: The framebuffer is MMIO memory accessed through volatile ops
// behind a Mutex. Only one core can hold the lock at a time.
unsafe impl Send for Framebuffer {}
unsafe impl Sync for Framebuffer {}

// ============================================================================
// VBE Register Access
// ============================================================================

/// Read a 16-bit value from a Bochs VBE register.
///
/// # Safety
/// Performs raw port I/O. Must only be called when the Bochs VBE
/// adapter is present.
fn vbe_read(index: u16) -> u16 {
    unsafe {
        let mut index_port = Port::<u16>::new(VBE_DISPI_IOPORT_INDEX);
        let mut data_port = Port::<u16>::new(VBE_DISPI_IOPORT_DATA);
        index_port.write(index);
        data_port.read()
    }
}

/// Write a 16-bit value to a Bochs VBE register.
///
/// # Safety
/// Performs raw port I/O. Must only be called when the Bochs VBE
/// adapter is present.
fn vbe_write(index: u16, value: u16) {
    unsafe {
        let mut index_port = Port::<u16>::new(VBE_DISPI_IOPORT_INDEX);
        let mut data_port = Port::<u16>::new(VBE_DISPI_IOPORT_DATA);
        index_port.write(index);
        data_port.write(value);
    }
}

// ============================================================================
// Detection & Initialization
// ============================================================================

/// Detect whether a Bochs VBE display adapter is present.
///
/// Reads the VBE ID register (index 0) and checks for the well-known
/// Bochs signature range `0xB0C0..=0xB0C5`.
pub fn detect() -> bool {
    let id = vbe_read(VBE_DISPI_INDEX_ID);
    (0xB0C0..=0xB0C5).contains(&id)
}

/// Initialize the Bochs VBE adapter in LFB mode and return a `Framebuffer`.
///
/// 1. Disables the VBE adapter (register 4 = 0).
/// 2. Programs the requested resolution and 32-bit color depth.
/// 3. Re-enables VBE with the linear framebuffer flag.
/// 4. Discovers the framebuffer physical base from PCI BAR0.
/// 5. Converts to a kernel virtual address via `phys_to_virt`.
///
/// # Errors
///
/// Returns `Err` if the Bochs VBE adapter is not detected or the PCI
/// device cannot be found.
pub fn init(width: u32, height: u32) -> Result<Framebuffer, &'static str> {
    if !detect() {
        return Err("Bochs VBE adapter not detected");
    }

    // Step 1: Disable VBE while changing mode parameters
    vbe_write(VBE_DISPI_INDEX_ENABLE, VBE_DISPI_DISABLED);

    // Step 2: Set resolution and color depth
    vbe_write(VBE_DISPI_INDEX_XRES, width as u16);
    vbe_write(VBE_DISPI_INDEX_YRES, height as u16);
    vbe_write(VBE_DISPI_INDEX_BPP, 32);

    // Step 3: Enable VBE with linear framebuffer
    vbe_write(VBE_DISPI_INDEX_ENABLE, VBE_DISPI_ENABLED_LFB);

    // Step 4: Find the Bochs VGA PCI device and read BAR0
    let pci_dev = crate::devices::pci::find_device(BOCHS_VGA_VENDOR_ID, BOCHS_VGA_DEVICE_ID)
        .ok_or("Bochs VGA PCI device (1234:1111) not found")?;

    let bar0_raw = crate::devices::pci::read_config_u32(
        pci_dev.bus,
        pci_dev.slot,
        pci_dev.func,
        PCI_BAR0_OFFSET,
    );

    // Mask off lower 4 bits (MMIO type/prefetchable flags)
    let bar0_addr = (bar0_raw & !0xF) as u64;

    // Step 5: Map to virtual address space
    let virt = crate::memory::phys_to_virt(PhysAddr::new(bar0_addr));

    let fb = Framebuffer {
        // Safety: `virt` points to the MMIO linear framebuffer mapped
        // by the bootloader's physical memory identity mapping.
        // All accesses go through volatile operations.
        base: virt.as_u64() as *mut u32,
        width,
        height,
        pitch: width, // For 32bpp the pitch in pixels equals the width
    };

    Ok(fb)
}

// ============================================================================
// Framebuffer Drawing Primitives
// ============================================================================

impl Framebuffer {
    /// Write a single pixel at `(x, y)` with the given 0x00RRGGBB color.
    ///
    /// Out-of-bounds coordinates are silently ignored.
    #[inline]
    pub fn set_pixel(&self, x: u32, y: u32, color: u32) {
        if x >= self.width || y >= self.height {
            return;
        }
        let offset = (y * self.pitch + x) as isize;
        // Safety: bounds-checked above; the framebuffer region is large
        // enough for `width * height` pixels. Volatile write ensures the
        // store is not elided or reordered by the compiler.
        unsafe {
            core::ptr::write_volatile(self.base.offset(offset), color);
        }
    }

    /// Read a single pixel at `(x, y)`, returning its 0x00RRGGBB color.
    ///
    /// Out-of-bounds coordinates return 0 (black).
    #[inline]
    pub fn get_pixel(&self, x: u32, y: u32) -> u32 {
        if x >= self.width || y >= self.height {
            return 0;
        }
        let offset = (y * self.pitch + x) as isize;
        // Safety: bounds-checked above. Volatile read ensures we get
        // the actual framebuffer value, not a stale cached copy.
        unsafe { core::ptr::read_volatile(self.base.offset(offset)) }
    }

    /// Fill the entire screen with a uniform color.
    pub fn clear(&self, color: u32) {
        for y in 0..self.height {
            for x in 0..self.width {
                let offset = (y * self.pitch + x) as isize;
                // Safety: stays within `width * height` bounds.
                unsafe {
                    core::ptr::write_volatile(self.base.offset(offset), color);
                }
            }
        }
    }

    /// Draw a filled rectangle. Coordinates are clipped to screen bounds.
    pub fn draw_rect(&self, x: u32, y: u32, w: u32, h: u32, color: u32) {
        let x_end = core::cmp::min(x + w, self.width);
        let y_end = core::cmp::min(y + h, self.height);
        for row in y..y_end {
            for col in x..x_end {
                let offset = (row * self.pitch + col) as isize;
                // Safety: clamped to framebuffer bounds above.
                unsafe {
                    core::ptr::write_volatile(self.base.offset(offset), color);
                }
            }
        }
    }

    /// Scroll the screen up by `rows_px` pixel rows.
    ///
    /// Copies each row upward and fills the vacated bottom region with
    /// `bg_color`.
    pub fn scroll_up(&self, rows_px: u32, bg_color: u32) {
        if rows_px == 0 || rows_px >= self.height {
            if rows_px >= self.height {
                self.clear(bg_color);
            }
            return;
        }

        // Copy rows upward
        for y in 0..(self.height - rows_px) {
            for x in 0..self.width {
                let src = ((y + rows_px) * self.pitch + x) as isize;
                let dst = (y * self.pitch + x) as isize;
                // Safety: both source and destination are within the
                // framebuffer region since we iterate in-bounds.
                unsafe {
                    let pixel = core::ptr::read_volatile(self.base.offset(src));
                    core::ptr::write_volatile(self.base.offset(dst), pixel);
                }
            }
        }

        // Clear the bottom region
        for y in (self.height - rows_px)..self.height {
            for x in 0..self.width {
                let offset = (y * self.pitch + x) as isize;
                // Safety: within bounds.
                unsafe {
                    core::ptr::write_volatile(self.base.offset(offset), bg_color);
                }
            }
        }
    }
}
