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

// ---- static kernel stacks ---------------------------------------------------
// The shell, desktop and dashboard tasks, the idle and return trampolines and
// the double-fault IST stack run on arrays in `.bss`. They had no guard: an
// overflow wrote into whatever static lay below (fi1 kernel round 4). Each is
// now a `GuardedStack`, page-aligned with one page in front of the stack, and
// `protect_static_stacks` unmaps that page at boot. The kernel image's page
// tables are shared by every address space, so one unmap covers all of them.

/// Bytes of the unmapped page below a static stack.
pub const STATIC_GUARD: usize = 4096;

/// A kernel stack in `.bss` with a page below it that
/// `protect_static_stacks` unmaps. `N` must be a multiple of 4096.
#[repr(C, align(4096))]
pub struct GuardedStack<const N: usize> {
    guard: [u8; STATIC_GUARD],
    stack: [u8; N],
}

impl<const N: usize> GuardedStack<N> {
    pub const fn new() -> Self {
        Self { guard: [0; STATIC_GUARD], stack: [0; N] }
    }
}

/// (lowest, one past the highest) address of the stack proper.
pub fn static_stack_bounds<const N: usize>(stack: *const GuardedStack<N>) -> (u64, u64) {
    let bottom = stack as u64 + STATIC_GUARD as u64;
    (bottom, bottom + N as u64)
}

/// The kernel's static stacks: (name, lowest, one past the highest address).
pub fn static_stacks() -> [(&'static str, u64, u64); 6] {
    let shell = crate::shell::static_stack_bounds();
    let desktop = crate::gui::static_stack_bounds();
    let dashboard = crate::shell::dashboard::static_stack_bounds();
    let [idle, ret] = crate::scheduler::static_stack_bounds();
    let df = crate::gdt::double_fault_stack_bounds();
    [
        ("shell", shell.0, shell.1),
        ("desktop", desktop.0, desktop.1),
        ("dashboard", dashboard.0, dashboard.1),
        ("idle", idle.0, idle.1),
        ("return", ret.0, ret.1),
        ("double_fault", df.0, df.1),
    ]
}

/// Static stacks whose guard page is unmapped (self-tests).
pub static STATIC_GUARDS: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

/// Unmap the guard page below every static stack. Called once at boot,
/// after the heap and the frame allocator exist. The guard frames belong to
/// the kernel image and are not returned to the allocator.
pub fn protect_static_stacks() {
    let mut done = 0;
    for (name, bottom, _) in static_stacks() {
        let page = Page::<Size4KiB>::containing_address(VirtAddr::new(bottom - STATIC_GUARD as u64));
        let ok = x86_64::instructions::interrupts::without_interrupts(|| match mapper().unmap(page) {
            Ok((_frame, flush)) => {
                flush.flush();
                true
            }
            Err(_) => false,
        });
        if ok {
            done += 1;
        } else {
            crate::serial_println!("[kstack] the guard page below the {} stack could not be unmapped", name);
        }
    }
    STATIC_GUARDS.store(done, core::sync::atomic::Ordering::SeqCst);
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
