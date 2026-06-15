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
    Timer = PIC_1_OFFSET,          // IRQ 0 - PIT timer
    Keyboard = PIC_1_OFFSET + 1,   // IRQ 1 - PS/2 keyboard
    Mouse = PIC_1_OFFSET + 12,     // IRQ 12 - PS/2 mouse
    AtaPrimary = PIC_1_OFFSET + 14,  // IRQ 14 - Primary ATA channel
    AtaSecondary = PIC_1_OFFSET + 15, // IRQ 15 - Secondary ATA channel
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
        unsafe {
            idt[InterruptIndex::Timer.as_u8()]
                .set_handler_addr(x86_64::VirtAddr::new(
                    timer_interrupt_entry_stub as *const () as u64,
                ));
        }
        idt[InterruptIndex::Keyboard.as_u8()]
            .set_handler_fn(keyboard_interrupt_handler);
        idt[InterruptIndex::Mouse.as_u8()]
            .set_handler_fn(mouse_interrupt_handler);

        // ATA disk interrupt handlers (IRQ 14 + 15)
        // These acknowledge the interrupt so the PIC does not lock up.
        // The ATA PIO driver uses polling, not IRQ-driven I/O.
        idt[InterruptIndex::AtaPrimary.as_u8()]
            .set_handler_fn(ata_primary_interrupt_handler);
        idt[InterruptIndex::AtaSecondary.as_u8()]
            .set_handler_fn(ata_secondary_interrupt_handler);

        // System call entry point. A naked stub saves the full
        // register file and forwards to the Rust dispatcher; results
        // travel back through the saved rax slot. The gate MUST be
        // DPL 3 — with the default DPL 0, a ring-3 `int 0x80` raises
        // #GP instead of entering the kernel, which made userspace
        // syscalls impossible.
        unsafe {
            idt[SYSCALL_VECTOR]
                .set_handler_addr(x86_64::VirtAddr::new(
                    syscall_entry_stub as *const () as u64,
                ))
                .set_privilege_level(x86_64::PrivilegeLevel::Ring3);
        }

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

fn handle_userspace_fault(fault_name: &str, stack_frame: &InterruptStackFrame) -> bool {
    // In x86_64 0.14.x, SegmentSelector has a privilege_level method, but we can just check the raw bits
    // Actually, x86_64 doesn't have an easy method to extract the raw u16 from SegmentSelector in all versions,
    // so we can use stack_frame.cs.0 if it's public, or just skip the CS check if we can't do it easily,
    // wait, we can just check CURRENT_PID! If CURRENT_PID > 0, it's a userspace task!
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    if pid != 0 {
        use x86_64::registers::control::Cr2;
        let rsp = stack_frame.stack_pointer.as_u64();
        println!("[KERNEL] Userspace process {} caused {}, accessed address={:?}, RIP={:#x}, RSP={:#x}, CS={:?}, terminating.", 
                 pid, fault_name, Cr2::read(), stack_frame.instruction_pointer.as_u64(), rsp, stack_frame.code_segment);
        
        // Print stack contents around RSP (up to 16 words / 128 bytes)
        println!("  Stack dump around RSP:");
        for i in 0..16 {
            let addr = rsp + (i * 8);
            // Check if address is in the kernel stack range to avoid faulting again
            let stack_top = 0x44444444c910u64;
            let stack_bottom = stack_top - 32 * 1024;
            if addr >= stack_bottom && addr < stack_top {
                let val = unsafe { *(addr as *const u64) };
                println!("    {:#x}: {:#x}", addr, val);
            } else {
                println!("    {:#x}: <out of stack bounds>", addr);
            }
        }

        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::SecurityViolation,
            alloc::format!("Userspace process {} terminated due to {} at {:?} (RIP={:#x})", 
                          pid, fault_name, Cr2::read(), stack_frame.instruction_pointer.as_u64()).as_str(),
        );
        // `kill` marks the task Dead, drains it from the run-queues,
        // records exit code 139 (SIGSEGV-style) and clears CURRENT_PID.
        crate::scheduler::kill(pid);

        // Hand the CPU to the next runnable task, idle if sleepers
        // remain, else fall back to the shell. Never returns.
        unsafe { resume_after_death() }
    }
    false
}

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
    if handle_userspace_fault("Page Fault", &stack_frame) {
        return;
    }

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
    if handle_userspace_fault("General Protection Fault", &stack_frame) {
        return;
    }

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
    if handle_userspace_fault("Invalid Opcode", &stack_frame) {
        return;
    }

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

#[unsafe(naked)]
unsafe extern "C" fn timer_interrupt_entry_stub() {
    core::arch::naked_asm!(
        "push rax",
        "push rbx",
        "push rcx",
        "push rdx",
        "push rsi",
        "push rdi",
        "push rbp",
        "push r8",
        "push r9",
        "push r10",
        "push r11",
        "push r12",
        "push r13",
        "push r14",
        "push r15",
        "mov rdi, rsp",
        "call {inner}",
        "pop r15",
        "pop r14",
        "pop r13",
        "pop r12",
        "pop r11",
        "pop r10",
        "pop r9",
        "pop r8",
        "pop rbp",
        "pop rdi",
        "pop rsi",
        "pop rdx",
        "pop rcx",
        "pop rbx",
        "pop rax",
        "iretq",
        inner = sym timer_interrupt_entry_inner,
    );
}

extern "C" fn timer_interrupt_entry_inner(frame: &mut SyscallFrame) {
    // Tick the scheduler (if initialized)
    crate::scheduler::tick();
    
    // Send End-of-Interrupt to the PIC
    unsafe {
        PICS.lock().notify_end_of_interrupt(InterruptIndex::Timer.as_u8());
    }

    // Preempt the current task if it was running in Ring 3 and its time slice has expired.
    if (frame.cs & 3) == 3 {
        let current_pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
        if current_pid != 0 {
            if crate::scheduler::should_preempt(current_pid) {
                unsafe {
                    if crate::scheduler::yield_current() {
                        save_user_context(current_pid, frame);
                        if let Some(next) = crate::scheduler::schedule_next() {
                            if next != current_pid {
                                crate::scheduler::resume_task(next);
                            }
                        }
                    }
                }
            }
        }
    }
}


/// ATA primary channel interrupt handler (IRQ 14)
///
/// Reads the status register to clear the interrupt condition, then
/// sends EOI. The PIO driver uses polling, so this handler only
/// exists to prevent spurious-IRQ lockups.
extern "x86-interrupt" fn ata_primary_interrupt_handler(_stack_frame: InterruptStackFrame) {
    // Read status to acknowledge the interrupt on the drive
    unsafe {
        x86_64::instructions::port::PortReadOnly::<u8>::new(0x1F7).read();
    }
    unsafe {
        PICS.lock().notify_end_of_interrupt(InterruptIndex::AtaPrimary.as_u8());
    }
}

/// ATA secondary channel interrupt handler (IRQ 15)
extern "x86-interrupt" fn ata_secondary_interrupt_handler(_stack_frame: InterruptStackFrame) {
    unsafe {
        x86_64::instructions::port::PortReadOnly::<u8>::new(0x177).read();
    }
    unsafe {
        PICS.lock().notify_end_of_interrupt(InterruptIndex::AtaSecondary.as_u8());
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

/// Push a synthetic character into the keyboard queue.
///
/// Used by the input injection subsystem (`crate::input`) to feed
/// agent-generated keystrokes into the shell. This makes the shell
/// see injected keys exactly as if they came from the PS/2 keyboard.
pub fn push_keyboard(ascii: u8) {
    let mut queue = KEYBOARD_QUEUE.lock();
    if let Some(q) = queue.as_mut() {
        if q.len() < 64 {
            q.push_back(ascii);
        }
    }
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
    if let Some(ch) = scancode_to_ascii(scancode) {
        crate::input::inject_key_event(ch, true);
    }
    
    unsafe {
        PICS.lock().notify_end_of_interrupt(InterruptIndex::Keyboard.as_u8());
    }
}

/// Hardware mouse interrupt handler (IRQ 12)
extern "x86-interrupt" fn mouse_interrupt_handler(_stack_frame: InterruptStackFrame) {
    // Process the mouse input
    crate::devices::ps2_mouse::handle_interrupt();

    // Acknowledge the interrupt to both PICs
    unsafe {
        PICS.lock()
            .notify_end_of_interrupt(InterruptIndex::Mouse.as_u8());
    }
}

/// Convert PS/2 Set 1 scancode to ASCII character
/// 
/// This is a simplified mapping for US QWERTY layout.
fn scancode_to_ascii(scancode: u8) -> Option<u8> {
    // Shift state tracking
    static SHIFT_PRESSED: spin::Mutex<bool> = spin::Mutex::new(false);
    
    match scancode {
        // Shift pressed
        0x2A | 0x36 => {
            *SHIFT_PRESSED.lock() = true;
            None
        }
        // Shift released
        0xAA | 0xB6 => {
            *SHIFT_PRESSED.lock() = false;
            None
        }
        _ => {
            let is_shift = *SHIFT_PRESSED.lock();
            match scancode {
                0x01 => Some(0x1B), // Escape
                0x02 => Some(if is_shift { b'!' } else { b'1' }),
                0x03 => Some(if is_shift { b'@' } else { b'2' }),
                0x04 => Some(if is_shift { b'#' } else { b'3' }),
                0x05 => Some(if is_shift { b'$' } else { b'4' }),
                0x06 => Some(if is_shift { b'%' } else { b'5' }),
                0x07 => Some(if is_shift { b'^' } else { b'6' }),
                0x08 => Some(if is_shift { b'&' } else { b'7' }),
                0x09 => Some(if is_shift { b'*' } else { b'8' }),
                0x0A => Some(if is_shift { b'(' } else { b'9' }),
                0x0B => Some(if is_shift { b')' } else { b'0' }),
                0x0C => Some(if is_shift { b'_' } else { b'-' }),
                0x0D => Some(if is_shift { b'+' } else { b'=' }),
                0x0E => Some(0x08), // Backspace
                0x0F => Some(b'\t'),
                0x10 => Some(if is_shift { b'Q' } else { b'q' }),
                0x11 => Some(if is_shift { b'W' } else { b'w' }),
                0x12 => Some(if is_shift { b'E' } else { b'e' }),
                0x13 => Some(if is_shift { b'R' } else { b'r' }),
                0x14 => Some(if is_shift { b'T' } else { b't' }),
                0x15 => Some(if is_shift { b'Y' } else { b'y' }),
                0x16 => Some(if is_shift { b'U' } else { b'u' }),
                0x17 => Some(if is_shift { b'I' } else { b'i' }),
                0x18 => Some(if is_shift { b'O' } else { b'o' }),
                0x19 => Some(if is_shift { b'P' } else { b'p' }),
                0x1A => Some(if is_shift { b'{' } else { b'[' }),
                0x1B => Some(if is_shift { b'}' } else { b']' }),
                0x1C => Some(b'\n'), // Enter
                0x1E => Some(if is_shift { b'A' } else { b'a' }),
                0x1F => Some(if is_shift { b'S' } else { b's' }),
                0x20 => Some(if is_shift { b'D' } else { b'd' }),
                0x21 => Some(if is_shift { b'F' } else { b'f' }),
                0x22 => Some(if is_shift { b'G' } else { b'g' }),
                0x23 => Some(if is_shift { b'H' } else { b'h' }),
                0x24 => Some(if is_shift { b'J' } else { b'j' }),
                0x25 => Some(if is_shift { b'K' } else { b'k' }),
                0x26 => Some(if is_shift { b'L' } else { b'l' }),
                0x27 => Some(if is_shift { b':' } else { b';' }),
                0x28 => Some(if is_shift { b'"' } else { b'\'' }),
                0x29 => Some(if is_shift { b'~' } else { b'`' }),
                0x2B => Some(if is_shift { b'|' } else { b'\\' }),
                0x2C => Some(if is_shift { b'Z' } else { b'z' }),
                0x2D => Some(if is_shift { b'X' } else { b'x' }),
                0x2E => Some(if is_shift { b'C' } else { b'c' }),
                0x2F => Some(if is_shift { b'V' } else { b'v' }),
                0x30 => Some(if is_shift { b'B' } else { b'b' }),
                0x31 => Some(if is_shift { b'N' } else { b'n' }),
                0x32 => Some(if is_shift { b'M' } else { b'm' }),
                0x33 => Some(if is_shift { b'<' } else { b',' }),
                0x34 => Some(if is_shift { b'>' } else { b'.' }),
                0x35 => Some(if is_shift { b'?' } else { b'/' }),
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

/// Saved register file pushed by `syscall_entry_stub` on the way into
/// the kernel, plus the CPU-pushed iretq frame. Field order matches
/// the push sequence in the stub (last push = lowest address = first
/// field) — do not reorder.
#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct SyscallFrame {
    pub r15: u64,
    pub r14: u64,
    pub r13: u64,
    pub r12: u64,
    pub r11: u64,
    pub r10: u64,
    pub r9: u64,
    pub r8: u64,
    pub rbp: u64,
    pub rdi: u64,
    pub rsi: u64,
    pub rdx: u64,
    pub rcx: u64,
    pub rbx: u64,
    pub rax: u64,
    // CPU-pushed interrupt frame (int 0x80 pushes all five in long mode).
    pub rip: u64,
    pub cs: u64,
    pub rflags: u64,
    pub rsp: u64,
    pub ss: u64,
}

/// Naked `int 0x80` entry. Saves the full GPR file so the dispatcher
/// reads syscall arguments from memory instead of racing the compiler
/// for live registers, then restores everything and iretqs back to
/// the caller. The dispatcher writes the syscall result into the
/// saved `rax` slot, which the pop sequence materialises.
#[unsafe(naked)]
unsafe extern "C" fn syscall_entry_stub() {
    core::arch::naked_asm!(
        "push rax",
        "push rbx",
        "push rcx",
        "push rdx",
        "push rsi",
        "push rdi",
        "push rbp",
        "push r8",
        "push r9",
        "push r10",
        "push r11",
        "push r12",
        "push r13",
        "push r14",
        "push r15",
        "mov rdi, rsp",
        "call {inner}",
        "pop r15",
        "pop r14",
        "pop r13",
        "pop r12",
        "pop r11",
        "pop r10",
        "pop r9",
        "pop r8",
        "pop rbp",
        "pop rdi",
        "pop rsi",
        "pop rdx",
        "pop rcx",
        "pop rbx",
        "pop rax",
        "iretq",
        inner = sym syscall_entry_inner,
    );
}

/// Capture the interrupted user state from the saved syscall frame
/// Capture the interrupted user state from the saved syscall frame
/// into the task's saved `TaskContext` so `scheduler::resume_task`
/// can continue it later. Both entry paths (syscall stub frame and
/// timer stub frame) use this helper, so all 15 GPRs are saved.
fn save_user_context(pid: u64, frame: &SyscallFrame) {
    let ctx = crate::scheduler::TaskContext {
        r15: frame.r15,
        r14: frame.r14,
        r13: frame.r13,
        r12: frame.r12,
        r11: frame.r11,
        r10: frame.r10,
        r9: frame.r9,
        r8: frame.r8,
        rbp: frame.rbp,
        rdi: frame.rdi,
        rsi: frame.rsi,
        rdx: frame.rdx,
        rcx: frame.rcx,
        rbx: frame.rbx,
        rax: frame.rax,
        rip: frame.rip,
        cs: frame.cs,
        rflags: frame.rflags,
        rsp: frame.rsp,
        ss: frame.ss,
        simd_state_ptr: 0,
    };
    crate::scheduler::write_context(pid, ctx);
    crate::scheduler::save_simd_state(pid);
}


/// After the current task died (exit, kill, fault): hand the CPU to
/// the next runnable task, else idle if sleepers remain, else return
/// to the shell. Never returns.
///
/// # Safety
/// The caller's stack frame is abandoned; it must never be resumed.
pub(crate) unsafe fn resume_after_death() -> ! {
    if let Some(next) = crate::scheduler::schedule_next() {
        crate::scheduler::resume_task(next);
    }
    if crate::scheduler::has_blocked_tasks() {
        crate::scheduler::enter_idle();
    }
    crate::scheduler::enter_kernel_return();
}

/// Yield the CPU from inside the syscall handler. Saves the caller's
/// context and switches to the next runnable task. If the scheduler
/// hands the CPU straight back (nothing else is ready), returns so
/// the stub can iretq back to the caller.
unsafe fn yield_from_syscall(pid: u64, frame: &SyscallFrame) {
    if !crate::scheduler::yield_current() {
        return;
    }
    save_user_context(pid, frame);
    match crate::scheduler::schedule_next() {
        Some(next) if next != pid => crate::scheduler::resume_task(next),
        // The scheduler picked us again: schedule_next already marked
        // us Running, so just keep going.
        Some(_) => {}
        None => {
            // Re-queued but nothing Ready (should not happen) —
            // defensively park in the idle loop.
            crate::scheduler::enter_idle();
        }
    }
}

/// Rust half of the `int 0x80` entry. `frame` aliases the register
/// file the stub pushed; mutating it changes what the stub pops
/// before `iretq` (this is how results travel back in rax).
extern "C" fn syscall_entry_inner(frame: &mut SyscallFrame) {
    use crate::serial::SERIAL1;

    let syscall_no = frame.rax;
    let arg0 = frame.rdi;
    let arg1 = frame.rsi;
    let arg2 = frame.rdx;
    let arg3 = frame.r10;

    // CURRENT_PID > 0 means a scheduled user process is executing;
    // dispatch on the stable SyscallNumber ABI. CURRENT_PID == 0 is
    // the kernel/shell context, which keeps the legacy Linux-style
    // numbers (SYS_WRITE=1, SYS_EXIT=60, ...).
    let current_pid =
        crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);

    if current_pid > 0 {
        use crate::syscall::SyscallNumber;
        let args = [arg0, arg1, arg2, arg3, frame.r8, frame.r9];

        // Lifecycle syscalls context-switch away and are handled
        // here; everything else goes through the dispatcher.
        if syscall_no == SyscallNumber::Exit as u64 {
            crate::scheduler::record_exit(current_pid, arg0 as u32);
            crate::scheduler::exit_current();
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::ProcessKilled,
                "user process exited via sys_exit",
            );
            unsafe { resume_after_death() }
        } else if syscall_no == SyscallNumber::Yield as u64 {
            unsafe { yield_from_syscall(current_pid, frame) };
            frame.rax = 0;
            return;
        } else if syscall_no == SyscallNumber::Sleep as u64 {
            // arg0 = milliseconds; PIT runs ~18.2 Hz (~55 ms/tick).
            let ticks = arg0.div_ceil(55).max(1);
            if crate::scheduler::sleep_current(ticks) {
                save_user_context(current_pid, frame);
                unsafe { resume_after_death() }
            }
            frame.rax = 0;
            return;
        } else if syscall_no == SyscallNumber::WaitPid as u64 {
            match crate::scheduler::waitpid_current(arg0) {
                Ok(Some(code)) => {
                    frame.rax = code as u64;
                }
                Ok(None) => {
                    save_user_context(current_pid, frame);
                    unsafe { resume_after_death() }
                }
                Err(err) => {
                    frame.rax = err as i64 as u64;
                }
            }
            return;
        }

        let res = crate::syscall::dispatch_for_process(current_pid, syscall_no, args);
        if res.status == crate::syscall::SyscallStatus::Blocked {
            save_user_context(current_pid, frame);
            {
                let mut sched = crate::scheduler::SCHEDULER.lock();
                if let Some(idx) = sched.tasks.iter().position(|t| t.id == current_pid) {
                    sched.contexts[idx].rip = sched.contexts[idx].rip.saturating_sub(2);
                }
            }
            crate::scheduler::CURRENT_PID.store(0, core::sync::atomic::Ordering::SeqCst);
            unsafe { resume_after_death() }
        }

        let active_pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
        if active_pid == 0 {
            unsafe { resume_after_death() }
        }

        frame.rax = if res.status == crate::syscall::SyscallStatus::Ok {
            res.value
        } else {
            res.status as i64 as u64
        };

        if crate::logging::audit::FLUSH_PENDING.load(core::sync::atomic::Ordering::SeqCst) {
            crate::logging::audit::FLUSH_PENDING.store(false, core::sync::atomic::Ordering::SeqCst);
            let _ = crate::logging::audit::flush_to_disk();
        }

        // Preemption point: if the time slice expired while we were
        // in the kernel, rotate to the next runnable task before
        // returning to user space. The saved context includes rax,
        // so the result above survives the round trip.
        if crate::scheduler::should_preempt(current_pid) {
            unsafe { yield_from_syscall(current_pid, frame) };
        }
        return;
    }

    // Legacy kernel/shell context: use Linux-style syscall numbers.
    let result = match syscall_no {
        syscall_number::SYS_WRITE => {
            // Arg0 = user pointer to bytes, arg1 = length,
            // arg2 = file descriptor. We only support fd=1
            // (stdout -> COM1). We copy the bytes out before
            // writing so we do not hold a reference into the
            // user mapping across the serial write.
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
        syscall_number::SYS_EXIT | syscall_number::SYS_YIELD | syscall_number::SYS_SLEEP => {
            // The kernel main context (pid 0) is not a schedulable
            // task; exit/yield/sleep have no meaning here. User
            // tasks enter through the scheduler with CURRENT_PID set
            // and use the SyscallNumber ABI above.
            0
        }
        syscall_number::SYS_WAIT => {
            // Arg0 = pid. Supports `wait(-1)` ("any dead task") and
            // `wait(pid)` where the pid is already dead. A live
            // child returns -ECHILD (Linux-compatible).
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

    frame.rax = result;
}

extern crate alloc;
