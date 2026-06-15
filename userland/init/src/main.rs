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
const SYS_WRITE_FILE: u64 = 16;
const SYS_EXEC: u64 = 18;
const SYS_DELETE_FILE: u64 = 22;
const SYS_INJECT_KEY: u64 = 26;
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

/// Write an integer with prefix and suffix.
fn write_num(prefix: &str, num: i64, suffix: &str) {
    write(prefix);
    let mut buf = [0u8; 20];
    let mut i = 20;
    let is_neg = num < 0;
    let mut val = if is_neg { -num } else { num } as u64;
    if val == 0 {
        i -= 1;
        buf[i] = b'0';
    } else {
        while val > 0 {
            i -= 1;
            buf[i] = b'0' + (val % 10) as u8;
            val /= 10;
        }
    }
    if is_neg {
        i -= 1;
        buf[i] = b'-';
    }
    unsafe {
        let s = core::str::from_utf8_unchecked(&buf[i..]);
        write(s);
    }
    write(suffix);
}

/// Get the test mode character from /tmp/init_test.
fn get_test_mode() -> u8 {
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
    if (res as i64) > 0 {
        buf[0]
    } else {
        0
    }
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

    let test_mode = get_test_mode();
    if test_mode == b'1' {
        write("[init] test mode 1 detected, running 5-beat sleep loop\n");
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
    } else if test_mode == b'2' {
        if pid == 2 {
            write("[test] --- Phase E Verification Suite ---\n");

            // Test 1: Syscall Rate Limit Quota
            write("[test] 1. Syscall Rate Limit Quota\n");
            write("[test] parent init spawning quota-test...\n");
            let child_pid = unsafe {
                syscall3(SYS_EXEC, "/bin/quota-test".as_ptr() as u64, "/bin/quota-test".len() as u64, 0)
            };
            if (child_pid as i64) < 0 {
                write_num("[test] failed to exec quota-test: ", child_pid as i64, "\n");
            } else {
                loop {
                    let status = unsafe { syscall3(SYS_WAITPID, child_pid, 0, 0) };
                    if (status as i64) >= 0 {
                        write_num("[test] child exited with status ", status as i64, "\n");
                        break;
                    }
                    sleep(100);
                }
            }

            // Test 2: Memory Quota
            write("[test] 2. Memory Quota\n");
            write("[test] parent init spawning huge-test...\n");
            let huge_pid = unsafe {
                syscall3(SYS_EXEC, "/bin/huge-test".as_ptr() as u64, "/bin/huge-test".len() as u64, 0)
            };
            write_num("[test] exec huge-test returned: ", huge_pid as i64, "\n");

            // Test 3: Confirmation Gates
            write("[test] 3. Confirmation Gates\n");

            // Sub-test 3.1: Timeout (5s)
            write("[test] sub-test 3.1: timeout (wait 5s)\n");
            unsafe {
                syscall4(SYS_WRITE_FILE, "/tmp/t1".as_ptr() as u64, "/tmp/t1".len() as u64, "data".as_ptr() as u64, 4);
            }
            let res1 = unsafe {
                syscall3(SYS_DELETE_FILE, "/tmp/t1".as_ptr() as u64, "/tmp/t1".len() as u64, 0)
            };
            write_num("[test] sub-test 3.1 result: ", res1 as i64, "\n");

            // Sub-test 3.2: Physical key approval
            write("[test] sub-test 3.2: physical key approval (wait for y)\n");
            unsafe {
                syscall4(SYS_WRITE_FILE, "/tmp/t2".as_ptr() as u64, "/tmp/t2".len() as u64, "data".as_ptr() as u64, 4);
            }
            let res2 = unsafe {
                syscall3(SYS_DELETE_FILE, "/tmp/t2".as_ptr() as u64, "/tmp/t2".len() as u64, 0)
            };
            write_num("[test] sub-test 3.2 result: ", res2 as i64, "\n");

            // Sub-test 3.3: Agent injected key
            write("[test] sub-test 3.3: injected key (should timeout/deny)\n");
            unsafe {
                syscall4(SYS_WRITE_FILE, "/tmp/t3".as_ptr() as u64, "/tmp/t3".len() as u64, "data".as_ptr() as u64, 4);
            }
            unsafe {
                syscall3(SYS_INJECT_KEY, 121, 1, 0); // 'y' pressed
                syscall3(SYS_INJECT_KEY, 121, 0, 0); // 'y' released
            }
            let res3 = unsafe {
                syscall3(SYS_DELETE_FILE, "/tmp/t3".as_ptr() as u64, "/tmp/t3".len() as u64, 0)
            };
            write_num("[test] sub-test 3.3 result: ", res3 as i64, "\n");

            write("[test] --- Verification Suite Complete ---\n");
            unsafe { syscall3(SYS_EXIT, 0, 0, 0); }
        } else {
            write("[test] child starting rate limit test...\n");
            for _ in 0..1100 {
                unsafe { syscall3(SYS_GETPID, 0, 0, 0); }
            }
            write("[test] child completed rate limit test (unexpected!)\n");
            unsafe { syscall3(SYS_EXIT, 0, 0, 0); }
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
