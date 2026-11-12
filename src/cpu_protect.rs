// ============================================================================
// FerrumOS - Supervisor-mode execution and access prevention (SMEP, SMAP)
// ============================================================================
// SMEP (CR4 bit 20) makes the CPU refuse to execute, in ring 0, any page the
// user may access; SMAP (CR4 bit 21) makes it refuse ring-0 reads and writes
// of such pages while RFLAGS.AC is clear. Both are set at boot when CPUID leaf
// 7 reports them (fi2 kernel workstream K1, items 1 and 2).
//
// The kernel's intended accesses to user memory all go through
// `syscall::fs::{read_user_str, read_user_bytes, copy_to_user}`, which open a
// `UserAccess` window (stac ... clac) around the copy and nothing else. Every
// other ring-0 access to a user page is a fault.
//
// Ring 3 controls RFLAGS.AC (`popfq`), and neither an interrupt gate nor
// `int 0x80` clears it, so a process that sets AC before a syscall would turn
// SMAP off for the whole syscall. Every entry point that can be reached from
// ring 3 clears AC first (`clear_ac_on_entry`); iretq restores the process's
// own flags.
//
// The fault probe (`probe_call`) lets self-tests provoke a ring-0 page fault
// on purpose and continue: the page-fault handler resumes at the probe's
// recovery point instead of stopping the kernel. It is armed only for the
// duration of one probe, with interrupts off.
// ============================================================================

use core::sync::atomic::{AtomicBool, AtomicU64, Ordering};

const CR4_SMEP: u64 = 1 << 20;
const CR4_SMAP: u64 = 1 << 21;
const RFLAGS_AC: u64 = 1 << 18;

/// The CPU reports the feature (CPUID.(7,0).EBX bit 7 and bit 20).
pub static CPU_HAS_SMEP: AtomicBool = AtomicBool::new(false);
pub static CPU_HAS_SMAP: AtomicBool = AtomicBool::new(false);
/// stac/clac are executed only while SMAP is on (they are #UD without it).
static SMAP_ON: AtomicBool = AtomicBool::new(false);
/// Self-test switches: `UserAccess` without stac/clac (a missed bracket on
/// every path), and entry points that leave AC as ring 3 set it.
pub static BRACKETS_ENABLED: AtomicBool = AtomicBool::new(true);
pub static CLEAR_AC_ON_ENTRY: AtomicBool = AtomicBool::new(true);

fn cpuid_leaf7_ebx() -> u32 {
    let max = unsafe { core::arch::x86_64::__cpuid(0) }.eax;
    if max < 7 {
        return 0;
    }
    unsafe { core::arch::x86_64::__cpuid_count(7, 0) }.ebx
}

fn read_cr4() -> u64 {
    let v: u64;
    unsafe { core::arch::asm!("mov {}, cr4", out(reg) v, options(nomem, nostack, preserves_flags)) };
    v
}

unsafe fn write_cr4(v: u64) {
    core::arch::asm!("mov cr4, {}", in(reg) v, options(nostack, preserves_flags));
}

/// Set SMEP and SMAP when the CPU has them. Runs once at boot, before any
/// ring-3 code exists. Returns (smep on, smap on).
pub fn enable() -> (bool, bool) {
    let ebx = cpuid_leaf7_ebx();
    let smep = ebx & (1 << 7) != 0;
    let smap = ebx & (1 << 20) != 0;
    CPU_HAS_SMEP.store(smep, Ordering::SeqCst);
    CPU_HAS_SMAP.store(smap, Ordering::SeqCst);
    set_smep(smep);
    set_smap(smap);
    (smep_on(), smap_on())
}

pub fn smep_on() -> bool {
    read_cr4() & CR4_SMEP != 0
}

pub fn smap_on() -> bool {
    read_cr4() & CR4_SMAP != 0
}

/// Turn SMEP on or off (off only for the self-test's control). No effect on
/// a CPU without SMEP.
pub fn set_smep(on: bool) {
    if !CPU_HAS_SMEP.load(Ordering::SeqCst) {
        return;
    }
    x86_64::instructions::interrupts::without_interrupts(|| unsafe {
        let cr4 = read_cr4();
        write_cr4(if on { cr4 | CR4_SMEP } else { cr4 & !CR4_SMEP });
    });
}

/// Turn SMAP on or off (off only for the self-test's control). No effect on
/// a CPU without SMAP.
pub fn set_smap(on: bool) {
    if !CPU_HAS_SMAP.load(Ordering::SeqCst) {
        return;
    }
    x86_64::instructions::interrupts::without_interrupts(|| unsafe {
        let cr4 = read_cr4();
        if on {
            SMAP_ON.store(true, Ordering::SeqCst);
            write_cr4(cr4 | CR4_SMAP);
        } else {
            write_cr4(cr4 & !CR4_SMAP);
            SMAP_ON.store(false, Ordering::SeqCst);
        }
    });
}

/// RFLAGS.AC of the current context.
#[inline(always)]
pub fn ac_set() -> bool {
    let flags: u64;
    unsafe { core::arch::asm!("pushfq", "pop {}", out(reg) flags, options(preserves_flags)) };
    flags & RFLAGS_AC != 0
}

/// Entries into the kernel from ring 3 that found AC set (counted before it
/// is cleared). Read by the self-test `smap-state`.
pub static AC_SET_AT_ENTRY: AtomicU64 = AtomicU64::new(0);

/// Clear RFLAGS.AC on entry to the kernel. Works with or without SMAP (no
/// stac/clac): flags through the stack.
#[inline(always)]
pub fn clear_ac_on_entry() {
    if !ac_set() {
        return;
    }
    AC_SET_AT_ENTRY.fetch_add(1, Ordering::Relaxed);
    if !CLEAR_AC_ON_ENTRY.load(Ordering::Relaxed) {
        return;
    }
    unsafe {
        core::arch::asm!(
            "pushfq",
            "and qword ptr [rsp], {mask}",
            "popfq",
            mask = in(reg) !RFLAGS_AC,
        )
    };
}

/// An open window for intended kernel accesses to user memory: stac on
/// creation, clac on drop. Keep it around the copy only; no allocation, no
/// lock and no call that could reach unrelated code inside it.
pub struct UserAccess {
    opened: bool,
}

impl UserAccess {
    #[inline(always)]
    pub fn open() -> Self {
        let opened = SMAP_ON.load(Ordering::Relaxed) && BRACKETS_ENABLED.load(Ordering::Relaxed);
        if opened {
            unsafe { core::arch::asm!("stac", options(nomem, nostack)) };
        }
        Self { opened }
    }
}

impl Drop for UserAccess {
    #[inline(always)]
    fn drop(&mut self) {
        if self.opened {
            unsafe { core::arch::asm!("clac", options(nomem, nostack)) };
        }
    }
}

// ---- fault probe ------------------------------------------------------------

static PROBE_FIXUP: AtomicU64 = AtomicU64::new(0);
static PROBE_RSP: AtomicU64 = AtomicU64::new(0);
/// The last probed fault: CR2 and the page-fault error code.
pub static PROBE_CR2: AtomicU64 = AtomicU64::new(0);
pub static PROBE_ERROR: AtomicU64 = AtomicU64::new(0);

/// Call `target(arg)` with the probe armed. Returns 0 if it returned, 1 if
/// it took a ring-0 page fault (recorded in `PROBE_CR2` / `PROBE_ERROR`).
#[unsafe(naked)]
unsafe extern "C" fn probe_call_raw(target: u64, arg: u64) -> u64 {
    core::arch::naked_asm!(
        "push rbx",
        "push rbp",
        "push r12",
        "push r13",
        "push r14",
        "push r15",
        "sub rsp, 8",
        "mov [rip + {rsp}], rsp",
        "lea rax, [rip + 2f]",
        "mov [rip + {fix}], rax",
        "mov rax, rdi",
        "mov rdi, rsi",
        "call rax",
        "xor eax, eax",
        "jmp 3f",
        "2:",
        "mov eax, 1",
        "3:",
        "mov qword ptr [rip + {fix}], 0",
        "add rsp, 8",
        "pop r15",
        "pop r14",
        "pop r13",
        "pop r12",
        "pop rbp",
        "pop rbx",
        "ret",
        rsp = sym PROBE_RSP,
        fix = sym PROBE_FIXUP,
    );
}

/// `probe_call_raw` with interrupts off (no other code may fault while the
/// probe is armed). Returns true if `target` faulted.
pub fn probe_call(target: u64, arg: u64) -> bool {
    x86_64::instructions::interrupts::without_interrupts(|| unsafe { probe_call_raw(target, arg) } != 0)
}

/// Called first by the page-fault handler for a ring-0 fault. When a probe is
/// armed, record the fault, resume at the probe's recovery point (AC cleared)
/// and return true.
pub fn probe_fixup(frame: &mut x86_64::structures::idt::InterruptStackFrame, error: u64) -> bool {
    let fix = PROBE_FIXUP.swap(0, Ordering::SeqCst);
    if fix == 0 {
        return false;
    }
    let cr2 = x86_64::registers::control::Cr2::read_raw();
    PROBE_CR2.store(cr2, Ordering::SeqCst);
    PROBE_ERROR.store(error, Ordering::SeqCst);
    let rsp = PROBE_RSP.load(Ordering::SeqCst);
    unsafe {
        frame.as_mut().update(|f| {
            f.instruction_pointer = x86_64::VirtAddr::new(fix);
            f.stack_pointer = x86_64::VirtAddr::new(rsp);
            f.cpu_flags = x86_64::registers::rflags::RFlags::from_bits_truncate(
                f.cpu_flags.bits() & !RFLAGS_AC,
            );
        })
    };
    true
}

/// Probe target: read one byte at `addr` with no bracket.
#[unsafe(naked)]
pub unsafe extern "C" fn read_byte_unbracketed(addr: u64) -> u64 {
    core::arch::naked_asm!("movzx eax, byte ptr [rdi]", "ret");
}

/// Probe target: read one byte at `addr` through `UserAccess`.
pub extern "C" fn read_byte_bracketed(addr: u64) -> u64 {
    let _window = UserAccess::open();
    unsafe { core::ptr::read_volatile(addr as *const u8) as u64 }
}

/// Probe target: write one byte at `addr` with no bracket.
#[unsafe(naked)]
pub unsafe extern "C" fn write_byte_unbracketed(addr: u64) -> u64 {
    core::arch::naked_asm!("mov byte ptr [rdi], 0x5A", "xor eax, eax", "ret");
}

// ---- entry probe (self-test `smap-entry`) ------------------------------------

/// The pid whose next syscall runs an unbracketed read of its first
/// argument under the probe, before dispatch (0: none).
pub static ENTRY_PROBE_PID: AtomicU64 = AtomicU64::new(0);
/// Result: bit 0 = AC was set when the probe ran, bit 1 = the read faulted,
/// bit 2 = the probe ran.
pub static ENTRY_PROBE_RESULT: AtomicU64 = AtomicU64::new(0);

/// Called from the syscall entry for `pid` after AC handling.
pub fn entry_probe(pid: u64, arg0: u64) {
    if pid == 0 || ENTRY_PROBE_PID.load(Ordering::SeqCst) != pid {
        return;
    }
    ENTRY_PROBE_PID.store(0, Ordering::SeqCst);
    let ac = ac_set();
    let faulted = if crate::syscall::fs::valid_user_range(arg0, 1) {
        probe_call(read_byte_unbracketed as *const () as u64, arg0)
    } else {
        false
    };
    ENTRY_PROBE_RESULT.store(4 | (faulted as u64) << 1 | ac as u64, Ordering::SeqCst);
}
