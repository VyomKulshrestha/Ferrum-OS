#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        asm!(
            "mov dx, 0x3f8",
            "mov al, 0x41",
            "out dx, al",
            "mov al, 0x42",
            "out dx, al",
            "mov al, 0x43",
            "out dx, al",
            "mov al, 0x0a",
            "out dx, al",
            "2:",
            "hlt",
            "jmp 2b",
            options(noreturn, preserves_flags),
        );
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {
        unsafe {
            asm!("hlt", options(nomem, nostack, preserves_flags));
        }
    }
}
