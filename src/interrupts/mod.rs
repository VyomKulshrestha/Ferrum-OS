// ============================================================================
// FerrumOS — Interrupt Handling Subsystem
// ============================================================================
// Manages the Interrupt Descriptor Table (IDT) and hardware interrupt routing.
//
// Architecture:
//   - CPU Exceptions (0-31): Page fault, double fault, etc.
//   - Hardware IRQs (32-47): Timer, keyboard via 8259 PIC
//   - System calls (future): Software interrupts for userspace
//
// The PIC is configured with standard offset 32 for IRQ remapping.
// ============================================================================

use crate::gdt;
use crate::println;
use lazy_static::lazy_static;
use pic8259::ChainedPics;
use spin;
use x86_64::structures::idt::{InterruptDescriptorTable, InterruptStackFrame, PageFaultErrorCode};

/// PIC1 starts at interrupt vector 32 (after CPU exceptions)
pub const PIC_1_OFFSET: u8 = 32;
/// PIC2 starts at interrupt vector 40
pub const PIC_2_OFFSET: u8 = PIC_1_OFFSET + 8;

/// Chained 8259 PIC configuration
/// 
/// PIC1 handles IRQs 0-7 (vectors 32-39)
/// PIC2 handles IRQs 8-15 (vectors 40-47)
pub static PICS: spin::Mutex<ChainedPics> = spin::Mutex::new(
    unsafe { ChainedPics::new(PIC_1_OFFSET, PIC_2_OFFSET) }
);

/// Hardware interrupt vector assignments
#[derive(Debug, Clone, Copy)]
#[repr(u8)]
pub enum InterruptIndex {
    Timer = PIC_1_OFFSET,       // IRQ 0 — PIT timer
    Keyboard = PIC_1_OFFSET + 1, // IRQ 1 — PS/2 keyboard
}

impl InterruptIndex {
    fn as_u8(self) -> u8 {
        self as u8
    }
}

lazy_static! {
    /// The Interrupt Descriptor Table
    /// 
    /// Maps interrupt vectors to their handler functions.
    /// Critical exceptions use separate stacks via the IST to prevent
    /// triple faults from stack overflow.
    static ref IDT: InterruptDescriptorTable = {
        let mut idt = InterruptDescriptorTable::new();
        
        // CPU Exception Handlers
        idt.breakpoint.set_handler_fn(breakpoint_handler);
        unsafe {
            idt.double_fault
                .set_handler_fn(double_fault_handler)
                .set_stack_index(gdt::DOUBLE_FAULT_IST_INDEX);
        }
        idt.page_fault.set_handler_fn(page_fault_handler);
        idt.general_protection_fault.set_handler_fn(general_protection_fault_handler);
        idt.invalid_opcode.set_handler_fn(invalid_opcode_handler);
        idt.overflow.set_handler_fn(overflow_handler);
        
        // Hardware Interrupt Handlers  
        idt[InterruptIndex::Timer.as_u8()]
            .set_handler_fn(timer_interrupt_handler);
        idt[InterruptIndex::Keyboard.as_u8()]
            .set_handler_fn(keyboard_interrupt_handler);
        
        idt
    };
}

/// Load the IDT into the CPU
pub fn init_idt() {
    IDT.load();
}

// ============================================================================
// CPU Exception Handlers
// ============================================================================

/// Breakpoint exception handler (INT 3)
/// 
/// Triggered by the `int3` instruction. Used for debugging.
extern "x86-interrupt" fn breakpoint_handler(stack_frame: InterruptStackFrame) {
    println!("[EXCEPTION] Breakpoint\n{:#?}", stack_frame);
}

/// Double fault handler
/// 
/// Triggered when the CPU fails to invoke an exception handler.
/// This runs on a separate stack (IST) to handle stack overflow scenarios.
/// A double fault is always fatal — the system cannot continue.
extern "x86-interrupt" fn double_fault_handler(
    stack_frame: InterruptStackFrame,
    _error_code: u64,
) -> ! {
    panic!("DOUBLE FAULT\n{:#?}", stack_frame);
}

/// Page fault handler
/// 
/// Triggered by invalid memory accesses:
/// - Reading from unmapped pages
/// - Writing to read-only pages
/// - Executing non-executable pages
extern "x86-interrupt" fn page_fault_handler(
    stack_frame: InterruptStackFrame,
    error_code: PageFaultErrorCode,
) {
    use x86_64::registers::control::Cr2;

    println!("[EXCEPTION] Page Fault");
    println!("  Accessed Address: {:?}", Cr2::read());
    println!("  Error Code: {:?}", error_code);
    println!("{:#?}", stack_frame);
    
    // Log the page fault for security auditing
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::SecurityViolation,
        "Page fault occurred — potential memory violation",
    );
    
    crate::hlt_loop();
}

/// General protection fault handler
/// 
/// Triggered by privilege violations, segment errors, etc.
extern "x86-interrupt" fn general_protection_fault_handler(
    stack_frame: InterruptStackFrame,
    error_code: u64,
) {
    println!("[EXCEPTION] General Protection Fault");
    println!("  Error Code: {}", error_code);
    println!("{:#?}", stack_frame);
    
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::SecurityViolation,
        "General protection fault — privilege violation",
    );
    
    crate::hlt_loop();
}

/// Invalid opcode handler
extern "x86-interrupt" fn invalid_opcode_handler(stack_frame: InterruptStackFrame) {
    println!("[EXCEPTION] Invalid Opcode\n{:#?}", stack_frame);
    crate::hlt_loop();
}

/// Overflow exception handler
extern "x86-interrupt" fn overflow_handler(stack_frame: InterruptStackFrame) {
    println!("[EXCEPTION] Overflow\n{:#?}", stack_frame);
}

// ============================================================================
// Hardware Interrupt Handlers
// ============================================================================

/// Timer interrupt handler (IRQ 0)
/// 
/// The PIT fires approximately 18.2 times per second by default.
/// This is used to drive the task scheduler.
extern "x86-interrupt" fn timer_interrupt_handler(_stack_frame: InterruptStackFrame) {
    // Tick the scheduler (if initialized)
    crate::scheduler::tick();
    
    // Send End-of-Interrupt to the PIC
    unsafe {
        PICS.lock().notify_end_of_interrupt(InterruptIndex::Timer.as_u8());
    }
}

/// Keyboard buffer for shell input
/// 
/// Keyboard scancodes are queued here and consumed by the shell.
static KEYBOARD_QUEUE: spin::Mutex<Option<alloc::collections::VecDeque<u8>>> = 
    spin::Mutex::new(None);

/// Initialize the keyboard queue (must be called after heap init)
pub fn init_keyboard_queue() {
    *KEYBOARD_QUEUE.lock() = Some(alloc::collections::VecDeque::with_capacity(64));
}

/// Read a character from the keyboard queue
pub fn read_keyboard() -> Option<u8> {
    let mut queue = KEYBOARD_QUEUE.lock();
    queue.as_mut().and_then(|q| q.pop_front())
}

/// Keyboard interrupt handler (IRQ 1)
/// 
/// Reads PS/2 scancodes and translates them to ASCII characters.
/// Characters are queued for the shell to consume.
extern "x86-interrupt" fn keyboard_interrupt_handler(_stack_frame: InterruptStackFrame) {
    use x86_64::instructions::port::Port;
    
    // Read scancode from PS/2 keyboard data port
    let mut port = Port::new(0x60);
    let scancode: u8 = unsafe { port.read() };
    
    // Simple scancode-to-ASCII translation (US QWERTY, Set 1)
    // Only key-down events (high bit clear)
    if scancode & 0x80 == 0 {
        let ascii = scancode_to_ascii(scancode);
        if let Some(ch) = ascii {
            let mut queue = KEYBOARD_QUEUE.lock();
            if let Some(ref mut q) = *queue {
                q.push_back(ch);
            }
        }
    }
    
    unsafe {
        PICS.lock().notify_end_of_interrupt(InterruptIndex::Keyboard.as_u8());
    }
}

/// Convert PS/2 Set 1 scancode to ASCII character
/// 
/// This is a simplified mapping for US QWERTY layout.
/// A full implementation would handle shift, caps lock, etc.
fn scancode_to_ascii(scancode: u8) -> Option<u8> {
    // Shift state tracking
    static SHIFT_PRESSED: spin::Mutex<bool> = spin::Mutex::new(false);
    
    match scancode {
        // Shift pressed
        0x2A | 0x36 => {
            *SHIFT_PRESSED.lock() = true;
            None
        }
        // Shift released (key-up codes handled separately)
        0xAA | 0xB6 => {
            *SHIFT_PRESSED.lock() = false;
            None
        }
        _ => {
            let _shift = *SHIFT_PRESSED.lock();
            match scancode {
                0x01 => Some(0x1B), // Escape
                0x02 => Some(b'1'),
                0x03 => Some(b'2'),
                0x04 => Some(b'3'),
                0x05 => Some(b'4'),
                0x06 => Some(b'5'),
                0x07 => Some(b'6'),
                0x08 => Some(b'7'),
                0x09 => Some(b'8'),
                0x0A => Some(b'9'),
                0x0B => Some(b'0'),
                0x0C => Some(b'-'),
                0x0D => Some(b'='),
                0x0E => Some(0x08), // Backspace
                0x0F => Some(b'\t'),
                0x10 => Some(b'q'),
                0x11 => Some(b'w'),
                0x12 => Some(b'e'),
                0x13 => Some(b'r'),
                0x14 => Some(b't'),
                0x15 => Some(b'y'),
                0x16 => Some(b'u'),
                0x17 => Some(b'i'),
                0x18 => Some(b'o'),
                0x19 => Some(b'p'),
                0x1A => Some(b'['),
                0x1B => Some(b']'),
                0x1C => Some(b'\n'), // Enter
                0x1E => Some(b'a'),
                0x1F => Some(b's'),
                0x20 => Some(b'd'),
                0x21 => Some(b'f'),
                0x22 => Some(b'g'),
                0x23 => Some(b'h'),
                0x24 => Some(b'j'),
                0x25 => Some(b'k'),
                0x26 => Some(b'l'),
                0x27 => Some(b';'),
                0x28 => Some(b'\''),
                0x29 => Some(b'`'),
                0x2B => Some(b'\\'),
                0x2C => Some(b'z'),
                0x2D => Some(b'x'),
                0x2E => Some(b'c'),
                0x2F => Some(b'v'),
                0x30 => Some(b'b'),
                0x31 => Some(b'n'),
                0x32 => Some(b'm'),
                0x33 => Some(b','),
                0x34 => Some(b'.'),
                0x35 => Some(b'/'),
                0x39 => Some(b' '), // Space
                _ => None,
            }
        }
    }
}

extern crate alloc;
