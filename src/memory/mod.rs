// ============================================================================
// FerrumOS - Memory Management Subsystem
// ============================================================================
// Manages physical and virtual memory for the kernel.
//
// Components:
//   - Page table initialization and mapping
//   - Physical frame allocator (from bootloader memory map)
//   - Kernel heap allocator
//   - Global frame-allocation + phys->virt translation helpers used by the
//     per-process address space module (Phase 1.3) and the future ring-3
//     loader (Phase 1.4).
//
// The bootloader provides a physical memory offset that maps all physical
// memory into virtual address space, allowing us to walk page tables.
// ============================================================================

pub mod heap;

use bootloader::bootinfo::{MemoryMap, MemoryRegionType};
use spin::Mutex;
use x86_64::{
    PhysAddr, VirtAddr,
    structures::paging::{
        FrameAllocator, OffsetPageTable, PageTable, PhysFrame, Size4KiB,
    },
};

/// Initialize the page table mapper
///
/// # Safety
///
/// The caller must guarantee that the complete physical memory is mapped
/// to virtual memory at the passed `physical_memory_offset`. Also, this
/// function must only be called once to avoid aliasing `&mut` references.
pub unsafe fn init(physical_memory_offset: VirtAddr) -> OffsetPageTable<'static> {
    init_globals(physical_memory_offset);
    let level_4_table = active_level_4_table(physical_memory_offset);
    OffsetPageTable::new(level_4_table, physical_memory_offset)
}

// ============================================================================
// Global frame allocator + phys->virt translation
// ============================================================================

static PHYS_MEM_OFFSET: Mutex<Option<VirtAddr>> = Mutex::new(None);
static FRAME_ALLOCATOR: Mutex<Option<BootInfoFrameAllocator>> = Mutex::new(None);

/// Store the physical memory offset and frame allocator in process-global
/// statics so the per-process address space module (and any future module
/// that needs a frame after `main` returns) can allocate from the same
/// pool the kernel boot sequence used.
fn init_globals(physical_memory_offset: VirtAddr) {
    *PHYS_MEM_OFFSET.lock() = Some(physical_memory_offset);
}

/// Install a `BootInfoFrameAllocator` instance as the global frame
/// allocator that subsystems (heliox, userspace, Phase 1.3 per-process
/// address space, future NIC ring buffers, etc.) can use to obtain new
/// physical frames without needing to thread an allocator through every
/// call site.
///
/// # Safety
///
/// The caller must guarantee that the memory map is valid AND that the
/// passed allocator's `next` bump pointer is past every physical frame
/// the kernel has already consumed (heap, framebuffer, GDT, etc.).
/// Handing the global a fresh `BootInfoFrameAllocator::init(memory_map)`
/// here would rewind the bump pointer to 0 and cause the next
/// allocation to overwrite kernel-private memory; pass the same
/// instance the local code used, or call this *after* the heap.
pub unsafe fn install_global_frame_allocator(allocator: BootInfoFrameAllocator) {
    *FRAME_ALLOCATOR.lock() = Some(allocator);
}

/// Translate a physical address into the kernel's linear mapping of all
/// physical memory. Panics if `init_globals` has not been called yet.
pub fn phys_to_virt(addr: PhysAddr) -> VirtAddr {
    let offset = PHYS_MEM_OFFSET
        .lock()
        .expect("physical_memory_offset not initialised");
    VirtAddr::new(offset.as_u64() + addr.as_u64())
}

/// Inverse of `phys_to_virt`: recovers the physical address backing a
/// pointer already known to lie in the kernel's linear physical-memory
/// mapping (e.g. a DMA buffer obtained via `allocate_contiguous_frames`
/// + `phys_to_virt`), without needing to have stashed the physical
/// address separately at allocation time.
pub fn virt_to_phys_offset(virt: u64) -> u64 {
    let offset = PHYS_MEM_OFFSET
        .lock()
        .expect("physical_memory_offset not initialised");
    virt - offset.as_u64()
}

/// Return the physical address of the active P4 table (read from CR3).
pub fn active_p4_phys() -> PhysAddr {
    use x86_64::registers::control::Cr3;
    Cr3::read().0.start_address()
}

/// Return the active P4 frame (read from CR3). Used by the
/// per-process address space code when it needs a fallback "the
/// kernel's own L4" value (e.g. for safety paths in
/// `Process::enter_ring3`).
pub fn active_p4_frame() -> PhysFrame {
    use x86_64::registers::control::Cr3;
    Cr3::read().0
}

/// Allocate a single 4 KiB physical frame from the global allocator.
/// Returns `None` if the allocator is not installed or the memory map is
/// exhausted.
pub fn allocate_frame() -> Option<PhysFrame> {
    FRAME_ALLOCATOR.lock().as_mut()?.allocate_frame()
}

/// Allocate `count` physically contiguous 4 KiB frames suitable for DMA
/// buffers (CORB/RIRB rings, audio BDLs, etc.).
///
/// Returns the first frame of the contiguous block. The caller may use
/// frames `first .. first + count` (each offset by 4 KiB). Returns
/// `None` if the allocator is exhausted or the requested frames are
/// not contiguous (extremely unlikely with the bump allocator since
/// physical frames are handed out in order).
pub fn allocate_contiguous_frames(count: usize) -> Option<PhysFrame> {
    if count == 0 {
        return None;
    }
    let mut alloc = FRAME_ALLOCATOR.lock();
    let alloc = alloc.as_mut()?;

    let first = alloc.allocate_frame()?;
    let first_addr = first.start_address().as_u64();

    for i in 1..count {
        let frame = alloc.allocate_frame()?;
        let expected = first_addr + (i as u64) * 4096;
        if frame.start_address().as_u64() != expected {
            // Non-contiguous; return what we have (frames are leaked since
            // the bump allocator doesn't support deallocation anyway)
            return None;
        }
    }

    Some(first)
}

/// Return a previously-allocated frame to the global pool. The current
/// `BootInfoFrameAllocator` is a bump allocator and ignores returned
/// frames, but tracking the API keeps the call sites honest until the
/// allocator learns to recycle.
pub fn deallocate_frame(_frame: PhysFrame) {
    // No-op until the frame allocator grows a free list.
}

/// Returns a mutable reference to the active level 4 page table
///
/// # Safety
///
/// The caller must guarantee that the complete physical memory is mapped
/// to virtual memory at the passed `physical_memory_offset`. Also, this
/// function must only be called once to avoid aliasing `&mut` references.
unsafe fn active_level_4_table(physical_memory_offset: VirtAddr) -> &'static mut PageTable {
    let phys = active_p4_phys();
    let virt = physical_memory_offset + phys.as_u64();
    let page_table_ptr: *mut PageTable = virt.as_mut_ptr();

    &mut *page_table_ptr
}

// ============================================================================
// Boot Info Frame Allocator
// ============================================================================

/// Physical frame allocator that uses the bootloader's memory map
///
/// Iterates over the memory map to find usable physical frames.
/// This is a simple bump allocator - frames are never freed.
/// A more sophisticated allocator would be needed for a production kernel.
pub struct BootInfoFrameAllocator {
    memory_map: &'static MemoryMap,
    next: usize,
}

impl BootInfoFrameAllocator {
    /// Create a new frame allocator from the bootloader memory map
    ///
    /// # Safety
    ///
    /// The caller must guarantee that the passed memory map is valid.
    /// All frames marked as `USABLE` must be actually unused.
    pub unsafe fn init(memory_map: &'static MemoryMap) -> Self {
        BootInfoFrameAllocator {
            memory_map,
            next: 0,
        }
    }

    /// Returns an iterator over usable physical frames
    fn usable_frames(&self) -> impl Iterator<Item = PhysFrame> {
        // Get usable regions from memory map
        let regions = self.memory_map.iter();
        let usable_regions = regions
            .filter(|r| r.region_type == MemoryRegionType::Usable);

        // Map each region to its start address range
        let addr_ranges = usable_regions
            .map(|r| r.range.start_addr()..r.range.end_addr());

        // Transform to an iterator of frame start addresses
        let frame_addresses = addr_ranges
            .flat_map(|r| r.step_by(4096));

        // Create PhysFrame types from the start addresses
        frame_addresses.map(|addr| PhysFrame::containing_address(PhysAddr::new(addr)))
    }

    /// Number of frames already handed out.
    pub fn allocated(&self) -> usize {
        self.next
    }
}

unsafe impl FrameAllocator<Size4KiB> for BootInfoFrameAllocator {
    fn allocate_frame(&mut self) -> Option<PhysFrame<Size4KiB>> {
        let frame = self.usable_frames().nth(self.next);
        self.next += 1;
        frame
    }
}

// ============================================================================
// Memory Statistics
// ============================================================================

/// Get total usable physical memory in bytes
pub fn total_usable_memory(memory_map: &MemoryMap) -> u64 {
    memory_map
        .iter()
        .filter(|r| r.region_type == MemoryRegionType::Usable)
        .map(|r| r.range.end_addr() - r.range.start_addr())
        .sum()
}

/// Get the number of usable physical frames
pub fn usable_frame_count(memory_map: &MemoryMap) -> u64 {
    total_usable_memory(memory_map) / 4096
}
