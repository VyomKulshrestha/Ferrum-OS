// ============================================================================
// FerrumOS - Guarded kernel stacks (fi1 kernel round 3)
// ============================================================================
// Every process's kernel stack (the stack its syscalls, faults and timer
// interrupts run on) used to be a 32 KiB box on the kernel heap. An overflow
// ran silently into whatever heap object lay below it. Stacks now live in
// their own virtual region inside the heap's P4 slot (P4[136]), whose P3 table
// every address space shares, so a mapping made here is visible in all of
// them. Each slot is 64 KiB: the top 32 KiB are mapped (read-write, no
// execute), the 32 KiB below are never mapped. An overflow faults on the
// guard; the CPU cannot push the page-fault frame onto that stack either, so
// it raises a double fault, which runs on its own IST stack and stops the
// kernel with a message.
// ============================================================================

use spin::Mutex;
use x86_64::structures::paging::{
    FrameAllocator, Mapper, OffsetPageTable, Page, PageTable, PageTableFlags, PhysFrame, Size4KiB,
};
use x86_64::{PhysAddr, VirtAddr};

/// Base of the stack region: P4 index 136 (shared with the heap at
/// 0x4444_4444_0000), P3 index 274, one above the heap's.
pub const REGION_BASE: u64 = 0x4444_8000_0000;
/// Bytes per slot: guard below, stack on top.
pub const SLOT_SIZE: u64 = 64 * 1024;
/// Mapped bytes at the top of each slot.
pub const STACK_SIZE: u64 = 32 * 1024;
/// Slots in the region (512 x 64 KiB = 32 MiB of address space; the process
/// table allows 64 records, so this is never the limit).
const SLOTS: usize = 512;

static USED: Mutex<[u64; SLOTS / 64]> = Mutex::new([0; SLOTS / 64]);

/// Stacks allocated and not yet freed (self-tests).
pub static LIVE: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

struct Frames;

unsafe impl FrameAllocator<Size4KiB> for Frames {
    fn allocate_frame(&mut self) -> Option<PhysFrame<Size4KiB>> {
        super::allocate_frame()
    }
}

fn mapper() -> OffsetPageTable<'static> {
    let offset = super::phys_to_virt(PhysAddr::new(0));
    let l4 = unsafe { &mut *super::phys_to_virt(super::active_p4_phys()).as_mut_ptr::<PageTable>() };
    unsafe { OffsetPageTable::new(l4, offset) }
}

/// A kernel stack with an unmapped guard below it. Dropping it unmaps the
/// stack and returns its frames; never drop the stack the CPU is running on.
pub struct KernelStack {
    slot: usize,
}

impl KernelStack {
    /// Lowest mapped address of the stack.
    pub fn bottom(&self) -> u64 {
        REGION_BASE + self.slot as u64 * SLOT_SIZE + (SLOT_SIZE - STACK_SIZE)
    }

    /// One past the highest mapped address (16-byte aligned).
    pub fn top(&self) -> VirtAddr {
        VirtAddr::new(REGION_BASE + (self.slot as u64 + 1) * SLOT_SIZE)
    }

    /// The highest address of the guard (the byte just below `bottom`).
    pub fn guard_address(&self) -> u64 {
        self.bottom() - 1
    }
}

/// Map a fresh, zeroed kernel stack. `None` if no slot or frame is free.
pub fn allocate() -> Option<KernelStack> {
    let slot = x86_64::instructions::interrupts::without_interrupts(|| {
        let mut used = USED.lock();
        for word in 0..used.len() {
            if used[word] != u64::MAX {
                let bit = (!used[word]).trailing_zeros() as usize;
                used[word] |= 1 << bit;
                return Some(word * 64 + bit);
            }
        }
        None
    })?;
    let stack = KernelStack { slot };
    let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::NO_EXECUTE;
    let first = Page::<Size4KiB>::containing_address(VirtAddr::new(stack.bottom()));
    let pages = (STACK_SIZE / 4096) as u64;
    let mut mapped = 0;
    let ok = x86_64::instructions::interrupts::without_interrupts(|| {
        let mut mapper = mapper();
        for i in 0..pages {
            let Some(frame) = super::allocate_frame() else { return false };
            match unsafe { mapper.map_to(first + i, frame, flags, &mut Frames) } {
                Ok(flush) => flush.flush(),
                Err(_) => {
                    super::deallocate_frame(frame);
                    return false;
                }
            }
            mapped += 1;
        }
        true
    });
    if !ok {
        unmap(first, mapped);
        release(slot);
        return None;
    }
    LIVE.fetch_add(1, core::sync::atomic::Ordering::SeqCst);
    Some(stack)
}

fn unmap(first: Page<Size4KiB>, pages: u64) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut mapper = mapper();
        for i in 0..pages {
            if let Ok((frame, flush)) = mapper.unmap(first + i) {
                flush.flush();
                super::deallocate_frame(frame);
            }
        }
    });
}

fn release(slot: usize) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        USED.lock()[slot / 64] &= !(1u64 << (slot % 64));
    });
}

impl Drop for KernelStack {
    fn drop(&mut self) {
        let first = Page::<Size4KiB>::containing_address(VirtAddr::new(self.bottom()));
        unmap(first, STACK_SIZE / 4096);
        release(self.slot);
        LIVE.fetch_sub(1, core::sync::atomic::Ordering::SeqCst);
    }
}

/// Flags of the leaf mapping of `addr` in the active address space, or `None`
/// if it is not mapped (self-tests).
pub fn leaf_flags(addr: u64) -> Option<PageTableFlags> {
    use x86_64::structures::paging::mapper::{Translate, TranslateResult};
    match mapper().translate(VirtAddr::new(addr)) {
        TranslateResult::Mapped { flags, .. } => Some(flags),
        _ => None,
    }
}
