// ============================================================================
// FerrumOS - GUI Mouse Cursor & Input
// ============================================================================

use spin::Mutex;
use crate::graphics;
use crate::devices::vga_fb::FRAMEBUFFER;
use crate::input::EVENT_QUEUE;
use crate::gui::compositor;

pub struct CursorState {
    pub x: u32,
    pub y: u32,
    pub left_down: bool,
}

lazy_static::lazy_static! {
    pub static ref CURSOR: Mutex<CursorState> = Mutex::new(CursorState {
        x: 512,
        y: 384,
        left_down: false,
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
    while let Some(event) = EVENT_QUEUE.lock().pop() {
        match event.event_type {
            crate::input::InputEventType::MouseMove(dx, dy) => {
                // Adjust cursor position
                let new_x = (cursor.x as i32 + dx as i32).clamp(0, max_w as i32 - 1) as u32;
                let new_y = (cursor.y as i32 + dy as i32).clamp(0, max_h as i32 - 1) as u32;
                
                cursor.x = new_x;
                cursor.y = new_y;
                
                compositor::handle_mouse_move(new_x, new_y);
            }
            crate::input::InputEventType::MouseButton(1, true) => {
                cursor.left_down = true;
                compositor::handle_mouse_down(cursor.x, cursor.y);
            }
            crate::input::InputEventType::MouseButton(1, false) => {
                cursor.left_down = false;
                compositor::handle_mouse_up();
            }
            // Ignore other inputs for MVP
            _ => {}
        }
    }
}

pub fn render() {
    let cursor = CURSOR.lock();
    
    // Draw a simple software cursor (a small arrow pointing up-left)
    // We draw lines to form the arrow
    let cx = cursor.x;
    let cy = cursor.y;
    let color = graphics::COLOR_WHITE;
    let outline = graphics::COLOR_BLACK;
    
    // Outline
    graphics::draw_line(cx, cy, cx, cy + 15, outline);
    graphics::draw_line(cx, cy, cx + 11, cy + 11, outline);
    graphics::draw_line(cx, cy + 15, cx + 4, cy + 11, outline);
    graphics::draw_line(cx + 11, cy + 11, cx + 4, cy + 11, outline);
    
    // Fill
    graphics::draw_line(cx + 1, cy + 2, cx + 1, cy + 13, color);
    graphics::draw_line(cx + 2, cy + 3, cx + 2, cy + 12, color);
    graphics::draw_line(cx + 3, cy + 4, cx + 3, cy + 11, color);
    graphics::draw_line(cx + 4, cy + 5, cx + 4, cy + 10, color);
    graphics::draw_line(cx + 5, cy + 6, cx + 8, cy + 9, color);
}
