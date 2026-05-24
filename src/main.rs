// ============================================================================
// FerrumOS - Main Entry Point
// ============================================================================
// This is the kernel entry point. The bootloader hands control here after
// setting up basic hardware state (GDT, page tables, stack).
//
// Architecture: x86_64 bare-metal
// No standard library - we are the operating system.
// ============================================================================

#![no_std]                          // No standard library
#![no_main]                         // No Rust runtime entry point
#![feature(custom_test_frameworks)] // Custom test runner
#![test_runner(ferrumos::test_runner)]
#![reexport_test_harness_main = "test_main"]

extern crate alloc;

use bootloader::{BootInfo, entry_point};
use core::panic::PanicInfo;
use ferrumos::println;

// Register our kernel entry point with the bootloader
entry_point!(kernel_main);

/// FerrumOS Kernel Entry Point
/// 
/// Called by the bootloader after basic hardware initialization.
/// This function initializes all kernel subsystems in the correct order
/// and then enters the main shell loop.
fn kernel_main(boot_info: &'static BootInfo) -> ! {
    // ========================================================================
    // Phase 1: Core Hardware Initialization
    // ========================================================================
    
    // Print boot banner
    print_boot_banner();
    
    // Initialize GDT, IDT, and interrupt controllers
    ferrumos::init();
    println!("[  OK  ] Interrupts and GDT initialized");

    // ========================================================================
    // Phase 2: Memory Subsystem
    // ========================================================================
    
    use ferrumos::memory;
    use x86_64::VirtAddr;

    // Initialize page table mapper
    let phys_mem_offset = VirtAddr::new(boot_info.physical_memory_offset);
    let mut mapper = unsafe { memory::init(phys_mem_offset) };
    
    // Initialize frame allocator from bootloader memory map
    let mut frame_allocator = unsafe {
        memory::BootInfoFrameAllocator::init(&boot_info.memory_map)
    };
    println!("[  OK  ] Page table mapper initialized");
    
    // Initialize kernel heap
    ferrumos::memory::heap::init_heap(&mut mapper, &mut frame_allocator)
        .expect("Heap initialization failed");
    println!("[  OK  ] Kernel heap initialized ({}KB)", 
        ferrumos::memory::heap::HEAP_SIZE / 1024);

    // ========================================================================
    // Phase 3: Kernel Subsystems
    // ========================================================================
    
    // Initialize logging subsystem
    ferrumos::logging::init();
    println!("[  OK  ] Logging subsystem initialized");
    
    // Initialize filesystem
    ferrumos::fs::init();
    println!("[  OK  ] RAM filesystem initialized");
    
    // Initialize security subsystem
    ferrumos::security::init();
    println!("[  OK  ] Capability-based security initialized");
    
    // Initialize service manager
    ferrumos::services::init();
    println!("[  OK  ] Service manager initialized");

    // Initialize the agent runtime boundary. This registers a sandboxed
    // runtime service without loading any probabilistic agent code in kernel.
    ferrumos::agent::init();
    println!("[  OK  ] Agent runtime boundary initialized");
    
    // Initialize scheduler
    ferrumos::scheduler::init();
    println!("[  OK  ] Task scheduler initialized");
    
    // ========================================================================
    // Phase 4: Post-Boot
    // ========================================================================
    
    // Log boot completion
    ferrumos::logging::audit::log_event(
        ferrumos::logging::audit::AuditEvent::SystemBoot,
        "FerrumOS kernel boot sequence completed successfully",
    );
    
    // VGA text mode supports a small character set, so leave the user at a
    // deterministic ASCII shell-ready screen after serial boot logging.
    ferrumos::vga::WRITER.lock().clear_screen();
    print_ready_banner();

    // Run tests if in test mode
    #[cfg(test)]
    test_main();

    // Enter the shell - this never returns
    ferrumos::shell::run();
}

/// Print the FerrumOS boot banner with ASCII art
fn print_boot_banner() {
    println!();
    println!("  _   _      _ _           ___  ____");
    println!(" | | | | ___| (_) _____  / _ \\/ ___|");
    println!(" | |_| |/ _ \\ | |/ / _ \\| | | \\___ \\");
    println!(" |  _  |  __/ |   < (_) | |_| |___) |");
    println!(" |_| |_|\\___|_|_|\\_\\___/ \\___/|____/");
    println!();
    println!("  Booting FerrumOS v0.1.0 - AI-Native Autonomous OS");
    println!("  Architecture: x86_64 | Mode: Protected");
    println!();
}

/// Print the shell-ready status screen using only VGA-safe ASCII.
fn print_ready_banner() {
    println!("FerrumOS v0.1.0");
    println!("AI-Native Autonomous OS Foundation");
    println!();
    println!("[ OK ] Interrupts and GDT initialized");
    println!("[ OK ] Page table mapper initialized");
    println!("[ OK ] Kernel heap initialized");
    println!("[ OK ] Logging subsystem initialized");
    println!("[ OK ] RAM filesystem initialized");
    println!("[ OK ] Capability security initialized");
    println!("[ OK ] Service manager initialized");
    println!("[ OK ] Task scheduler initialized");
    println!();
    println!("Kernel boundary: deterministic; AI runs in runtime services.");
    println!("Type 'help' for available commands.");
    println!();
}

/// Panic handler - called on unrecoverable errors
/// 
/// In a bare-metal environment, there's nowhere to unwind to.
/// We print the panic info and halt the CPU.
#[cfg(not(test))]
#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    println!("\x1b[31m[KERNEL PANIC]\x1b[0m {}", info);
    ferrumos::hlt_loop();
}

/// Test-mode panic handler - exits QEMU with failure code
#[cfg(test)]
#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    ferrumos::test_panic_handler(info)
}
