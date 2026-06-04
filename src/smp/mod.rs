use core::ptr::copy_nonoverlapping;
use x86_64::VirtAddr;
use crate::println;

pub mod per_cpu;

// The trampoline binary is compiled by nasm
static TRAMPOLINE_BIN: &[u8] = include_bytes!("trampoline.bin");

/// The physical address where the trampoline is copied
const TRAMPOLINE_ADDR: u64 = 0x8000;

pub fn init(phys_mem_offset: VirtAddr) {
    println!("Initializing SMP subsystem...");
    
    // Copy the trampoline to physical address 0x8000
    // In FerrumOS, physical addresses are mapped at `phys_mem_offset`.
    let dest_virt = phys_mem_offset + TRAMPOLINE_ADDR;
    
    unsafe {
        copy_nonoverlapping(
            TRAMPOLINE_BIN.as_ptr(),
            dest_virt.as_mut_ptr::<u8>(),
            TRAMPOLINE_BIN.len()
        );
    }
    
    // At this point, we would use the x2apic crate to:
    // 1. Setup the BSP Local APIC
    // 2. Read the MADT table to find other CPU cores
    // 3. For each AP, patch the trampoline variables (cr3_value, stack_pointer, entry_point)
    // 4. Send INIT IPI
    // 5. Send SIPI IPI with vector 0x08 (0x8000 >> 12)
    
    println!("[  OK  ] AP trampoline loaded at 0x{:X}", TRAMPOLINE_ADDR);
}

/// The entry point for awakened Application Processors
#[no_mangle]
pub extern "C" fn ap_entry() -> ! {
    // We are now in 64-bit mode on an AP
    // Initialize Local APIC for this core
    // Setup PerCpu structures via GS segment
    loop {
        x86_64::instructions::hlt();
    }
}
