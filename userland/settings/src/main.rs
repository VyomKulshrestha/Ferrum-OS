// ============================================================================
// FerrumOS - Settings (system info + persistent desktop preferences)
// ============================================================================
// Shows live hardware/Heliox state and lets the user persist bounded desktop
// theme/accent choices. Heliox provider editing remains in Assistant setup.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::String;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 1024 * 1024] = [0; 1024 * 1024];

const CANVAS_W: u32 = 420;
const CANVAS_H: u32 = 300;
const CONFIG_PATH: &str = "/disk/heliox/config.json";
const PREFERENCES_PATH: &str = "/disk/desktop.conf";

const SYS_SYSTEM_QUERY: u64 = 29;

fn refresh_button_rect() -> (u32, u32, u32, u32) {
    (CANVAS_W - 90, CANVAS_H - 36, 80, 26)
}

fn theme_button_rect() -> (u32, u32, u32, u32) {
    (12, 238, 185, 26)
}

fn accent_button_rect() -> (u32, u32, u32, u32) {
    (207, 238, 201, 26)
}

fn point_in(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (x, y, w, h) = rect;
    px >= x && px < x + w && py >= y && py < y + h
}

/// Pull one `"key":"value"` or `"key":value` field out of a flat JSON
/// object without a real parser - config.json is always written in this
/// exact flat, single-line shape (see heliox-assistant-panel's
/// `finish_setup`), so a substring search is enough and avoids pulling in
/// a JSON dependency for a read-only viewer.
fn extract_field<'a>(json: &'a str, key: &str) -> Option<&'a str> {
    let needle = format!("\"{}\"", key);
    let key_pos = json.find(&needle)?;
    let after_key = &json[key_pos + needle.len()..];
    let colon_pos = after_key.find(':')?;
    let after_colon = after_key[colon_pos + 1..].trim_start();
    if let Some(rest) = after_colon.strip_prefix('"') {
        let end = rest.find('"')?;
        Some(&rest[..end])
    } else {
        let end = after_colon.find(|c: char| c == ',' || c == '}').unwrap_or(after_colon.len());
        Some(after_colon[..end].trim())
    }
}

struct State {
    config_raw: Option<alloc::vec::Vec<u8>>,
    sys_info_raw: [u8; 512],
    sys_info_len: usize,
    theme: u8,
    accent: u8,
}

impl State {
    fn load() -> Self {
        let config_raw = ferrumgui::read_file(CONFIG_PATH, 4096);
        let mut sys_info_raw = [0u8; 512];
        let sys_info_result = unsafe {
            ferrumgui::syscall4(SYS_SYSTEM_QUERY, 0, sys_info_raw.as_mut_ptr() as u64, sys_info_raw.len() as u64, 0)
        };
        let sys_info_len = if (sys_info_result as i64) > 0 && (sys_info_result as usize) <= sys_info_raw.len() {
            sys_info_result as usize
        } else {
            0
        };
        let preferences = ferrumgui::read_file(PREFERENCES_PATH, 256)
            .and_then(|bytes| String::from_utf8(bytes).ok())
            .unwrap_or_default();
        let theme = preference_value(&preferences, "theme=").unwrap_or(0).min(2);
        let accent = preference_value(&preferences, "accent=").unwrap_or(0).min(2);
        ferrumgui::write_console("[settings] loaded preferences theme=");
        ferrumgui::write_int(theme as i64);
        ferrumgui::write_console(" accent=");
        ferrumgui::write_int(accent as i64);
        ferrumgui::write_console("\n");
        State { config_raw, sys_info_raw, sys_info_len, theme, accent }
    }
}

fn preference_value(raw: &str, prefix: &str) -> Option<u8> {
    raw.lines()
        .find_map(|line| line.strip_prefix(prefix))
        .and_then(|value| value.parse::<u8>().ok())
}

fn theme_name(theme: u8) -> &'static str {
    match theme {
        1 => "Midnight",
        2 => "Contrast",
        _ => "Dark",
    }
}

fn accent_name(accent: u8) -> &'static str {
    match accent {
        1 => "Blue",
        2 => "Amber",
        _ => "Cyan",
    }
}

fn persist_preferences(state: &State) -> bool {
    ferrumgui::apply_desktop_preferences(state.theme, state.accent)
}

fn draw_field(canvas: &mut Canvas, y: u32, label: &str, value: &str) {
    canvas.draw_string(12, y, label, 0x88, 0x88, 0x88);
    canvas.draw_string(160, y, value, 0xEE, 0xEE, 0xEE);
}

fn redraw(canvas: &mut Canvas, state: &State) {
    canvas.clear(0x14, 0x16, 0x1E);
    canvas.draw_string(12, 10, "System", 0x00, 0xCC, 0xFF);

    let sys_str = core::str::from_utf8(&state.sys_info_raw[..state.sys_info_len]).unwrap_or("{}");
    draw_field(canvas, 30, "Hardware tier:", extract_field(sys_str, "tier").unwrap_or("unknown"));
    draw_field(canvas, 48, "RAM (MB):", extract_field(sys_str, "ram_mb").unwrap_or("?"));
    draw_field(canvas, 66, "AVX2:", extract_field(sys_str, "avx2").unwrap_or("?"));
    draw_field(canvas, 84, "CPU count:", extract_field(sys_str, "cpu_count").unwrap_or("?"));
    draw_field(canvas, 102, "Uptime (ticks):", extract_field(sys_str, "uptime_ticks").unwrap_or("?"));

    canvas.draw_string(12, 132, "Heliox Agent", 0x00, 0xCC, 0xFF);
    match &state.config_raw {
        Some(bytes) => {
            let cfg_str = core::str::from_utf8(bytes).unwrap_or("");
            draw_field(canvas, 152, "Provider:", extract_field(cfg_str, "provider").unwrap_or("?"));
            draw_field(canvas, 170, "Model:", extract_field(cfg_str, "model_name").unwrap_or("?"));
            draw_field(canvas, 188, "API host:", extract_field(cfg_str, "api_host").unwrap_or("?"));
        }
        None => {
            canvas.draw_string(12, 152, "Not configured yet - open Heliox Assistant to set up.", 0xAA, 0x88, 0x00);
        }
    }

    canvas.draw_string(12, 216, "Desktop", 0x00, 0xCC, 0xFF);
    let (tx, ty, tw, th) = theme_button_rect();
    canvas.fill_rect(tx, ty, tw, th, 0x22, 0x28, 0x32);
    canvas.draw_rect_outline(tx, ty, tw, th, 0x44, 0x44, 0x44);
    canvas.draw_string(tx + 8, ty + 8, &format!("Theme: {}", theme_name(state.theme)), 0xDD, 0xDD, 0xDD);
    let (ax, ay, aw, ah) = accent_button_rect();
    canvas.fill_rect(ax, ay, aw, ah, 0x22, 0x28, 0x32);
    canvas.draw_rect_outline(ax, ay, aw, ah, 0x44, 0x44, 0x44);
    canvas.draw_string(ax + 8, ay + 8, &format!("Accent: {}", accent_name(state.accent)), 0xDD, 0xDD, 0xDD);

    let (bx, by, bw, bh) = refresh_button_rect();
    canvas.fill_rect(bx, by, bw, bh, 0x22, 0x28, 0x32);
    canvas.draw_rect_outline(bx, by, bw, bh, 0x44, 0x44, 0x44);
    canvas.draw_string(bx + 12, by + 8, "Refresh", 0xDD, 0xDD, 0xDD);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[settings] alive in ring 3\n");

    let window_id = ferrumgui::create_window("Settings", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[settings] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut state = State::load();
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &state);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag == 3 && b == 1 {
                if point_in(c, d, refresh_button_rect()) {
                    state = State::load();
                    let _ = ferrumgui::apply_desktop_preferences(state.theme, state.accent);
                    ferrumgui::write_console("[settings] refreshed\n");
                    dirty = true;
                } else if point_in(c, d, theme_button_rect()) {
                    state.theme = (state.theme + 1) % 3;
                    if persist_preferences(&state) {
                        ferrumgui::write_console("[settings] preferences saved theme=");
                        ferrumgui::write_int(state.theme as i64);
                        ferrumgui::write_console(" accent=");
                        ferrumgui::write_int(state.accent as i64);
                        ferrumgui::write_console("\n");
                    } else {
                        ferrumgui::write_console("[settings] preference save failed\n");
                    }
                    dirty = true;
                } else if point_in(c, d, accent_button_rect()) {
                    state.accent = (state.accent + 1) % 3;
                    if persist_preferences(&state) {
                        ferrumgui::write_console("[settings] preferences saved theme=");
                        ferrumgui::write_int(state.theme as i64);
                        ferrumgui::write_console(" accent=");
                        ferrumgui::write_int(state.accent as i64);
                        ferrumgui::write_console("\n");
                    } else {
                        ferrumgui::write_console("[settings] preference save failed\n");
                    }
                    dirty = true;
                }
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
