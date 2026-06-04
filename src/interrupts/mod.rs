// ============================================================================
// FerrumOS - Interrupt Handling Subsystem
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
    Timer = PIC_1_OFFSET,       // IRQ 0 - PIT timer
    Keyboard = PIC_1_OFFSET + 1, // IRQ 1 - PS/2 keyboard
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

        // System call entry point used by ring-3 code in Phase 1.4.
        // The handler reads the syscall number from rax and returns
        // a result in rax; only `SYS_WRITE` (1), `SYS_EXIT` (60),
        // `SYS_YIELD` (24), and `SYS_AUDIT_WRITE` (200) are
        // recognised today. Every other number is acknowledged
        // and returns -ENOSYS so the user process can degrade
        // gracefully.
        idt[SYSCALL_VECTOR]
            .set_handler_fn(syscall_interrupt_handler);

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
/// A double fault is always fatal - the system cannot continue.
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
        "Page fault occurred - potential memory violation",
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
        "General protection fault - privilege violation",
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

// ============================================================================
// Software System Call (INT 0x80)
// ============================================================================
//
// Phase 1.4 of the v0.2 completion roadmap wires the user process to the
// kernel through a single software interrupt. The handler reads the
// syscall number from rax and dispatches on it. Only a tiny subset is
// implemented today; future phases will add IPC, networking, and
// audit-log syscalls.

/// Software interrupt vector reserved for system calls. Kept well
/// above the PIC range (32..48) and below the CPU exception range.
pub const SYSCALL_VECTOR: u8 = 0x80;

/// Syscall numbers recognised by the kernel. The values match the
/// Linux x86_64 numbers for the calls we have actually
/// implemented, which keeps the door open for "compat" code
/// later without renumbering.
pub mod syscall_number {
    pub const SYS_WRITE: u64 = 1;
    pub const SYS_EXIT: u64 = 60;
    pub const SYS_YIELD: u64 = 24;
    pub const SYS_SLEEP: u64 = 35;
    pub const SYS_WAIT: u64 = 61;
    pub const SYS_AUDIT_WRITE: u64 = 200;
}

/// Return code used when a syscall number is not recognised. The
/// negative encoding is the same as Linux (top half of u64 is
/// 0xFFFF_FFFF_FFFF...).
const ENOSYS: u64 = u64::MAX - 38;
const EPERM: u64 = u64::MAX - 0;

/// Ring-3 system call entry. The kernel trampoline pushed the
/// user-mode SS/RSP/RFLAGS/CS/RIP on the way in, so the
/// `InterruptStackFrame` reflects the user stack at the time of
/// the `int 0x80` instruction.
extern "x86-interrupt" fn syscall_interrupt_handler(stack_frame: InterruptStackFrame) {
    use crate::serial::SERIAL1;

    let syscall_no: u64;
    let arg0: u64;
    let arg1: u64;
    let arg2: u64;
    // Safety: we are in a privileged interrupt handler, and the
    // user process gave us rax/rdi/rsi/rdx via the standard
    // SysV-style ABI. We do not trust the user pointer values
    // for the write path beyond their length.
    unsafe {
        core::arch::asm!(
            "mov {0}, rax",
            "mov {1}, rdi",
            "mov {2}, rsi",
            "mov {3}, rdx",
            out(reg) syscall_no,
            out(reg) arg0,
            out(reg) arg1,
            out(reg) arg2,
            options(nostack, preserves_flags),
        );
    }

    let result = match syscall_no {
        syscall_number::SYS_WRITE => {
            // Arg0 = user pointer to bytes, arg1 = length,
            // arg2 = file descriptor. We only support fd=1
            // (stdout -> COM1). The user pointer is trusted
            // because it points into the process's own user
            // half (which the kernel can read via the
            // phys_to_virt alias) but we still need to copy
            // it out before writing so we do not hold a
            // reference into the user mapping across the
            // serial write.
            if arg2 != 1 {
                EPERM
            } else {
                let len = arg1.min(4096);
                let mut buf = [0u8; 256];
                let take = len.min(buf.len() as u64) as usize;
                // Safety: user pointer is part of the
                // process's own user half. We only read up to
                // `take` bytes.
                let src = arg0 as *const u8;
                unsafe {
                    core::ptr::copy_nonoverlapping(src, buf.as_mut_ptr(), take);
                }
                use core::fmt::Write;
                let mut serial = SERIAL1.lock();
                let _ = serial.write_str(
                    core::str::from_utf8(&buf[..take]).unwrap_or(""),
                );
                take as u64
            }
        }
        syscall_number::SYS_AUDIT_WRITE => {
            // Arg0 = user pointer to a null-terminated UTF-8
            // string the user process wants appended to the
            // kernel audit log. We cap the read at 256 bytes.
            if arg0 == 0 {
                EPERM
            } else {
                let mut buf = [0u8; 256];
                let mut i = 0;
                unsafe {
                    while i < buf.len() {
                        let byte = core::ptr::read_volatile(
                            (arg0 + i as u64) as *const u8,
                        );
                        if byte == 0 {
                            break;
                        }
                        buf[i] = byte;
                        i += 1;
                    }
                    let s = core::str::from_utf8_unchecked(&buf[..i]);
                    crate::logging::audit::log_event(
                        crate::logging::audit::AuditEvent::SecurityViolation,
                        s,
                    );
                }
                0
            }
        }
        syscall_number::SYS_EXIT => {
            // Mark the current task dead and pick the next
            // runnable task. If there is none, halt (this
            // is the original Phase 1.4 behaviour, which
            // the `ring3` sweep test relies on).
            let reaped = crate::scheduler::exit_current();
            if reaped {
                if let Some(next_pid) = crate::scheduler::schedule_next() {
                    if let Some((kstack, _cr3)) =
                        crate::scheduler::switch_target(next_pid)
                    {
                        unsafe {
                            crate::gdt::set_kernel_stack(
                                x86_64::VirtAddr::new(kstack),
                            );
                        }
                        let scratch = crate::scheduler::scratch_context()
                            as *mut crate::scheduler::TaskContext;
                        // The incoming task's context has
                        // never been populated for a
                        // freshly-spawned user task, so
                        // there is nothing to load. The
                        // switch will write garbage into
                        // the incoming iretq frame, which
                        // is fine because the only safe
                        // destination is a task that has
                        // its iretq frame on the stack
                        // from a previous interrupt. In
                        // the single-task case the
                        // run-queue is empty and we fall
                        // through to `hlt_loop()`.
                        unsafe {
                            crate::scheduler::context_switch_to(
                                scratch,
                                scratch,
                                kstack,
                            );
                        }
                    }
                }
            }
            crate::hlt_loop();
        }
        syscall_number::SYS_YIELD => {
            // Cooperative yield. If the run-queue is empty
            // (the single-task case the `ring3` test uses)
            // we just return 0.
            if crate::scheduler::yield_current() {
                if let Some(next_pid) = crate::scheduler::schedule_next() {
                    if let Some((kstack, _cr3)) =
                        crate::scheduler::switch_target(next_pid)
                    {
                        unsafe {
                            crate::gdt::set_kernel_stack(
                                x86_64::VirtAddr::new(kstack),
                            );
                        }
                        let scratch = crate::scheduler::scratch_context()
                            as *mut crate::scheduler::TaskContext;
                        unsafe {
                            crate::scheduler::context_switch_to(
                                scratch,
                                scratch,
                                kstack,
                            );
                        }
                    }
                }
            }
            0
        }
        syscall_number::SYS_SLEEP => {
            // Arg0 = milliseconds. Convert to PIT ticks
            // (PIT fires ~18.2 Hz → ~55 ms per tick, round
            // up so a non-zero ms always sleeps at least
            // one tick).
            if arg0 == 0 {
                0
            } else {
                let ticks = arg0.div_ceil(55).max(1);
                if crate::scheduler::sleep_current(ticks) {
                    if let Some(next_pid) = crate::scheduler::schedule_next() {
                        if let Some((kstack, _cr3)) =
                            crate::scheduler::switch_target(next_pid)
                        {
                            unsafe {
                                crate::gdt::set_kernel_stack(
                                    x86_64::VirtAddr::new(kstack),
                                );
                            }
                            let scratch =
                                crate::scheduler::scratch_context()
                                    as *mut crate::scheduler::TaskContext;
                            unsafe {
                                crate::scheduler::context_switch_to(
                                    scratch,
                                    scratch,
                                    kstack,
                                );
                            }
                        }
                    }
                    // No other task: idle until the next
                    // PIT tick re-evaluates the run-queue.
                    crate::hlt_loop();
                }
                0
            }
        }
        syscall_number::SYS_WAIT => {
            // Arg0 = pid. Phase 2.2 only supports
            // `wait(-1)` ("wait for any child") and
            // `wait(pid)` where the pid is already dead.
            // A live child returns -ECHILD
            // (Linux-compatible: u64::MAX - 10).
            let requested = arg0 as i64;
            let sched = crate::scheduler::list_tasks();
            if requested == -1 {
                if sched.iter().any(|t| {
                    matches!(t.state, crate::scheduler::TaskState::Dead)
                }) {
                    0
                } else {
                    u64::MAX - 10
                }
            } else {
                let pid = requested as u64;
                if sched.iter().any(|t| {
                    t.id == pid
                        && matches!(t.state, crate::scheduler::TaskState::Dead)
                }) {
                    pid
                } else {
                    u64::MAX - 10
                }
            }
        }
        _ => {
            // Unknown syscall: log the user-supplied vector
            // and return -ENOSYS so user code can branch on
            // it.
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::SecurityViolation,
                alloc::format!("unknown syscall rax={:#x}", syscall_no).as_str(),
            );
            ENOSYS
        }
    };

    // Place the result in rax so it is visible to user code
    // when `iretq` returns. We do not change the rest of the
    // GPRs; the kernel ABI contract is "rcx and r11 are
    // clobbered by syscall" but we are using `int` not
    // `syscall` so this does not apply.
    unsafe {
        core::arch::asm!(
            "mov rax, {0}",
            in(reg) result,
            options(nostack, preserves_flags),
        );
    }

    // Suppress the unused warning for `stack_frame` so the
    // debug build still builds. Phase 1.5+ will read
    // `stack_frame.cs` to enforce that we are returning to
    // ring 3.
    let _ = stack_frame;
}

extern crate alloc;
