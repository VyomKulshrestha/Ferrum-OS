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

/// ATA PIO disk driver
/// IDE primary/secondary channel access for persistent storage
pub mod ata;

/// Graphics subsystem
/// VGA framebuffer, bitmap font rendering, and graphical text console
pub mod graphics;

// ============================================================================
// Global Descriptor Table
// ============================================================================

/// GDT module - manages segment descriptors and TSS
pub mod gdt;

// ============================================================================
// Kernel Initialization
// ============================================================================

/// Initialize core kernel hardware
/// 
/// This sets up the GDT, IDT, and enables hardware interrupts.
/// Must be called before any interrupt-dependent subsystem.
pub fn init() {
    gdt::init();
    interrupts::init_idt();
    unsafe { interrupts::PICS.lock().initialize() };
    x86_64::instructions::interrupts::enable();
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
