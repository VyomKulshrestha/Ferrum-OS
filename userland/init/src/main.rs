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
const SYS_CREATE_DIR: u64 = 21;
const SYS_DELETE_FILE: u64 = 22;
const SYS_INJECT_KEY: u64 = 26;
const SYS_EXIT: u64 = 30;
const SYS_GETPID: u64 = 31;
const SYS_SLEEP: u64 = 32;
const SYS_WAITPID: u64 = 33;
const SYS_WRITE: u64 = 34;
const SYS_KEXEC: u64 = 38;

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

fn test_sse_preemption() -> bool {
    let val0: u64 = 0xDEADBEEF11223344;
    let val1: u64 = 0xCAFEBABE55667788;
    let mut out0: u64 = 0;
    let mut out1: u64 = 0;

    unsafe {
        asm!(
            "movq xmm0, {val0}",
            "movq xmm1, {val1}",
            // Loop 20 times yielding CPU so we get preempted and scheduled out/in
            "mov rcx, 20",
            "2:",
            "mov rax, 0", // SYS_YIELD is 0
            "int 0x80",
            // Also spin a bit to let timer interrupt preemption happen
            "mov rdx, 2000000",
            "3:",
            "dec rdx",
            "jnz 3b",
            "dec rcx",
            "jnz 2b",
            // Read back xmm0 and xmm1
            "movq {out0}, xmm0",
            "movq {out1}, xmm1",
            val0 = in(reg) val0,
            val1 = in(reg) val1,
            out0 = out(reg) out0,
            out1 = out(reg) out1,
            out("rcx") _,
            out("rdx") _,
            out("rax") _,
            options(nostack)
        );
    }

    out0 == val0 && out1 == val1
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
    } else if test_mode == b'3' {
        if pid == 2 {
            write("[test] --- Phase F Verification Suite ---\n");

            // Test 1: SSE preemption safety
            write("[test] 1. SSE preemption safety\n");
            if test_sse_preemption() {
                write("[test] 1. SSE preemption safety: OK\n");
            } else {
                write("[test] 1. SSE preemption safety: FAILED\n");
            }

            // Test 2: Local offline inference
            write("[test] 2. Local offline inference\n");
            let res_dir1 = unsafe {
                syscall3(SYS_CREATE_DIR, "/disk/heliox".as_ptr() as u64, "/disk/heliox".len() as u64, 0)
            };
            write_num("[test] create /disk/heliox res: ", res_dir1 as i64, "\n");

            let res_dir2 = unsafe {
                syscall3(SYS_CREATE_DIR, "/disk/heliox/models".as_ptr() as u64, "/disk/heliox/models".len() as u64, 0)
            };
            write_num("[test] create /disk/heliox/models res: ", res_dir2 as i64, "\n");

            let mut model_bytes = [0u8; 1024];
            model_bytes[0] = b'G';
            model_bytes[1] = b'G';
            model_bytes[2] = b'U';
            model_bytes[3] = b'F';
            model_bytes[4] = 3;
            model_bytes[5] = 0;
            model_bytes[6] = 0;
            model_bytes[7] = 0;
            for idx in 8..1024 {
                model_bytes[idx] = (idx % 250) as u8;
            }
            let res_write1 = unsafe {
                syscall4(
                    SYS_WRITE_FILE,
                    "/disk/heliox/models/toy.gguf".as_ptr() as u64,
                    "/disk/heliox/models/toy.gguf".len() as u64,
                    model_bytes.as_ptr() as u64,
                    model_bytes.len() as u64,
                )
            };
            write_num("[test] write /disk/heliox/models/toy.gguf res: ", res_write1 as i64, "\n");
            write("[test] 2. Local offline inference setup complete\n");

            // Test 3: Setup host-assisted self-evolution kexec target
            write("[test] 3. Setup host-assisted self-evolution kexec target\n");
            let res_dir3 = unsafe {
                syscall3(SYS_CREATE_DIR, "/disk/boot".as_ptr() as u64, "/disk/boot".len() as u64, 0)
            };
            write_num("[test] create /disk/boot res: ", res_dir3 as i64, "\n");
            let mut payload = [0x90u8; 128];
            payload[0] = 0x7F;
            payload[1] = 0x45;
            payload[2] = 0x4C;
            payload[3] = 0x46;
            
            payload[71] = 0x66; payload[72] = 0xBA; payload[73] = 0xF8; payload[74] = 0x03; // mov dx, 0x3f8
            payload[75] = 0xB0; payload[76] = 0x4B; // mov al, 'K'
            payload[77] = 0xEE; // out dx, al
            payload[78] = 0xB0; payload[79] = 0x45; // mov al, 'E'
            payload[80] = 0xEE; // out dx, al
            payload[81] = 0xB0; payload[82] = 0x58; // mov al, 'X'
            payload[83] = 0xEE; // out dx, al
            payload[84] = 0xB0; payload[85] = 0x45; // mov al, 'E'
            payload[86] = 0xEE; // out dx, al
            payload[87] = 0xB0; payload[88] = 0x43; // mov al, 'C'
            payload[89] = 0xEE; // out dx, al
            payload[90] = 0xB0; payload[91] = 0x0A; // mov al, '\n'
            payload[92] = 0xEE; // out dx, al
            payload[93] = 0xFA; // cli
            payload[94] = 0xF4; // hlt

            let res_write2 = unsafe {
                syscall4(
                    SYS_WRITE_FILE,
                    "/disk/boot/kernel.bin".as_ptr() as u64,
                    "/disk/boot/kernel.bin".len() as u64,
                    payload.as_ptr() as u64,
                    payload.len() as u64,
                )
            };
            write_num("[test] write /disk/boot/kernel.bin res: ", res_write2 as i64, "\n");
            write("[test] 3. Kexec payload written to /disk/boot/kernel.bin\n");

            // Now, spawn heliox-daemon and let it run
            write("[test] Setup complete, spawning heliox-daemon...\n");
            let path = "/bin/heliox-daemon";
            let daemon_pid = unsafe {
                syscall3(
                    SYS_EXEC,
                    path.as_ptr() as u64,
                    path.len() as u64,
                    0,
                )
            };
            if (daemon_pid as i64) < 0 {
                write("[test] Failed to spawn heliox-daemon!\n");
                unsafe { syscall3(SYS_EXIT, 1, 0, 0); }
            } else {
                write("[test] Spawned heliox-daemon successfully. Monitoring...\n");
                // Wait for the daemon to run (which will be tested externally over websocket)
                loop {
                    let status = unsafe { syscall3(SYS_WAITPID, daemon_pid, 0, 0) };
                    if (status as i64) >= 0 {
                        break;
                    }
                    sleep(100);
                }
                write("[test] heliox-daemon exited, ending test suite\n");
                unsafe { syscall3(SYS_EXIT, 0, 0, 0); }
            }
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
