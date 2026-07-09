// ============================================================================
// FerrumOS - VirtIO-GPU 2D Driver
// ============================================================================
// Hardware-mediated 2D present path, additive only: when a virtio-gpu-pci
// device is present, the compositor's frame present goes through this
// driver's resource/transfer/flush command set instead of the existing
// raw Bochs-VBE MMIO framebuffer copy (src/devices/vga_fb.rs, untouched
// and still the fallback whenever this device isn't found).
//
// Scoped to 2D only (no virgl/3D) - this is genuinely the only kind of
// "hardware acceleration" available given the display devices QEMU
// actually exposes here. Bochs VBE (the existing path) is a bare linear
// framebuffer with no blit/fill engine at all; virtio-gpu's real
// contribution is that pixel delivery to the display becomes a command
// the (virtual) GPU executes - RESOURCE_CREATE_2D/ATTACH_BACKING once at
// setup, then TRANSFER_TO_HOST_2D + RESOURCE_FLUSH per frame - instead of
// the CPU synchronously writing every byte of a fixed MMIO region itself.
//
// Deliberately simple, polling-based (no MSI-X/interrupts), matching this
// codebase's existing ATA PIO driver precedent: only ever one command in
// flight, always reusing the same two descriptor slots, synchronously
// waiting for the used ring to advance. Throughput isn't a concern for a
// boot-time-setup-plus-occasional-present driver.
// ============================================================================

extern crate alloc;

use crate::devices::pci;
use crate::memory::{allocate_contiguous_frames, phys_to_virt};
use spin::Mutex;
use x86_64::PhysAddr;

const VIRTIO_VENDOR_ID: u16 = 0x1af4;
/// Modern virtio-gpu-pci device id (0x1040 + virtio device type 16).
const VIRTIO_GPU_DEVICE_ID: u16 = 0x1050;

const PCI_CAP_ID_VENDOR: u8 = 0x09;
const PCI_CAP_LIST_POINTER: u8 = 0x34;
const PCI_STATUS: u8 = 0x06;
const PCI_STATUS_CAP_LIST: u16 = 0x10;

const VIRTIO_PCI_CAP_COMMON_CFG: u8 = 1;
const VIRTIO_PCI_CAP_NOTIFY_CFG: u8 = 2;
const VIRTIO_PCI_CAP_DEVICE_CFG: u8 = 4;

const STATUS_ACKNOWLEDGE: u8 = 1;
const STATUS_DRIVER: u8 = 2;
const STATUS_DRIVER_OK: u8 = 4;
const STATUS_FEATURES_OK: u8 = 8;

const VIRTIO_F_VERSION_1: u32 = 1 << (32 - 32); // bit 32, i.e. bit 0 of the high feature word

const GPU_CMD_GET_DISPLAY_INFO: u32 = 0x0100;
const GPU_CMD_RESOURCE_CREATE_2D: u32 = 0x0101;
const GPU_CMD_SET_SCANOUT: u32 = 0x0103;
const GPU_CMD_RESOURCE_FLUSH: u32 = 0x0104;
const GPU_CMD_TRANSFER_TO_HOST_2D: u32 = 0x0105;
const GPU_CMD_RESOURCE_ATTACH_BACKING: u32 = 0x0106;
const GPU_RESP_OK_NODATA: u32 = 0x1100;
/// B8G8R8X8 - matches this codebase's existing pixel convention
/// (`(r << 16) | (g << 8) | b` packed into a little-endian u32, i.e.
/// byte order B,G,R,X in memory - see src/gui/desktop.rs / app_window.rs).
const FORMAT_B8G8R8X8_UNORM: u32 = 2;

const QUEUE_CONTROL: u16 = 0;

/// One page each for the descriptor table / available ring / used ring -
/// wasteful but simple, and each allocation's 4KB alignment comfortably
/// exceeds the spec's actual alignment requirements (16/2/4 bytes) for
/// any realistic queue size this device reports.
struct VirtQueue {
    desc: *mut u8,
    avail: *mut u8,
    used: *mut u8,
    size: u16,
    notify_addr: *mut u16,
    /// Next used-ring index we expect the device to produce.
    next_used_idx: u16,
}
unsafe impl Send for VirtQueue {}

struct CommonCfg {
    base: *mut u8,
}
unsafe impl Send for CommonCfg {}

impl CommonCfg {
    unsafe fn write_u32(&self, offset: usize, val: u32) {
        core::ptr::write_volatile(self.base.add(offset) as *mut u32, val);
    }
    unsafe fn read_u32(&self, offset: usize) -> u32 {
        core::ptr::read_volatile(self.base.add(offset) as *const u32)
    }
    unsafe fn write_u16(&self, offset: usize, val: u16) {
        core::ptr::write_volatile(self.base.add(offset) as *mut u16, val);
    }
    unsafe fn read_u16(&self, offset: usize) -> u16 {
        core::ptr::read_volatile(self.base.add(offset) as *const u16)
    }
    unsafe fn write_u8(&self, offset: usize, val: u8) {
        core::ptr::write_volatile(self.base.add(offset), val);
    }
    unsafe fn read_u8(&self, offset: usize) -> u8 {
        core::ptr::read_volatile(self.base.add(offset))
    }
    unsafe fn write_u64(&self, offset: usize, val: u64) {
        core::ptr::write_volatile(self.base.add(offset) as *mut u64, val);
    }
}

struct Device {
    /// Kept for potential future device-status re-checks (e.g. detecting
    /// DEVICE_NEEDS_RESET); not read again after `init()` today.
    #[allow(dead_code)]
    common: CommonCfg,
    controlq: VirtQueue,
    /// Scratch DMA buffers reused for every command's request/response -
    /// only one command is ever in flight.
    req_buf: *mut u8,
    resp_buf: *mut u8,
    /// The framebuffer's backing store, attached to resource 1 once at
    /// setup - present() copies composited pixels in here before every
    /// transfer/flush.
    backing: *mut u8,
    backing_phys: u64,
    width: u32,
    height: u32,
}
unsafe impl Send for Device {}

static DEVICE: Mutex<Option<Device>> = Mutex::new(None);

fn alloc_dma_pages(pages: usize) -> (u64, *mut u8) {
    let frame = allocate_contiguous_frames(pages).expect("virtio-gpu: out of DMA memory");
    let phys = frame.start_address();
    let virt = phys_to_virt(phys);
    let ptr = virt.as_u64() as *mut u8;
    unsafe { core::ptr::write_bytes(ptr, 0, pages * 4096) };
    (phys.as_u64(), ptr)
}

/// Walks the PCI capability list looking for the vendor-specific virtio
/// capability structures, returning (bar_index, bar_offset, notify_off_multiplier)
/// for the requested cfg_type. notify_off_multiplier is only meaningful
/// (and only read) for VIRTIO_PCI_CAP_NOTIFY_CFG.
fn find_virtio_cap(dev: pci::PciDevice, cfg_type: u8) -> Option<(u8, u32, u32)> {
    let status = pci::read_config_u16(dev.bus, dev.slot, dev.func, PCI_STATUS);
    if status & PCI_STATUS_CAP_LIST == 0 {
        return None;
    }
    let mut ptr = pci::read_config_u8(dev.bus, dev.slot, dev.func, PCI_CAP_LIST_POINTER) & 0xFC;
    let mut guard = 0;
    while ptr != 0 && guard < 64 {
        guard += 1;
        let cap_id = pci::read_config_u8(dev.bus, dev.slot, dev.func, ptr);
        let next = pci::read_config_u8(dev.bus, dev.slot, dev.func, ptr + 1);
        if cap_id == PCI_CAP_ID_VENDOR {
            let this_type = pci::read_config_u8(dev.bus, dev.slot, dev.func, ptr + 3);
            if this_type == cfg_type {
                let bar = pci::read_config_u8(dev.bus, dev.slot, dev.func, ptr + 4);
                let offset = pci::read_config_u32(dev.bus, dev.slot, dev.func, ptr + 8);
                let multiplier = if cfg_type == VIRTIO_PCI_CAP_NOTIFY_CFG {
                    pci::read_config_u32(dev.bus, dev.slot, dev.func, ptr + 16)
                } else {
                    0
                };
                return Some((bar, offset, multiplier));
            }
        }
        ptr = next & 0xFC;
    }
    None
}

fn bar_virt_addr(dev: pci::PciDevice, bar_index: u8) -> Option<u64> {
    let bar_offset = 0x10 + (bar_index as u8) * 4;
    let lo = pci::read_config_u32(dev.bus, dev.slot, dev.func, bar_offset);
    if lo & 0x1 == 1 {
        return None; // I/O space bar, not expected for a modern virtio device
    }
    let is_64bit = (lo & 0x6) == 0x4;
    let hi = if is_64bit {
        pci::read_config_u32(dev.bus, dev.slot, dev.func, bar_offset + 4)
    } else {
        0
    };
    let phys = ((hi as u64) << 32) | ((lo & !0xF) as u64);
    if phys == 0 {
        return None;
    }
    Some(phys_to_virt(PhysAddr::new(phys)).as_u64())
}

/// Enables PCI bus mastering (required for the device to DMA from guest
/// memory) and memory-space decoding, via the standard PCI command register.
fn enable_bus_master(dev: pci::PciDevice) {
    let cmd = pci::read_config_u32(dev.bus, dev.slot, dev.func, 0x04);
    pci::write_config_u32(dev.bus, dev.slot, dev.func, 0x04, cmd | 0x4 | 0x2);
}

pub fn init() -> Result<(), &'static str> {
    let pci_dev = pci::find_device(VIRTIO_VENDOR_ID, VIRTIO_GPU_DEVICE_ID)
        .ok_or("virtio-gpu: device not found on PCI bus")?;
    enable_bus_master(pci_dev);

    let (common_bar, common_off, _) =
        find_virtio_cap(pci_dev, VIRTIO_PCI_CAP_COMMON_CFG).ok_or("virtio-gpu: no COMMON_CFG capability")?;
    let (notify_bar, notify_off, notify_mult) =
        find_virtio_cap(pci_dev, VIRTIO_PCI_CAP_NOTIFY_CFG).ok_or("virtio-gpu: no NOTIFY_CFG capability")?;
    // DEVICE_CFG (display geometry) exists but isn't read here - the
    // scanout size is driven by whatever the compositor already renders
    // at (matching src/devices/vga_fb.rs's fixed 1024x768), not queried
    // from the device.
    let _ = find_virtio_cap(pci_dev, VIRTIO_PCI_CAP_DEVICE_CFG);

    let common_base = bar_virt_addr(pci_dev, common_bar).ok_or("virtio-gpu: COMMON_CFG bar not memory-mapped")? + common_off as u64;
    let notify_base = bar_virt_addr(pci_dev, notify_bar).ok_or("virtio-gpu: NOTIFY_CFG bar not memory-mapped")? + notify_off as u64;
    let common = CommonCfg { base: common_base as *mut u8 };

    unsafe {
        // Standard virtio 1.0 device initialization sequence.
        common.write_u8(20, 0); // device_status = 0 (reset)
        common.write_u8(20, STATUS_ACKNOWLEDGE);
        common.write_u8(20, STATUS_ACKNOWLEDGE | STATUS_DRIVER);

        // Feature negotiation: only ever accept VIRTIO_F_VERSION_1 (bit
        // 32, the high feature word) - 2D commands need nothing else.
        common.write_u32(0, 1); // device_feature_select = high word
        let hi = common.read_u32(4);
        common.write_u32(8, 1); // driver_feature_select = high word
        common.write_u32(12, hi & VIRTIO_F_VERSION_1);
        common.write_u32(8, 0); // driver_feature_select = low word
        common.write_u32(12, 0);

        common.write_u8(20, STATUS_ACKNOWLEDGE | STATUS_DRIVER | STATUS_FEATURES_OK);
        let status = common.read_u8(20);
        if status & STATUS_FEATURES_OK == 0 {
            return Err("virtio-gpu: device rejected feature negotiation");
        }

        // Queue 0 (controlq) setup.
        common.write_u16(22, QUEUE_CONTROL);
        let qsize = common.read_u16(24);
        if qsize == 0 {
            return Err("virtio-gpu: controlq size is zero");
        }

        let (desc_phys, desc_virt) = alloc_dma_pages(1);
        let (avail_phys, avail_virt) = alloc_dma_pages(1);
        let (used_phys, used_virt) = alloc_dma_pages(1);

        common.write_u64(32, desc_phys);
        common.write_u64(40, avail_phys);
        common.write_u64(48, used_phys);
        common.write_u16(28, 1); // queue_enable

        let queue_notify_off = common.read_u16(30);
        let notify_addr = (notify_base + (queue_notify_off as u64) * (notify_mult as u64)) as *mut u16;

        common.write_u8(20, STATUS_ACKNOWLEDGE | STATUS_DRIVER | STATUS_FEATURES_OK | STATUS_DRIVER_OK);

        let (_, req_buf) = alloc_dma_pages(1);
        let (_, resp_buf) = alloc_dma_pages(1);
        let (backing_phys, backing) = alloc_dma_pages(256); // up to 1MB backing (1024x768x4 fits in ~192 pages)

        let controlq = VirtQueue {
            desc: desc_virt,
            avail: avail_virt,
            used: used_virt,
            size: qsize,
            notify_addr,
            next_used_idx: 0,
        };

        *DEVICE.lock() = Some(Device {
            common,
            controlq,
            req_buf,
            resp_buf,
            backing,
            backing_phys,
            width: 0,
            height: 0,
        });
    }

    crate::serial_println!("[  OK  ] VirtIO-GPU 2D device initialized (bus={} slot={})", pci_dev.bus, pci_dev.slot);
    Ok(())
}

/// Submits one request/response command pair and blocks (polling) until
/// the device completes it. Always reuses descriptor slots 0/1 and
/// avail/used index 0-relative counters - only one command is ever
/// outstanding, so there's no concurrent-chain bookkeeping to get wrong.
unsafe fn send_sync(device: &mut Device, req: &[u8], resp_len: usize) -> alloc::vec::Vec<u8> {
    core::ptr::copy_nonoverlapping(req.as_ptr(), device.req_buf, req.len());

    let q = &mut device.controlq;
    let desc_req = q.desc as *mut [u8; 16];
    let write_desc = |slot: u16, addr: u64, len: u32, flags: u16, next: u16| {
        let base = (q.desc as *mut u8).add(slot as usize * 16);
        core::ptr::write_volatile(base as *mut u64, addr);
        core::ptr::write_volatile(base.add(8) as *mut u32, len);
        core::ptr::write_volatile(base.add(12) as *mut u16, flags);
        core::ptr::write_volatile(base.add(14) as *mut u16, next);
    };
    let _ = desc_req;

    // Physical addresses for the scratch buffers: recomputed from the
    // virtual pointer each call is unnecessary since these never move -
    // stash them at init time instead. For simplicity here, re-derive via
    // the frame allocator's identity offset (phys_to_virt is an additive
    // offset, so virt - offset = phys).
    let req_phys = crate::memory::virt_to_phys_offset(device.req_buf as u64);
    let resp_phys = crate::memory::virt_to_phys_offset(device.resp_buf as u64);

    const DESC_F_NEXT: u16 = 1;
    const DESC_F_WRITE: u16 = 2;
    write_desc(0, req_phys, req.len() as u32, DESC_F_NEXT, 1);
    write_desc(1, resp_phys, resp_len as u32, DESC_F_WRITE, 0);

    // Publish descriptor chain 0 in the avail ring.
    let avail_idx_ptr = q.avail.add(2) as *mut u16; // avail.idx
    let cur_avail_idx = core::ptr::read_volatile(avail_idx_ptr);
    let ring_slot = q.avail.add(4 + (cur_avail_idx as usize % q.size as usize) * 2) as *mut u16;
    core::ptr::write_volatile(ring_slot, 0);
    core::sync::atomic::fence(core::sync::atomic::Ordering::SeqCst);
    core::ptr::write_volatile(avail_idx_ptr, cur_avail_idx.wrapping_add(1));
    core::sync::atomic::fence(core::sync::atomic::Ordering::SeqCst);

    // Notify the device.
    core::ptr::write_volatile(q.notify_addr, QUEUE_CONTROL);

    // Poll the used ring until it produces our entry.
    let used_idx_ptr = q.used.add(2) as *const u16;
    let target = q.next_used_idx.wrapping_add(1);
    let mut spins: u64 = 0;
    while core::ptr::read_volatile(used_idx_ptr) != target {
        core::hint::spin_loop();
        spins += 1;
        if spins > 200_000_000 {
            break; // avoid a true infinite loop if the device never responds
        }
    }
    q.next_used_idx = target;

    let mut out = alloc::vec![0u8; resp_len];
    core::ptr::copy_nonoverlapping(device.resp_buf, out.as_mut_ptr(), resp_len);
    out
}

fn write_ctrl_hdr(buf: &mut alloc::vec::Vec<u8>, cmd_type: u32) {
    buf.extend_from_slice(&cmd_type.to_le_bytes());
    buf.extend_from_slice(&0u32.to_le_bytes()); // flags
    buf.extend_from_slice(&0u64.to_le_bytes()); // fence_id
    buf.extend_from_slice(&0u32.to_le_bytes()); // ctx_id
    buf.extend_from_slice(&0u32.to_le_bytes()); // padding
}

fn resp_type(resp: &[u8]) -> u32 {
    u32::from_le_bytes([resp[0], resp[1], resp[2], resp[3]])
}

pub fn is_available() -> bool {
    DEVICE.lock().is_some()
}

/// Sets up resource 1 as the scanout's backing framebuffer. Called once,
/// the first time `present()` runs with a new width/height.
fn setup_scanout(device: &mut Device, width: u32, height: u32) -> Result<(), &'static str> {
    unsafe {
        let mut req = alloc::vec::Vec::with_capacity(40);
        write_ctrl_hdr(&mut req, GPU_CMD_RESOURCE_CREATE_2D);
        req.extend_from_slice(&1u32.to_le_bytes()); // resource_id = 1
        req.extend_from_slice(&FORMAT_B8G8R8X8_UNORM.to_le_bytes());
        req.extend_from_slice(&width.to_le_bytes());
        req.extend_from_slice(&height.to_le_bytes());
        let resp = send_sync(device, &req, 24);
        if resp_type(&resp) != GPU_RESP_OK_NODATA {
            return Err("virtio-gpu: RESOURCE_CREATE_2D failed");
        }

        let mut req = alloc::vec::Vec::with_capacity(48);
        write_ctrl_hdr(&mut req, GPU_CMD_RESOURCE_ATTACH_BACKING);
        req.extend_from_slice(&1u32.to_le_bytes()); // resource_id
        req.extend_from_slice(&1u32.to_le_bytes()); // nr_entries
        req.extend_from_slice(&device.backing_phys.to_le_bytes());
        req.extend_from_slice(&((width * height * 4) as u32).to_le_bytes());
        req.extend_from_slice(&0u32.to_le_bytes()); // padding
        let resp = send_sync(device, &req, 24);
        if resp_type(&resp) != GPU_RESP_OK_NODATA {
            return Err("virtio-gpu: RESOURCE_ATTACH_BACKING failed");
        }

        let mut req = alloc::vec::Vec::with_capacity(48);
        write_ctrl_hdr(&mut req, GPU_CMD_SET_SCANOUT);
        req.extend_from_slice(&0u32.to_le_bytes()); // rect.x
        req.extend_from_slice(&0u32.to_le_bytes()); // rect.y
        req.extend_from_slice(&width.to_le_bytes());
        req.extend_from_slice(&height.to_le_bytes());
        req.extend_from_slice(&0u32.to_le_bytes()); // scanout_id
        req.extend_from_slice(&1u32.to_le_bytes()); // resource_id
        let resp = send_sync(device, &req, 24);
        if resp_type(&resp) != GPU_RESP_OK_NODATA {
            return Err("virtio-gpu: SET_SCANOUT failed");
        }
    }
    device.width = width;
    device.height = height;
    Ok(())
}

/// Presents a fully-composited frame. `pixels` must be `width * height`
/// u32s in the same B8G8R8X8 packing the rest of the GUI stack already
/// uses. Transfers and flushes the whole frame every call - a per-frame
/// dirty-rect (rows only, since TRANSFER_TO_HOST_2D's linear offset
/// only cleanly addresses whole-row spans without a multi-entry
/// scatter-gather list) is a natural follow-up, not implemented here.
pub fn present(pixels: &[u32], width: u32, height: u32) -> Result<(), &'static str> {
    let mut guard = DEVICE.lock();
    let device = guard.as_mut().ok_or("virtio-gpu: not initialized")?;

    if device.width != width || device.height != height {
        setup_scanout(device, width, height)?;
    }

    let byte_len = (width as usize) * (height as usize) * 4;
    unsafe {
        core::ptr::copy_nonoverlapping(pixels.as_ptr() as *const u8, device.backing, byte_len);

        let mut req = alloc::vec::Vec::with_capacity(56);
        write_ctrl_hdr(&mut req, GPU_CMD_TRANSFER_TO_HOST_2D);
        req.extend_from_slice(&0u32.to_le_bytes());
        req.extend_from_slice(&0u32.to_le_bytes());
        req.extend_from_slice(&width.to_le_bytes());
        req.extend_from_slice(&height.to_le_bytes());
        req.extend_from_slice(&0u64.to_le_bytes()); // offset
        req.extend_from_slice(&1u32.to_le_bytes()); // resource_id
        req.extend_from_slice(&0u32.to_le_bytes()); // padding
        let resp = send_sync(device, &req, 24);
        if resp_type(&resp) != GPU_RESP_OK_NODATA {
            return Err("virtio-gpu: TRANSFER_TO_HOST_2D failed");
        }

        let mut req = alloc::vec::Vec::with_capacity(48);
        write_ctrl_hdr(&mut req, GPU_CMD_RESOURCE_FLUSH);
        req.extend_from_slice(&0u32.to_le_bytes());
        req.extend_from_slice(&0u32.to_le_bytes());
        req.extend_from_slice(&width.to_le_bytes());
        req.extend_from_slice(&height.to_le_bytes());
        req.extend_from_slice(&1u32.to_le_bytes()); // resource_id
        req.extend_from_slice(&0u32.to_le_bytes()); // padding
        let resp = send_sync(device, &req, 24);
        if resp_type(&resp) != GPU_RESP_OK_NODATA {
            return Err("virtio-gpu: RESOURCE_FLUSH failed");
        }
    }

    Ok(())
}

/// Unused today (GET_DISPLAY_INFO would let the driver discover scanout
/// geometry from the device instead of matching vga_fb's fixed
/// 1024x768) - kept as a documented, real command the protocol
/// implementation supports, not a stub.
#[allow(dead_code)]
pub fn get_display_info() -> Result<(u32, u32), &'static str> {
    let mut guard = DEVICE.lock();
    let device = guard.as_mut().ok_or("virtio-gpu: not initialized")?;
    unsafe {
        let mut req = alloc::vec::Vec::with_capacity(24);
        write_ctrl_hdr(&mut req, GPU_CMD_GET_DISPLAY_INFO);
        // Response is virtio_gpu_resp_display_info: hdr(24) + 16 pmodes
        // of {rect(16), enabled(4), flags(4)} = 24 bytes each = 24 + 384.
        let resp = send_sync(device, &req, 24 + 24);
        let width = u32::from_le_bytes([resp[32], resp[33], resp[34], resp[35]]);
        let height = u32::from_le_bytes([resp[36], resp[37], resp[38], resp[39]]);
        Ok((width, height))
    }
}
