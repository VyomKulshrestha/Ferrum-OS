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
    println!(
        "[  OK  ] Kernel heap initialized ({}KB)",
        ferrumos::memory::heap::HEAP_SIZE / 1024
    );

    // Hand the SAME frame allocator instance (now past the heap frames)
    // to the global registry. If we re-initialized a fresh allocator
    // here, its bump pointer would rewind to 0 and the next consumer
    // would overwrite heap memory via `phys_to_virt`.
    unsafe { memory::install_global_frame_allocator(frame_allocator) };
    println!("[  OK  ] Global frame allocator installed (bump past heap)");

    // ========================================================================
    // Phase 3: Kernel Subsystems
    // ========================================================================
    
    // Initialize logging subsystem
    ferrumos::logging::init();
    println!("[  OK  ] Logging subsystem initialized");
    
    // Initialize filesystem
    ferrumos::fs::init();
    println!("[  OK  ] RAM filesystem initialized");

    // Initialize the device registry after base console/storage surfaces exist.
    ferrumos::devices::init();
    println!("[  OK  ] Device registry initialized");

    // Initialize ATA PIO disk driver — probe IDE channels for attached drives.
    ferrumos::ata::init();
    println!("[  OK  ] ATA PIO disk driver initialized");
    
    // Initialize security subsystem
    ferrumos::security::init();
    println!("[  OK  ] Capability-based security initialized");
    
    // Initialize service manager
    ferrumos::services::init();
    println!("[  OK  ] Service manager initialized");

    // Initialize deterministic networking before userspace runtime services.
    ferrumos::net::init();
    println!("[  OK  ] Network subsystem initialized");

    // Initialize userspace manifests before runtime agents are exposed.
    ferrumos::userspace::init();
    println!("[  OK  ] Userspace registry initialized");

    // Initialize the agent runtime boundary. This registers a sandboxed
    // runtime service without loading any probabilistic agent code in kernel.
    ferrumos::agent::init();
    println!("[  OK  ] Agent runtime boundary initialized");

    // Initialize the Heliox-OS integration boundary. This registers the
    // Heliox JSON-RPC method catalog, permission tiers, and runtime service
    // slots that the future Heliox-compatible agent runtime can attach to.
    ferrumos::heliox::init();
    println!("[  OK  ] Heliox-OS integration boundary initialized");

    // Initialize scheduler
    ferrumos::scheduler::init();
    println!("[  OK  ] Task scheduler initialized");

    match ferrumos::userspace::bootstrap_init() {
        Ok(pid) => println!("[  OK  ] Userspace init launched as PID {}", pid),
        Err(err) => println!("[ WARN ] Userspace init launch failed: {}", err),
    }

    match ferrumos::elf::parse(ferrumos::userspace::INIT_ELF) {
        Ok(parsed) => {
            let loads = parsed.load_segments().count();
            println!(
                "[  OK  ] Embedded init ELF: {} bytes, entry={:#x}, {} PT_LOAD segment(s)",
                ferrumos::userspace::init_elf_size(),
                parsed.entry(),
                loads
            );
        }
        Err(err) => println!(
            "[ WARN ] Embedded init ELF failed ELF64 parse: {}",
            err
        ),
    }

    // Phase 1.3 smoke test: build a sample process, allocate a fresh
    // address space, map a single user page with a known byte pattern,
    // register it, and leave it in the process table so the shell can
    // inspect it via `process`.
    let (heap_used, heap_free) = ferrumos::memory::heap::heap_stats();
    println!("[ INFO ] Kernel heap: {} used / {} free", heap_used, heap_free);
    match ferrumos::process::create("init-sample") {
        Ok(mut process) => {
            use x86_64::structures::paging::PageTableFlags;
            let vaddr = x86_64::VirtAddr::new(0x1000_0000);
            let flags = PageTableFlags::PRESENT
                | PageTableFlags::USER_ACCESSIBLE
                | PageTableFlags::WRITABLE;
            let payload = b"ferrumos phase 1.3 address space round-trip\n";
            match process.map_user(vaddr, payload, flags) {
                Ok(mapped) => {
                    let l4 = process
                        .address_space()
                        .map(|s| s.l4_frame().start_address().as_u64())
                        .unwrap_or(0);
                    let pid = process.pid();
                    ferrumos::process::register(process);
                    println!(
                        "[  OK  ] Sample address space: pid={} L4={:#x} mapped={} bytes",
                        pid, l4, mapped
                    );
                }
                Err(err) => println!("[ WARN ] Sample address space map failed: {:?}", err),
            }
        }
        Err(err) => println!("[ WARN ] Sample address space create failed: {}", err),
    }

    // Phase 1.4: build the ring-3 init process, load the embedded
    // ELF, register it so the shell can introspect it via `process`
    // and dispatch into it via `ring3`. We do NOT enter ring 3
    // automatically — the operator types `ring3 init` (or just
    // `ring3`) when they want to dispatch.
    match ferrumos::process::create("init") {
        Ok(mut process) => match process.load_elf(ferrumos::userspace::INIT_ELF) {
            Ok(entry) => {
                let pid = process.pid();
                let user_rsp = process.user_stack_top().as_u64();
                let kernel_rsp = process.kernel_stack_top().as_u64();
                ferrumos::process::register(process);
                println!(
                    "[  OK  ] Ring-3 init loaded: pid={} entry={:#x} user_rsp={:#x} kernel_rsp0={:#x}",
                    pid, entry, user_rsp, kernel_rsp
                );
            }
            Err(err) => println!("[ WARN ] init load_elf failed: {}", err),
        },
        Err(err) => println!("[ WARN ] init process create failed: {}", err),
    }

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
    println!("[ OK ] Device registry initialized");
    println!("[ OK ] Capability security initialized");
    println!("[ OK ] Service manager initialized");
    println!("[ OK ] Network subsystem initialized");
    println!("[ OK ] Userspace registry initialized");
    println!("[ OK ] Task scheduler initialized");
    println!("[ OK ] Userspace init launched");
    println!();
    println!("Kernel boundary: deterministic; AI runs in runtime services.");
    println!("Heliox-OS JSON-RPC bridge registered (try 'heliox status').");
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
