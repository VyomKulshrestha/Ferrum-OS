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
use alloc::vec::Vec;
use spin::Mutex;
use x86_64::{
    PhysAddr, VirtAddr,
    structures::paging::{
        FrameAllocator, OffsetPageTable, PageSize, PageTable, PhysFrame, Size4KiB,
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
    let frame = FRAME_ALLOCATOR.lock().as_mut()?.allocate_frame()?;
    zero_frame(frame);
    Some(frame)
}

fn zero_frame(frame: PhysFrame) {
    let address = phys_to_virt(frame.start_address());
    unsafe { core::ptr::write_bytes(address.as_mut_ptr::<u8>(), 0, Size4KiB::SIZE as usize) };
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
    let mut allocator_guard = FRAME_ALLOCATOR.lock();
    let alloc = allocator_guard.as_mut()?;

    // DMA callers require true physical adjacency. Recycled frames are valid
    // for ordinary pages but may be scattered, so contiguous allocations use
    // only the still-monotonic fresh side of the allocator.
    let first = alloc.allocate_fresh_frame()?;
    let first_addr = first.start_address().as_u64();
    let mut frames = Vec::with_capacity(count);
    frames.push(first);

    for i in 1..count {
        let frame = match alloc.allocate_fresh_frame() {
            Some(frame) => frame,
            None => {
                for allocated in frames {
                    alloc.recycle(allocated);
                }
                return None;
            }
        };
        let expected = first_addr + (i as u64) * 4096;
        if frame.start_address().as_u64() != expected {
            frames.push(frame);
            for allocated in frames {
                alloc.recycle(allocated);
            }
            return None;
        }
        frames.push(frame);
    }
    drop(allocator_guard);
    for frame in frames {
        zero_frame(frame);
    }
    Some(first)
}

/// Return a previously-allocated frame to the global pool. Duplicate and
/// foreign returns are ignored, preventing allocator corruption if a cleanup
/// path is invoked twice or passes a device-owned address by mistake.
pub fn deallocate_frame(frame: PhysFrame) {
    if let Some(allocator) = FRAME_ALLOCATOR.lock().as_mut() {
        allocator.recycle(frame);
    }
}

/// `(fresh frames ever handed out, frames currently available for reuse)`.
pub fn frame_allocator_stats() -> Option<(usize, usize)> {
    let allocator = FRAME_ALLOCATOR.lock();
    let allocator = allocator.as_ref()?;
    Some((allocator.allocated(), allocator.recycled.len()))
}

/// End-to-end allocator invariant used by the QEMU release verifier: the most
/// recently returned frame must be reused and scrubbed before it is visible to
/// its next owner.
pub fn verify_frame_recycling() -> bool {
    let Some(first) = allocate_frame() else { return false };
    let first_addr = first.start_address().as_u64();
    let first_virt = phys_to_virt(first.start_address());
    unsafe { first_virt.as_mut_ptr::<u64>().write_volatile(0xF3AA_5A5A_DEAD_BEEF) };
    deallocate_frame(first);
    let Some(second) = allocate_frame() else { return false };
    let second_addr = second.start_address().as_u64();
    let second_virt = phys_to_virt(second.start_address());
    let scrubbed = unsafe { second_virt.as_ptr::<u64>().read_volatile() } == 0;
    deallocate_frame(second);
    first_addr == second_addr && scrubbed
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
/// Fresh frames come from the boot map in order; returned frames are retained
/// in a LIFO free list and scrubbed by the global allocation wrapper before
/// reuse.
pub struct BootInfoFrameAllocator {
    memory_map: &'static MemoryMap,
    next: usize,
    recycled: Vec<PhysFrame>,
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
            recycled: Vec::new(),
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

    fn allocate_fresh_frame(&mut self) -> Option<PhysFrame> {
        let frame = self.usable_frames().nth(self.next);
        if frame.is_some() {
            self.next += 1;
        }
        frame
    }

    fn was_allocated(&self, frame: PhysFrame) -> bool {
        let target = frame.start_address().as_u64();
        let mut handed_out = self.next;
        for region in self
            .memory_map
            .iter()
            .filter(|region| region.region_type == MemoryRegionType::Usable)
        {
            if handed_out == 0 {
                return false;
            }
            let start = region.range.start_addr();
            let len = region.range.end_addr().saturating_sub(start);
            let region_frames = ((len + Size4KiB::SIZE - 1) / Size4KiB::SIZE) as usize;
            let consumed = handed_out.min(region_frames);
            let consumed_end = start.saturating_add(consumed as u64 * Size4KiB::SIZE);
            if target >= start
                && target < consumed_end
                && (target - start) % Size4KiB::SIZE == 0
            {
                return true;
            }
            handed_out -= consumed;
        }
        false
    }

    fn recycle(&mut self, frame: PhysFrame) {
        if self.was_allocated(frame) && !self.recycled.contains(&frame) {
            self.recycled.push(frame);
        }
    }
}

unsafe impl FrameAllocator<Size4KiB> for BootInfoFrameAllocator {
    fn allocate_frame(&mut self) -> Option<PhysFrame<Size4KiB>> {
        self.recycled.pop().or_else(|| self.allocate_fresh_frame())
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
