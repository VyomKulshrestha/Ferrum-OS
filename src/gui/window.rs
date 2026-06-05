// ============================================================================
// FerrumOS - GUI Window Object
// ============================================================================

use alloc::string::String;
use alloc::vec::Vec;
use crate::graphics;
use crate::graphics::font;

pub struct Window {
    pub id: u64,
    pub title: String,
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
    pub bg_color: u32,
    pub content: Vec<u8>, // simple text content for MVP
}

impl Window {
    pub fn new(id: u64, title: &str, x: u32, y: u32, width: u32, height: u32, bg_color: u32) -> Self {
        Window {
            id,
            title: String::from(title),
            x,
            y,
            width,
            height,
            bg_color,
            content: Vec::new(),
        }
    }

    /// Renders the window to the global framebuffer.
    /// In a true window manager, this would render to a backbuffer,
    /// but for MVP we render directly when compositing.
    pub fn render(&self) {
        // 1. Draw Window Background
        graphics::fill_rect(self.x, self.y, self.width, self.height, self.bg_color);
        
        // 2. Draw Title Bar Background (top 20 pixels)
        let title_bar_height = 20;
        let title_bg = 0x00444444; // Dark gray
        graphics::fill_rect(self.x, self.y, self.width, title_bar_height, title_bg);
        
        // 3. Draw Title Text
        graphics::draw_string(
            self.x + 5, 
            self.y + 2, 
            &self.title, 
            graphics::COLOR_WHITE, 
            title_bg
        );
        
        // 4. Draw Window Border
        let border_color = 0x00777777;
        // Top
        graphics::draw_line(self.x, self.y, self.x + self.width, self.y, border_color);
        // Bottom
        graphics::draw_line(self.x, self.y + self.height, self.x + self.width, self.y + self.height, border_color);
        // Left
        graphics::draw_line(self.x, self.y, self.x, self.y + self.height, border_color);
        // Right
        graphics::draw_line(self.x + self.width, self.y, self.x + self.width, self.y + self.height, border_color);
        
        // 5. Draw Content (Text)
        if !self.content.is_empty() {
            let mut cx = self.x + 5;
            let mut cy = self.y + title_bar_height + 5;
            for &byte in &self.content {
                if byte == b'\n' {
                    cx = self.x + 5;
                    cy += font::FONT_HEIGHT + 2;
                } else {
                    graphics::draw_char(cx, cy, byte, graphics::COLOR_BLACK, self.bg_color);
                    cx += font::FONT_WIDTH;
                }
            }
        }
    }
    
    pub fn contains_point(&self, px: u32, py: u32) -> bool {
        px >= self.x && px <= self.x + self.width &&
        py >= self.y && py <= self.y + self.height
    }
    
    pub fn is_title_bar(&self, px: u32, py: u32) -> bool {
        let title_bar_height = 20;
        px >= self.x && px <= self.x + self.width &&
        py >= self.y && py <= self.y + title_bar_height
    }
}
