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

/// Set EFER.NXE if it is not set. The bootloader sets it on the boot CPU; the
/// kernel's NO_EXECUTE bits are reserved bits (a fault on every access)
/// without it, so the kernel checks rather than assumes.
pub fn ensure_nxe() {
    use x86_64::registers::model_specific::{Efer, EferFlags};
    if !Efer::read().contains(EferFlags::NO_EXECUTE_ENABLE) {
        unsafe { Efer::update(|flags| *flags |= EferFlags::NO_EXECUTE_ENABLE) };
    }
}

/// P4 index of the physical-memory alias marked non-executable by
/// `harden_kernel_mappings` (usize::MAX when it was not).
pub static PHYS_MAP_NX_INDEX: core::sync::atomic::AtomicUsize =
    core::sync::atomic::AtomicUsize::new(usize::MAX);

/// Mark the bootloader's mapping of all physical memory non-executable. It
/// spans every RAM frame (page tables, user frames, DMA buffers, the heap's
/// frames) read-write and was executable, so any data the kernel wrote
/// anywhere could be run through its alias. Nothing executes from it: the
/// kernel runs at its link address (P4[0]), kexec jumps through an identity
/// page, and the SMP trampoline is copied there but never started. The bit is
/// set on the P4 entry, which covers the whole alias; process address spaces
/// copy that entry when they are created, after this runs.
pub fn harden_kernel_mappings() {
    ensure_nxe();
    let Some(offset) = *PHYS_MEM_OFFSET.lock() else { return };
    let offset = offset.as_u64();
    // Only when the alias owns its P4 slot outright.
    if offset & ((1u64 << 39) - 1) != 0 {
        return;
    }
    let index = ((offset >> 39) & 0x1FF) as usize;
    if index == 0 {
        return; // shared with the kernel image
    }
    let l4 = unsafe { &mut *(VirtAddr::new(offset + active_p4_phys().as_u64())).as_mut_ptr::<PageTable>() };
    let entry = &mut l4[index];
    if !entry.flags().contains(x86_64::structures::paging::PageTableFlags::PRESENT) {
        return;
    }
    let flags = entry.flags() | x86_64::structures::paging::PageTableFlags::NO_EXECUTE;
    let addr = entry.addr();
    entry.set_addr(addr, flags);
    x86_64::instructions::tlb::flush_all();
    PHYS_MAP_NX_INDEX.store(index, core::sync::atomic::Ordering::SeqCst);
}

/// Flags of the active P4 entry `index` (self-tests).
pub fn kernel_p4_flags(index: usize) -> x86_64::structures::paging::PageTableFlags {
    let offset = PHYS_MEM_OFFSET.lock().map(|o| o.as_u64()).unwrap_or(0);
    let l4 = unsafe { &*(VirtAddr::new(offset + active_p4_phys().as_u64())).as_ptr::<PageTable>() };
    l4[index & 0x1FF].flags()
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
    /// Position of the next fresh frame: index among the usable regions and
    /// frame offset inside that region. Kept so a fresh allocation is O(1)
    /// (amortized) instead of re-walking `next` frames of the memory map on
    /// every call, which made booting (tens of thousands of frames for the
    /// heliox-daemon image) quadratic.
    fresh_region: usize,
    fresh_offset: u64,
    recycled: Vec<PhysFrame>,
    /// Start addresses of the frames in `recycled`, for an O(log n)
    /// duplicate check in `recycle` (a linear `contains` made dropping a
    /// large address space quadratic in its frame count).
    recycled_set: alloc::collections::BTreeSet<u64>,
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
            fresh_region: 0,
            fresh_offset: 0,
            recycled: Vec::new(),
            recycled_set: alloc::collections::BTreeSet::new(),
        }
    }

    /// Number of frames already handed out.
    pub fn allocated(&self) -> usize {
        self.next
    }

    fn allocate_fresh_frame(&mut self) -> Option<PhysFrame> {
        // Same order the original iterator walked (usable regions in map order,
        // `start, start + 4096, ...` below `end`), which `was_allocated`
        // relies on, without re-walking the frames already handed out.
        loop {
            let region = self
                .memory_map
                .iter()
                .filter(|r| r.region_type == MemoryRegionType::Usable)
                .nth(self.fresh_region)?;
            let start = region.range.start_addr();
            let end = region.range.end_addr();
            let addr = start.saturating_add(self.fresh_offset * Size4KiB::SIZE);
            if addr < end {
                self.fresh_offset += 1;
                self.next += 1;
                return Some(PhysFrame::containing_address(PhysAddr::new(addr)));
            }
            self.fresh_region += 1;
            self.fresh_offset = 0;
        }
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
        if self.was_allocated(frame) && self.recycled_set.insert(frame.start_address().as_u64()) {
            self.recycled.push(frame);
        }
    }

    fn pop_recycled(&mut self) -> Option<PhysFrame> {
        let frame = self.recycled.pop()?;
        self.recycled_set.remove(&frame.start_address().as_u64());
        Some(frame)
    }
}

unsafe impl FrameAllocator<Size4KiB> for BootInfoFrameAllocator {
    fn allocate_frame(&mut self) -> Option<PhysFrame<Size4KiB>> {
        self.pop_recycled().or_else(|| self.allocate_fresh_frame())
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
