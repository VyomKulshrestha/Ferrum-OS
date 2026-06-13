// ============================================================================
// FerrumOS - init (PID 2)
// ============================================================================
// The first userspace process. It runs in ring 3 and may only touch the
// kernel through the `int 0x80` system call ABI.
// ============================================================================
#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

// Stable syscall numbers — must match `src/syscall/mod.rs::SyscallNumber`.
const SYS_YIELD: u64 = 0;
const SYS_READ_FILE: u64 = 15;
const SYS_EXEC: u64 = 18;
const SYS_EXIT: u64 = 30;
const SYS_GETPID: u64 = 31;
const SYS_SLEEP: u64 = 32;
const SYS_WAITPID: u64 = 33;
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

/// Four-argument `int 0x80`. rax = number, rdi/rsi/rdx/r10 = args.
#[inline(always)]
unsafe fn syscall4(number: u64, a1: u64, a2: u64, a3: u64, a4: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") a1,
        in("rsi") a2,
        in("rdx") a3,
        in("r10") a4,
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

/// Checks if we should run in test mode (clean exit for scripts).
fn is_test_mode() -> bool {
    let path = "/tmp/init_test";
    let mut buf = [0u8; 1];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            path.as_ptr() as u64,
            path.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    (res as i64) > 0 && buf[0] == b'1'
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    write("[init] userspace is alive in ring 3\n");

    let pid = unsafe { syscall3(SYS_GETPID, 0, 0, 0) };
    if pid != 0 {
        write("[init] obtained pid from kernel via SYS_GETPID\n");
    } else {
        write("[init] SYS_GETPID returned 0 (unexpected)\n");
    }

    if is_test_mode() {
        write("[init] test mode detected, running 5-beat sleep loop\n");
        let mut beats: u64 = 0;
        while beats < 5 {
            sleep(200);
            unsafe {
                syscall3(SYS_YIELD, 0, 0, 0);
            }
            beats += 1;
        }
        write("[init] supervision complete, exiting cleanly\n");
        unsafe {
            syscall3(SYS_EXIT, 0, 0, 0);
        }
    } else {
        let path = "/bin/heliox-daemon";
        loop {
            write("[init] Spawning heliox-daemon...\n");
            let daemon_pid = unsafe {
                syscall3(
                    SYS_EXEC,
                    path.as_ptr() as u64,
                    path.len() as u64,
                    0,
                )
            };

            if (daemon_pid as i64) < 0 {
                write("[init] Failed to spawn heliox-daemon! Retrying in 1 second...\n");
                sleep(1000);
                continue;
            }

            write("[init] Spawned heliox-daemon successfully, supervising...\n");

            // Sleep-polling loop to check daemon exit status
            loop {
                let status = unsafe { syscall3(SYS_WAITPID, daemon_pid, 0, 0) };
                if (status as i64) >= 0 {
                    break;
                }
                sleep(100);
            }

            write("[init] heliox-daemon exited or crashed! Restarting...\n");
            sleep(500); // Throttling restart
        }
    }

    // fallback exit
    unsafe {
        syscall3(SYS_EXIT, 0, 0, 0);
    }
    loop {
        unsafe {
            syscall3(SYS_YIELD, 0, 0, 0);
        }
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {
        unsafe {
            syscall3(SYS_YIELD, 0, 0, 0);
        }
    }
}
