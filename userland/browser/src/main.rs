// ============================================================================
// FerrumOS - Browser (minimal HTTP text browser)
// ============================================================================
// v1 scope: plain HTTP (no TLS, no HTML rendering) over a raw TCP socket -
// type "ip:port/path" (e.g. "10.0.2.2:8000/index.txt"), it opens a real
// socket, sends a GET request, and displays whatever text comes back. This
// is deliberately not a web-rendering engine; it proves FerrumOS has a real
// app that does real network I/O and shows the result, the same honest
// scope heliox-assistant-panel's chat UI took for text rendering.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;
use core::arch::asm;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 2 * 1024 * 1024] = [0; 2 * 1024 * 1024];

const CANVAS_W: u32 = 560;
const CANVAS_H: u32 = 400;
const ADDR_BAR_H: u32 = 24;
const LINE_H: u32 = ferrumgui::font::FONT_HEIGHT as u32 + 3;
const MAX_CHARS_PER_LINE: usize = ((CANVAS_W - 16) / ferrumgui::font::FONT_WIDTH) as usize;

// Raw socket syscalls - single consumer, so defined locally rather than
// added to libferrumgui (same reasoning libferrumgui's own history notes
// for not abstracting a thing only one app needs yet).
const SYS_SOCKET: u64 = 7;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;
const SYS_CONNECT: u64 = 14;

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

/// Parse "ip:port/path" (path optional, defaults to "/"). Returns
/// (ip_octets, port, path) or None if the address part isn't a valid
/// dotted-quad:port - there's no DNS resolver here, only raw IPv4.
fn parse_address(input: &str) -> Option<([u8; 4], u16, String)> {
    let (host_port, path) = match input.find('/') {
        Some(idx) => (&input[..idx], &input[idx..]),
        None => (input, "/"),
    };
    let (ip_str, port_str) = host_port.split_once(':')?;
    let mut octets = [0u8; 4];
    let parts: Vec<&str> = ip_str.split('.').collect();
    if parts.len() != 4 {
        return None;
    }
    for (i, p) in parts.iter().enumerate() {
        octets[i] = p.parse().ok()?;
    }
    let port: u16 = port_str.parse().ok()?;
    Some((octets, port, path.to_string()))
}

fn fetch(ip: [u8; 4], port: u16, path: &str) -> Result<String, String> {
    let fd = unsafe { syscall3(SYS_SOCKET, 2, 1, 0) };
    if (fd as i64) < 100 {
        return Err(String::from("socket() failed"));
    }
    let ip_packed = u32::from_be_bytes(ip) as u64;
    let connected = unsafe { syscall3(SYS_CONNECT, fd, ip_packed, port as u64) };
    if connected != 0 {
        return Err(String::from("connect() failed"));
    }

    let request = format!("GET {} HTTP/1.0\r\nHost: {}.{}.{}.{}\r\nConnection: close\r\n\r\n", path, ip[0], ip[1], ip[2], ip[3]);
    let sent = unsafe { syscall3(SYS_SEND, fd, request.as_ptr() as u64, request.len() as u64) };
    if (sent as i64) < 0 {
        return Err(String::from("send() failed"));
    }

    let mut body = Vec::new();
    let mut buf = [0u8; 2048];
    // No blocking-recv semantics documented for this syscall's callers
    // (heliox-daemon's own network.rs treats a single recv call as
    // "whatever's available now"), so poll with a short sleep, matching
    // the same non-blocking-poll pattern every other syscall in this OS
    // uses for I/O - stop once several consecutive empty reads suggest the
    // connection is closed or idle.
    let mut empty_reads = 0;
    for _ in 0..500 {
        let n = unsafe { syscall3(SYS_RECV, fd, buf.as_mut_ptr() as u64, buf.len() as u64) };
        if (n as i64) > 0 {
            body.extend_from_slice(&buf[..n as usize]);
            empty_reads = 0;
        } else {
            empty_reads += 1;
            if empty_reads > 20 {
                break;
            }
        }
        ferrumgui::sleep(20);
    }

    if body.is_empty() {
        return Err(String::from("no response received"));
    }

    let text = String::from_utf8_lossy(&body).to_string();
    // Strip HTTP headers (up to the first blank line) so the display shows
    // the actual page content, not the response's own header block.
    let display = match text.find("\r\n\r\n") {
        Some(idx) => &text[idx + 4..],
        None => &text,
    };
    Ok(display.to_string())
}

struct State {
    address_input: String,
    page_text: String,
    status: String,
}

fn wrap_text(text: &str, out: &mut Vec<String>) {
    for raw_line in text.lines() {
        let mut line = String::new();
        for word in raw_line.split(' ') {
            if line.len() + word.len() + 1 > MAX_CHARS_PER_LINE {
                out.push(line.clone());
                line.clear();
            }
            if !line.is_empty() {
                line.push(' ');
            }
            line.push_str(word);
        }
        out.push(line);
        if out.len() > 500 {
            break; // bound the display, this is a viewer not a pager
        }
    }
}

fn redraw(canvas: &mut Canvas, state: &State) {
    canvas.clear(0x12, 0x14, 0x1A);

    canvas.fill_rect(0, 0, CANVAS_W, ADDR_BAR_H, 0x1E, 0x22, 0x2C);
    canvas.draw_string(4, 4, ">", 0xFF, 0xFF, 0xFF);
    canvas.draw_string(20, 4, &state.address_input, 0x00, 0xFF, 0xCC);

    canvas.draw_string(4, ADDR_BAR_H + 4, &state.status, 0x88, 0x88, 0x88);

    let mut lines = Vec::new();
    wrap_text(&state.page_text, &mut lines);
    let visible_rows = ((CANVAS_H - ADDR_BAR_H - 24) / LINE_H) as usize;
    // Top-anchored (show the start of the page), not tail-anchored - a
    // browser reads from the top, unlike the assistant panel's chat log
    // which should show the most recent messages.
    let mut cy = ADDR_BAR_H + 22;
    for line in lines.iter().take(visible_rows) {
        canvas.draw_string(6, cy, line, 0xCC, 0xCC, 0xCC);
        cy += LINE_H;
    }
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[browser] alive in ring 3\n");

    let window_id = ferrumgui::create_window("Browser", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[browser] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut state = State {
        address_input: String::new(),
        page_text: String::new(),
        status: String::from("Type an address like 10.0.2.2:8000/ and press Enter"),
    };
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &state);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, a, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 0 {
                continue;
            }
            let ascii = a as u8;
            match ascii {
                b'\n' | b'\r' => {
                    let addr = state.address_input.trim().to_string();
                    if !addr.is_empty() {
                        match parse_address(&addr) {
                            Some((ip, port, path)) => {
                                state.status = format!("Loading {}...", addr);
                                dirty = true;
                                redraw(&mut canvas, &state);
                                canvas.present(window_id);

                                ferrumgui::write_console("[browser] fetching ");
                                ferrumgui::write_console(&addr);
                                ferrumgui::write_console("\n");

                                match fetch(ip, port, &path) {
                                    Ok(text) => {
                                        state.status = format!("Loaded {}", addr);
                                        state.page_text = text;
                                    }
                                    Err(e) => {
                                        state.status = format!("Failed: {}", e);
                                        state.page_text.clear();
                                    }
                                }
                            }
                            None => {
                                state.status = String::from("Invalid address - expected ip:port/path");
                            }
                        }
                    }
                    dirty = true;
                }
                0x08 => {
                    if !state.address_input.is_empty() {
                        state.address_input.pop();
                        dirty = true;
                    }
                }
                _ if ascii.is_ascii_graphic() || ascii == b' ' => {
                    state.address_input.push(ascii as char);
                    dirty = true;
                }
                _ => {}
            }
        }

        if dirty {
            redraw(&mut canvas, &state);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
