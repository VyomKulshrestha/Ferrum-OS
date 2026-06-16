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

// Static heap size: 16 MB
static mut HEAP: [u8; 16 * 1024 * 1024] = [0; 16 * 1024 * 1024];

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
const FD_CONSOLE: u64 = 1;
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

    // Initialize cognitive systems
    let mut orchestrator = cognitive::orchestrator::Orchestrator::new();

    // Print active provider
    let provider_msg = alloc::format!("[heliox-daemon] active provider: {}\n", orchestrator.config.provider);
    unsafe {
        syscall3(SYS_WRITE, FD_CONSOLE, provider_msg.as_ptr() as u64, provider_msg.len() as u64);
    }
    
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
    let mut server_fd = match init_server_socket() {
        Ok(fd) => Some(fd),
        Err(e) => {
            let err_msg = alloc::format!("[heliox-daemon] warning: failed to init server socket (offline mode): {}\n", e);
            unsafe {
                syscall3(SYS_WRITE, FD_CONSOLE, err_msg.as_ptr() as u64, err_msg.len() as u64);
            }
            None
        }
    };
    let mut bridge_connected = false;
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
                    tracker.push(detected);
                    last_detailed = detailed.clone();
                    if let Some(stable) = tracker.stable_gesture() {
                        let g_name = cognitive::gesture::gesture_name(stable);
                        let log_msg = alloc::format!("[heliox-daemon] gesture: {}\n", g_name);
                        unsafe {
                            syscall3(SYS_WRITE, FD_CONSOLE, log_msg.as_ptr() as u64, log_msg.len() as u64);
                        }
                        orchestrator.push_gesture(stable as u8);
                        if stable == cognitive::gesture::GestureType::Pointing {
                            let ticks = cognitive::fusion::get_uptime_ticks();
                            cognitive::fusion::note_gesture(ticks, detailed.cx, detailed.cy);
                        }
                    }
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
                                let direct_msg = "[heliox-daemon] gesture Pointing -> direct: mouse click\n";
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                                unsafe {
                                    syscall3(27, 1, 0, 0); // InjectMouse: click, button=0
                                }
                            }
                            cognitive::gesture::GestureType::Peace => {
                                let direct_msg = "[heliox-daemon] gesture Peace -> direct: help command\n";
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                                for &b in b"help\n" {
                                    unsafe {
                                        syscall3(26, b as u64, 0, 0);
                                    }
                                }
                            }
                            cognitive::gesture::GestureType::ThumbsUp => {
                                let direct_msg = "[heliox-daemon] gesture ThumbsUp -> direct: confirm/approve\n";
                                unsafe {
                                    syscall3(SYS_WRITE, FD_CONSOLE, direct_msg.as_ptr() as u64, direct_msg.len() as u64);
                                }
                                for &b in b"y\n" {
                                    unsafe {
                                        syscall3(26, b as u64, 0, 0);
                                    }
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
        }

        orchestrator.tick();
        
        if !bridge_connected {
            if let Some(fd) = server_fd {
                // Check for connection
                let res = unsafe { syscall3(SYS_ACCEPT, fd, 0, 0) };
                if (res as i64) >= 0 {
                    match network::ws_accept(fd) {
                        Ok(conn) => {
                            let print_msg = "[heliox-daemon] bridge client connected, handshake successful!\n";
                            unsafe {
                                syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                            }
                            ws_conn = Some(conn);
                            bridge_connected = true;
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

        if !bridge_connected && orchestrator.config.stt_host != "unconfigured" {
            // Ambient Voice Command Listener (1-second buffer)
            if let Ok(buf) = cognitive::voice::record_audio(1000) {
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
                                                    
                                                    // Execute tool mapping
                                                    let tool_result = cognitive::tool_mapper::execute(
                                                        &tool_call,
                                                        &mut orchestrator.confirmation_gate,
                                                        4, // auto_approve_tier = 4 to bypass confirmation
                                                        loop_count
                                                    );
                                                    
                                                    let res_json = alloc::format!(
                                                        "{{\"jsonrpc\":\"2.0\",\"result\":{{\"success\":{},\"output\":{}}},\"id\":{}}}",
                                                        tool_result.success,
                                                        escape_json_string(&tool_result.output),
                                                        id_str
                                                    );
                                                    let _ = network::ws_send_text_server(conn.fd, &res_json);
                                                }
                                            }
                                        } else if method == "gesture_event" {
                                            if let Some(params) = parsed.get("params") {
                                                if let Some(gesture) = params.get("gesture").and_then(|g| g.as_str()) {
                                                    if gesture == "circle_clockwise" {
                                                        let print_msg = "[heliox-daemon] gesture circle_clockwise mapped: injecting 'g'\n";
                                                        unsafe {
                                                            syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                                                        }
                                                        const SYS_INJECT_KEY: u64 = 26;
                                                        unsafe {
                                                            syscall3(SYS_INJECT_KEY, b'g' as u64, 0, 0);
                                                        }
                                                        let res_json = alloc::format!("{{\"jsonrpc\":\"2.0\",\"result\":\"ok\",\"id\":{}}}", id_str);
                                                        let _ = network::ws_send_text_server(conn.fd, &res_json);
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Err(_) => {
                                        let print_msg = "[heliox-daemon] failed to parse JSON-RPC payload\n";
                                        unsafe {
                                            syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                                        }
                                    }
                                }
                            }
                        } else if frame.opcode == 0x08 { // WS_OP_CLOSE
                            let print_msg = "[heliox-daemon] client closed connection\n";
                            unsafe {
                                syscall3(SYS_WRITE, FD_CONSOLE, print_msg.as_ptr() as u64, print_msg.len() as u64);
                            }
                            bridge_connected = false;
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

        let sug_str = if orchestrator.paused {
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

