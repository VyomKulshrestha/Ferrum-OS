// ============================================================================
// FerrumOS — Memory Management Subsystem
// ============================================================================
// Manages physical and virtual memory for the kernel.
//
// Components:
//   - Page table initialization and mapping
//   - Physical frame allocator (from bootloader memory map)
//   - Kernel heap allocator
//
// The bootloader provides a physical memory offset that maps all physical
// memory into virtual address space, allowing us to walk page tables.
// ============================================================================

pub mod heap;

use bootloader::bootinfo::{MemoryMap, MemoryRegionType};
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
    let level_4_table = active_level_4_table(physical_memory_offset);
    OffsetPageTable::new(level_4_table, physical_memory_offset)
}

/// Returns a mutable reference to the active level 4 page table
/// 
/// # Safety
/// 
/// The caller must guarantee that the complete physical memory is mapped
/// to virtual memory at the passed `physical_memory_offset`. Also, this
/// function must only be called once to avoid aliasing `&mut` references.
unsafe fn active_level_4_table(physical_memory_offset: VirtAddr) -> &'static mut PageTable {
    use x86_64::registers::control::Cr3;

    let (level_4_table_frame, _) = Cr3::read();
    let phys = level_4_table_frame.start_address();
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
/// This is a simple bump allocator — frames are never freed.
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
