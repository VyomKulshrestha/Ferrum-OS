// ============================================================================
// FerrumOS - First userspace process (init)
// ============================================================================
// This is the placeholder userspace binary that the kernel will load in ring 3
// in Phase 1.4. For now it just prints a banner to the COM1 serial port and
// halts. Once the syscall ABI and ring-3 entry exist, this binary will
// transition to a small `hlt`-yielding loop that exercises `SYS_YIELD` and
// the audit log via `SYS_AUDIT_WRITE`.
// ============================================================================

#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

const COM1: u16 = 0x3F8;
const BANNER: &[u8] = b"FERRUMOS_INIT v1: ring-3 placeholder reached\n";

#[no_mangle]
pub extern "C" fn _start() -> ! {
    write_serial(BANNER);
    loop {
        unsafe {
            asm!("hlt", options(nomem, nostack, preserves_flags));
        }
    }
}

fn write_serial(msg: &[u8]) {
    for &byte in msg {
        unsafe {
            asm!(
                "out dx, al",
                in("dx") COM1,
                in("al") byte,
                options(nomem, nostack, preserves_flags),
            );
        }
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    write_serial(b"FERRUMOS_INIT panic\n");
    loop {
        unsafe {
            asm!("hlt", options(nomem, nostack, preserves_flags));
        }
    }
}
