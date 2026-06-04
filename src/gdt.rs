// ============================================================================
// FerrumOS - Global Descriptor Table & Task State Segment
// ============================================================================
// Phase 1.4 of the v0.2 completion roadmap.
//
// Owns the GDT (kernel code/data, user code/data, TSS) and exposes a
// mutator for `TSS.RSP0` so the kernel can hand each user process a
// dedicated kernel stack for ring-3 -> ring-0 transitions (syscalls,
// interrupts, page faults).
//
// Selector layout:
//
//     Index 0x00  null
//     Index 0x01  kernel code (64-bit, ring 0)   selector 0x08
//     Index 0x02  kernel data (64-bit, ring 0)   selector 0x10
//     Index 0x03  user   code (64-bit, ring 3)   selector 0x1B
//     Index 0x04  user   data (64-bit, ring 3)   selector 0x23
//     Index 0x05  TSS                              selector 0x28
//
// The kernel does not have a "real" data segment in 64-bit long mode
// (the CPU ignores most segment base/limit fields), but adding an
// explicit kernel data descriptor matches the standard layout and
// simplifies the iretq math (SS still matters for iretq).
// ============================================================================

use core::arch::asm;
use lazy_static::lazy_static;
use x86_64::structures::gdt::{Descriptor, GlobalDescriptorTable, SegmentSelector};
use x86_64::structures::tss::TaskStateSegment;
use x86_64::VirtAddr;

/// IST slot used for the double fault handler. The IST provides
/// dedicated stacks for critical exception handlers so a kernel
/// stack overflow does not turn into a triple fault.
pub const DOUBLE_FAULT_IST_INDEX: u16 = 0;

/// Size of the double fault handler stack (5 pages = 20 KiB).
const DOUBLE_FAULT_STACK_SIZE: usize = 4096 * 5;

/// GDT selectors. `u64` casts avoid exposing the internal
/// `SegmentSelector` newtype at every call site.
pub const KERNEL_CODE_SELECTOR: u64 = 0x08;
pub const KERNEL_DATA_SELECTOR: u64 = 0x10;
pub const USER_CODE_SELECTOR: u64 = 0x18 | 0x03; // RPL 3
pub const USER_DATA_SELECTOR: u64 = 0x20 | 0x03; // RPL 3
pub const TSS_SELECTOR: u64 = 0x28;

/// Backing storage for the TSS. The IST slot is filled in at
/// `init()` time. `privilege_stack_table[0]` (= RSP0) is updated
/// every time the kernel switches to a user process via
/// `set_kernel_stack`.
///
/// We hold the TSS in a `static mut` because `TaskStateSegment`
/// is neither `Sync` nor `Send` and `Descriptor::tss_segment`
/// wants a `&'static TaskStateSegment`. Access is single-threaded
/// in the kernel so the `static mut` is sound; we expose mutating
/// helpers that perform the `unsafe` write in one place.
static mut TSS: TaskStateSegment = TaskStateSegment::new();

/// Borrow the TSS as a `&'static` for use with the GDT builder.
/// Callers must not retain the reference past the GDT append
/// call.
fn tss_ref() -> &'static TaskStateSegment {
    // Safety: `TSS` is a `static mut` initialised at compile time
    // (TaskStateSegment::new() is const). The kernel is
    // single-threaded so handing out a shared ref here is sound
    // as long as no `&mut` is alive concurrently. The GDT builder
    // does not retain the reference, and our mutation helpers go
    // through `set_*` functions that own the `&mut` for the
    // duration of the write only.
    unsafe { &*(&raw const TSS) }
}

/// IST stack for the double fault handler. Placed in `.bss` so
/// the kernel can keep using it after the initial mapping.
static mut DOUBLE_FAULT_STACK: [u8; DOUBLE_FAULT_STACK_SIZE] =
    [0; DOUBLE_FAULT_STACK_SIZE];

struct Selectors {
    kernel_code: SegmentSelector,
    kernel_data: SegmentSelector,
    user_code: SegmentSelector,
    user_data: SegmentSelector,
    tss: SegmentSelector,
}

lazy_static! {
    static ref GDT: (GlobalDescriptorTable, Selectors) = {
        let mut gdt = GlobalDescriptorTable::new();
        let kernel_code = gdt.append(Descriptor::kernel_code_segment());
        let kernel_data = gdt.append(Descriptor::kernel_data_segment());
        let user_code = gdt.append(Descriptor::user_code_segment());
        let user_data = gdt.append(Descriptor::user_data_segment());
        // Safety: TSS is a `static mut`; we only borrow it for the
        // duration of `Descriptor::tss_segment` to build the GDT
        // entry, then drop the borrow before returning.
        let tss = gdt.append(Descriptor::tss_segment(tss_ref()));
        (
            gdt,
            Selectors {
                kernel_code,
                kernel_data,
                user_code,
                user_data,
                tss,
            },
        )
    };
}

/// Set `TSS.privilege_stack_table[0]` (RSP0) to `rsp0`. The CPU
/// loads this value whenever a ring-3 -> ring-0 transition
/// happens, so it must point to the top of the *current* user
/// process's kernel stack.
///
/// # Safety
///
/// Must be called with a valid kernel stack pointer that is
/// 16-byte aligned and that the kernel owns for the lifetime of
/// the next ring-0 entry. Single-threaded kernel so no locking
/// is required.
pub unsafe fn set_kernel_stack(rsp0: VirtAddr) {
    TSS.privilege_stack_table[0] = rsp0;
}

/// Set the IST entry used for the double fault handler. Called
/// once at init time.
fn install_double_fault_ist() {
    // Safety: single-threaded init code, no concurrent access.
    let stack_top =
        VirtAddr::from_ptr(&raw const DOUBLE_FAULT_STACK) + DOUBLE_FAULT_STACK_SIZE as u64;
    unsafe {
        TSS.interrupt_stack_table[DOUBLE_FAULT_IST_INDEX as usize] = stack_top;
    }
}

/// Initialize the GDT and load segment registers. Must be called
/// before interrupts are enabled and before any ring-3 process is
/// launched.
pub fn init() {
    use x86_64::instructions::segmentation::{CS, DS, ES, FS, GS, SS, Segment};
    use x86_64::instructions::tables::load_tss;

    install_double_fault_ist();

    GDT.0.load();
    unsafe {
        CS::set_reg(GDT.1.kernel_code);
        DS::set_reg(GDT.1.kernel_data);
        ES::set_reg(GDT.1.kernel_data);
        FS::set_reg(GDT.1.kernel_data);
        GS::set_reg(GDT.1.kernel_data);
        SS::set_reg(GDT.1.kernel_data);
        load_tss(GDT.1.tss);
    }

    // Sanity-check that the selectors we exposed line up with the
    // GDT we actually loaded. If a refactor ever changes the
    // ordering this will catch it before we get to ring-3.
    let selectors = &GDT.1;
    let expected = [
        (KERNEL_CODE_SELECTOR, selectors.kernel_code),
        (KERNEL_DATA_SELECTOR, selectors.kernel_data),
        (USER_CODE_SELECTOR, selectors.user_code),
        (USER_DATA_SELECTOR, selectors.user_data),
        (TSS_SELECTOR, selectors.tss),
    ];
    for (expected_raw, actual) in expected {
        debug_assert_eq!(expected_raw, actual.0 as u64, "GDT selector drift");
    }

    // The x86_64 crate exposes the current CS via inline asm
    // because there is no MSR to read it from. Re-reading it
    // here also makes sure the inline asm path stays compiled
    // (otherwise the linker may drop the segment of the binary
    // that performs the `swapgs`/`iretq` trampoline later).
    let _cs: u64;
    unsafe {
        asm!("mov {0}, cs", out(reg) _cs, options(nomem, nostack, preserves_flags));
    }
    debug_assert_eq!(_cs, KERNEL_CODE_SELECTOR, "CS not loaded from GDT");
}
