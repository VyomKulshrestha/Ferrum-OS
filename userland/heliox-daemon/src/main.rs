#![no_std]
#![no_main]

extern crate alloc;

use core::arch::asm;
use core::panic::PanicInfo;
use alloc::string::String;
use alloc::vec::Vec;

pub mod memory;
pub mod cognitive;
pub mod network;
pub mod config;

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
        "int 0x80",
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
pub unsafe fn syscall4(number: u64, arg1: u64, arg2: u64, arg3: u64, arg4: u64) -> u64 {
    let mut ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        in("r10") arg4,
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
pub const SYS_READ_FILE: u64 = 15;
pub const SYS_WRITE_FILE: u64 = 16;
pub const SYS_READ_DIR: u64 = 17;
pub const SYS_EXEC: u64 = 18;
const SYS_EXIT: u64 = 30;
const SYS_SLEEP: u64 = 32;
const SYS_WRITE: u64 = 34;
const FD_CONSOLE: u64 = 1;

#[no_mangle]
pub extern "C" fn _start() -> ! {
    // Write startup log
    let startup_msg = "[heliox-daemon] userspace agent daemon is alive in ring 3\n";
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, startup_msg.as_ptr() as u64, startup_msg.len() as u64);
    }

    // Initialize heap
    unsafe {
        ALLOCATOR.lock().init(HEAP.as_mut_ptr(), HEAP.len());
    }

    // Initialize cognitive systems
    let mut orchestrator = cognitive::orchestrator::Orchestrator::new();
    
    // Send a message via IPC to the kernel to announce readiness
    let svc = "gui";
    let msg = b"HELIOX_READY";
    unsafe {
        syscall4(SYS_IPC_SEND, svc.as_ptr() as u64, svc.len() as u64, msg.as_ptr() as u64, msg.len() as u64);
    }
    let ready_msg = "[heliox-daemon] sent HELIOX_READY IPC announce\n";
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, ready_msg.as_ptr() as u64, ready_msg.len() as u64);
    }
    
    // Main Agent Loop
    let mut loop_count = 0;
    loop {
        orchestrator.tick();
        
        if orchestrator.config.api_host != "unconfigured" {
            // Ambient Voice Command Listener (1-second buffer)
            if let Ok(buf) = cognitive::voice::record_audio(1000) {
                if cognitive::voice::detect_voice_activity(&buf) {
                    if let Ok(text) = cognitive::voice::transcribe(&buf) {
                        // Voice command detected!
                        // In a real implementation we would route this to orchestrator
                        let _ = cognitive::voice::play_audio(&cognitive::voice::generate_beep());
                    }
                }
            }
        }

        loop_count += 1;
        if loop_count <= 5 {
            let tick_msg = "[heliox-daemon] loop tick complete, sleeping...\n";
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, tick_msg.as_ptr() as u64, tick_msg.len() as u64);
            }
        }

        // Sleep to cooperatively yield CPU time
        unsafe {
            syscall3(SYS_SLEEP, 100, 0, 0);
        }
    }
}

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    loop {
        unsafe {
            syscall3(SYS_EXIT, 101, 0, 0);
        }
    }
}

