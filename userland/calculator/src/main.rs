// ============================================================================
// FerrumOS - Calculator (D3 core app)
// ============================================================================
// A basic two-operand calculator, driven entirely by mouse clicks on a
// button grid the app draws into its own canvas - the simplest possible
// exercise of the D1 mouse-input path (MouseButtonDown events carry
// window-relative x/y), kept intentionally small.
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

// Must exceed the canvas buffer (CANVAS_W * CANVAS_H * 4 = ~224 KB) -
// undersizing this caused a silent allocation failure (abort) right after
// window creation, before this comment was added.
static mut HEAP: [u8; 1024 * 1024] = [0; 1024 * 1024];

const CANVAS_W: u32 = 200;
const CANVAS_H: u32 = 280;
const DISPLAY_H: u32 = 50;
const BTN_COLS: u32 = 4;
const BTN_ROWS: u32 = 5;
const BTN_W: u32 = CANVAS_W / BTN_COLS;
const BTN_H: u32 = (CANVAS_H - DISPLAY_H) / BTN_ROWS;

// Row-major button labels; "C" spans the whole last row.
const LABELS: [&str; 20] = [
    "7", "8", "9", "/",
    "4", "5", "6", "*",
    "1", "2", "3", "-",
    "0", ".", "=", "+",
    "C", "C", "C", "C",
];

fn button_at(x: u32, y: u32) -> Option<usize> {
    if y < DISPLAY_H {
        return None;
    }
    let row = (y - DISPLAY_H) / BTN_H;
    let col = x / BTN_W;
    if row >= BTN_ROWS || col >= BTN_COLS {
        return None;
    }
    Some((row * BTN_COLS + col) as usize)
}

struct State {
    display: String,
    accumulator: f64,
    pending_op: Option<char>,
}

impl State {
    fn new() -> Self {
        State { display: String::from("0"), accumulator: 0.0, pending_op: None }
    }

    fn press(&mut self, label: &str) {
        match label {
            "C" => {
                self.display = String::from("0");
                self.accumulator = 0.0;
                self.pending_op = None;
            }
            "." => {
                if !self.display.contains('.') {
                    self.display.push('.');
                }
            }
            "+" | "-" | "*" | "/" => {
                let value: f64 = self.display.parse().unwrap_or(0.0);
                if let Some(op) = self.pending_op {
                    self.accumulator = apply(self.accumulator, value, op);
                } else {
                    self.accumulator = value;
                }
                self.pending_op = Some(label.chars().next().unwrap());
                self.display = String::from("0");
            }
            "=" => {
                let value: f64 = self.display.parse().unwrap_or(0.0);
                if let Some(op) = self.pending_op {
                    self.accumulator = apply(self.accumulator, value, op);
                    self.display = format_number(self.accumulator);
                    self.pending_op = None;
                    ferrumgui::write_console("[calculator] result=");
                    ferrumgui::write_console(&self.display);
                    ferrumgui::write_console("\n");
                }
            }
            digit => {
                if self.display == "0" {
                    self.display = String::from(digit);
                } else {
                    self.display.push_str(digit);
                }
            }
        }
    }
}

fn apply(a: f64, b: f64, op: char) -> f64 {
    match op {
        '+' => a + b,
        '-' => a - b,
        '*' => a * b,
        '/' => {
            if b == 0.0 {
                0.0
            } else {
                a / b
            }
        }
        _ => b,
    }
}

fn format_number(v: f64) -> String {
    // Trim a trailing ".0" so whole-number results read cleanly.
    let s = format!("{}", v);
    if let Some(stripped) = s.strip_suffix(".0") {
        String::from(stripped)
    } else {
        s
    }
}

fn redraw(canvas: &mut Canvas, state: &State) {
    canvas.clear(0x18, 0x1c, 0x24);
    canvas.fill_rect(0, 0, CANVAS_W, DISPLAY_H, 0x10, 0x14, 0x1a);
    let text_x = CANVAS_W.saturating_sub((state.display.len() as u32) * ferrumgui::font::FONT_WIDTH + 8);
    canvas.draw_string(text_x, DISPLAY_H / 2 - 8, &state.display, 0x00, 0xff, 0xcc);

    for (i, label) in LABELS.iter().enumerate() {
        // Skip the C row's duplicate labels - drawn once as a full-width button below.
        if i >= 16 {
            break;
        }
        let row = (i as u32) / BTN_COLS;
        let col = (i as u32) % BTN_COLS;
        let x = col * BTN_W;
        let y = DISPLAY_H + row * BTN_H;
        canvas.fill_rect(x + 2, y + 2, BTN_W - 4, BTN_H - 4, 0x28, 0x30, 0x40);
        canvas.draw_rect_outline(x + 2, y + 2, BTN_W - 4, BTN_H - 4, 0x44, 0x44, 0x44);
        let label_x = x + BTN_W / 2 - (label.len() as u32) * ferrumgui::font::FONT_WIDTH / 2;
        canvas.draw_string(label_x, y + BTN_H / 2 - 8, label, 0xcc, 0xcc, 0xcc);
    }

    let clear_y = DISPLAY_H + 4 * BTN_H;
    canvas.fill_rect(2, clear_y + 2, CANVAS_W - 4, BTN_H - 4, 0x40, 0x28, 0x28);
    canvas.draw_rect_outline(2, clear_y + 2, CANVAS_W - 4, BTN_H - 4, 0x66, 0x33, 0x33);
    canvas.draw_string(CANVAS_W / 2 - ferrumgui::font::FONT_WIDTH, clear_y + BTN_H / 2 - 8, "C", 0xff, 0x88, 0x88);
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[calculator] alive in ring 3\n");

    let window_id = ferrumgui::create_window("Calculator", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[calculator] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut state = State::new();
    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &state);
    canvas.present(window_id);

    loop {
        let mut dirty = false;
        while let Some(InputEvent { tag, b, c, d, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 3 || b != 1 {
                continue; // only mouse-down presses drive this app
            }
            if let Some(idx) = button_at(c, d) {
                let label = LABELS[idx];
                state.press(label);
                ferrumgui::write_console("[calculator] pressed ");
                ferrumgui::write_console(label);
                ferrumgui::write_console("\n");
                dirty = true;
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
