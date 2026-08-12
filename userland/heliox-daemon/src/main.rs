#![no_std]
#![no_main]

extern crate alloc;

use core::arch::asm;
use alloc::string::String;
use alloc::vec::Vec;

pub mod memory;
pub mod cognitive;
pub mod network;
pub mod config;
pub mod physical;
pub mod neural;

// Basic bump allocator for userspace
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

// Static heap size: 64 MB. The real checkpoint remains mmap'd and quantized;
// inference expands only the currently used token row, while RunState, the
// tokenizer, networking, and the cognitive services share this heap.  Keep
// the explicit headroom for long-lived OS workloads: ELF BSS is mapped
// eagerly at process-spawn time, so increasing it also has a real boot cost.
static mut HEAP: [u8; 64 * 1024 * 1024] = [0; 64 * 1024 * 1024];

pub static LATEST_GESTURE: core::sync::atomic::AtomicU8 = core::sync::atomic::AtomicU8::new(0);

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

const SYS_GET_RANDOM: u64 = 42;

fn custom_getrandom(buf: &mut [u8]) -> Result<(), getrandom::Error> {
    let ret = unsafe { syscall3(SYS_GET_RANDOM, buf.as_mut_ptr() as u64, buf.len() as u64, 0) };
    if (ret as i64) < 0 {
        return Err(getrandom::Error::UNSUPPORTED);
    }
    Ok(())
}
getrandom::register_custom_getrandom!(custom_getrandom);

const SYS_IPC_SEND: u64 = 1; // Assuming 1 is IpcSend in SyscallNumber
const SYS_SOCKET: u64 = 7;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;
pub const SYS_READ_FILE: u64 = 15;
pub const SYS_WRITE_FILE: u64 = 16;
pub const SYS_READ_DIR: u64 = 17;
pub const SYS_EXEC: u64 = 18;
const SYS_DELETE_FILE: u64 = 22;
const SYS_EXIT: u64 = 30;
const SYS_SLEEP: u64 = 32;
const SYS_WRITE: u64 = 34;
const FD_CONSOLE: u64 = 2;
const SYS_INJECT_KEY: u64 = 26;
const SYS_INJECT_MOUSE: u64 = 27;

fn check_and_trigger_supervision_test() {
    let test_file = "/tmp/daemon_exit_once";
    let mut buf = [0u8; 1];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            test_file.as_ptr() as u64,
            test_file.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (res as i64) > 0 {
        // Delete the file so it doesn't loop forever
        unsafe {
            syscall3(SYS_DELETE_FILE, test_file.as_ptr() as u64, test_file.len() as u64, 0);
        }
        let exit_msg = "[heliox-daemon] exiting for supervision test\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, exit_msg.as_ptr() as u64, exit_msg.len() as u64);
            syscall3(SYS_EXIT, 42, 0, 0);
        }
    }
}

fn check_and_trigger_net_test() {
    let test_file = "/tmp/net_test";
    let mut buf = [0u8; 64];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            test_file.as_ptr() as u64,
            test_file.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (res as i64) > 0 {
        // Delete the file so it doesn't loop forever
        unsafe {
            syscall3(SYS_DELETE_FILE, test_file.as_ptr() as u64, test_file.len() as u64, 0);
        }
        // Format: host:port/path (e.g. 10.0.2.2:8080/test)
        let content = core::str::from_utf8(&buf[..res as usize]).unwrap_or("").trim();
        if !content.is_empty() {
            if let Some((addr, path)) = content.split_once('/') {
                if let Some((host, port_str)) = addr.split_once(':') {
                    if let Ok(port) = port_str.parse::<u16>() {
                        let print_msg = alloc::format!("[heliox-daemon] running network test GET to {}:{}/{}\n", host, port, path);
                        unsafe {
                            syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                        }
                        
                        match network::http_get(host, port, &alloc::format!("/{}", path)) {
                            Ok(resp) => {
                                let success_msg = alloc::format!("[heliox-daemon] net_test response status: {}, body: {}\n", resp.status_code, resp.body);
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, success_msg.as_ptr() as u64, success_msg.len() as u64);
                                    syscall3(SYS_EXIT, 0, 0, 0);
                                }
                            }
                            Err(e) => {
                                let err_msg = alloc::format!("[heliox-daemon] net_test failed: {}\n", e);
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
                                    syscall3(SYS_EXIT, 1, 0, 0);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn check_and_trigger_mmap_test() {
    let test_file = "/tmp/mmap_test";
    let mut buf = [0u8; 64];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            test_file.as_ptr() as u64,
            test_file.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (res as i64) > 0 {
        // Delete the file so it doesn't loop
        unsafe {
            syscall3(SYS_DELETE_FILE, test_file.as_ptr() as u64, test_file.len() as u64, 0);
        }
        
        let path = "/disk/mmap_verify";
        let mmap_msg = "[heliox-daemon] running mmap test...\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, mmap_msg.as_ptr() as u64, mmap_msg.len() as u64);
        }

        const SYS_MMAP: u64 = 41;
        let vaddr = unsafe {
            syscall4(
                SYS_MMAP,
                path.as_ptr() as u64,
                path.len() as u64,
                64 * 1024 * 1024, // 64 MiB
                0, // flags
            )
        };

        if (vaddr as i64) < 0 {
            let err_msg = alloc::format!("[heliox-daemon] mmap failed: {}\n", vaddr as i64);
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
                syscall3(SYS_EXIT, 1, 0, 0);
            }
        }

        let success_msg = alloc::format!("[heliox-daemon] mmap success, base=0x{:x}\n", vaddr);
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, success_msg.as_ptr() as u64, success_msg.len() as u64);
        }

        let ready_msg = "[heliox-daemon] ready for initial frame check\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, ready_msg.as_ptr() as u64, ready_msg.len() as u64);
        }

        // Sleep 1 second to give the monitor time to run `process`
        unsafe {
            syscall3(SYS_SLEEP, 1000, 0, 0);
        }

        // Touch first page (offset 0)
        let ptr = vaddr as *const u8;
        let val1_0 = unsafe { *ptr.add(0) };
        let val1_1 = unsafe { *ptr.add(1) };
        let val1_2 = unsafe { *ptr.add(2) };
        let val1_3 = unsafe { *ptr.add(3) };

        // Touch middle page (offset 32 MiB)
        let val2_0 = unsafe { *ptr.add(32 * 1024 * 1024 + 0) };
        let val2_1 = unsafe { *ptr.add(32 * 1024 * 1024 + 1) };
        let val2_2 = unsafe { *ptr.add(32 * 1024 * 1024 + 2) };
        let val2_3 = unsafe { *ptr.add(32 * 1024 * 1024 + 3) };

        // Touch last page (offset 64 MiB - 4 KiB)
        let val3_0 = unsafe { *ptr.add(64 * 1024 * 1024 - 4096 + 0) };
        let val3_1 = unsafe { *ptr.add(64 * 1024 * 1024 - 4096 + 1) };
        let val3_2 = unsafe { *ptr.add(64 * 1024 * 1024 - 4096 + 2) };
        let val3_3 = unsafe { *ptr.add(64 * 1024 * 1024 - 4096 + 3) };

        let match1 = val1_0 == 0x11 && val1_1 == 0x22 && val1_2 == 0x33 && val1_3 == 0x44;
        let match2 = val2_0 == 0x55 && val2_1 == 0x66 && val2_2 == 0x77 && val2_3 == 0x88;
        let match3 = val3_0 == 0xAA && val3_1 == 0xBB && val3_2 == 0xCC && val3_3 == 0xDD;

        let result_msg = alloc::format!(
            "[heliox-daemon] mmap bytes: p1={:x}{:x}{:x}{:x} p2={:x}{:x}{:x}{:x} p3={:x}{:x}{:x}{:x}\n",
            val1_0, val1_1, val1_2, val1_3,
            val2_0, val2_1, val2_2, val2_3,
            val3_0, val3_1, val3_2, val3_3
        );
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, result_msg.as_ptr() as u64, result_msg.len() as u64);
        }

        if match1 && match2 && match3 {
            let match_msg = "[heliox-daemon] mmap validation success: bytes match!\n";
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, match_msg.as_ptr() as u64, match_msg.len() as u64);
                syscall3(SYS_SLEEP, 2000, 0, 0);
                syscall3(SYS_EXIT, 0, 0, 0);
            }
        } else {
            let mismatch_msg = "[heliox-daemon] mmap validation failed: bytes mismatch!\n";
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, mismatch_msg.as_ptr() as u64, mismatch_msg.len() as u64);
                syscall3(SYS_SLEEP, 2000, 0, 0);
                syscall3(SYS_EXIT, 1, 0, 0);
            }
        }
    }
}

/// Test hook for verifying non-blocking audio capture (H5). Triggered by
/// `/tmp/audio_test` (mirrors the mmap/net test hooks above). Records for a
/// fixed duration and reports byte count + elapsed wall-clock ticks, so the
/// verification harness can confirm real DMA-timed capture happened (not an
/// instant no-op) while the shell/other tasks stay responsive throughout.
fn check_and_trigger_audio_test() {
    let test_file = "/tmp/audio_test";
    let mut buf = [0u8; 64];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            test_file.as_ptr() as u64,
            test_file.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (res as i64) > 0 {
        unsafe {
            syscall3(SYS_DELETE_FILE, test_file.as_ptr() as u64, test_file.len() as u64, 0);
        }

        let start_msg = "[heliox-daemon] running audio capture test...\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, start_msg.as_ptr() as u64, start_msg.len() as u64);
        }

        const SYS_RECORD_AUDIO: u64 = 24;
        const DURATION_MS: u64 = 1000;
        let mut rec_buf = alloc::vec![0u8; 4096 * 1024];
        let start_ticks = cognitive::fusion::get_uptime_ticks();
        let n = unsafe {
            syscall3(
                SYS_RECORD_AUDIO,
                rec_buf.as_mut_ptr() as u64,
                rec_buf.len() as u64,
                DURATION_MS,
            )
        };
        let end_ticks = cognitive::fusion::get_uptime_ticks();
        let elapsed_ticks = end_ticks.saturating_sub(start_ticks);

        let result_msg = alloc::format!(
            "[heliox-daemon] audio capture result: bytes={} elapsed_ticks={}\n",
            n as i64,
            elapsed_ticks
        );
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, result_msg.as_ptr() as u64, result_msg.len() as u64);
        }

        let done_msg = "[heliox-daemon] audio capture test complete\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, done_msg.as_ptr() as u64, done_msg.len() as u64);
        }
    }
}

/// Test hook for collecting real world-model training data (see
/// cognitive::world_model's module doc). Triggered by
/// `/tmp/world_model_collect`, whose content is the number of synthetic
/// actions to run (mirrors the mmap/net/audio test hooks above, except
/// the file content is a count rather than just a presence check). Runs
/// entirely before the daemon's normal tick loop starts, so it doesn't
/// compete with anything else for ring-3 time.
fn check_and_trigger_world_model_collect(orchestrator: &mut cognitive::orchestrator::Orchestrator) {
    let test_file = "/tmp/world_model_collect";
    let mut buf = [0u8; 32];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            test_file.as_ptr() as u64,
            test_file.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (res as i64) <= 0 {
        return;
    }
    unsafe {
        syscall3(SYS_DELETE_FILE, test_file.as_ptr() as u64, test_file.len() as u64, 0);
    }

    let count_str = core::str::from_utf8(&buf[..res as usize]).unwrap_or("0").trim();
    let count: u32 = count_str.parse().unwrap_or(0);
    if count == 0 {
        return;
    }

    let start_msg = alloc::format!("[heliox-daemon] running world-model data collection ({} actions)...\n", count);
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, start_msg.as_ptr() as u64, start_msg.len() as u64);
    }
    orchestrator.run_data_collection(count);
}

/// Runs the in-guest world-model benchmark before the ambient loop starts.
/// The trigger file contains the number of preview-only actions per horizon.
fn check_and_trigger_world_model_benchmark(orchestrator: &mut cognitive::orchestrator::Orchestrator) {
    let test_file = "/tmp/world_model_benchmark";
    let mut buf = [0u8; 32];
    let res = unsafe {
        syscall4(
            SYS_READ_FILE,
            test_file.as_ptr() as u64,
            test_file.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    if (res as i64) <= 0 {
        return;
    }
    unsafe {
        syscall3(SYS_DELETE_FILE, test_file.as_ptr() as u64, test_file.len() as u64, 0);
    }
    let iterations = core::str::from_utf8(&buf[..res as usize])
        .unwrap_or("0")
        .trim()
        .parse::<u32>()
        .unwrap_or(0);
    if iterations == 0 {
        return;
    }
    let marker = alloc::format!(
        "[heliox-daemon] running world-model in-guest benchmark ({} previews per horizon)...\n",
        iterations,
    );
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, marker.as_ptr() as u64, marker.len() as u64);
    }
    orchestrator.run_world_model_benchmark(iterations);
}

const SYS_ACCEPT: u64 = 10;

fn init_server_socket() -> Result<u64, &'static str> {
    let fd = network::tcp_socket()?;
    if let Err(e) = network::tcp_bind(fd, 8785) {
        let _ = network::tcp_close(fd);
        return Err(e);
    }
    if let Err(e) = network::tcp_listen(fd, 5) {
        let _ = network::tcp_close(fd);
        return Err(e);
    }
    Ok(fd)
}

fn escape_json_string(s: &str) -> String {
    let mut res = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => res.push_str("\\\""),
            '\\' => res.push_str("\\\\"),
            '\n' => res.push_str("\\n"),
            '\r' => res.push_str("\\r"),
            '\t' => res.push_str("\\t"),
            _ => res.push(c),
        }
    }
    res.push('"');
    res
}

fn decode_hex_exact<const N: usize>(text: &str) -> Result<[u8; N], &'static str> {
    if text.len() != N * 2 {
        return Err("invalid hex length");
    }
    let mut output = [0u8; N];
    let bytes = text.as_bytes();
    for index in 0..N {
        let high = hex_nibble(bytes[index * 2]).ok_or("invalid hex character")?;
        let low = hex_nibble(bytes[index * 2 + 1]).ok_or("invalid hex character")?;
        output[index] = (high << 4) | low;
    }
    Ok(output)
}

fn hex_nibble(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

fn neural_now_ns() -> u64 {
    cognitive::fusion::get_uptime_ticks().saturating_mul(1_000_000)
}

fn generate_bridge_pairing_token() -> Result<String, &'static str> {
    let mut bytes = [0u8; 16];
    custom_getrandom(&mut bytes).map_err(|_| "cryptographic random syscall failed")?;
    let mut token = String::with_capacity(bytes.len() * 2);
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for byte in bytes {
        token.push(HEX[(byte >> 4) as usize] as char);
        token.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(token)
}

/// Length-oblivious token comparison. The pairing token is short-lived and
/// random, but avoiding an early-exit comparison also removes a cheap remote
/// timing oracle from the privileged control plane.
fn bridge_token_matches(expected: &str, supplied: &str) -> bool {
    let mut difference = expected.len() ^ supplied.len();
    let max_len = core::cmp::max(expected.len(), supplied.len());
    let expected_bytes = expected.as_bytes();
    let supplied_bytes = supplied.as_bytes();
    for index in 0..max_len {
        let left = expected_bytes.get(index).copied().unwrap_or(0);
        let right = supplied_bytes.get(index).copied().unwrap_or(0);
        difference |= (left ^ right) as usize;
    }
    difference == 0
}

fn send_rpc_error(fd: u64, id: &str, code: i64, message: &str) {
    let response = alloc::format!(
        "{{\"jsonrpc\":\"2.0\",\"error\":{{\"code\":{},\"message\":{}}},\"id\":{}}}",
        code,
        escape_json_string(message),
        id
    );
    let _ = network::ws_send_text_server(fd, &response);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    // Write startup log
    let startup_msg = "[heliox-daemon] userspace agent daemon is alive in ring 3\n";
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, startup_msg.as_ptr() as u64, startup_msg.len() as u64);
    }

    // Check for test exit trigger
    check_and_trigger_supervision_test();

    // Initialize heap
    unsafe {
        ALLOCATOR.lock().init(HEAP.as_mut_ptr(), HEAP.len());
    }

    // Check for network test trigger
    check_and_trigger_net_test();

    // Check for mmap test trigger
    check_and_trigger_mmap_test();

    // Check for audio capture test trigger
    check_and_trigger_audio_test();

    // Initialize cognitive systems
    let mut orchestrator = cognitive::orchestrator::Orchestrator::new();

    // The network bridge delegates the daemon's powerful native syscall
    // authority to an external model/client. Require a fresh physical-console
    // pairing secret on every daemon boot before exposing any state or action.
    let bridge_token = match generate_bridge_pairing_token() {
        Ok(token) => {
            let message = alloc::format!(
                "[heliox-daemon] bridge pairing token: {}\n",
                token
            );
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, message.as_ptr() as u64, message.len() as u64);
            }
            Some(token)
        }
        Err(error) => {
            let message = alloc::format!(
                "[heliox-daemon] bridge disabled: {}\n",
                error
            );
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, message.as_ptr() as u64, message.len() as u64);
            }
            None
        }
    };

    // Check for world-model data collection trigger
    check_and_trigger_world_model_collect(&mut orchestrator);
    check_and_trigger_world_model_benchmark(&mut orchestrator);

    // Print active provider
    let provider_msg = alloc::format!("[heliox-daemon] active provider: {}\n", orchestrator.config.provider);
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, provider_msg.as_ptr() as u64, provider_msg.len() as u64);
    }
    
    // Send a message via IPC to the kernel to announce readiness
    // Queue readiness on the daemon's live control mailbox. The retired
    // kernel-hardcoded `gui` endpoint had no owner and could accumulate
    // forever when no assistant panel was running.
    let svc = "heliox";
    let msg = b"HELIOX_READY";
    unsafe {
        syscall4(SYS_IPC_SEND, svc.as_ptr() as u64, svc.len() as u64, msg.as_ptr() as u64, msg.len() as u64);
    }
    let ready_msg = "[heliox-daemon] sent HELIOX_READY IPC announce\n";
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, ready_msg.as_ptr() as u64, ready_msg.len() as u64);
    }
    
    // Allocate camera frame/label/mask buffers once
    let mut frame_buf = alloc::vec![0u8; 153_600];
    let mut label_buf = alloc::vec![0u16; 76_800];
    let mut mask_buf = alloc::vec![0u8; 9_600];

    // Check camera availability
    let mut camera_info_buf = [0u8; 128];
    let has_camera = match network::camera_info(&mut camera_info_buf) {
        Ok(len) => {
            let s = core::str::from_utf8(&camera_info_buf[..len]).unwrap_or("");
            s.contains("\"available\":true")
        }
        Err(_) => false,
    };
    if has_camera {
        let msg = "[heliox-daemon] camera device detected, enabling gesture pipeline\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
        }
    } else {
        let msg = "[heliox-daemon] no camera device detected\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
        }
    }

    let mut tracker = cognitive::gesture::GestureTracker::new();

    // Initialize server socket
    let mut server_fd = match bridge_token.as_ref() {
        Some(_) => match init_server_socket() {
        Ok(fd) => Some(fd),
        Err(e) => {
            let err_msg = alloc::format!("[heliox-daemon] warning: failed to init server socket (offline mode): {}\n", e);
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
            }
            None
        }
        },
        None => None,
    };
    let mut bridge_connected = false;
    let mut bridge_authorized = false;
    let mut bridge_exclusive = false;
    let mut ws_conn: Option<network::WsConnection> = None;

    let mut last_detailed = cognitive::gesture::DetailedGesture {
        gesture: cognitive::gesture::GestureType::None,
        cx: 0,
        cy: 0,
        landmarks: alloc::vec::Vec::new(),
    };

    // Warm up the camera and stabilize initial gesture detection
    if has_camera {
        let warm_up_msg = "[heliox-daemon] warming up camera pipeline...\n";
        unsafe {
            syscall3(SYS_WRITE, FD_CONSOLE, warm_up_msg.as_ptr() as u64, warm_up_msg.len() as u64);
        }
        for _ in 0..5 {
            if let Ok(bytes_read) = network::read_camera_frame(&mut frame_buf) {
                if bytes_read == 153_600 {
                    let detailed = cognitive::gesture::process_frame_detailed(
                        &frame_buf,
                        320,
                        240,
                        &mut label_buf,
                        &mut mask_buf,
                    );
                    let detected = detailed.gesture;
                    LATEST_GESTURE.store(detected as u8, core::sync::atomic::Ordering::SeqCst);
                    // Only `push()` here, priming the tracker's rolling
                    // history - do NOT call `stable_gesture()` during
                    // warm-up. It has a one-shot side effect (marks the
                    // gesture as already emitted, `GestureTracker` above),
                    // and this loop has no direct-action handling (the
                    // Fist/OpenPalm/Pointing match below) to react with. If
                    // the gesture present at boot was already stable across
                    // all 5 warm-up frames, consuming the event here meant
                    // the main loop's *first* `stable_gesture()` call always
                    // saw it as already-handled and silently dropped the
                    // pause/resume/click action forever - reproduced
                    // directly: a gesture set before `ring3 init` never
                    // triggered its direct action at all, only the informational
                    // "gesture: <name>" log line, no matter how long the
                    // daemon then ran (see work.md).
                    tracker.push(detected);
                    last_detailed = detailed.clone();
                }
            }
            unsafe {
                syscall3(SYS_SLEEP, 50, 0, 0);
            }
        }
    }

    // Main Agent Loop
    let mut loop_count = 0;
    loop {
        // Camera capture & gesture pipeline
        if has_camera && (loop_count % 2 == 0) {
            if let Ok(bytes_read) = network::read_camera_frame(&mut frame_buf) {
                if bytes_read == 153_600 {
                    let detailed = cognitive::gesture::process_frame_detailed(
                        &frame_buf,
                        320,
                        240,
                        &mut label_buf,
                        &mut mask_buf,
                    );
                    let detected = detailed.gesture;
                    LATEST_GESTURE.store(detected as u8, core::sync::atomic::Ordering::SeqCst);
                    tracker.push(detected);
                    last_detailed = detailed.clone();
                    if let Some(stable) = tracker.stable_gesture() {
                        let g_name = cognitive::gesture::gesture_name(stable);
                        let log_msg = alloc::format!("[heliox-daemon] gesture: {}\n", g_name);
                        unsafe {
                            syscall3(SYS_WRITE, FD_CONSOLE, log_msg.as_ptr() as u64, log_msg.len() as u64);
                        }

                        // Push stable gesture to orchestrator
                        orchestrator.push_gesture(stable as u8);

                        // If pointing, note the gesture coordinate using uptime ticks
                        if stable == cognitive::gesture::GestureType::Pointing {
                            let ticks = cognitive::fusion::get_uptime_ticks();
                            cognitive::fusion::note_gesture(ticks, detailed.cx, detailed.cy);
                        }

                        // Direct-map control gestures
                        match stable {
                            cognitive::gesture::GestureType::Fist => {
                                let direct_msg = "[heliox-daemon] gesture Fist -> direct: pause agent\n";
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                                orchestrator.set_paused(true);
                            }
                            cognitive::gesture::GestureType::OpenPalm => {
                                let direct_msg = "[heliox-daemon] gesture OpenPalm -> direct: resume agent\n";
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                                orchestrator.set_paused(false);
                            }
                            cognitive::gesture::GestureType::Pointing => {
                                let call = cognitive::json::ToolCall {
                                    name: String::from("mouse_click"),
                                    arguments: alloc::vec![
                                        (String::from("button"), cognitive::json::JsonValue::Number(0.0)),
                                    ],
                                };
                                let result = orchestrator.execute_tool_with_world_model(&call);
                                let direct_msg = alloc::format!(
                                    "[heliox-daemon] gesture Pointing -> gated mouse_click: {}\n",
                                    result.output
                                );
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                            }
                            cognitive::gesture::GestureType::Peace => {
                                let call = cognitive::json::ToolCall {
                                    name: String::from("keyboard_type"),
                                    arguments: alloc::vec![
                                        (String::from("text"), cognitive::json::JsonValue::Str(String::from("help\n"))),
                                    ],
                                };
                                let result = orchestrator.execute_tool_with_world_model(&call);
                                let direct_msg = alloc::format!(
                                    "[heliox-daemon] gesture Peace -> gated keyboard_type: {}\n",
                                    result.output
                                );
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                            }
                            cognitive::gesture::GestureType::ThumbsUp => {
                                // A probabilistic camera gesture is useful
                                // intent context, but it must not synthesize a
                                // physical 'y' and approve destructive kernel
                                // authority. The orchestrator already receives
                                // the gesture above and can explain the pending
                                // action; approval remains an explicit shell or
                                // hardware-key operation.
                                let direct_msg = "[heliox-daemon] gesture ThumbsUp observed; explicit confirmation still required\n";
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
        }

        if !bridge_connected {
            if let Some(fd) = server_fd {
                // Check for connection
                let res = unsafe { syscall3(SYS_ACCEPT, fd | (1 << 63), 0, 0) };
                if res != 0 && (res as i64) >= 0 {
                    match network::ws_accept(fd) {
                        Ok(conn) => {
                            let print_msg = "[heliox-daemon] bridge client connected, handshake successful!\n";
                            unsafe {
                                syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                            }
                            ws_conn = Some(conn);
                            bridge_connected = true;
                            bridge_authorized = false;
                            bridge_exclusive = false;
                            orchestrator.neural_disconnect();
                        }
                        Err(e) => {
                            let print_msg = alloc::format!("[heliox-daemon] handshake failed: {}\n", e);
                            unsafe {
                                syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                            }
                            let _ = network::tcp_close(fd);
                            server_fd = match init_server_socket() {
                                Ok(new_fd) => Some(new_fd),
                                Err(err) => {
                                    let err_msg = alloc::format!("[heliox-daemon] warning: failed to re-init server socket: {}\n", err);
                                    unsafe {
                                        syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
                                    }
                                    None
                                }
                            };
                        }
                    }
                }
            }
        }

        let mut waveform = [0u8; 64];
        let mut is_listening = false;

        // Ambient hearing remains active while an external model is paired.
        // Sample for 250 ms every ten event-loop iterations: enough for VAD's 200 ms floor,
        // while bounding ordinary bridge latency instead of monopolizing the
        // daemon's single cooperative event loop with continuous 1 s reads.
        // Offset the first sample so clients can pair immediately after boot.
        let spatial_fusion_due = loop_count == 0
            && LATEST_GESTURE.load(core::sync::atomic::Ordering::SeqCst)
                == cognitive::gesture::GestureType::Pointing as u8;
        if orchestrator.config.stt_host != "unconfigured"
            && (loop_count % 10 == 5 || spatial_fusion_due)
        {
            if let Ok(buf) = cognitive::voice::record_audio(250) {
                let has_voice = cognitive::voice::detect_voice_activity(&buf, orchestrator.config.vad_threshold);
                if has_voice {
                    is_listening = true;
                    waveform = cognitive::fusion::downsample_to_waveform(&buf);

                    let print_msg = "[heliox-daemon] voice activity detected, recording command...\n";
                    unsafe {
                        syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                    }

                    // Play notification beep
                    let beep = cognitive::voice::generate_beep();
                    let _ = cognitive::voice::play_audio(&beep);

                    // Record 3-second command buffer
                    if let Ok(cmd_buf) = cognitive::voice::record_audio(3000) {
                        waveform = cognitive::fusion::downsample_to_waveform(&cmd_buf);
                        match cognitive::voice::transcribe(&cmd_buf, &orchestrator.config.stt_host, orchestrator.config.stt_port) {
                            Ok(text) => {
                                let transcript_msg = alloc::format!("[heliox-daemon] voice transcript: {}\n", text);
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, transcript_msg.as_ptr() as u64, transcript_msg.len() as u64);
                                }

                                let text_lower = text.to_lowercase();
                                if let Some(idx) = text_lower.find("hey heliox") {
                                    let cmd = &text[idx + "hey heliox".len()..];
                                    let cmd_trimmed = cmd.trim();

                                    let goal_msg = alloc::format!("[heliox-daemon] new goal set: {}\n", cmd_trimmed);
                                    unsafe {
                                        syscall3(SYS_WRITE, FD_CONSOLE, goal_msg.as_ptr() as u64, goal_msg.len() as u64);
                                    }

                                    // Set goal
                                    orchestrator.set_goal(cmd_trimmed);

                                    // Play confirmation beep
                                    let _ = cognitive::voice::play_audio(&beep);
                                }
                            }
                            Err(e) => {
                                let err_msg = alloc::format!("[heliox-daemon] transcription failed: {}\n", e);
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
                                }
                            }
                        }
                    }
                } else {
                    waveform = cognitive::fusion::idle_waveform(loop_count);
                }
            } else {
                waveform = cognitive::fusion::idle_waveform(loop_count);
            }
        } else {
            waveform = cognitive::fusion::idle_waveform(loop_count);
        }

        if bridge_connected {
            if let Some(ref mut conn) = ws_conn {
                match network::ws_recv_frame(conn) {
                    Ok(frame) => {
                        if frame.opcode == 0x01 { // WS_OP_TEXT
                            // Consume confirmations/control queued while this
                            // task was blocked in socket receive before the
                            // waking request is dispatched.
                            orchestrator.poll_control();
                            if let Ok(payload_str) = core::str::from_utf8(&frame.payload) {
                                match cognitive::json::parse(payload_str) {
                                    Ok(parsed) => {
                                        let method = parsed.get("method").and_then(|m| m.as_str()).unwrap_or("");
                                        let id_str = match parsed.get("id") {
                                            Some(cognitive::json::JsonValue::Number(n)) => alloc::format!("{}", n),
                                            Some(cognitive::json::JsonValue::Str(s)) => alloc::format!("\"{}\"", s),
                                            _ => String::from("null"),
                                        };
                                        
                                        if method == "ping" {
                                            let pong_json = alloc::format!("{{\"jsonrpc\":\"2.0\",\"result\":\"pong\",\"id\":{}}}", id_str);
                                            let _ = network::ws_send_text_server(conn.fd, &pong_json);
                                        } else if method == "pair" {
                                            let supplied = parsed.get("params")
                                                .and_then(|params| params.get("token"))
                                                .and_then(|token| token.as_str())
                                                .unwrap_or("");
                                            let control_mode = parsed.get("params")
                                                .and_then(|params| params.get("control_mode"))
                                                .and_then(|mode| mode.as_str())
                                                .unwrap_or("exclusive");
                                            if control_mode != "exclusive" && control_mode != "cooperative" {
                                                send_rpc_error(conn.fd, &id_str, -32602, "control_mode must be exclusive or cooperative");
                                                continue;
                                            }
                                            if bridge_token.as_ref()
                                                .map(|expected| bridge_token_matches(expected, supplied))
                                                .unwrap_or(false)
                                            {
                                                bridge_authorized = true;
                                                bridge_exclusive = control_mode == "exclusive";
                                                if orchestrator.neural_pair(supplied.as_bytes(), control_mode).is_err() {
                                                    bridge_authorized = false;
                                                    bridge_exclusive = false;
                                                    send_rpc_error(conn.fd, &id_str, -32031, "neural session derivation failed");
                                                    continue;
                                                }
                                                let response = alloc::format!(
                                                    "{{\"jsonrpc\":\"2.0\",\"result\":{{\"authorized\":true,\"control_mode\":{}}},\"id\":{}}}",
                                                    escape_json_string(control_mode),
                                                    id_str
                                                );
                                                let _ = network::ws_send_text_server(conn.fd, &response);
                                            } else {
                                                send_rpc_error(conn.fd, &id_str, -32003, "pairing denied");
                                            }
                                        } else if !bridge_authorized {
                                            send_rpc_error(conn.fd, &id_str, -32003, "bridge pairing required");
                                        } else if method == "set_control_mode" {
                                            let control_mode = parsed.get("params")
                                                .and_then(|params| params.get("control_mode"))
                                                .and_then(|mode| mode.as_str())
                                                .unwrap_or("");
                                            if control_mode == "exclusive" || control_mode == "cooperative" {
                                                bridge_exclusive = control_mode == "exclusive";
                                                orchestrator.neural_set_control_mode(control_mode);
                                                let response = alloc::format!(
                                                    "{{\"jsonrpc\":\"2.0\",\"result\":{{\"control_mode\":{}}},\"id\":{}}}",
                                                    escape_json_string(control_mode),
                                                    id_str
                                                );
                                                let _ = network::ws_send_text_server(conn.fd, &response);
                                            } else {
                                                send_rpc_error(conn.fd, &id_str, -32602, "control_mode must be exclusive or cooperative");
                                            }
                                        } else if method == "neural_status" {
                                            let response = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{},\"id\":{}}}",
                                                orchestrator.neural_status_json(neural_now_ns()),
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &response);
                                        } else if method == "neural_calibrate" {
                                            let params = parsed.get("params");
                                            let transport_name = params
                                                .and_then(|value| value.get("transport"))
                                                .and_then(|value| value.as_str())
                                                .unwrap_or("");
                                            let sample_rate_value = params
                                                .and_then(|value| value.get("sample_rate_hz"))
                                                .and_then(|value| value.as_f64())
                                                .unwrap_or(0.0);
                                            let channel_count_value = params
                                                .and_then(|value| value.get("channel_count"))
                                                .and_then(|value| value.as_f64())
                                                .unwrap_or(0.0);
                                            let calibration_hex = params
                                                .and_then(|value| value.get("calibration_id_hex"))
                                                .and_then(|value| value.as_str())
                                                .unwrap_or("");
                                            if !(1.0..=4096.0).contains(&sample_rate_value)
                                                || !(1.0..=32.0).contains(&channel_count_value)
                                                || sample_rate_value != sample_rate_value as u16 as f64
                                                || channel_count_value != channel_count_value as u8 as f64
                                            {
                                                send_rpc_error(conn.fd, &id_str, -32602, "invalid neural stream shape");
                                                continue;
                                            }
                                            let transport = match neural::transport_from_name(transport_name) {
                                                Ok(value) => value,
                                                Err(_) => {
                                                    send_rpc_error(conn.fd, &id_str, -32602, "unsupported neural transport");
                                                    continue;
                                                }
                                            };
                                            let calibration_id = match decode_hex_exact::<32>(calibration_hex) {
                                                Ok(value) => value,
                                                Err(message) => {
                                                    send_rpc_error(conn.fd, &id_str, -32602, message);
                                                    continue;
                                                }
                                            };
                                            match orchestrator.neural_calibrate(
                                                transport,
                                                sample_rate_value as u16,
                                                channel_count_value as u8,
                                                calibration_id,
                                                neural_now_ns(),
                                            ) {
                                                Ok(()) => {
                                                    let response = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{},\"id\":{}}}",
                                                        orchestrator.neural_status_json(neural_now_ns()),
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &response);
                                                }
                                                Err(error) => send_rpc_error(
                                                    conn.fd,
                                                    &id_str,
                                                    -32032,
                                                    neural::error_name(error),
                                                ),
                                            }
                                        } else if method == "neural_intent_preview" {
                                            let intent_hex = parsed.get("params")
                                                .and_then(|value| value.get("intent_hex"))
                                                .and_then(|value| value.as_str())
                                                .unwrap_or("");
                                            let wire = match decode_hex_exact::<{ ferrum_neural_protocol::NEURAL_INTENT_WIRE_BYTES }>(intent_hex) {
                                                Ok(value) => value,
                                                Err(message) => {
                                                    send_rpc_error(conn.fd, &id_str, -32602, message);
                                                    continue;
                                                }
                                            };
                                            match orchestrator.neural_preview(&wire, neural_now_ns()) {
                                                Ok(preview) => {
                                                    let physical_forecast = if preview.disposition
                                                        == ferrum_neural_protocol::PreviewDisposition::PhysicalProposalOnly
                                                    {
                                                        orchestrator.neural_physical_preview_json().unwrap_or_else(|_| String::from("null"))
                                                    } else {
                                                        String::from("null")
                                                    };
                                                    let response = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{{\"preview\":{},\"physical_forecast\":{}}},\"id\":{}}}",
                                                        neural::preview_json(preview),
                                                        physical_forecast,
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &response);
                                                }
                                                Err(error) => send_rpc_error(
                                                    conn.fd,
                                                    &id_str,
                                                    -32033,
                                                    neural::error_name(error),
                                                ),
                                            }
                                        } else if method == "neural_intent_commit" {
                                            let intent_hex = parsed.get("params")
                                                .and_then(|value| value.get("intent_id"))
                                                .and_then(|value| value.as_str())
                                                .unwrap_or("");
                                            let intent_id = match decode_hex_exact::<16>(intent_hex) {
                                                Ok(value) => value,
                                                Err(message) => {
                                                    send_rpc_error(conn.fd, &id_str, -32602, message);
                                                    continue;
                                                }
                                            };
                                            match orchestrator.neural_commit(intent_id, neural_now_ns()) {
                                                Ok(neural::NeuralCommit::FocusChanged) => {
                                                    let response = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{{\"committed\":true,\"effect\":\"focus_changed\",\"status\":{}}},\"id\":{}}}",
                                                        orchestrator.neural_status_json(neural_now_ns()),
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &response);
                                                }
                                                Ok(neural::NeuralCommit::ReadOnlyTool(tool)) => {
                                                    let call = cognitive::json::ToolCall {
                                                        name: String::from(tool),
                                                        arguments: Vec::new(),
                                                    };
                                                    let result = orchestrator.execute_tool_with_world_model(&call);
                                                    let response = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{{\"committed\":true,\"effect\":\"read_only_tool\",\"tool\":{},\"success\":{},\"output\":{}}},\"id\":{}}}",
                                                        escape_json_string(tool),
                                                        result.success,
                                                        escape_json_string(&result.output),
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &response);
                                                }
                                                Err(error) => send_rpc_error(
                                                    conn.fd,
                                                    &id_str,
                                                    -32034,
                                                    neural::error_name(error),
                                                ),
                                            }
                                        } else if method == "neural_disarm" {
                                            orchestrator.neural_disarm();
                                            let response = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{},\"id\":{}}}",
                                                orchestrator.neural_status_json(neural_now_ns()),
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &response);
                                        } else if method == "world_model_preview" {
                                            if let Some(params) = parsed.get("params") {
                                                if let Some(tool_name) = params.get("tool").and_then(|tool| tool.as_str()) {
                                                    let arguments = match params.get("args") {
                                                        Some(cognitive::json::JsonValue::Object(pairs)) => pairs.clone(),
                                                        _ => Vec::new(),
                                                    };
                                                    let call = cognitive::json::ToolCall {
                                                        name: String::from(tool_name),
                                                        arguments,
                                                    };
                                                    let advice = orchestrator.preview_world_model_action(&call);
                                                    let response = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{{\"allowed\":{},\"risk\":{:.4},\"lookahead_steps\":{},\"reason\":{},\"suggestion\":{}}},\"id\":{}}}",
                                                        advice.allowed,
                                                        advice.risk,
                                                        advice.lookahead_steps,
                                                        escape_json_string(&advice.reason),
                                                        escape_json_string(&advice.suggestion),
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &response);
                                                } else {
                                                    send_rpc_error(conn.fd, &id_str, -32602, "missing tool");
                                                }
                                            } else {
                                                send_rpc_error(conn.fd, &id_str, -32602, "missing params");
                                            }
                                        } else if method == "execute_tool" {
                                            if let Some(params) = parsed.get("params") {
                                                if let Some(tool_name) = params.get("tool").and_then(|t| t.as_str()) {
                                                    let args_obj = params.get("args");
                                                    let arguments = match args_obj {
                                                        Some(cognitive::json::JsonValue::Object(pairs)) => pairs.clone(),
                                                        _ => Vec::new(),
                                                    };
                                                    
                                                    let tool_call = cognitive::json::ToolCall {
                                                        name: String::from(tool_name),
                                                        arguments,
                                                    };
                                                    
                                                    // Public tool calls use the same world-model
                                                    // prediction, safety gate, and experience recorder
                                                    // as provider-generated ReAct actions.
                                                    let tool_result = orchestrator
                                                        .execute_tool_with_world_model(&tool_call);
                                                    
                                                    let res_json = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{{\"success\":{},\"output\":{}}},\"id\":{}}}",
                                                        tool_result.success,
                                                        escape_json_string(&tool_result.output),
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &res_json);
                                                } else {
                                                    send_rpc_error(conn.fd, &id_str, -32602, "missing tool");
                                                }
                                            } else {
                                                send_rpc_error(conn.fd, &id_str, -32602, "missing params");
                                            }
                                        } else if method == "agent_step" {
                                            let goal = parsed.get("params")
                                                .and_then(|p| p.get("goal"))
                                                .and_then(|g| g.as_str())
                                                .unwrap_or("");
                                            if goal.is_empty() {
                                                let res_json = alloc::format!(
                                                    "{{\"jsonrpc\":\"2.0\",\"error\":{{\"code\":-32602,\"message\":\"missing goal\"}},\"id\":{}}}",
                                                    id_str
                                                );
                                                let _ = network::ws_send_text_server(conn.fd, &res_json);
                                            } else {
                                                match orchestrator.run_goal_once(goal) {
                                                    Ok((response, actions)) => {
                                                        let mut actions_json = String::from("[");
                                                        for (index, (tool, success, output)) in actions.iter().enumerate() {
                                                            if index > 0 {
                                                                actions_json.push(',');
                                                            }
                                                            actions_json.push_str(&alloc::format!(
                                                                "{{\"tool\":{},\"success\":{},\"output\":{}}}",
                                                                escape_json_string(tool),
                                                                success,
                                                                escape_json_string(output)
                                                            ));
                                                        }
                                                        actions_json.push(']');
                                                        let res_json = alloc::format!(
                                                            "{{\"jsonrpc\":\"2.0\",\"result\":{{\"response\":{},\"actions\":{}}},\"id\":{}}}",
                                                            escape_json_string(&response),
                                                            actions_json,
                                                            id_str
                                                        );
                                                        let _ = network::ws_send_text_server(conn.fd, &res_json);
                                                    }
                                                    Err(message) => {
                                                        let res_json = alloc::format!(
                                                            "{{\"jsonrpc\":\"2.0\",\"error\":{{\"code\":-32001,\"message\":{}}},\"id\":{}}}",
                                                            escape_json_string(message),
                                                            id_str
                                                        );
                                                        let _ = network::ws_send_text_server(conn.fd, &res_json);
                                                    }
                                                }
                                            }
                                        } else if method == "gesture_event" {
                                            if let Some(params) = parsed.get("params") {
                                                if let Some(gesture) = params.get("gesture").and_then(|g| g.as_str()) {
                                                    if gesture == "circle_clockwise" {
                                                        let tool_call = cognitive::json::ToolCall {
                                                            name: String::from("keyboard_type"),
                                                            arguments: alloc::vec![
                                                                (String::from("text"), cognitive::json::JsonValue::Str(String::from("g"))),
                                                            ],
                                                        };
                                                        let tool_result = orchestrator
                                                            .execute_tool_with_world_model(&tool_call);
                                                        let print_msg = alloc::format!(
                                                            "[heliox-daemon] gesture circle_clockwise mapped through gated keyboard_type: {}\n",
                                                            tool_result.output
                                                        );
                                                        unsafe {
                                                            syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                                                        }
                                                        let res_json = alloc::format!(
                                                            "{{\"jsonrpc\":\"2.0\",\"result\":{{\"success\":{},\"output\":{}}},\"id\":{}}}",
                                                            tool_result.success,
                                                            escape_json_string(&tool_result.output),
                                                            id_str
                                                        );
                                                        let _ = network::ws_send_text_server(conn.fd, &res_json);
                                                    } else {
                                                        send_rpc_error(conn.fd, &id_str, -32602, "unsupported gesture");
                                                    }
                                                } else {
                                                    send_rpc_error(conn.fd, &id_str, -32602, "missing gesture");
                                                }
                                            } else {
                                                send_rpc_error(conn.fd, &id_str, -32602, "missing params");
                                            }
                                        } else if method == "health" {
                                            // Distinct from `ping`: reports whether the agent has
                                            // completed setup and which provider is actually active,
                                            // not just "the socket is alive".
                                            let configured = orchestrator.config.api_host != "unconfigured" || orchestrator.config.provider.starts_with("local");
                                            let res_json = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{{\"status\":\"ok\",\"configured\":{},\"provider\":{}}},\"id\":{}}}",
                                                configured,
                                                escape_json_string(&orchestrator.config.provider),
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &res_json);
                                        } else if method == "get_config" {
                                            // api_key is deliberately omitted - this method is meant
                                            // for a trusted local UI to display current settings, not
                                            // to round-trip secrets back over the wire.
                                            let res_json = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{{\"provider\":{},\"model_name\":{},\"api_host\":{},\"api_port\":{},\"tick_interval\":{},\"auto_approve_tier\":{}}},\"id\":{}}}",
                                                escape_json_string(&orchestrator.config.provider),
                                                escape_json_string(&orchestrator.config.model_name),
                                                escape_json_string(&orchestrator.config.api_host),
                                                orchestrator.config.api_port,
                                                orchestrator.config.tick_interval,
                                                orchestrator.config.auto_approve_tier,
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &res_json);
                                        } else if method == "physical_status" {
                                            let response = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{},\"id\":{}}}",
                                                orchestrator.physical_status_json(),
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &response);
                                        } else if method == "physical_maintenance_demo" {
                                            let confirmed = parsed.get("params")
                                                .and_then(|params| params.get("confirm_simulation"))
                                                .and_then(|value| value.as_bool())
                                                .unwrap_or(false);
                                            if !confirmed {
                                                send_rpc_error(conn.fd, &id_str, -32602, "confirm_simulation=true is required");
                                            } else {
                                                match orchestrator.run_physical_maintenance_simulation() {
                                                    Ok(result) => {
                                                        let response = alloc::format!(
                                                            "{{\"jsonrpc\":\"2.0\",\"result\":{},\"id\":{}}}",
                                                            result,
                                                            id_str
                                                        );
                                                        let _ = network::ws_send_text_server(conn.fd, &response);
                                                    }
                                                    Err(message) => {
                                                        send_rpc_error(conn.fd, &id_str, -32020, message);
                                                    }
                                                }
                                            }
                                        } else if method == "system_status" {
                                            let mut buf = [0u8; 512];
                                            let bytes_written = unsafe {
                                                syscall4(29, 0, buf.as_mut_ptr() as u64, buf.len() as u64, 0)
                                            };
                                            let sys_info = if bytes_written > 0 {
                                                core::str::from_utf8(&buf[..bytes_written as usize]).unwrap_or("{}")
                                            } else {
                                                "{}"
                                            };
                                            let res_json = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{{\"tick_count\":{},\"goal\":{},\"system\":{}}},\"id\":{}}}",
                                                orchestrator.tick_count(),
                                                escape_json_string(&orchestrator.current_goal()),
                                                sys_info,
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &res_json);
                                        } else if method == "agent_stats" {
                                            // Backed by the same ring buffer `emit_telemetry` has
                                            // always recorded internally - previously write-only
                                            // (forwarded to a "gui" IPC listener that no longer
                                            // exists now that AgentHud is a real app instead of a
                                            // kernel-hardcoded window), now actually readable.
                                            let (count, last) = orchestrator.telemetry_summary();
                                            let last_json = match last {
                                                Some((tick, kind, message)) => alloc::format!(
                                                    "{{\"tick\":{},\"kind\":{},\"message\":{}}}",
                                                    tick,
                                                    escape_json_string(kind),
                                                    escape_json_string(&message)
                                                ),
                                                None => String::from("null"),
                                            };
                                            let res_json = alloc::format!(
                                                "{{\"jsonrpc\":\"2.0\",\"result\":{{\"telemetry_event_count\":{},\"last_event\":{}}},\"id\":{}}}",
                                                count,
                                                last_json,
                                                id_str
                                            );
                                            let _ = network::ws_send_text_server(conn.fd, &res_json);
                                        } else {
                                            send_rpc_error(conn.fd, &id_str, -32601, "method not found");
                                        }
                                    }
                                    Err(_) => {
                                        let print_msg = "[heliox-daemon] failed to parse JSON-RPC payload\n";
                                        unsafe {
                                            syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                                        }
                                        send_rpc_error(conn.fd, "null", -32700, "parse error");
                                    }
                                }
                            }
                        } else if frame.opcode == 0x08 { // WS_OP_CLOSE
                            let print_msg = "[heliox-daemon] client closed connection\n";
                            unsafe {
                                syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                            }
                            bridge_connected = false;
                            bridge_authorized = false;
                            bridge_exclusive = false;
                            orchestrator.neural_disconnect();
                            ws_conn = None;
                            if let Some(fd) = server_fd {
                                let _ = network::tcp_close(fd);
                                server_fd = match init_server_socket() {
                                    Ok(new_fd) => Some(new_fd),
                                    Err(err) => {
                                        let err_msg = alloc::format!("[heliox-daemon] warning: failed to re-init server socket: {}\n", err);
                                        unsafe {
                                            syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
                                        }
                                        None
                                    }
                                };
                            }
                        }
                    }
                    Err(e) if e == "ws: no data" => {
                        // Just no data, do nothing
                    }
                    Err(e) => {
                        let print_msg = alloc::format!("[heliox-daemon] connection lost: {}\n", e);
                        unsafe {
                            syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                        }
                        bridge_connected = false;
                        bridge_authorized = false;
                        bridge_exclusive = false;
                        orchestrator.neural_disconnect();
                        ws_conn = None;
                        if let Some(fd) = server_fd {
                            let _ = network::tcp_close(fd);
                            server_fd = match init_server_socket() {
                                Ok(new_fd) => Some(new_fd),
                                Err(err) => {
                                    let err_msg = alloc::format!("[heliox-daemon] warning: failed to re-init server socket: {}\n", err);
                                    unsafe {
                                        syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
                                    }
                                    None
                                }
                            };
                        }
                    }
                }
            }
        }

        // Plan only after every input source for this iteration has had a
        // chance to update the observation. In particular, a stable gesture
        // must not start provider inference before configured voice sampling,
        // IPC confirmation, or an external controller frame is serviced.
        if bridge_authorized && bridge_exclusive {
            // The paired model owns planning while the exclusive lease is
            // active. Keep consuming IPC/confirmation control, but do not let
            // the built-in provider race it with independent actions.
            orchestrator.poll_control();
        } else {
            orchestrator.tick();
        }

        let mut hud_state = cognitive::fusion::HudState {
            flags: 1, // bit0 = visible
            waveform,
            gesture_type: LATEST_GESTURE.load(core::sync::atomic::Ordering::SeqCst),
            point_x: 0,
            point_y: 0,
            landmark_count: 0,
            landmarks: [[0; 2]; 8],
            suggestion_len: 0,
            suggestion: [0; 128],
        };

        if is_listening {
            hud_state.flags |= 2;
        }

        if hud_state.gesture_type == cognitive::gesture::GestureType::Pointing as u8 {
            hud_state.flags |= 4;
            hud_state.point_x = (last_detailed.cx as u32 * 1024 / 320) as u16;
            hud_state.point_y = (last_detailed.cy as u32 * 768 / 240) as u16;
        }

        let l_count = core::cmp::min(last_detailed.landmarks.len(), 8);
        hud_state.landmark_count = l_count as u8;
        for i in 0..l_count {
            let lx = (last_detailed.landmarks[i].0 as u32 * 1024 / 320) as u16;
            let ly = (last_detailed.landmarks[i].1 as u32 * 768 / 240) as u16;
            hud_state.landmarks[i] = [lx, ly];
        }

        let world_model_suggestion = orchestrator.world_model_suggestion();
        let sug_str = if !world_model_suggestion.is_empty() {
            world_model_suggestion
        } else if orchestrator.paused {
            alloc::string::String::from("Agent paused (OpenPalm to resume)")
        } else {
            let cur_goal = orchestrator.current_goal();
            if cur_goal != "Explore the system" && !cur_goal.is_empty() {
                cur_goal
            } else {
                alloc::string::String::from("Listening... (Hey Heliox)")
            }
        };
        let sug_bytes = sug_str.as_bytes();
        let copy_len = core::cmp::min(sug_bytes.len(), 128);
        hud_state.suggestion_len = copy_len as u8;
        hud_state.suggestion[..copy_len].copy_from_slice(&sug_bytes[..copy_len]);

        let _ = cognitive::fusion::push_hud_state(&hud_state);

        loop_count += 1;
        if loop_count <= 5 {
            let tick_msg = "[heliox-daemon] loop tick complete, sleeping...\n";
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, tick_msg.as_ptr() as u64, tick_msg.len() as u64);
            }
        }

        // Keep the bridge responsive under a burst of outstanding JSON-RPC
        // requests. The loop consumes one complete WebSocket frame at a time;
        // the old unconditional 100 ms sleep imposed an avoidable 10 req/s
        // ceiling even when inference itself was ready. A connected client
        // gets a one-tick cooperative cadence while the idle daemon retains
        // its low-CPU 100 ms cadence. This preserves an explicit throttle for
        // connected-but-idle clients while removing the old ten-tick floor
        // from an authorized client's request queue.
        unsafe {
            if bridge_connected {
                syscall3(SYS_SLEEP, 1, 0, 0);
            } else {
                syscall3(SYS_SLEEP, 100, 0, 0);
            }
        }
    }
}

#[panic_handler]
fn panic(info: &core::panic::PanicInfo) -> ! {
    let msg = alloc::format!("[heliox-daemon PANIC] {}\n", info);
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
        syscall3(SYS_EXIT, 101, 0, 0);
    }
    loop {}
}
