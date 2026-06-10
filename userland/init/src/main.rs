// ============================================================================
// FerrumOS - init (PID 1)
// ============================================================================
// The first userspace process. It runs in ring 3 and may only touch the
// kernel through the `int 0x80` system call ABI — any attempt to execute a
// privileged instruction (in/out, hlt, cli, ...) faults and the kernel
// terminates the process.
//
// Responsibilities (minimal, but real):
//   1. Announce itself on the console via SYS_WRITE.
//   2. Report its own pid via SYS_GETPID.
//   3. Enter a supervision loop that sleeps (SYS_SLEEP) so it yields the
//      CPU cooperatively instead of spinning, the way a real init does
//      while waiting to reap children.
//
// When the operator wants the machine back, init exits cleanly via
// SYS_EXIT, which returns control to the kernel shell.
// ============================================================================
#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

// Stable syscall numbers — must match `src/syscall/mod.rs::SyscallNumber`.
const SYS_YIELD: u64 = 0;
const SYS_EXIT: u64 = 30;
const SYS_GETPID: u64 = 31;
const SYS_SLEEP: u64 = 32;
const SYS_WRITE: u64 = 34;

/// File descriptor for the console (mirrored to serial).
const FD_CONSOLE: u64 = 1;

/// Three-argument `int 0x80`. rax = number, rdi/rsi/rdx = args.
#[inline(always)]
unsafe fn syscall3(number: u64, a1: u64, a2: u64, a3: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") a1,
        in("rsi") a2,
        in("rdx") a3,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags),
    );
    ret
}

/// Write a byte slice to the console via SYS_WRITE.
fn write(msg: &str) {
    unsafe {
        syscall3(
            SYS_WRITE,
            FD_CONSOLE,
            msg.as_ptr() as u64,
            msg.len() as u64,
        );
    }
}

/// Sleep for `ms` milliseconds, yielding the CPU.
fn sleep(ms: u64) {
    unsafe {
        syscall3(SYS_SLEEP, ms, 0, 0);
    }
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    write("[init] userspace is alive in ring 3\n");

    // Confirm SYS_GETPID round-trips. The kernel assigns this process its
    // real pid (not necessarily 1 — the boot sequence creates demo address
    // spaces first), so we only assert the call returned a valid (non-zero)
    // pid rather than a specific number.
    let pid = unsafe { syscall3(SYS_GETPID, 0, 0, 0) };
    if pid != 0 {
        write("[init] obtained pid from kernel via SYS_GETPID\n");
    } else {
        write("[init] SYS_GETPID returned 0 (unexpected)\n");
    }

    write("[init] entering supervision loop (sleeping)\n");

    // Supervision loop: sleep so we cooperatively yield the CPU. A real
    // init would also reap exited children here via SYS_WAITPID. We run a
    // bounded number of iterations and then exit cleanly so the demo
    // returns control to the shell rather than spinning forever.
    let mut beats: u64 = 0;
    while beats < 5 {
        sleep(200);
        // Touch SYS_YIELD too, exercising the cooperative path.
        unsafe {
            syscall3(SYS_YIELD, 0, 0, 0);
        }
        beats += 1;
    }

    write("[init] supervision complete, exiting cleanly\n");
    unsafe {
        syscall3(SYS_EXIT, 0, 0, 0);
    }
    // SYS_EXIT does not return; satisfy the `!` return type.
    loop {
        unsafe {
            syscall3(SYS_YIELD, 0, 0, 0);
        }
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    // Cannot use privileged instructions in ring 3; spin on yield.
    loop {
        unsafe {
            syscall3(SYS_YIELD, 0, 0, 0);
        }
    }
}
