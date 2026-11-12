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

/// The heap's spin lock, taken with interrupts disabled.
///
/// Interrupt handlers allocate (the timer's `scheduler::tick` grows run
/// queues, a fault or quota kill writes audit records), and kernel tasks
/// allocate with interrupts enabled. With a plain `LockedHeap`, an interrupt
/// that arrived while a kernel task was inside `alloc` or `dealloc` spun on
/// the heap lock with interrupts off, on the only CPU: the kernel hung.
pub struct IrqSafeHeap(LockedHeap);

unsafe impl core::alloc::GlobalAlloc for IrqSafeHeap {
    unsafe fn alloc(&self, layout: core::alloc::Layout) -> *mut u8 {
        x86_64::instructions::interrupts::without_interrupts(|| self.0.alloc(layout))
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: core::alloc::Layout) {
        x86_64::instructions::interrupts::without_interrupts(|| self.0.dealloc(ptr, layout))
    }
}

/// Global allocator instance
///
/// This is the allocator used by Rust's `alloc` crate for all
/// dynamic memory allocation (Box, Vec, String, etc.)
#[global_allocator]
static ALLOCATOR: IrqSafeHeap = IrqSafeHeap(LockedHeap::empty());

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

    // NO_EXECUTE is a reserved bit unless EFER.NXE is set.
    super::ensure_nxe();

    // Map each page to a physical frame
    for page in page_range {
        let frame = frame_allocator
            .allocate_frame()
            .ok_or(MapToError::FrameAllocationFailed)?;
        // Heap pages hold data only (Vec buffers, process kernel stacks,
        // canvases); they were mapped executable.
        let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
        unsafe {
            mapper.map_to(page, frame, flags, frame_allocator)?.flush();
        }
    }

    // Initialize the allocator with the heap memory region
    unsafe {
        ALLOCATOR.0.lock().init(HEAP_START as *mut u8, HEAP_SIZE);
    }

    super::harden_kernel_mappings();

    Ok(())
}

/// Get heap usage statistics
/// 
/// Returns (used_bytes, free_bytes) for the kernel heap
pub fn heap_stats() -> (usize, usize) {
    let free = x86_64::instructions::interrupts::without_interrupts(|| ALLOCATOR.0.lock().free());
    let used = HEAP_SIZE - free;
    (used, free)
}
