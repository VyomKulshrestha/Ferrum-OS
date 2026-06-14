// ============================================================================
// FerrumOS — Synthetic Camera (Hand Frame Generator)
// ============================================================================
// Produces deterministic 320×240 YUYV frames containing skin-colored hand
// shapes with a configurable finger count.  Used for:
//   1.  CV pipeline development and testing without real camera hardware
//   2.  Deterministic gesture verification: "3-finger frame → ThreeFingers"
//   3.  Fallback when no UVC device is enumerated (Phase D-HW)
//
// Frame format: YUYV (YUV 4:2:2), 2 bytes/pixel = 153 600 bytes per frame.
// Double-buffered: the producer writes to one buffer while the consumer
// reads from the other.
// ============================================================================

#![allow(dead_code)]

extern crate alloc;

use spin::Mutex;
use x86_64::{PhysAddr, VirtAddr};

// ============================================================================
// Constants
// ============================================================================

/// Frame dimensions.
pub const FRAME_WIDTH: u16 = 320;
pub const FRAME_HEIGHT: u16 = 240;

/// Bytes per pixel in YUYV (average).
const BYTES_PER_PIXEL: usize = 2;

/// Total frame size in bytes.
pub const FRAME_SIZE: usize = FRAME_WIDTH as usize * FRAME_HEIGHT as usize * BYTES_PER_PIXEL;

/// Number of 4 KiB pages needed for one frame buffer.
const PAGES_PER_FRAME: usize = (FRAME_SIZE + 4095) / 4096; // 38 pages

// ============================================================================
// Skin / background colour constants (YUYV)
// ============================================================================

/// Background: dark neutral grey. Y=16 means nearly black.
/// Cb=128, Cr=128 is the achromatic point — NOT skin.
const BG_Y: u8 = 16;
const BG_CB: u8 = 128;
const BG_CR: u8 = 128;

/// Skin fill: Y=180 (bright), Cb=100, Cr=155.
/// Firmly inside the Chai & Ngan skin range: 77 ≤ Cb ≤ 127, 133 ≤ Cr ≤ 173.
const SKIN_Y: u8 = 180;
const SKIN_CB: u8 = 100;
const SKIN_CR: u8 = 155;

// ============================================================================
// Synthetic gesture presets
// ============================================================================

/// Which gesture shape the generator should produce.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SyntheticGesture {
    /// No hand in frame.
    None,
    /// Closed fist: small compact palm, no fingers.
    Fist,
    /// Open palm with 5 fingers.
    OpenPalm,
    /// Single extended finger (index), elongated.
    Pointing,
    /// Two fingers (V-sign).
    Peace,
    /// Three fingers extended.
    ThreeFingers,
    /// Four fingers extended.
    FourFingers,
    /// Thumb extended laterally, fingers closed.
    ThumbsUp,
}

// ============================================================================
// Camera state
// ============================================================================

pub struct SynthCamera {
    /// Physical base of double-buffer (2 * PAGES_PER_FRAME pages).
    _buf_phys: PhysAddr,
    /// Virtual base of double-buffer.
    buf_virt: VirtAddr,
    /// Which buffer the producer writes to (0 or 1).
    write_idx: usize,
    /// Current gesture being generated.
    gesture: SyntheticGesture,
    /// Frame counter (incremented every tick).
    frame_count: u64,
    /// Whether initialisation succeeded.
    ready: bool,
}

pub static SYNTH_CAMERA: Mutex<Option<SynthCamera>> = Mutex::new(Option::None);

// ============================================================================
// Public API
// ============================================================================

/// Initialise the synthetic camera.  Allocates double-buffer frames.
pub fn init() -> Result<(), &'static str> {
    // Allocate 2 × PAGES_PER_FRAME contiguous pages for double-buffering.
    let total_pages = PAGES_PER_FRAME * 2;
    let first_frame = crate::memory::allocate_contiguous_frames(total_pages)
        .ok_or("camera_synth: failed to allocate frame buffers")?;
    let phys = first_frame.start_address();
    let virt = crate::memory::phys_to_virt(phys);

    // Zero-initialise.
    unsafe {
        core::ptr::write_bytes(virt.as_u64() as *mut u8, 0, total_pages * 4096);
    }

    let cam = SynthCamera {
        _buf_phys: phys,
        buf_virt: virt,
        write_idx: 0,
        gesture: SyntheticGesture::OpenPalm,
        frame_count: 0,
        ready: true,
    };

    *SYNTH_CAMERA.lock() = Some(cam);
    crate::serial_println!("[camera_synth] initialized ({}x{} YUYV, double-buffered)",
                           FRAME_WIDTH, FRAME_HEIGHT);
    Ok(())
}

/// Change the gesture that will be produced on the next `tick()`.
pub fn set_gesture(g: SyntheticGesture) {
    if let Some(cam) = SYNTH_CAMERA.lock().as_mut() {
        cam.gesture = g;
    }
}

/// Generate the next frame for the current gesture preset.
/// Should be called at ~5 fps (every 200 ms) from a timer or main loop.
pub fn tick() {
    if let Some(cam) = SYNTH_CAMERA.lock().as_mut() {
        if !cam.ready {
            return;
        }
        let buf = write_buffer(cam);
        generate_frame(buf, cam.gesture);
        // Swap buffers.
        cam.write_idx ^= 1;
        cam.frame_count += 1;
    }
}

/// Return a slice over the latest complete frame, or `None` if no frame
/// has been generated yet.
pub fn latest_frame() -> Option<&'static [u8]> {
    let cam_lock = SYNTH_CAMERA.lock();
    let cam = cam_lock.as_ref()?;
    if cam.frame_count == 0 {
        return Option::None;
    }
    // The *read* buffer is the opposite of the current write_idx.
    let read_idx = cam.write_idx ^ 1;
    let base = cam.buf_virt.as_u64() + (read_idx as u64) * (PAGES_PER_FRAME as u64 * 4096);
    // Safety: the buffer was allocated and is valid for FRAME_SIZE bytes.
    Some(unsafe { core::slice::from_raw_parts(base as *const u8, FRAME_SIZE) })
}

/// Returns `true` if the synthetic camera is initialised and ready.
pub fn is_available() -> bool {
    SYNTH_CAMERA.lock().as_ref().map_or(false, |c| c.ready)
}

/// Frame width in pixels.
pub fn frame_width() -> u16 {
    FRAME_WIDTH
}

/// Frame height in pixels.
pub fn frame_height() -> u16 {
    FRAME_HEIGHT
}

/// Current frame count.
pub fn frame_count() -> u64 {
    SYNTH_CAMERA.lock().as_ref().map_or(0, |c| c.frame_count)
}

/// Current gesture preset.
pub fn current_gesture() -> SyntheticGesture {
    SYNTH_CAMERA.lock().as_ref().map_or(SyntheticGesture::None, |c| c.gesture)
}

// ============================================================================
// Internal: buffer helpers
// ============================================================================

/// Get a mutable slice over the current write buffer.
fn write_buffer(cam: &SynthCamera) -> &mut [u8] {
    let base = cam.buf_virt.as_u64() + (cam.write_idx as u64) * (PAGES_PER_FRAME as u64 * 4096);
    unsafe { core::slice::from_raw_parts_mut(base as *mut u8, FRAME_SIZE) }
}

// ============================================================================
// Internal: YUYV pixel writing
// ============================================================================

/// Write a YUYV macro-pixel (2 horizontal pixels) at column `x` (must be
/// even), row `y` with the given Y/Cb/Cr values.
#[inline]
fn put_yuyv(buf: &mut [u8], x: u16, y: u16, y_val: u8, cb: u8, cr: u8) {
    let offset = ((y as usize) * (FRAME_WIDTH as usize) + (x as usize)) * 2;
    if offset + 3 < buf.len() {
        buf[offset] = y_val;     // Y0
        buf[offset + 1] = cb;    // U (Cb)
        buf[offset + 2] = y_val; // Y1
        buf[offset + 3] = cr;    // V (Cr)
    }
}

/// Set a single pixel to skin or background.  Since YUYV shares Cb/Cr
/// across pairs we operate on macro-pixel granularity (x is rounded down
/// to even).
#[inline]
fn set_pixel(buf: &mut [u8], x: u16, y: u16, skin: bool) {
    let ax = x & !1; // align to even column
    if skin {
        put_yuyv(buf, ax, y, SKIN_Y, SKIN_CB, SKIN_CR);
    } else {
        put_yuyv(buf, ax, y, BG_Y, BG_CB, BG_CR);
    }
}

// ============================================================================
// Internal: shape drawing
// ============================================================================

/// Fill the entire frame with background colour.
fn fill_background(buf: &mut [u8]) {
    let w = FRAME_WIDTH as usize;
    let h = FRAME_HEIGHT as usize;
    for y in 0..h {
        let mut x: usize = 0;
        while x < w {
            let offset = (y * w + x) * 2;
            if offset + 3 < buf.len() {
                buf[offset] = BG_Y;
                buf[offset + 1] = BG_CB;
                buf[offset + 2] = BG_Y;
                buf[offset + 3] = BG_CR;
            }
            x += 2;
        }
    }
}

/// Draw a filled skin-coloured ellipse centred at (`cx`, `cy`) with
/// semi-axes (`rx`, `ry`).  Uses the standard integer ellipse test:
///   (dx*dx * ry*ry + dy*dy * rx*rx) <= rx*rx * ry*ry
fn draw_ellipse(buf: &mut [u8], cx: i16, cy: i16, rx: i16, ry: i16) {
    let rx2 = (rx as i32) * (rx as i32);
    let ry2 = (ry as i32) * (ry as i32);
    let threshold = rx2 * ry2;

    let y_start = (cy - ry).max(0) as u16;
    let y_end = (cy + ry).min(FRAME_HEIGHT as i16 - 1) as u16;
    let x_start = (cx - rx).max(0) as u16;
    let x_end = (cx + rx).min(FRAME_WIDTH as i16 - 1) as u16;

    for y in y_start..=y_end {
        let dy = y as i32 - cy as i32;
        for x in (x_start..=x_end).step_by(2) {
            let dx = x as i32 - cx as i32;
            if dx * dx * ry2 + dy * dy * rx2 <= threshold {
                set_pixel(buf, x, y, true);
                // Also fill the odd pixel of the pair if inside.
                if x + 1 <= x_end {
                    let dx1 = (x + 1) as i32 - cx as i32;
                    if dx1 * dx1 * ry2 + dy * dy * rx2 <= threshold {
                        // Already set by set_pixel since it writes macro-pixels.
                    }
                }
            }
        }
    }
}

/// Draw a filled skin-coloured rectangle.
fn draw_rect(buf: &mut [u8], x0: u16, y0: u16, w: u16, h: u16) {
    let x_end = (x0 + w).min(FRAME_WIDTH);
    let y_end = (y0 + h).min(FRAME_HEIGHT);
    for y in y0..y_end {
        let mut x = x0 & !1; // align to even
        while x < x_end {
            set_pixel(buf, x, y, true);
            x += 2;
        }
    }
}

// ============================================================================
// Internal: gesture-specific frame generation
// ============================================================================

/// Finger geometry: (x_offset_from_palm_left, width, height).
/// We space up to 5 fingers evenly across the palm.
struct FingerSpec {
    x_offset: i16,
    width: u16,
    height: u16,
}

/// Compute finger positions for `count` fingers across a palm of width
/// `palm_w` starting at `palm_x`.  Returns up to 5 FingerSpec entries.
/// Compute finger positions for `heights` count of fingers across a palm of width
/// `palm_w` starting at `palm_x`.  Returns up to 5 FingerSpec entries.
fn finger_positions(palm_x: i16, palm_w: u16, heights: &[u16]) -> [Option<FingerSpec>; 5] {
    let mut specs: [Option<FingerSpec>; 5] = [Option::None, Option::None, Option::None, Option::None, Option::None];
    let count = heights.len();
    if count == 0 || count > 5 {
        return specs;
    }

    let finger_w: u16 = 14;

    // Distribute `count` fingers evenly across the palm width.
    let spacing = if count > 1 {
        (palm_w as i16 - finger_w as i16) / (count as i16 - 1)
    } else {
        0
    };

    let start_x = if count == 1 {
        // Single finger: center it
        palm_x + (palm_w as i16 / 2) - (finger_w as i16 / 2)
    } else {
        palm_x
    };

    for i in 0..count {
        let x_off = start_x + (i as i16) * spacing;
        specs[i] = Some(FingerSpec {
            x_offset: x_off,
            width: finger_w,
            height: heights[i],
        });
    }
    specs
}

/// Generate a complete YUYV frame for the given gesture.
fn generate_frame(buf: &mut [u8], gesture: SyntheticGesture) {
    fill_background(buf);

    match gesture {
        SyntheticGesture::None => {
            // Empty frame — no hand.
        }
        SyntheticGesture::Fist => {
            // Compact small palm, no fingers.
            draw_ellipse(buf, 160, 150, 40, 45);
        }
        SyntheticGesture::OpenPalm => {
            // Large palm + 5 fingers extending upward.
            let palm_cx: i16 = 160;
            let palm_cy: i16 = 155;
            let palm_rx: i16 = 55;
            let palm_ry: i16 = 60;
            draw_ellipse(buf, palm_cx, palm_cy, palm_rx, palm_ry);

            // 5 fingers above the palm.
            let palm_top = palm_cy - palm_ry;
            let palm_left = palm_cx - palm_rx;
            let palm_w = (palm_rx * 2) as u16;
            let heights = [25, 48, 65, 48, 25];
            let fingers = finger_positions(palm_left, palm_w, &heights);
            for spec in &fingers {
                if let Some(f) = spec {
                    let fy = (palm_top - f.height as i16).max(0) as u16;
                    let draw_h = (palm_cy - fy as i16 + 10) as u16;
                    draw_rect(buf, f.x_offset as u16, fy, f.width, draw_h);
                }
            }
        }
        SyntheticGesture::Pointing => {
            // Compact palm + single elongated finger (index).
            let palm_cx: i16 = 160;
            let palm_cy: i16 = 170;
            let palm_rx: i16 = 35;
            let palm_ry: i16 = 40;
            draw_ellipse(buf, palm_cx, palm_cy, palm_rx, palm_ry);

            // Single tall finger.
            let palm_top = palm_cy - palm_ry;
            let finger_x = (palm_cx - 7) as u16;
            let finger_h: u16 = 70;
            let fy = (palm_top - finger_h as i16).max(0) as u16;
            let draw_h = (palm_cy - fy as i16 + 10) as u16;
            draw_rect(buf, finger_x, fy, 14, draw_h);
        }
        SyntheticGesture::Peace => {
            // Palm + 2 fingers (V-sign).
            let palm_cx: i16 = 160;
            let palm_cy: i16 = 160;
            let palm_rx: i16 = 45;
            let palm_ry: i16 = 50;
            draw_ellipse(buf, palm_cx, palm_cy, palm_rx, palm_ry);

            let palm_top = palm_cy - palm_ry;
            let palm_left = palm_cx - palm_rx;
            let palm_w = (palm_rx * 2) as u16;
            let heights = [50, 50];
            let fingers = finger_positions(palm_left, palm_w, &heights);
            for spec in &fingers {
                if let Some(f) = spec {
                    let fy = (palm_top - f.height as i16).max(0) as u16;
                    let draw_h = (palm_cy - fy as i16 + 10) as u16;
                    draw_rect(buf, f.x_offset as u16, fy, f.width, draw_h);
                }
            }
        }
        SyntheticGesture::ThreeFingers => {
            let palm_cx: i16 = 160;
            let palm_cy: i16 = 160;
            let palm_rx: i16 = 50;
            let palm_ry: i16 = 55;
            draw_ellipse(buf, palm_cx, palm_cy, palm_rx, palm_ry);

            let palm_top = palm_cy - palm_ry;
            let palm_left = palm_cx - palm_rx;
            let palm_w = (palm_rx * 2) as u16;
            let heights = [35, 55, 35];
            let fingers = finger_positions(palm_left, palm_w, &heights);
            for spec in &fingers {
                if let Some(f) = spec {
                    let fy = (palm_top - f.height as i16).max(0) as u16;
                    let draw_h = (palm_cy - fy as i16 + 10) as u16;
                    draw_rect(buf, f.x_offset as u16, fy, f.width, draw_h);
                }
            }
        }
        SyntheticGesture::FourFingers => {
            let palm_cx: i16 = 160;
            let palm_cy: i16 = 160;
            let palm_rx: i16 = 52;
            let palm_ry: i16 = 55;
            draw_ellipse(buf, palm_cx, palm_cy, palm_rx, palm_ry);

            let palm_top = palm_cy - palm_ry;
            let palm_left = palm_cx - palm_rx;
            let palm_w = (palm_rx * 2) as u16;
            let heights = [30, 50, 50, 30];
            let fingers = finger_positions(palm_left, palm_w, &heights);
            for spec in &fingers {
                if let Some(f) = spec {
                    let fy = (palm_top - f.height as i16).max(0) as u16;
                    let draw_h = (palm_cy - fy as i16 + 10) as u16;
                    draw_rect(buf, f.x_offset as u16, fy, f.width, draw_h);
                }
            }
        }
        SyntheticGesture::ThumbsUp => {
            // Compact palm + one lateral (horizontal) thumb to the right.
            let palm_cx: i16 = 155;
            let palm_cy: i16 = 155;
            let palm_rx: i16 = 38;
            let palm_ry: i16 = 45;
            draw_ellipse(buf, palm_cx, palm_cy, palm_rx, palm_ry);

            // Thumb: horizontal rectangle extending upward-right.
            let thumb_x = (palm_cx + palm_rx - 5) as u16;
            let thumb_y = (palm_cy - palm_ry - 10).max(0) as u16;
            draw_rect(buf, thumb_x, thumb_y, 45, 16);
        }
    }
}

// Safety: the camera struct only contains raw pointers to kernel-mapped
// physical memory and primitive state; it is only accessed under the
// global spinlock.
unsafe impl Send for SynthCamera {}
unsafe impl Sync for SynthCamera {}
