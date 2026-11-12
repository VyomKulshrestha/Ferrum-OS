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

/// True while the master 8259 runs in auto-EOI mode (ICW4 bit 1): it clears
/// the in-service bit itself when the CPU acknowledges an interrupt, so the
/// timer handler skips its EOI write, a port write that under WHPX with
/// `kernel-irqchip=off` exits to QEMU's user process on every tick. Other
/// handlers still send their EOI; on the master it is then a no-op, and the
/// slave (IRQ 8-15) stays in normal mode.
pub static PIC_AUTO_EOI: core::sync::atomic::AtomicBool = core::sync::atomic::AtomicBool::new(false);

/// Re-initialise the master 8259 with or without auto-EOI, keeping its
/// vector offset, cascade wiring and interrupt mask.
pub fn set_pic_auto_eoi(on: bool) {
    use x86_64::instructions::port::Port;
    x86_64::instructions::interrupts::without_interrupts(|| {
        let _pics = PICS.lock();
        let mut command: Port<u8> = Port::new(0x20);
        let mut data: Port<u8> = Port::new(0x21);
        unsafe {
            let mask = data.read();
            command.write(0x11); // ICW1: edge, cascade, ICW4 follows
            data.write(PIC_1_OFFSET); // ICW2: vector offset
            data.write(0x04); // ICW3: slave on IRQ2
            data.write(if on { 0x03 } else { 0x01 }); // ICW4: 8086 mode (+ auto-EOI)
            data.write(mask);
        }
        PIC_AUTO_EOI.store(on, core::sync::atomic::Ordering::SeqCst);
    });
}

/// Load the IDT into the CPU
pub fn init_idt() {
    IDT.load();
}

// ============================================================================
// PIT (Programmable Interval Timer) configuration
// ============================================================================
//
// Left at its power-on-default divisor (65536) - an un-reprogrammed 8253/8254
// free-runs at ~18.2 Hz (~55ms/tick) - this used to be genuinely fine for a
// coarse round-robin slice, but it also meant every `sys_sleep` request under
// 55ms (e.g. a GUI app's `sleep(30)` poll loop, see `userland/*/src/main.rs`)
// rounded up to "wake on literally the very next tick": with a background
// ring-3 app active, that put a scheduler context-switch decision (with
// interrupts briefly disabled - see `scheduler::resume_task`) on nearly every
// single tick, continuously, for as long as that app ran. Combined with the
// PS/2 8042 controller's single-scancode/small-FIFO buffering, a keyboard
// scancode arriving during one of those windows could be lost outright -
// reproduced directly: typing a command while a background app polls every
// ~30ms lost whole trailing words, not just an occasional character (see
// work.md). Reprogrammed to 1000 Hz (1ms/tick) so `sleep()` no longer forces
// a wake (and therefore a context-switch decision) far more often than the
// caller actually asked for - this doesn't change the *existence* of the
// race (nothing can un-overwrite an already-clobbered hardware scancode
// register), but it removes the amplification that turned an inherent,
// narrow hardware race into a near-guaranteed one.
//
// Every tick-based constant elsewhere in the kernel that assumed the old
// ~55ms/tick rate (`scheduler::TIME_SLICE_TICKS`, the quota windows in
// `scheduler::TaskQuotas::default_user`, `sys_sleep`'s ms-to-ticks
// conversion, `net::iface`'s tick-to-millisecond timestamp conversion, and
// the `uptime`/`scheduler` shell commands' tick-to-time display) has been
// rescaled to preserve the same real-world durations at the new rate -
// search for `PIT_TICK_MS` to find every dependent site.

/// The PIT's own oscillator frequency (fixed by the hardware).
const PIT_BASE_HZ: u32 = 1_193_182;

/// Target tick rate after reprogramming. 1000 Hz (1ms/tick) is the standard
/// choice for a general-purpose preemptible kernel - fine enough for
/// millisecond-precision `sleep()`, coarse enough that the timer ISR itself
/// (see `timer_interrupt_entry_inner`) is a vanishingly small fraction of
/// each tick's duration.
const PIT_HZ: u32 = 1000;

/// Milliseconds per tick at `PIT_HZ`. Every ms<->tick conversion elsewhere
/// in the kernel is written in terms of this constant instead of a
/// hardcoded literal, so there is exactly one place to change the rate.
pub const PIT_TICK_MS: u64 = 1000 / PIT_HZ as u64;

/// Reprogram PIT channel 0 (the timer IRQ0 source) from its power-on-default
/// ~18.2 Hz to `PIT_HZ`. Must run once, after `init_idt`/PIC init and before
/// interrupts are enabled, so the very first tick already arrives at the new
/// rate.
pub fn init_pit() {
    use x86_64::instructions::port::Port;

    let divisor = (PIT_BASE_HZ / PIT_HZ) as u16;
    unsafe {
        let mut command: Port<u8> = Port::new(0x43);
        let mut channel0: Port<u8> = Port::new(0x40);
        // Channel 0, lobyte/hibyte access, mode 3 (square wave generator) -
        // the standard configuration for a periodic timer interrupt.
        command.write(0x36u8);
        channel0.write((divisor & 0xFF) as u8);
        channel0.write((divisor >> 8) as u8);
    }
}

// ============================================================================
// CPU Exception Handlers
// ============================================================================

/// Kernel faults that were not turned into a user-process kill since boot
/// (the self-test `ring0-fault` checks the classification below).
pub static KERNEL_FAULTS: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

/// True when the exception interrupted ring 3. A fault taken in ring 0 is a
/// kernel bug (or a kernel access a syscall should have refused) even while a
/// user process is current: it used to be treated as that process's fault,
/// which killed the process, hid the corruption and resumed the scheduler
/// with whatever locks the faulting kernel code held.
pub fn fault_from_user_mode(code_segment: u64) -> bool {
    code_segment & 3 == 3
}

fn handle_userspace_fault(fault_name: &str, stack_frame: &InterruptStackFrame) -> bool {
    let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    let from_user = fault_from_user_mode(stack_frame.code_segment.0 as u64);
    if !from_user {
        KERNEL_FAULTS.fetch_add(1, core::sync::atomic::Ordering::SeqCst);
        crate::serial_println!(
            "[KERNEL] {} in ring 0 (current pid {}): stopping the kernel",
            fault_name,
            pid
        );
        return false;
    }
    if pid != 0 {
        use x86_64::registers::control::Cr2;
        let rsp = stack_frame.stack_pointer.as_u64();
        crate::serial_println!("[KERNEL] Userspace process {} caused {}, accessed address={:?}, RIP={:#x}, RSP={:#x}, CS={:?}, terminating.", 
                 pid, fault_name, Cr2::read(), stack_frame.instruction_pointer.as_u64(), rsp, stack_frame.code_segment);
        
        // Print stack contents around RSP (up to 16 words / 128 bytes)
        crate::serial_println!("  Stack dump around RSP:");
        for i in 0..16 {
            let addr = rsp + (i * 8);
            // Check if address is in the kernel stack range to avoid faulting again
            let stack_top = 0x44444444c910u64;
            let stack_bottom = stack_top - 32 * 1024;
            if addr >= stack_bottom && addr < stack_top {
                let val = unsafe { *(addr as *const u64) };
                crate::serial_println!("    {:#x}: {:#x}", addr, val);
            } else {
                crate::serial_println!("    {:#x}: <out of stack bounds>", addr);
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
    use x86_64::registers::control::Cr2;
    if let Ok(cr2_addr) = Cr2::read() {
        let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
        if pid != 0 {
            // Only attempt to resolve the fault if it was caused by a non-present page,
            // not a protection violation (e.g. write to a read-only page table mapping).
            if !error_code.contains(PageFaultErrorCode::PROTECTION_VIOLATION) {
                if crate::process::fault_in_page(pid, cr2_addr) {
                    x86_64::instructions::tlb::flush(cr2_addr);
                    return;
                }
            }
        }
    }

    if handle_userspace_fault("Page Fault", &stack_frame) {
        return;
    }

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
        // The SysV ABI requires DF = 0 on every call. Ring 3 controls
        // RFLAGS.DF (`std`), and an interrupt or `int 0x80` does not clear
        // it, so without this the kernel's memcpy/memset (`rep movs`/`stos`)
        // run backwards over memory below their destination. The user's DF
        // is restored by iretq from the saved RFLAGS.
        "cld",
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

/// TSC cycles spent in timer interrupts and syscalls that returned to their
/// caller (paths that switch tasks are not counted), and how many there were.
/// Read by `test-syscall perf`.
pub static TIMER_CYCLES: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static TIMER_COUNT: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
/// The two parts of a timer interrupt: `scheduler::tick` and the PIC EOI.
pub static TICK_FN_CYCLES: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static TICK_FN_COUNT: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static TIMER_EOI_CYCLES: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static TIMER_EOI_COUNT: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
/// Entries into the timer and syscall handlers' Rust code with RFLAGS.DF set
/// (self-test `df-entry`; must stay 0, see the `cld` in both entry stubs).
pub static DF_SET_AT_TIMER_ENTRY: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static DF_SET_AT_SYSCALL_ENTRY: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
/// Set by self-test `df-entry`: the next syscall entries copy a buffer with
/// the kernel's memcpy and count copies whose result differs from the source.
pub static DF_COPY_PROBE_ARMED: core::sync::atomic::AtomicBool = core::sync::atomic::AtomicBool::new(false);
pub static DF_COPY_PROBE_RUNS: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static DF_COPY_PROBE_BAD: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

#[inline(always)]
fn direction_flag_set() -> bool {
    let flags: u64;
    unsafe { core::arch::asm!("pushfq", "pop {}", out(reg) flags, options(preserves_flags)) };
    flags & (1 << 10) != 0
}

/// Copy 256 bytes inside one static buffer with the kernel's memcpy and check
/// the result. With DF set, `rep movsb` walks downwards from the destination.
fn df_copy_probe() {
    static mut PROBE: [u8; 1024] = [0; 1024];
    let len = core::hint::black_box(256usize);
    unsafe {
        let buf = &raw mut PROBE as *mut u8;
        for i in 0..len {
            *buf.add(768 + i) = (i as u8) ^ 0x5A;
            *buf.add(512 + i) = 0;
        }
        core::ptr::copy_nonoverlapping(
            core::hint::black_box(buf.add(768) as *const u8),
            core::hint::black_box(buf.add(512)),
            len,
        );
        let mut bad = false;
        for i in 0..len {
            if *buf.add(512 + i) != (i as u8) ^ 0x5A {
                bad = true;
            }
        }
        DF_COPY_PROBE_RUNS.fetch_add(1, core::sync::atomic::Ordering::SeqCst);
        if bad {
            DF_COPY_PROBE_BAD.fetch_add(1, core::sync::atomic::Ordering::SeqCst);
        }
    }
}

pub static SYSCALL_CYCLES: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);
pub static SYSCALL_COUNT: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

struct CycleMeter {
    start: u64,
    cycles: &'static core::sync::atomic::AtomicU64,
    count: &'static core::sync::atomic::AtomicU64,
}

impl CycleMeter {
    fn start(
        cycles: &'static core::sync::atomic::AtomicU64,
        count: &'static core::sync::atomic::AtomicU64,
    ) -> Self {
        Self { start: unsafe { core::arch::x86_64::_rdtsc() }, cycles, count }
    }
}

impl Drop for CycleMeter {
    fn drop(&mut self) {
        let spent = unsafe { core::arch::x86_64::_rdtsc() }.wrapping_sub(self.start);
        self.cycles.fetch_add(spent, core::sync::atomic::Ordering::Relaxed);
        self.count.fetch_add(1, core::sync::atomic::Ordering::Relaxed);
    }
}

extern "C" fn timer_interrupt_entry_inner(frame: &mut SyscallFrame) {
    if direction_flag_set() {
        DF_SET_AT_TIMER_ENTRY.fetch_add(1, core::sync::atomic::Ordering::Relaxed);
    }
    let _meter = CycleMeter::start(&TIMER_CYCLES, &TIMER_COUNT);
    // Tick the scheduler (if initialized)
    {
        let _tick = CycleMeter::start(&TICK_FN_CYCLES, &TICK_FN_COUNT);
        crate::scheduler::tick();
    }

    // Send End-of-Interrupt to the PIC (not needed in auto-EOI mode)
    if !PIC_AUTO_EOI.load(core::sync::atomic::Ordering::Relaxed) {
        let _eoi = CycleMeter::start(&TIMER_EOI_CYCLES, &TIMER_EOI_COUNT);
        unsafe {
            PICS.lock().notify_end_of_interrupt(InterruptIndex::Timer.as_u8());
        }
    }

    // Preempt the current task if it was running in Ring 3 and its time slice has expired.
    if (frame.cs & 3) == 3 {
        let current_pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
        if current_pid != 0 {
            // Charge this tick to the task's continuous ring-3 run (reset
            // by every syscall). `check_and_enforce_quotas` existed but was
            // never called, so a non-exempt task could spin for ever.
            if crate::scheduler::charge_user_tick(current_pid) {
                crate::serial_println!(
                    "[KERNEL] pid {} exceeded its continuous CPU quota, terminating.",
                    current_pid
                );
                unsafe { resume_after_death() }
            }
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
        return;
    }

    // Not ring-3: check whether we interrupted a registered kernel
    // task (see `CURRENT_KERNEL_TASK_PID`'s doc) parked at its own
    // designated safe point, immediately before its own `hlt`.
    // Arbitrary ring-0 code (syscall handlers, boot, anything holding
    // a lock) is NEVER touched here - only a loop that explicitly
    // opted in by calling `enter_kernel_task_safepoint` right before
    // this exact `hlt` is. Every such loop reaches this point at most
    // once per iteration, so there's no time-slice check to make here
    // the way there is for ring-3 - this IS the task's own yield point.
    let kernel_task_pid = crate::scheduler::CURRENT_KERNEL_TASK_PID.load(core::sync::atomic::Ordering::SeqCst);
    if kernel_task_pid != 0 {
        unsafe {
            if crate::scheduler::yield_current_kernel_task(kernel_task_pid) {
                // The task is no longer executing at its safepoint once we
                // switch away; it re-marks itself the next time it parks.
                crate::scheduler::leave_kernel_task_safepoint();
                save_user_context(kernel_task_pid, frame);
                if let Some(next) = crate::scheduler::schedule_next() {
                    if next != kernel_task_pid {
                        crate::scheduler::resume_task(next);
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
    // The keyboard interrupt pushes into this queue. The shell polls it with
    // interrupts enabled; a key arriving while the shell held the lock spun
    // in the interrupt handler for good (one CPU, interrupts off).
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut queue = KEYBOARD_QUEUE.lock();
        queue.as_mut().and_then(|q| q.pop_front())
    })
}

/// Push a synthetic character into the keyboard queue.
///
/// Used by the input injection subsystem (`crate::input`) to feed
/// agent-generated keystrokes into the shell. This makes the shell
/// see injected keys exactly as if they came from the PS/2 keyboard.
pub fn push_keyboard(ascii: u8) {
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut queue = KEYBOARD_QUEUE.lock();
        if let Some(q) = queue.as_mut() {
            if q.len() < 64 {
                q.push_back(ascii);
            }
        }
    })
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

/// Drain keyboard bytes left in the i8042 output buffer when an IRQ edge is
/// missed.  The normal interrupt path remains authoritative; this bounded
/// poll is used by the interactive desktop loop and deliberately leaves AUX
/// (mouse) bytes for the mouse handler.
pub fn poll_ps2_keyboard() {
    use x86_64::instructions::port::Port;

    // With interrupts off, as the IRQ 1 handler runs: otherwise the handler
    // could read the byte between this status check and the data read (this
    // loop then reads the stale byte again: a doubled key), and it takes the
    // modifier and event-queue locks this loop may be holding.
    x86_64::instructions::interrupts::without_interrupts(|| {
        let mut status_port = Port::<u8>::new(0x64);
        let mut data_port = Port::<u8>::new(0x60);
        for _ in 0..16 {
            let status = unsafe { status_port.read() };
            if status & 0x01 == 0 || status & 0x20 != 0 {
                break;
            }
            let scancode = unsafe { data_port.read() };
            if let Some(ch) = scancode_to_ascii(scancode) {
                crate::input::inject_key_event(ch, true);
            }
        }
    })
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
    static CTRL_PRESSED: spin::Mutex<bool> = spin::Mutex::new(false);
    static ALT_PRESSED: spin::Mutex<bool> = spin::Mutex::new(false);
    
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
        // Ctrl pressed/released. Applications receive conventional ASCII
        // control bytes for shortcuts rather than raw modifier events.
        0x1D => {
            *CTRL_PRESSED.lock() = true;
            None
        }
        0x9D => {
            *CTRL_PRESSED.lock() = false;
            None
        }
        0x38 => {
            *ALT_PRESSED.lock() = true;
            None
        }
        0xB8 => {
            *ALT_PRESSED.lock() = false;
            None
        }
        _ => {
            let is_shift = *SHIFT_PRESSED.lock();
            let is_ctrl = *CTRL_PRESSED.lock();
            let is_alt = *ALT_PRESSED.lock();
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
                0x0F => Some(if is_alt { crate::input::KEY_ALT_TAB } else { b'\t' }),
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
                0x2E => Some(if is_ctrl { 0x03 } else if is_shift { b'C' } else { b'c' }),
                0x2F => Some(if is_ctrl { 0x16 } else if is_shift { b'V' } else { b'v' }),
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
        // The SysV ABI requires DF = 0 on every call. Ring 3 controls
        // RFLAGS.DF (`std`), and an interrupt or `int 0x80` does not clear
        // it, so without this the kernel's memcpy/memset (`rep movs`/`stos`)
        // run backwards over memory below their destination. The user's DF
        // is restored by iretq from the saved RFLAGS.
        "cld",
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
    if direction_flag_set() {
        DF_SET_AT_SYSCALL_ENTRY.fetch_add(1, core::sync::atomic::Ordering::Relaxed);
    }
    if DF_COPY_PROBE_ARMED.load(core::sync::atomic::Ordering::Relaxed) {
        df_copy_probe();
    }
    let _meter = CycleMeter::start(&SYSCALL_CYCLES, &SYSCALL_COUNT);
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

    // The legacy Linux-numbered path below trusts its pointers (SYS_WRITE
    // copies from arg0 unchecked) and is meant for ring-0 callers. Ring-3
    // code always runs with its pid in CURRENT_PID; if it ever reached here
    // without one, refuse rather than act with kernel trust.
    if current_pid == 0 && fault_from_user_mode(frame.cs) {
        frame.rax = EPERM;
        return;
    }

    if current_pid > 0 {
        // Entering the kernel restarts the task's continuous-CPU count.
        crate::scheduler::note_syscall_entry(current_pid);
        use crate::syscall::SyscallNumber;
        let args = [arg0, arg1, arg2, arg3, frame.r8, frame.r9];

        // A child that woke this task from blocked waitpid could not be freed
        // while the kernel was still running on the child's own stack. We are
        // now on a different, live task's syscall stack, so reclaim it before
        // handling the next operation (including a parent that exits next).
        crate::scheduler::reap_deferred(current_pid);

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
            // arg0 = milliseconds.
            let ticks = arg0.div_ceil(PIT_TICK_MS).max(1);
            // The scheduler snapshots this frame before switching away, so
            // write the eventual return value first. Otherwise a woken task
            // resumes with the syscall number (32) still in rax and callers
            // incorrectly observe a failed sleep.
            frame.rax = 0;
            if crate::scheduler::sleep_current(ticks) {
                save_user_context(current_pid, frame);
                unsafe { resume_after_death() }
            }
            return;
        } else if syscall_no == SyscallNumber::WaitPid as u64
            || syscall_no == SyscallNumber::Wait as u64
        {
            // Syscall 13 is the original wait-any ABI. Keep it as a real
            // compatibility alias for WaitPid(-1), not a success-returning
            // stub that lets a parent race ahead of a live child.
            let target = if syscall_no == SyscallNumber::Wait as u64 {
                u64::MAX
            } else {
                arg0
            };
            match crate::scheduler::waitpid_current(target) {
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
            let mut confirmation_wait = false;
            {
                let mut sched = crate::scheduler::SCHEDULER.lock();
                if let Some(idx) = sched.tasks.iter().position(|t| t.id == current_pid) {
                    sched.contexts[idx].rip = sched.contexts[idx].rip.saturating_sub(2);

                    let task = &mut sched.tasks[idx];
                    // The confirmation gate (`syscall::mod.rs`'s gated-syscall
                    // check) already put this task into a genuine
                    // Blocked-until-`wake_at` state of its own, complete with a
                    // real future deadline, *before* returning this same
                    // `Blocked` status - unconditionally overwriting that back
                    // to Ready here (the correct thing to do for a plain
                    // retry-ASAP syscall like the non-blocking audio capture
                    // poll, which never touches `task.state` itself) discarded
                    // the confirmation timeout entirely: every retry re-entered
                    // the gate check, found itself still neither approved nor
                    // denied, and set a *fresh* 5-second `wake_at` again,
                    // spinning forever and re-printing the confirmation prompt
                    // on every scheduler cycle instead of ever actually timing
                    // out (see work.md). Leave a task alone here if it already
                    // arranged its own real wake-up - `scheduler::tick()`'s
                    // normal `wake_at <= now` sweep is what should resume it.
                    let already_genuinely_blocked =
                        task.state == crate::scheduler::TaskState::Blocked
                            && task.wake_at != u64::MAX;
                    confirmation_wait = already_genuinely_blocked
                        && task.blocked_on_confirmation;
                    if !already_genuinely_blocked {
                        task.state = crate::scheduler::TaskState::Ready;
                        task.time_remaining = crate::scheduler::TIME_SLICE_TICKS;
                        task.quotas.used_cpu_ticks_continuous = 0;

                        let pri = task.priority.index();
                        if !sched.run_queues[pri].contains(&current_pid) {
                            sched.run_queues[pri].push_back(current_pid);
                        }
                    }
                }
            }
            crate::scheduler::CURRENT_PID.store(0, core::sync::atomic::Ordering::SeqCst);
            if confirmation_wait {
                // Confirmation is a modal security boundary. Park on the
                // scheduler's dedicated idle stack until the PIT deadline or
                // a physical y/n interrupt wakes the requester. Resuming a
                // previously parked kernel UI task here can otherwise leave
                // the only deadline-bearing ring-3 task without a reliable
                // handoff back from that kernel task's safepoint.
                unsafe { crate::scheduler::enter_idle() }
            }
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
