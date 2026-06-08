// ============================================================================
// FerrumOS - Kernel Heap Allocator
// ============================================================================
// Sets up a heap region in virtual memory for dynamic allocation.
//
// The heap is mapped to a fixed virtual address range and uses the
// linked_list_allocator crate for allocation management.
//
// Heap Parameters:
//   Start:  0x4444_4444_0000
//   Size:   1 MiB (bumped from 256 KiB in Phase 1.3 once the per-process
//           address space module started allocating intermediate P3/P2/P1
//           page-table frames and Vec bookkeeping in the kernel heap.)
//   Backing: Physical frames from BootInfoFrameAllocator
// ============================================================================

use linked_list_allocator::LockedHeap;
use x86_64::{
    structures::paging::{
        mapper::MapToError, FrameAllocator, Mapper, Page, PageTableFlags, Size4KiB,
    },
    VirtAddr,
};

/// Start address of the kernel heap in virtual memory
pub const HEAP_START: usize = 0x_4444_4444_0000;
/// Size of the kernel heap (256 KiB)
/// 
/// This is sufficient for early kernel operations. For a production kernel,
/// this would need to be expandable on demand.
pub const HEAP_SIZE: usize = 12 * 1024 * 1024; // 12 MiB (increased to support VBE double-buffering)

/// Global allocator instance
/// 
/// This is the allocator used by Rust's `alloc` crate for all
/// dynamic memory allocation (Box, Vec, String, etc.)
#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

/// Initialize the kernel heap
/// 
/// Maps virtual pages for the heap and initializes the allocator.
/// Must be called after page table and frame allocator initialization.
/// 
/// # Arguments
/// * `mapper` - The page table mapper
/// * `frame_allocator` - Physical frame allocator
/// 
/// # Errors
/// Returns `MapToError` if page mapping fails
pub fn init_heap(
    mapper: &mut impl Mapper<Size4KiB>,
    frame_allocator: &mut impl FrameAllocator<Size4KiB>,
) -> Result<(), MapToError<Size4KiB>> {
    // Calculate the page range for the heap
    let page_range = {
        let heap_start = VirtAddr::new(HEAP_START as u64);
        let heap_end = heap_start + HEAP_SIZE as u64 - 1u64;
        let heap_start_page = Page::containing_address(heap_start);
        let heap_end_page = Page::containing_address(heap_end);
        Page::range_inclusive(heap_start_page, heap_end_page)
    };

    // Map each page to a physical frame
    for page in page_range {
        let frame = frame_allocator
            .allocate_frame()
            .ok_or(MapToError::FrameAllocationFailed)?;
        let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE;
        unsafe {
            mapper.map_to(page, frame, flags, frame_allocator)?.flush();
        }
    }

    // Initialize the allocator with the heap memory region
    unsafe {
        ALLOCATOR.lock().init(HEAP_START as *mut u8, HEAP_SIZE);
    }

    Ok(())
}

/// Get heap usage statistics
/// 
/// Returns (used_bytes, free_bytes) for the kernel heap
pub fn heap_stats() -> (usize, usize) {
    let allocator = ALLOCATOR.lock();
    let free = allocator.free();
    let used = HEAP_SIZE - free;
    (used, free)
}
