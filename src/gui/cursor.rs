// ============================================================================
// FerrumOS - GUI Mouse Cursor & Input
// ============================================================================

use spin::Mutex;
use crate::devices::vga_fb::FRAMEBUFFER;
use crate::input::EVENT_QUEUE;
use crate::gui::compositor;

pub struct CursorState {
    pub x: u32,
    pub y: u32,
    pub old_x: u32,
    pub old_y: u32,
    pub left_down: bool,
    pub saved_pixels: [u32; 16 * 16],
    pub has_saved: bool,
    pub dirty: bool,
}

lazy_static::lazy_static! {
    pub static ref CURSOR: Mutex<CursorState> = Mutex::new(CursorState {
        x: 512,
        y: 384,
        old_x: 512,
        old_y: 384,
        left_down: false,
        saved_pixels: [0; 256],
        has_saved: false,
        dirty: true, // Draw on first frame
    });
}

pub fn init() {
    // Initialized by lazy_static
}

pub fn process_input() {
    let mut cursor = CURSOR.lock();
    let (max_w, max_h) = {
        let fb_guard = FRAMEBUFFER.lock();
        if let Some(fb) = fb_guard.as_ref() {
            (fb.width, fb.height)
        } else {
            (1024, 768)
        }
    };
    
    // Process all pending input events
    loop {
        let event_opt = x86_64::instructions::interrupts::without_interrupts(|| {
            EVENT_QUEUE.lock().pop()
        });

        let event = match event_opt {
            Some(e) => e,
            None => break,
        };

        match event.event_type {
            crate::input::InputEventType::MouseMove(dx, dy) => {
                // Adjust cursor position
                let new_x = (cursor.x as i32 + dx as i32).clamp(0, max_w as i32 - 1) as u32;
                let new_y = (cursor.y as i32 + dy as i32).clamp(0, max_h as i32 - 1) as u32;
                
                if new_x != cursor.x || new_y != cursor.y {
                    cursor.x = new_x;
                    cursor.y = new_y;
                    cursor.dirty = true;
                }
                
                compositor::handle_mouse_move(new_x, new_y);
            }
            crate::input::InputEventType::MouseButton(0, true) | crate::input::InputEventType::MouseButton(1, true) => {
                cursor.left_down = true;
                compositor::handle_mouse_down(cursor.x, cursor.y);
            }
            crate::input::InputEventType::MouseButton(0, false) | crate::input::InputEventType::MouseButton(1, false) => {
                cursor.left_down = false;
                compositor::handle_mouse_up();
            }
            crate::input::InputEventType::KeyPress(ascii) => {
                compositor::handle_key_press(ascii);
            }
            // Ignore other inputs for MVP
            _ => {}
        }
    }
}

pub fn restore_background() {
    let cursor = CURSOR.lock();
    if !cursor.has_saved {
        return;
    }
    
    let fb_guard = FRAMEBUFFER.lock();
    let fb = match fb_guard.as_ref() {
        Some(fb) => fb,
        None => return,
    };
    
    for row in 0..16 {
        for col in 0..16 {
            let px = cursor.old_x + col;
            let py = cursor.old_y + row;
            let color = cursor.saved_pixels[(row * 16 + col) as usize];
            fb.set_pixel(px, py, color);
        }
    }
}

pub fn save_and_draw() {
    let mut cursor = CURSOR.lock();
    let cx = cursor.x;
    let cy = cursor.y;
    
    let fb_guard = FRAMEBUFFER.lock();
    let fb = match fb_guard.as_ref() {
        Some(fb) => fb,
        None => return,
    };
    
    // 1. Save background pixels
    for row in 0..16 {
        for col in 0..16 {
            let px = cx + col;
            let py = cy + row;
            cursor.saved_pixels[(row * 16 + col) as usize] = fb.get_pixel(px, py);
        }
    }
    cursor.old_x = cx;
    cursor.old_y = cy;
    cursor.has_saved = true;
    
    // 2. Draw Cursor using a 12x16 bitmap arrow shape
    //    We write directly to `fb` to avoid deadlocking on FRAMEBUFFER.
    //    Legend: 0 = transparent, 1 = outline (dark), 2 = fill (neon cyan)
    const CURSOR_BITMAP: [[u8; 12]; 16] = [
        [1,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,0,0,0,0,0,0,0,0,0,0],
        [1,2,1,0,0,0,0,0,0,0,0,0],
        [1,2,2,1,0,0,0,0,0,0,0,0],
        [1,2,2,2,1,0,0,0,0,0,0,0],
        [1,2,2,2,2,1,0,0,0,0,0,0],
        [1,2,2,2,2,2,1,0,0,0,0,0],
        [1,2,2,2,2,2,2,1,0,0,0,0],
        [1,2,2,2,2,2,2,2,1,0,0,0],
        [1,2,2,2,2,2,2,2,2,1,0,0],
        [1,2,2,2,2,2,1,1,1,1,1,0],
        [1,2,2,1,2,2,1,0,0,0,0,0],
        [1,2,1,0,1,2,2,1,0,0,0,0],
        [1,1,0,0,1,2,2,1,0,0,0,0],
        [1,0,0,0,0,1,2,2,1,0,0,0],
        [0,0,0,0,0,1,1,1,0,0,0,0],
    ];
    
    let outline_color: u32 = 0x00111111;
    let fill_color: u32 = 0x0000FFCC;
    
    for row in 0..16u32 {
        for col in 0..12u32 {
            let val = CURSOR_BITMAP[row as usize][col as usize];
            if val != 0 {
                let color = if val == 1 { outline_color } else { fill_color };
                fb.set_pixel(cx + col, cy + row, color);
            }
        }
    }
}
