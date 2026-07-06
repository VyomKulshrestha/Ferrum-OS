// ============================================================================
// FerrumOS - GUI Desktop & Taskbar
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;
use crate::graphics;
use crate::devices::vga_fb::FRAMEBUFFER;
use crate::gui::compositor::{HoverTarget, LAUNCHER_ENTRIES};

pub const COLOR_BACKGROUND: u32 = 0x00101824; // Deep blue-gray, visibly non-black

pub fn init() {
    // Nothing to initialize for MVP
}

/// True if `(x, y)` falls inside `rect = (rx, ry, rw, rh)`.
pub fn point_in(x: u32, y: u32, rect: (u32, u32, u32, u32)) -> bool {
    let (rx, ry, rw, rh) = rect;
    x >= rx && x < rx + rw && y >= ry && y < ry + rh
}

pub fn render_background() {
    let fb_guard = FRAMEBUFFER.lock();
    if let Some(fb) = fb_guard.as_ref() {
        // Solid background - no debug grid. A desktop wallpaper reads as a
        // dev console when it has a visible measurement grid painted over
        // it; a plain gradient reads as a real desktop instead.
        fb.clear(COLOR_BACKGROUND);

        // A soft horizontal gradient along the top 60 pixels gives the
        // desktop some depth and reads as a status bar / menu strip
        // instead of a flat void.
        for y in 0..60 {
            let t = y as f32 / 60.0;
            let r = (0x10 as f32 + (0x20 - 0x10) as f32 * (1.0 - t)) as u32;
            let g = (0x18 as f32 + (0x30 - 0x18) as f32 * (1.0 - t)) as u32;
            let b = (0x24 as f32 + (0x48 - 0x24) as f32 * (1.0 - t)) as u32;
            let color = (r << 16) | (g << 8) | b;
            for x in 0..fb.width {
                fb.set_pixel(x, y, color);
            }
        }

        // A subtle vertical gradient over the rest of the desktop so it
        // doesn't read as a completely flat fill, without the grid's
        // "measurement overlay" look.
        for y in 60..fb.height {
            let t = ((y - 60) as f32 / (fb.height - 60).max(1) as f32).min(1.0);
            let r = (0x10 as f32 * (1.0 - t * 0.3)) as u32;
            let g = (0x18 as f32 * (1.0 - t * 0.3)) as u32;
            let b = (0x24 as f32 * (1.0 - t * 0.2)) as u32;
            let color = (r << 16) | (g << 8) | b;
            for x in (0..fb.width).step_by(4) {
                fb.set_pixel(x, y, color);
                if x + 1 < fb.width {
                    fb.set_pixel(x + 1, y, color);
                }
                if x + 2 < fb.width {
                    fb.set_pixel(x + 2, y, color);
                }
                if x + 3 < fb.width {
                    fb.set_pixel(x + 3, y, color);
                }
            }
        }
    }
}

/// Draw a single button. `bg` and `border` change based on the
/// button's hover/press/active state so the user gets immediate
/// visual feedback.
fn draw_button(x: u32, y: u32, w: u32, h: u32, label: &str, label_color: u32, state: ButtonState) {
    let (bg, border) = match state {
        ButtonState::Idle => (0x00222222u32, 0x00444444u32),
        ButtonState::Hover => (0x00304050u32, 0x0000FFCCu32),
        ButtonState::Pressed => (0x00445878u32, 0x00FFFFFFu32),
        ButtonState::Active => (0x00253550u32, 0x0000FFCCu32),
    };
    graphics::fill_rect(x, y, w, h, bg);
    graphics::draw_line(x, y, x + w - 1, y, border);
    graphics::draw_line(x, y + h - 1, x + w - 1, y + h - 1, border);
    graphics::draw_line(x, y, x, y + h - 1, border);
    graphics::draw_line(x + w - 1, y, x + w - 1, y + h - 1, border);

    graphics::draw_string(x + 8, y + 5, label, label_color, bg);
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ButtonState {
    Idle,
    Hover,
    /// Currently held down.
    Pressed,
    /// Not being interacted with, but represents the focused window (a
    /// taskbar entry stays visually distinct from idle ones while its
    /// window has focus, the way every real taskbar highlights the active
    /// app).
    Active,
}

/// How many open windows the taskbar shows a button for. Windows beyond
/// this are still open (and still show up if brought to front), they just
/// don't get a taskbar slot - a real limit, not silently dropped: this is
/// the same tradeoff the old fixed 3-button dock already made (it could
/// only ever launch 3 specific things), just generalized.
pub const MAX_TASKBAR_SLOTS: usize = 4;

const START_BTN_W: u32 = 70;
const EXIT_BTN_W: u32 = 70;
const WINDOW_SLOT_W: u32 = 110;
const SLOT_GAP: u32 = 6;
const GROUP_GAP: u32 = 15;
const DOCK_SIDE_PADDING: u32 = 15;
const DOCK_H: u32 = 40;
const BTN_H: u32 = 24;
const BTN_Y_INSET: u32 = 8;

pub struct TaskbarLayout {
    pub dock_x: u32,
    pub dock_y: u32,
    pub dock_w: u32,
    pub dock_h: u32,
    pub start_rect: (u32, u32, u32, u32),
    pub exit_rect: (u32, u32, u32, u32),
    /// Fixed-size slots, independent of how many windows are actually
    /// open right now - callers only look at `window_rects[..open_count]`.
    pub window_rects: Vec<(u32, u32, u32, u32)>,
}

/// The single source of truth for where every taskbar element sits.
/// `render_taskbar` and every hit-test in `compositor.rs` call this so the
/// two can never drift out of sync with each other, unlike the old
/// hand-duplicated magic numbers.
pub fn compute_taskbar_layout(fb_w: u32, fb_h: u32) -> TaskbarLayout {
    let windows_w = MAX_TASKBAR_SLOTS as u32 * WINDOW_SLOT_W + (MAX_TASKBAR_SLOTS as u32 - 1) * SLOT_GAP;
    let dock_w = DOCK_SIDE_PADDING * 2 + START_BTN_W + GROUP_GAP + windows_w + GROUP_GAP + EXIT_BTN_W;
    let dock_x = fb_w.saturating_sub(dock_w) / 2;
    let dock_y = fb_h.saturating_sub(DOCK_H + 10);

    let start_rect = (dock_x + DOCK_SIDE_PADDING, dock_y + BTN_Y_INSET, START_BTN_W, BTN_H);

    let mut window_rects = Vec::with_capacity(MAX_TASKBAR_SLOTS);
    let mut cx = start_rect.0 + START_BTN_W + GROUP_GAP;
    for _ in 0..MAX_TASKBAR_SLOTS {
        window_rects.push((cx, dock_y + BTN_Y_INSET, WINDOW_SLOT_W, BTN_H));
        cx += WINDOW_SLOT_W + SLOT_GAP;
    }

    let exit_rect = (dock_x + dock_w - DOCK_SIDE_PADDING - EXIT_BTN_W, dock_y + BTN_Y_INSET, EXIT_BTN_W, BTN_H);

    TaskbarLayout { dock_x, dock_y, dock_w, dock_h: DOCK_H, start_rect, exit_rect, window_rects }
}

fn truncate_label(s: &str, max_chars: usize) -> alloc::string::String {
    if s.chars().count() <= max_chars {
        alloc::string::String::from(s)
    } else {
        let mut out: alloc::string::String = s.chars().take(max_chars.saturating_sub(1)).collect();
        out.push('.');
        out
    }
}

/// `windows` is the live list of `(id, title, focused, minimized)` for
/// every open window, in the same order they occupy taskbar slots.
pub fn render_taskbar(
    hover: HoverTarget,
    pressed: HoverTarget,
    _mx: u32,
    _my: u32,
    _left_down: bool,
) {
    let (fb_w, fb_h) = {
        let fb_guard = FRAMEBUFFER.lock();
        match fb_guard.as_ref() {
            Some(fb) => (fb.width, fb.height),
            None => return,
        }
    };
    let layout = compute_taskbar_layout(fb_w, fb_h);

    {
        let fb_guard = FRAMEBUFFER.lock();
        let fb = match fb_guard.as_ref() {
            Some(fb) => fb,
            None => return,
        };

        fb.draw_rect(layout.dock_x, layout.dock_y, layout.dock_w, layout.dock_h, 0x00141828);
        for y in layout.dock_y..layout.dock_y + 2 {
            for x in layout.dock_x..layout.dock_x + layout.dock_w {
                fb.set_pixel(x, y, 0x00202838);
            }
        }

        let neon_cyan = 0x0000FFCC;
        for x in layout.dock_x..layout.dock_x + layout.dock_w {
            fb.set_pixel(x, layout.dock_y, neon_cyan);
            fb.set_pixel(x, layout.dock_y + layout.dock_h - 1, neon_cyan);
        }
        for y in layout.dock_y..layout.dock_y + layout.dock_h {
            fb.set_pixel(layout.dock_x, y, neon_cyan);
            fb.set_pixel(layout.dock_x + layout.dock_w - 1, y, neon_cyan);
        }
    }

    // Start button.
    let start_state = if pressed == HoverTarget::StartButton {
        ButtonState::Pressed
    } else if hover == HoverTarget::StartButton {
        ButtonState::Hover
    } else {
        ButtonState::Idle
    };
    let (sx, sy, sw, sh) = layout.start_rect;
    draw_button(sx, sy, sw, sh, "Start", 0x0000FFCC, start_state);

    // One slot per open window (windows beyond MAX_TASKBAR_SLOTS just
    // don't get a button - see the constant's doc comment). Lock once and
    // pull out everything needed - a MutexGuard's drop is tied to the end
    // of its enclosing statement, so nesting a second `.lock()` inside an
    // expression that still holds an outer guard would deadlock this
    // non-reentrant spinlock.
    let (windows, focused_id) = {
        let state = crate::gui::compositor::COMPOSITOR.lock();
        let windows: Vec<(u64, alloc::string::String, bool)> = state
            .windows
            .iter()
            .map(|w| (w.id, w.title.clone(), w.minimized))
            .collect();
        let focused_id = state.focused_idx.and_then(|i| state.windows.get(i)).map(|w| w.id);
        (windows, focused_id)
    };

    for (slot, rect) in layout.window_rects.iter().enumerate() {
        let Some((id, title, minimized)) = windows.get(slot) else { break };
        let (wx, wy, ww, wh) = *rect;
        let is_hover = hover == HoverTarget::TaskbarWindow(*id);
        let is_pressed = pressed == HoverTarget::TaskbarWindow(*id);
        let is_active = focused_id == Some(*id) && !minimized;
        let state = if is_pressed {
            ButtonState::Pressed
        } else if is_hover {
            ButtonState::Hover
        } else if is_active {
            ButtonState::Active
        } else {
            ButtonState::Idle
        };
        let max_chars = ((ww - 12) / 8).max(1) as usize;
        let label = truncate_label(title, max_chars);
        let label_color = if *minimized { 0x00777777 } else if is_active || is_hover { 0x00FFFFFF } else { 0x00AAAAAA };
        draw_button(wx, wy, ww, wh, &label, label_color, state);
    }

    // Exit button.
    let exit_state = if pressed == HoverTarget::ExitButton {
        ButtonState::Pressed
    } else if hover == HoverTarget::ExitButton {
        ButtonState::Hover
    } else {
        ButtonState::Idle
    };
    let (ex, ey, ew, eh) = layout.exit_rect;
    draw_button(ex, ey, ew, eh, "Exit", 0x00FF8888, exit_state);

    graphics::draw_string(24, 12, "FerrumOS Desktop", 0x0000FFCC, COLOR_BACKGROUND);
    graphics::draw_string(24, 32, "Start: launch apps    Drag a title bar to move a window", 0x00B8C7D9, COLOR_BACKGROUND);
}

// ============================================================================
// Launcher popup
// ============================================================================

const LAUNCHER_ENTRY_W: u32 = 180;
const LAUNCHER_ENTRY_H: u32 = 28;
const LAUNCHER_PADDING: u32 = 8;

fn launcher_rect(fb_w: u32, fb_h: u32) -> (u32, u32, u32, u32) {
    let layout = compute_taskbar_layout(fb_w, fb_h);
    let entries = LAUNCHER_ENTRIES.len() as u32;
    let popup_h = LAUNCHER_PADDING * 2 + entries * LAUNCHER_ENTRY_H;
    let popup_w = LAUNCHER_PADDING * 2 + LAUNCHER_ENTRY_W;
    let popup_x = layout.start_rect.0;
    let popup_y = layout.dock_y.saturating_sub(popup_h + 8);
    (popup_x, popup_y, popup_w, popup_h)
}

fn launcher_entry_rect(fb_w: u32, fb_h: u32, index: usize) -> (u32, u32, u32, u32) {
    let (px, py, pw, _ph) = launcher_rect(fb_w, fb_h);
    (
        px + LAUNCHER_PADDING,
        py + LAUNCHER_PADDING + index as u32 * LAUNCHER_ENTRY_H,
        pw - LAUNCHER_PADDING * 2,
        LAUNCHER_ENTRY_H - 4,
    )
}

/// Which launcher entry (if any) is at `(mx, my)`, when the launcher is
/// open. Shared by rendering (for hover highlight) and click handling.
pub fn launcher_entry_at(mx: u32, my: u32) -> Option<usize> {
    let (fb_w, fb_h) = {
        let fb_guard = FRAMEBUFFER.lock();
        match fb_guard.as_ref() {
            Some(fb) => (fb.width, fb.height),
            None => return None,
        }
    };
    for i in 0..LAUNCHER_ENTRIES.len() {
        if point_in(mx, my, launcher_entry_rect(fb_w, fb_h, i)) {
            return Some(i);
        }
    }
    None
}

pub fn render_launcher(hover: HoverTarget) {
    let (fb_w, fb_h) = {
        let fb_guard = FRAMEBUFFER.lock();
        match fb_guard.as_ref() {
            Some(fb) => (fb.width, fb.height),
            None => return,
        }
    };
    let (px, py, pw, ph) = launcher_rect(fb_w, fb_h);
    graphics::fill_rect(px, py, pw, ph, 0x00181C28);
    let border = 0x0000FFCC;
    graphics::draw_line(px, py, px + pw - 1, py, border);
    graphics::draw_line(px, py + ph - 1, px + pw - 1, py + ph - 1, border);
    graphics::draw_line(px, py, px, py + ph - 1, border);
    graphics::draw_line(px + pw - 1, py, px + pw - 1, py + ph - 1, border);

    for (i, name) in LAUNCHER_ENTRIES.iter().enumerate() {
        let (ex, ey, ew, eh) = launcher_entry_rect(fb_w, fb_h, i);
        let is_hover = hover == HoverTarget::LauncherEntry(i);
        let bg = if is_hover { 0x00304050 } else { 0x00181C28 };
        if is_hover {
            graphics::fill_rect(ex, ey, ew, eh, bg);
        }
        graphics::draw_string(ex + 8, ey + 6, name, if is_hover { 0x00FFFFFF } else { 0x00CCCCCC }, bg);
    }
}
