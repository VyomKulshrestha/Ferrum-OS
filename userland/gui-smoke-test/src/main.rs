// ============================================================================
// FerrumOS - GUI App Window Framework Smoke Test (D1)
// ============================================================================
// Exercises the CreateWindow/PresentWindow/PollWindowInput syscalls end to
// end: creates a window, fills its canvas with a known color, and echoes
// received input events to serial. `scripts/verify_app_window.mjs` boots
// the appliance, spawns this binary, screendumps the framebuffer to check
// the fill color landed on screen, then sends a keystroke and checks it
// was received via PollWindowInput.
// ============================================================================
#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

const SYS_YIELD: u64 = 0;
const SYS_EXIT: u64 = 30;
const SYS_SLEEP: u64 = 32;
const SYS_WRITE: u64 = 34;
const SYS_CREATE_WINDOW: u64 = 44;
const SYS_PRESENT_WINDOW: u64 = 45;
const SYS_POLL_WINDOW_INPUT: u64 = 46;

/// File descriptor for the console (mirrored to serial).
const FD_CONSOLE: u64 = 2;

const CANVAS_W: usize = 200;
const CANVAS_H: usize = 120;
const FILL_R: u8 = 0x11;
const FILL_G: u8 = 0x66;
const FILL_B: u8 = 0xCC;

/// The canvas buffer. Kept as a fixed-size static rather than a heap
/// allocation so this smoke test needs no allocator setup.
static mut CANVAS: [u8; CANVAS_W * CANVAS_H * 4] = [0; CANVAS_W * CANVAS_H * 4];

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

fn write(msg: &str) {
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
    }
}

fn sleep(ms: u64) {
    unsafe {
        syscall3(SYS_SLEEP, ms, 0, 0);
    }
}

/// Write an integer with no surrounding text, for chaining onto a
/// prefix/suffix pair written separately (used to build one log line out
/// of several fields without needing a `no_std` formatter).
fn write_int(num: i64) {
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
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    write("[gui-smoke-test] alive in ring 3\n");

    let title = "Smoke Test";
    let window_id = unsafe {
        syscall4(
            SYS_CREATE_WINDOW,
            title.as_ptr() as u64,
            title.len() as u64,
            CANVAS_W as u64,
            CANVAS_H as u64,
        )
    };

    write("[gui-smoke-test] window created id=");
    write_int(window_id as i64);
    write(" canvas_w=");
    write_int(CANVAS_W as i64);
    write(" canvas_h=");
    write_int(CANVAS_H as i64);
    write("\n");

    unsafe {
        let mut i = 0;
        while i < CANVAS_W * CANVAS_H {
            let o = i * 4;
            CANVAS[o] = FILL_R;
            CANVAS[o + 1] = FILL_G;
            CANVAS[o + 2] = FILL_B;
            CANVAS[o + 3] = 0xFF;
            i += 1;
        }
    }

    let present_res = unsafe {
        syscall3(
            SYS_PRESENT_WINDOW,
            window_id,
            core::ptr::addr_of!(CANVAS) as u64,
            (CANVAS_W * CANVAS_H * 4) as u64,
        )
    };
    write("[gui-smoke-test] presented fill r=17 g=102 b=204 res=");
    write_int(present_res as i64);
    write("\n");

    // Poll for input for up to ~10s (200 * 50ms), logging every event
    // received. Exits early on the 'q' key so the verify script doesn't
    // have to wait out the full timeout on the happy path.
    let mut buf = [0u32; 5];
    let mut iterations = 0u32;
    loop {
        if iterations >= 200 {
            write("[gui-smoke-test] input wait timed out\n");
            break;
        }
        let got = unsafe { syscall3(SYS_POLL_WINDOW_INPUT, window_id, buf.as_mut_ptr() as u64, 20) };
        if got == 1 {
            let tag = buf[0];
            if tag == 0 {
                write("[gui-smoke-test] received key ascii=");
                write_int(buf[1] as i64);
                write("\n");
                if buf[1] == b'q' as u32 {
                    write("[gui-smoke-test] exit key received, shutting down\n");
                    break;
                }
            } else if tag == 3 {
                write("[gui-smoke-test] received mouse-down x=");
                write_int(buf[2] as i64);
                write(" y=");
                write_int(buf[3] as i64);
                write("\n");
            }
        } else {
            sleep(50);
            iterations += 1;
        }
    }

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
