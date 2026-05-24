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

/// Security subsystem
/// Capability-based permissions and sandbox enforcement
pub mod security;

/// Modular runtime service manager
/// Lifecycle management for kernel and userspace services
pub mod services;

/// IPC contracts for runtime services
/// Kernel-owned deterministic message metadata for future service transport
pub mod ipc;

/// Syscall ABI definitions for future userspace processes
/// Defines stable syscall numbers and result codes before usermode exists
pub mod syscall;

/// Agent runtime service boundary
/// Minimal deterministic bridge for the future agent runtime runtime
pub mod agent;

/// Logging and audit trail
/// Structured kernel logging with security audit events
pub mod logging;

// ============================================================================
// Global Descriptor Table
// ============================================================================

/// GDT module - manages segment descriptors and TSS
pub mod gdt {
    use x86_64::structures::tss::TaskStateSegment;
    use x86_64::structures::gdt::{GlobalDescriptorTable, Descriptor, SegmentSelector};
    use x86_64::VirtAddr;
    use lazy_static::lazy_static;

    /// Index of the IST entry used for double fault handling
    /// Using a separate stack prevents triple faults from stack overflow
    pub const DOUBLE_FAULT_IST_INDEX: u16 = 0;

    /// Size of the double fault handler stack (5 pages = 20KB)
    const STACK_SIZE: usize = 4096 * 5;

    lazy_static! {
        /// Task State Segment - configures interrupt stack table
        /// 
        /// The IST provides dedicated stacks for critical exception handlers,
        /// ensuring that stack overflow in the kernel doesn't cause triple faults.
        static ref TSS: TaskStateSegment = {
            let mut tss = TaskStateSegment::new();
            tss.interrupt_stack_table[DOUBLE_FAULT_IST_INDEX as usize] = {
                // Safety: Static mutable access is safe here because this only
                // runs once during initialization
                static mut STACK: [u8; STACK_SIZE] = [0; STACK_SIZE];
                #[allow(static_mut_refs)]
                let stack_start = VirtAddr::from_ptr(unsafe { &STACK });
                let stack_end = stack_start + STACK_SIZE as u64;
                stack_end // Stack grows downward
            };
            tss
        };
    }

    lazy_static! {
        /// Global Descriptor Table with kernel code/data segments and TSS
        static ref GDT: (GlobalDescriptorTable, Selectors) = {
            let mut gdt = GlobalDescriptorTable::new();
            let code_selector = gdt.append(Descriptor::kernel_code_segment());
            let tss_selector = gdt.append(Descriptor::tss_segment(&TSS));
            (gdt, Selectors { code_selector, tss_selector })
        };
    }

    /// Segment selectors for the kernel code segment and TSS
    struct Selectors {
        code_selector: SegmentSelector,
        tss_selector: SegmentSelector,
    }

    /// Initialize the GDT and load segment registers
    /// 
    /// This must be called before interrupts are enabled.
    pub fn init() {
        use x86_64::instructions::tables::load_tss;
        use x86_64::instructions::segmentation::{CS, Segment};

        GDT.0.load();
        unsafe {
            CS::set_reg(GDT.1.code_selector);
            load_tss(GDT.1.tss_selector);
        }
    }
}

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
