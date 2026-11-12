// ============================================================================
// FerrumOS - SMP: the kernel runs on one CPU
// ============================================================================
// No application processor is started: there is no Local APIC set-up and no
// INIT/SIPI sequence anywhere in the kernel. Every other CPU listed in the
// ACPI MADT stays in the firmware's wait-for-SIPI state for the whole boot.
//
// Much of the kernel depends on that. The scheduler, the syscall layer, the
// heap and the input queues reason "interrupts are off, so nothing else
// runs", which holds only on one CPU (fi1 kernel round 4 lists what must
// change before an application processor may run kernel code:
// docs/research/fi1_reports/kernel_round4.md, "The single-processor
// assumption"). The facts are checked, not only stated: `init` prints them
// at boot, `ap_entry` counts any CPU that reaches it and parks it with
// interrupts off before it touches shared state, `assert_single_cpu` stops
// the kernel if one did, and the self-test `smp-state` reports the counters.
// ============================================================================

use core::ptr::copy_nonoverlapping;
use core::sync::atomic::{AtomicUsize, Ordering};
use x86_64::VirtAddr;
use crate::println;

pub mod per_cpu;

// The trampoline binary is compiled by nasm
static TRAMPOLINE_BIN: &[u8] = include_bytes!("trampoline.bin");

/// The physical address where the trampoline is copied
const TRAMPOLINE_ADDR: u64 = 0x8000;

/// CPUs that run kernel code. The kernel never starts another one.
pub const ONLINE_CPUS: usize = 1;

/// Application processors the ACPI MADT lists (set by `acpi::init`).
pub static MADT_APPLICATION_PROCESSORS: AtomicUsize = AtomicUsize::new(0);

/// Application processors that reached `ap_entry`. Must stay 0.
pub static APS_STARTED: AtomicUsize = AtomicUsize::new(0);

/// 1 if the trampoline was copied to 0x8000 (only when that frame is not
/// one the frame allocator may hand out).
pub static TRAMPOLINE_COPIED: AtomicUsize = AtomicUsize::new(0);

pub fn init(phys_mem_offset: VirtAddr) {
    // The trampoline is not used (no AP is started) but is kept in place for
    // a future bring-up. Copying it overwrites physical 0x8000..0x80E6, which
    // is safe only while that frame is the bootloader's, never a usable frame
    // the allocator may already have given to a page table or the heap.
    let region = crate::memory::boot_region_type(TRAMPOLINE_ADDR);
    let usable = region.map_or(true, |r| r == bootloader::bootinfo::MemoryRegionType::Usable);
    if !usable {
        let dest_virt = phys_mem_offset + TRAMPOLINE_ADDR;
        unsafe {
            copy_nonoverlapping(TRAMPOLINE_BIN.as_ptr(), dest_virt.as_mut_ptr::<u8>(), TRAMPOLINE_BIN.len());
        }
        TRAMPOLINE_COPIED.store(1, Ordering::SeqCst);
    }
    println!(
        "[ INFO ] SMP: online_cpus={} application_processors_started={} madt_application_processors={} trampoline_region={:?} trampoline_copied={}",
        ONLINE_CPUS,
        APS_STARTED.load(Ordering::SeqCst),
        MADT_APPLICATION_PROCESSORS.load(Ordering::SeqCst),
        region,
        !usable
    );
    println!("[ INFO ] SMP: the kernel runs on one CPU; application processors are not started");
}

/// Stop the kernel if any other CPU has entered it: the single-CPU arguments
/// of the scheduler and the syscall layer are void from that moment.
pub fn assert_single_cpu() {
    let started = APS_STARTED.load(Ordering::SeqCst);
    if started != 0 {
        panic!("SMP: {} application processor(s) entered the kernel, which assumes one CPU", started);
    }
}

/// The entry point for awakened Application Processors. Nothing starts one;
/// if one ever arrives here it is counted and parked with interrupts off
/// before it can touch any kernel state.
#[no_mangle]
pub extern "C" fn ap_entry() -> ! {
    APS_STARTED.fetch_add(1, Ordering::SeqCst);
    loop {
        x86_64::instructions::interrupts::disable();
        x86_64::instructions::hlt();
    }
}
