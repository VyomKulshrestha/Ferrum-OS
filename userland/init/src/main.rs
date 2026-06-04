#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

#[no_mangle]
pub extern "C" fn _start() -> ! {
    let msg: *const u8 = b"FERRUMOS_INIT v1: ring-3 placeholder reached\n".as_ptr();
    let len: u64 = 45;
    let fd: u64 = 1;
    unsafe {
        asm!(
            "mov rax, {sys_write}",
            "mov rdi, {fd}",
            "mov rsi, {msg}",
            "mov rdx, {len}",
            "int 0x80",
            sys_write = in(reg) 1u64,
            fd = in(reg) fd,
            msg = in(reg) msg,
            len = in(reg) len,
            options(preserves_flags),
        );
    }
    unsafe {
        asm!(
            "mov rax, {sys_exit}",
            "int 0x80",
            sys_exit = in(reg) 2u64,
            options(preserves_flags),
        );
    }
    loop {
        unsafe {
            asm!("hlt", options(nomem, nostack, preserves_flags));
        }
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
