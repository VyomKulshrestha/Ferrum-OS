#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

#[inline(always)]
unsafe fn syscall3(number: u64, arg1: u64, arg2: u64, arg3: u64) -> u64 {
    let mut ret: u64;
    asm!(
        "syscall",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

#[inline(always)]
unsafe fn syscall2(number: u64, arg1: u64, arg2: u64) -> u64 {
    let mut ret: u64;
    asm!(
        "syscall",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

#[inline(always)]
unsafe fn syscall1(number: u64, arg1: u64) -> u64 {
    let mut ret: u64;
    asm!(
        "syscall",
        inout("rax") number => ret,
        in("rdi") arg1,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

const SYS_SOCKET: u64 = 7;
const SYS_BIND: u64 = 8;
const SYS_LISTEN: u64 = 9;
const SYS_ACCEPT: u64 = 10;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        // 1. Create a socket (domain=2 AF_INET, type=1 SOCK_STREAM, protocol=0)
        let fd = syscall3(SYS_SOCKET, 2, 1, 0);
        
        // 2. Bind to port 8785
        let _ = syscall2(SYS_BIND, fd, 8785);

        // 3. Listen
        let _ = syscall2(SYS_LISTEN, fd, 10);

        loop {
            // 4. Accept connection
            let client_fd = syscall1(SYS_ACCEPT, fd);

            if client_fd > 0 {
                // 5. Receive WebSocket Handshake
                let mut buf = [0u8; 1024];
                let bytes_read = syscall3(SYS_RECV, client_fd, buf.as_mut_ptr() as u64, buf.len() as u64);

                // For a full implementation, we'd parse the HTTP headers, compute the 
                // Sec-WebSocket-Accept hash, and send the response back via SYS_SEND.
                // Then we'd enter a loop reading JSON-RPC WebSocket frames, 
                // and forwarding them to the kernel IPC broker (runtime.heliox.bridge).
                
                if bytes_read > 0 {
                    let response = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n";
                    let _ = syscall3(SYS_SEND, client_fd, response.as_ptr() as u64, response.len() as u64);
                }
            }
            
            // Wait/yield loop in a real implementation
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
