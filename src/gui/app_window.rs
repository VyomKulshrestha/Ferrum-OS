// ============================================================================
// FerrumOS - Generic App Window Registry
// ============================================================================
// Backs the CreateWindow / PresentWindow / PollWindowInput syscalls. This is
// the piece that turns "the compositor can draw a few hardcoded window
// types" into "any userland process can own a real window": a window's
// pixels are whatever the owning process last submitted via `present`, and
// its input events are queued per-window instead of only ever reaching the
// kernel's own Terminal handling.
// ============================================================================

extern crate alloc;

use alloc::collections::{BTreeMap, VecDeque};
use core::sync::atomic::{AtomicU64, Ordering};
use spin::Mutex;

use crate::gui::compositor;
use crate::gui::window::{Window, WindowType};

/// App windows are allocated ids starting well above the kernel's own
/// hardcoded window ids (1=SystemMonitor, 2=Terminal) so the two spaces
/// never collide.
static NEXT_APP_WINDOW_ID: AtomicU64 = AtomicU64::new(1000);

/// Default placement for newly created app windows. Fixed (not
/// auto-cascaded) deliberately: this keeps the layout deterministic for the
/// verification harness, the same tradeoff already made for the taskbar's
/// hardcoded dock coordinates in `desktop.rs`.
pub const DEFAULT_APP_X: u32 = 150;
pub const DEFAULT_APP_Y: u32 = 150;

// 96px is the practical floor: the title bar now has three right-aligned
// buttons (minimize/maximize/close) at 16px + gaps each, so anything
// narrower would make them overlap or crowd out the title text entirely.
const MIN_CANVAS_W: u32 = 96;
const MIN_CANVAS_H: u32 = 48;
const MAX_CANVAS_W: u32 = 760;
const MAX_CANVAS_H: u32 = 560;
const MAX_QUEUED_EVENTS: usize = 64;

/// One input event scoped to a single app window. Serialized to userspace
/// as five little-endian u32s (20 bytes) by `sys_poll_window_input`.
#[derive(Debug, Clone, Copy)]
pub struct AppInputEvent {
    /// 0 = KeyPress, 3 = MouseButtonDown
    pub tag: u32,
    pub a: u32,
    pub b: u32,
    pub c: u32,
    pub d: u32,
}

static INPUT_QUEUES: Mutex<BTreeMap<u64, VecDeque<AppInputEvent>>> = Mutex::new(BTreeMap::new());

/// Clamp a requested canvas dimension into a sane, boundable range so a
/// misbehaving app can't allocate an unreasonably large pixel buffer.
fn clamp_dim(v: u32, min: u32, max: u32) -> u32 {
    v.max(min).min(max)
}

/// Create a new app-owned window for `pid` and register it with the
/// compositor. Returns the new window's id.
pub fn create_window(pid: u64, title: &str, canvas_w: u32, canvas_h: u32) -> u64 {
    let canvas_w = clamp_dim(canvas_w, MIN_CANVAS_W, MAX_CANVAS_W);
    let canvas_h = clamp_dim(canvas_h, MIN_CANVAS_H, MAX_CANVAS_H);
    let id = NEXT_APP_WINDOW_ID.fetch_add(1, Ordering::SeqCst);

    let window = Window::new_app(id, pid, title, DEFAULT_APP_X, DEFAULT_APP_Y, canvas_w, canvas_h);

    // Every window normally takes focus immediately on creation (a direct
    // user action - clicking a launcher entry - expects that). The one
    // exception is an opportunistic, out-of-band launch (see
    // `compositor::launch_assistant_panel_if_unconfigured`), which
    // shouldn't steal focus - and, since new windows all share the same
    // default screen position, visually cover - whatever the caller
    // already had open.
    let suppress_focus_steal = compositor::take_suppress_focus_steal(pid);

    let mut state = compositor::COMPOSITOR.lock();
    if suppress_focus_steal {
        // Windows render back-to-front in vec order regardless of focus,
        // so pushing to the end (like every other window) would still
        // visually cover whatever's already on screen even without
        // taking focus. Insert at the bottom of the stack instead -
        // behind every existing window, focused or not - and shift
        // `focused_idx` to keep pointing at the same logical window.
        state.windows.insert(0, window);
        if let Some(idx) = state.focused_idx.as_mut() {
            *idx += 1;
        }
    } else {
        state.windows.push(window);
        state.focused_idx = Some(state.windows.len() - 1);
    }
    state.needs_redraw = true;
    drop(state);

    INPUT_QUEUES.lock().insert(id, VecDeque::new());
    id
}

/// The pid that owns `window_id`, if it exists and is an app window.
pub fn owner_of(window_id: u64) -> Option<u64> {
    compositor::COMPOSITOR
        .lock()
        .windows
        .iter()
        .find(|w| w.id == window_id)
        .and_then(|w| match w.win_type {
            WindowType::App(pid) => Some(pid),
            _ => None,
        })
}

/// Copy an RGBA8 pixel buffer (4 bytes/pixel: R,G,B,A; A ignored) submitted
/// by `pid` into `window_id`'s canvas. `pixel_bytes.len()` must equal
/// `canvas_w * canvas_h * 4` exactly.
pub fn present(window_id: u64, pid: u64, pixel_bytes: &[u8]) -> Result<(), &'static str> {
    let mut state = compositor::COMPOSITOR.lock();
    let win = state
        .windows
        .iter_mut()
        .find(|w| w.id == window_id)
        .ok_or("no such window")?;

    match win.win_type {
        WindowType::App(owner) if owner == pid => {}
        WindowType::App(_) => return Err("not the owning process"),
        _ => return Err("not an app window"),
    }

    let pixel_count = win.canvas_w as usize * win.canvas_h as usize;
    if pixel_bytes.len() != pixel_count * 4 {
        return Err("pixel buffer size does not match canvas w*h*4");
    }

    for i in 0..pixel_count {
        let o = i * 4;
        let r = pixel_bytes[o] as u32;
        let g = pixel_bytes[o + 1] as u32;
        let b = pixel_bytes[o + 2] as u32;
        win.pixels[i] = (r << 16) | (g << 8) | b;
    }

    state.needs_redraw = true;
    Ok(())
}

/// Queue an input event for `window_id`. Silently dropped if the window
/// doesn't exist or its queue is full (a stalled app shouldn't be able to
/// grow this without bound).
pub fn push_input(window_id: u64, event: AppInputEvent) {
    let mut queues = INPUT_QUEUES.lock();
    if let Some(queue) = queues.get_mut(&window_id) {
        if queue.len() < MAX_QUEUED_EVENTS {
            queue.push_back(event);
        }
    }
}

/// Pop the oldest pending input event for `window_id`, if `pid` owns it.
pub fn poll_input(window_id: u64, pid: u64) -> Option<AppInputEvent> {
    if owner_of(window_id) != Some(pid) {
        return None;
    }
    INPUT_QUEUES.lock().get_mut(&window_id).and_then(|q| q.pop_front())
}

/// Drop a closed app window's input queue. Called by the compositor when a
/// window is closed via its `[X]` button, regardless of type; a no-op for
/// non-app window ids since they were never registered here.
pub fn on_window_closed(window_id: u64) {
    INPUT_QUEUES.lock().remove(&window_id);
}
