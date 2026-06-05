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

    pub fn render(&self, focused: bool) {
        // 1. Draw Window Background
        graphics::fill_rect(self.x, self.y, self.width, self.height, self.bg_color);
        
        // 2. Draw Title Bar Background (top 20 pixels)
        let title_bar_height = 20;
        let title_bg = 0x001A1A1A; // Dark Title Bar
        graphics::fill_rect(self.x, self.y, self.width, title_bar_height, title_bg);
        
        // 3. Draw Title Text
        let title_text_color = if focused { 0x00FFFFFF } else { 0x00AAAAAA };
        graphics::draw_string(
            self.x + 8, 
            self.y + 2, 
            &self.title, 
            title_text_color, 
            title_bg
        );
        
        // 4. Draw Window Border
        let border_color = if focused { 0x0000FFCC } else { 0x00333333 }; // Neon Cyan if focused
        // Top
        graphics::draw_line(self.x, self.y, self.x + self.width - 1, self.y, border_color);
        // Bottom
        graphics::draw_line(self.x, self.y + self.height - 1, self.x + self.width - 1, self.y + self.height - 1, border_color);
        // Left
        graphics::draw_line(self.x, self.y, self.x, self.y + self.height - 1, border_color);
        // Right
        graphics::draw_line(self.x + self.width - 1, self.y, self.x + self.width - 1, self.y + self.height - 1, border_color);
        
        // 5. Draw Content (Text)
        if !self.content.is_empty() {
            let mut cx = self.x + 8;
            let mut cy = self.y + title_bar_height + 8;
            for &byte in &self.content {
                if byte == b'\n' {
                    cx = self.x + 8;
                    cy += font::FONT_HEIGHT + 4;
                } else {
                    graphics::draw_char(cx, cy, byte, 0x00CCCCCC, self.bg_color); // Light gray text
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
