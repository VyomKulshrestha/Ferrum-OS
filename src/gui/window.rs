// ============================================================================
// FerrumOS - GUI Window Object
// ============================================================================

use alloc::string::String;
use alloc::vec::Vec;
use crate::graphics;
use crate::graphics::font;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowType {
    Normal,
    SystemMonitor,
    Terminal,
    AgentHud,
}

pub struct Window {
    pub id: u64,
    pub win_type: WindowType,
    pub title: String,
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
    pub bg_color: u32,
    pub content: Vec<u8>, // simple text content for MVP
    
    // For AgentHud input buffer
    pub input_buffer: String,
}

impl Window {
    pub fn new(id: u64, win_type: WindowType, title: &str, x: u32, y: u32, width: u32, height: u32, bg_color: u32) -> Self {
        Window {
            id,
            win_type,
            title: String::from(title),
            x,
            y,
            width,
            height,
            bg_color,
            content: Vec::new(),
            input_buffer: String::new(),
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

    pub fn render(&self, focused: bool, close_hovered: bool) {
        // 1. Draw Window Background
        graphics::fill_rect(self.x, self.y, self.width, self.height, self.bg_color);

        // 2. Draw Title Bar Background (top 20 pixels). A focused
        //    window gets a brighter title bar so the user can
        //    see which window is active at a glance.
        let title_bar_height = 20;
        let title_bg = if focused { 0x00253040 } else { 0x001A1A1A };
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

        // Draw Close Button [X] at top-right. When hovered the
        // background turns red so the user knows it's
        // clickable.
        if close_hovered {
            graphics::fill_rect(
                self.x + self.width - 20,
                self.y + 2,
                16,
                16,
                0x00FF3333,
            );
        }
        graphics::draw_string(
            self.x + self.width - 16,
            self.y + 2,
            "X",
            if close_hovered { 0x00FFFFFF } else { 0x00FF3333 },
            if close_hovered { 0x00FF3333 } else { title_bg }
        );

        // 4. Draw Window Border. Focused windows get a 2px
        //    neon-cyan border; unfocused windows get a 1px
        //    dark-gray border.
        let border_color = if focused { 0x0000FFCC } else { 0x00333333 };
        let border_w = if focused { 2 } else { 1 };
        for i in 0..border_w {
            graphics::draw_line(self.x + i, self.y + i, self.x + self.width - 1 - i, self.y + i, border_color);
            graphics::draw_line(self.x + i, self.y + self.height - 1 - i, self.x + self.width - 1 - i, self.y + self.height - 1 - i, border_color);
            graphics::draw_line(self.x + i, self.y + i, self.x + i, self.y + self.height - 1 - i, border_color);
            graphics::draw_line(self.x + self.width - 1 - i, self.y + i, self.x + self.width - 1 - i, self.y + self.height - 1 - i, border_color);
        }

        // 5. Draw Content (Text & custom visual elements)
        let lines = self.get_wrapped_lines();
        let line_height = font::FONT_HEIGHT as u32 + 4;
        let max_visible_lines = ((self.height - 20 - 16) / line_height) as usize;

        if self.win_type == WindowType::SystemMonitor {
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
        } else if self.win_type == WindowType::AgentHud {
            // Agent HUD: Draw translucent background over the content area
            // (We assume bg_color has an alpha/blend capability or is solid for now)
            
            // Check if we are in NeedsConfig state
            let content_str = core::str::from_utf8(&self.content).unwrap_or("");
            if content_str.starts_with("NEEDS_CONFIG_") {
                let step = content_str.chars().nth(13).unwrap_or('0');
                
                graphics::draw_string(self.x + 8, self.y + 40, "Heliox Initial Setup", 0x00FFFFFF, self.bg_color);
                
                match step {
                    '0' => {
                        graphics::draw_string(self.x + 8, self.y + 60, "Step 1: Select Provider", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 80, "(ollama, openai, gemini, claude)", 0x00AAAAAA, self.bg_color);
                    }
                    '1' => {
                        graphics::draw_string(self.x + 8, self.y + 60, "Step 2: API Host / Port", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 80, "(e.g. 10.0.2.2:4000 or 10.0.2.2:11434)", 0x00AAAAAA, self.bg_color);
                    }
                    '2' => {
                        graphics::draw_string(self.x + 8, self.y + 60, "Step 3: API Key (if required)", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 80, "(Leave blank for local Ollama)", 0x00AAAAAA, self.bg_color);
                    }
                    _ => {}
                }
                
                // Draw Input Buffer Field for Setup
                let input_y = self.y + 110;
                graphics::fill_rect(self.x + 8, input_y, self.width - 16, 20, 0x001A1A1A);
                graphics::draw_string(self.x + 12, input_y + 4, ">", 0x00FFFFFF, 0x001A1A1A);
                graphics::draw_string(self.x + 28, input_y + 4, &self.input_buffer, 0x00FFFFFF, 0x001A1A1A);
            } else {
                // Draw Live Telemetry (Scrollable)
                let start_line = if lines.len() > max_visible_lines - 2 {
                    lines.len() - (max_visible_lines - 2)
                } else {
                    0
                };

                let mut cy = self.y + 20 + 8;
                for line in &lines[start_line..] {
                    let mut cx = self.x + 8;
                    for ch in line.chars() {
                        if cx + font::FONT_WIDTH as u32 <= self.x + self.width - 8 {
                            graphics::draw_char(cx, cy, ch as u8, 0x0000FFCC, self.bg_color); // Neon Cyan for JARVIS feel
                            cx += font::FONT_WIDTH as u32;
                        }
                    }
                    cy += line_height;
                }
                
                // Draw Input Buffer Field
                let input_y = self.y + self.height - 20;
                graphics::fill_rect(self.x, input_y, self.width, 20, 0x001A1A1A);
                graphics::draw_string(self.x + 4, input_y + 4, ">", 0x00FFFFFF, 0x001A1A1A);
                graphics::draw_string(self.x + 20, input_y + 4, &self.input_buffer, 0x00FFFFFF, 0x001A1A1A);
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
