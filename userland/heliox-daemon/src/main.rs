#![no_std]
#![no_main]

extern crate alloc;

use core::arch::asm;
use core::panic::PanicInfo;
use alloc::string::String;
use alloc::vec::Vec;

pub mod memory;
pub mod cognitive;

// Basic bump allocator for userspace
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

// Static heap size: 2 MB
static mut HEAP: [u8; 2 * 1024 * 1024] = [0; 2 * 1024 * 1024];

#[inline(always)]
pub unsafe fn syscall3(number: u64, arg1: u64, arg2: u64, arg3: u64) -> u64 {
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

const SYS_IPC_SEND: u64 = 1; // Assuming 1 is IpcSend in SyscallNumber
const SYS_SOCKET: u64 = 7;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;

#[no_mangle]
pub extern "C" fn _start() -> ! {
    // Initialize heap
    unsafe {
        ALLOCATOR.lock().init(HEAP.as_mut_ptr(), HEAP.len());
    }

    // Initialize cognitive systems
    let mut orchestrator = cognitive::orchestrator::Orchestrator::new();
    
    // Send a message via IPC to the kernel to announce readiness
    let msg = b"HELIOX_READY";
    unsafe {
        syscall3(SYS_IPC_SEND, 1 /* target pid */, msg.as_ptr() as u64, msg.len() as u64);
    }
    
    // Main Agent Loop
    loop {
        orchestrator.tick();
        
        // Wait/yield loop in a real implementation
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
