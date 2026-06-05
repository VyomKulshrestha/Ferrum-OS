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

    pub fn get_wrapped_lines(&self) -> Vec<String> {
        let mut lines = Vec::new();
        let mut current_line = String::new();
        let max_chars_per_line = ((self.width - 16) / font::FONT_WIDTH as u32) as usize;
        
        for &byte in &self.content {
            if byte == b'\n' {
                lines.push(current_line);
                current_line = String::new();
            } else if byte == 0x08 {
                current_line.pop();
            } else {
                current_line.push(byte as char);
                if current_line.len() >= max_chars_per_line {
                    lines.push(current_line);
                    current_line = String::new();
                }
            }
        }
        lines.push(current_line);
        lines
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
        
        // Draw Close Button [X] at top-right
        graphics::draw_string(
            self.x + self.width - 16,
            self.y + 2,
            "X",
            0x00FF3333,
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
        
        // 5. Draw Content (Text & custom visual elements)
        let lines = self.get_wrapped_lines();
        let line_height = font::FONT_HEIGHT as u32 + 4;
        let max_visible_lines = ((self.height - 20 - 16) / line_height) as usize;
        
        if self.id == 1 {
            // System Monitor: Draw text lines normally, leaving room for graph
            let mut cy = self.y + 20 + 8;
            for line in &lines {
                let mut cx = self.x + 8;
                for ch in line.chars() {
                    if cx + font::FONT_WIDTH as u32 <= self.x + self.width - 8 {
                        graphics::draw_char(cx, cy, ch as u8, 0x00CCCCCC, self.bg_color);
                        cx += font::FONT_WIDTH as u32;
                    }
                }
                cy += line_height;
            }
            
            // Draw Graph bounding box
            let graph_x = self.x + 10;
            let graph_y = self.y + 110;
            let graph_w = self.width - 20; // 280
            let graph_h = 70;
            
            // Draw box border (dark gray)
            let box_border_color = 0x00333333;
            graphics::fill_rect(graph_x, graph_y, graph_w, 1, box_border_color); // top
            graphics::fill_rect(graph_x, graph_y + graph_h - 1, graph_w, 1, box_border_color); // bottom
            graphics::fill_rect(graph_x, graph_y, 1, graph_h, box_border_color); // left
            graphics::fill_rect(graph_x + graph_w - 1, graph_y, 1, graph_h, box_border_color); // right
            
            // Plot history lines
            let history = crate::gui::compositor::CPU_HISTORY.lock();
            let num_points = history.len();
            
            if num_points > 1 {
                let step_x = graph_w / (num_points as u32 - 1);
                
                let get_coord = |index: usize| -> (u32, u32) {
                    let px = graph_x + (index as u32 * step_x);
                    let val = history[index] as u32;
                    // scale val (0..100) to height (0..60) with 5px padding top/bottom
                    let py = (graph_y + graph_h - 5) - (val * (graph_h - 10) / 100);
                    (px, py)
                };
                
                let line_color = 0x0000FFCC; // Neon Cyan
                for i in 0..num_points - 1 {
                    let (x1, y1) = get_coord(i);
                    let (x2, y2) = get_coord(i + 1);
                    graphics::draw_line(x1, y1, x2, y2, line_color);
                }
            }
        } else {
            // Regular windows: Draw text with scroll-scrolling if it exceeds visible limits
            let start_line = if lines.len() > max_visible_lines {
                lines.len() - max_visible_lines
            } else {
                0
            };
            
            let mut cy = self.y + 20 + 8;
            for line in &lines[start_line..] {
                let mut cx = self.x + 8;
                for ch in line.chars() {
                    if cx + font::FONT_WIDTH as u32 <= self.x + self.width - 8 {
                        graphics::draw_char(cx, cy, ch as u8, 0x00CCCCCC, self.bg_color);
                        cx += font::FONT_WIDTH as u32;
                    }
                }
                cy += line_height;
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
