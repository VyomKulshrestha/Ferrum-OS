// ============================================================================
// FerrumOS - Kernel Library Root
// ============================================================================
// This is the central library that exposes all kernel subsystems.
// Each subsystem is a separate module with clear boundaries.
//
// Module Organization:
//   vga        - VGA text mode display driver
//   serial     - Serial port (UART) output for debugging
//   interrupts - IDT, exception handlers, hardware interrupts
//   memory     - Physical/virtual memory management, heap
//   scheduler  - Cooperative task scheduler
//   shell      - Interactive kernel shell
//   fs         - RAM-based filesystem
//   security   - Capability-based security model
//   services   - Modular runtime service manager
//   logging    - Kernel logging and audit trail
// ============================================================================

#![no_std]
#![cfg_attr(test, no_main)]
#![feature(custom_test_frameworks)]
#![test_runner(crate::test_runner)]
#![reexport_test_harness_main = "test_main"]
#![feature(abi_x86_interrupt)]

extern crate alloc;

// ============================================================================
// Kernel Subsystem Modules
// ============================================================================

/// VGA text mode display driver
/// Provides direct framebuffer access for text output
pub mod vga;

/// Serial port driver (UART 16550)
/// Used for debug output to QEMU's serial console
pub mod serial;

/// Interrupt Descriptor Table and hardware interrupt handling
/// Manages CPU exceptions and IRQ routing
pub mod interrupts;

/// Memory management subsystem
/// Physical frame allocation, virtual memory mapping, kernel heap
pub mod memory;

/// Task scheduler
/// Cooperative round-robin scheduling with task state management
pub mod scheduler;

/// Interactive kernel shell
/// Command-line interface with built-in system commands
pub mod shell;

/// Filesystem abstraction and RAM filesystem implementation
/// In-memory hierarchical file/directory storage
pub mod fs;

/// Kernel device registry and early HAL inventory
/// Tracks online and planned device driver surfaces
pub mod devices;

/// Security subsystem
/// Capability-based permissions and sandbox enforcement
pub mod security;

/// Modular runtime service manager
/// Lifecycle management for kernel and userspace services
pub mod services;

/// IPC contracts for runtime services
/// Kernel-owned deterministic message metadata for future service transport
pub mod ipc;

/// Volatile, capability-gated clipboard shared by desktop applications.
pub mod clipboard;

/// Bounded capability-gated desktop notification history.
pub mod notification;

/// Network subsystem
/// Provides loopback networking and interface state before NIC drivers exist
pub mod net;

/// ACPI implementation
/// ACPI table parsing and hardware configuration
pub mod acpi;

/// Synchronization primitives
pub mod sync;

/// Symmetric Multiprocessing (SMP)
/// Booting APs and per-CPU state
pub mod smp;

/// Syscall ABI definitions for future userspace processes
/// Defines stable syscall numbers and result codes before usermode exists
pub mod syscall;

/// Userspace process registry
/// Tracks program manifests and process capabilities before ring-3 execution
pub mod userspace;

/// Package manager (ferrumpkg) - install/remove/list for packages staged
/// on the appliance disk, gating what `sys_exec` will run (src/syscall/process.rs)
pub mod pkg;

/// Multi-user account registry - real usernames/uids/home directories/
/// capability profiles, persisted to disk (src/shell/commands.rs's
/// `login`/`useradd`/`whoami` are the user-facing surface)
pub mod accounts;

/// ELF64 binary parser
/// Minimal header and program-header parser used by the future userspace
/// loader (Phase 1.4). Pure, allocation-light, no_std-compatible.
pub mod elf;

/// Per-process address space
/// Allocates a fresh P4 page table for each user process and seeds it
/// with the kernel's upper-half mappings. Used by the future ring-3
/// loader (Phase 1.4).
pub mod process;

/// Agent runtime service boundary
/// Minimal deterministic bridge for the future agent runtime runtime
pub mod agent;

/// Heliox-OS integration boundary
/// JSON-RPC 2.0 contracts, method registry, permission tiers, and runtime
/// service topology required to host a Heliox-compatible agent runtime above
/// the FerrumOS kernel.
pub mod heliox;

/// Logging and audit trail
/// Structured kernel logging with security audit events
pub mod logging;

/// Hardware identification and tier classification
pub mod hardware;

/// ATA PIO disk driver
/// IDE primary/secondary channel access for persistent storage
pub mod ata;

/// Graphics subsystem
/// VGA framebuffer, bitmap font rendering, and graphical text console
pub mod graphics;

/// Audio subsystem
/// Intel HDA driver, PCM playback/recording, and audio format handling
pub mod audio;

/// Input subsystem
/// Unified keyboard/mouse event queue, input injection for agent automation
pub mod input;

/// Graphical Desktop Environment
/// Window manager, compositor, and graphical shell interface
pub mod gui;

// ============================================================================
// Global Descriptor Table
// ============================================================================

/// GDT module - manages segment descriptors and TSS
pub mod gdt;

/// SMEP and SMAP: CR4 bits, the user-access window, the ring-0 fault probe
pub mod cpu_protect;

// ============================================================================
// Kernel Initialization
// ============================================================================

pub fn init() {
    gdt::init();
    interrupts::init_idt();
    unsafe { interrupts::PICS.lock().initialize() };
    // Unmask only the lines that have a handler: timer, keyboard and the
    // cascade on the master; the ATA channels on the slave (the mouse driver
    // unmasks IRQ 12 itself). An interrupt on any other line used to arrive
    // at a vector with no gate, which ends in a double fault.
    unsafe { interrupts::PICS.lock().write_masks(0xF8, 0x3F) };
    // Auto-EOI on the master 8259: the timer handler no longer writes an EOI
    // on every tick (fi1 kernel round 3 measured the median timer interrupt
    // at 61,610 TSC cycles with the EOI write and 37,539 without, five boots;
    // `test-syscall pic-aeoi-off` switches back for comparison).
    interrupts::set_pic_auto_eoi(true);
    interrupts::init_pit();
    unsafe { enable_sse_extensions() };
    // SMEP and SMAP wherever CPUID reports them (fi2 K1). Before this, CR4
    // bits 20 and 21 were never set: a kernel bug that jumped to or followed
    // a user pointer was not stopped by the CPU.
    let (smep, smap) = cpu_protect::enable();
    println!(
        "[  OK  ] CPU protections: smep={} smap={} (cpuid smep={} smap={})",
        smep,
        smap,
        cpu_protect::CPU_HAS_SMEP.load(core::sync::atomic::Ordering::SeqCst),
        cpu_protect::CPU_HAS_SMAP.load(core::sync::atomic::Ordering::SeqCst)
    );
    x86_64::instructions::interrupts::enable();
}

/// Enable SSE and AVX extensions in CPU control registers if supported.
/// This enables legacy FPU, SSE registers, FXSAVE/FXRSTOR support,
/// and AVX register state management.
pub unsafe fn enable_sse_extensions() {
    // 1. Enable legacy FPU & SSE in CR0 by clearing EM and setting MP, and
    // set NE (bit 5): an unmasked x87 error raises #MF in the process that
    // caused it. With NE clear the error went to the legacy FERR#/IRQ 13
    // line, which is masked, and the process ran on with the error pending
    // (fi1 kernel round 4; fi2 K1 item 6).
    core::arch::asm!(
        "mov rax, cr0",
        "and ax, 0xFFFB", // clear EM (bit 2)
        "or ax, 0x0022",  // set MP (bit 1) and NE (bit 5)
        "mov cr0, rax",
        out("rax") _,
    );

    // 2. Enable FXSAVE/FXRSTOR and SIMD exceptions in CR4
    core::arch::asm!(
        "mov rax, cr4",
        "or eax, 0x600",  // set OSFXSR (bit 9) and OSXMMEXCPT (bit 10)
        "mov cr4, rax",
        out("rax") _,
    );

    // 3. Enable AVX if supported by the hardware. With AVX on, a task's
    // vector state is larger than the FXSAVE area (the upper halves of the
    // YMM registers are not in it), so the scheduler then saves and restores
    // with XSAVE/XRSTOR into an area of the size CPUID leaf 0xD reports
    // (`scheduler::enable_xsave`). It used to save only the FXSAVE area: the
    // YMM upper halves passed from one process to the next (fi1 kernel round
    // 4, finding 1). The daemon's local inference uses AVX2.
    let cpuid_1 = core::arch::x86_64::__cpuid(1);
    let avx_supported = (cpuid_1.ecx & (1 << 28)) != 0 && (cpuid_1.ecx & (1 << 26)) != 0;
    if avx_supported {
        core::arch::asm!(
            "mov rax, cr4",
            "or eax, 1 << 18", // OSXSAVE (bit 18)
            "mov cr4, rax",
            "xor ecx, ecx",    // XCR0 index
            "xgetbv",          // read XCR0
            "or eax, 0x6",     // SSE (bit 1) & AVX (bit 2)
            "xsetbv",          // write back to XCR0
            out("rax") _,
            out("rcx") _,
            out("rdx") _,
        );
        // Bytes XSAVE writes for the features now enabled in XCR0: the end
        // of the furthest enabled component (CPUID.(0xD,i): EAX size, EBX
        // offset). CPUID.(0xD,0).EBX alone is not enough: under WHPX it
        // reports 576 (legacy area and header only) with XCR0 = 7, and XSAVE
        // then wrote 256 bytes past every task's area into the next heap
        // object (fi1 kernel round 4, image A).
        let xcr0_lo: u32;
        core::arch::asm!("xgetbv", in("ecx") 0u32, out("eax") xcr0_lo, out("edx") _);
        let mut size = (core::arch::x86_64::__cpuid_count(0xD, 0).ebx as usize).max(576);
        for component in 2..32u32 {
            if xcr0_lo & (1 << component) != 0 {
                let leaf = core::arch::x86_64::__cpuid_count(0xD, component);
                size = size.max(leaf.ebx as usize + leaf.eax as usize);
            }
        }
        scheduler::enable_xsave(size);
    }
}


// ============================================================================
// CPU Control
// ============================================================================

/// Energy-efficient halt loop
/// 
/// Halts the CPU between interrupts instead of busy-spinning.
/// This is the standard way to wait for interrupts in x86.
pub fn hlt_loop() -> ! {
    loop {
        x86_64::instructions::hlt();
    }
}

// ============================================================================
// Test Framework
// ============================================================================

/// Trait for test functions that can report their name
pub trait Testable {
    fn run(&self);
}

impl<T: Fn()> Testable for T {
    fn run(&self) {
        serial_print!("test {} ... ", core::any::type_name::<T>());
        self();
        serial_println!("[ok]");
    }
}

/// Test runner - executes all registered tests and exits QEMU
pub fn test_runner(tests: &[&dyn Testable]) {
    serial_println!("Running {} tests", tests.len());
    for test in tests {
        test.run();
    }
    exit_qemu(QemuExitCode::Success);
}

/// Panic handler for test mode - prints error and exits QEMU
pub fn test_panic_handler(info: &core::panic::PanicInfo) -> ! {
    serial_println!("[failed]");
    serial_println!("Error: {}", info);
    exit_qemu(QemuExitCode::Failed);
    hlt_loop();
}

/// Panic handler for library tests.
#[cfg(test)]
#[panic_handler]
fn panic(info: &core::panic::PanicInfo) -> ! {
    test_panic_handler(info)
}

/// QEMU exit codes for automated testing
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u32)]
pub enum QemuExitCode {
    Success = 0x10,
    Failed = 0x11,
}

/// Exit QEMU with the given exit code
/// 
/// Writes to the QEMU debug exit device at port 0xf4
pub fn exit_qemu(exit_code: QemuExitCode) {
    use x86_64::instructions::port::Port;
    unsafe {
        let mut port = Port::new(0xf4);
        port.write(exit_code as u32);
    }
}
