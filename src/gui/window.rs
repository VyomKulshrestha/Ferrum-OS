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
    /// A window owned by an arbitrary userland process (identified by the
    /// `u64` pid), drawing into its own RGBA8 canvas via `PresentWindow`
    /// instead of the kernel hand-drawing its content. This is the generic
    /// app-window primitive: everything else (`Terminal`, `SystemMonitor`,
    /// `AgentHud`) is still kernel-drawn and predates this variant.
    App(u64),
}

/// Chrome geometry shared between window rendering and the app-window
/// syscalls, so a process's requested canvas size maps to the same pixels
/// the compositor actually blits. Total window size = canvas size + chrome.
pub const CHROME_SIDE: u32 = 2;
pub const CHROME_TOP: u32 = 22;
pub const CHROME_BOTTOM: u32 = 2;

/// Title-bar button geometry, right-aligned in this order (left to right):
/// minimize, maximize, close. Shared between rendering and hit-testing so
/// the two can never drift apart.
const TITLE_BTN_SIZE: u32 = 16;
const TITLE_BTN_TOP: u32 = 2;
const TITLE_BTN_GAP: u32 = 4;

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

    /// RGB canvas for `WindowType::App` windows, row-major, `canvas_w *
    /// canvas_h` entries of `0x00RRGGBB`. Unused (empty) for every other
    /// window type.
    pub pixels: Vec<u32>,
    pub canvas_w: u32,
    pub canvas_h: u32,

    /// Hidden but still open: not rendered, not hit-testable, but keeps a
    /// taskbar entry so it can be restored.
    pub minimized: bool,
    /// Snapped to fill the desktop content area (below the top strip,
    /// above the dock). `restore_rect` holds the pre-maximize geometry so
    /// toggling back off restores it exactly.
    pub maximized: bool,
    pub restore_rect: Option<(u32, u32, u32, u32)>,
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
            pixels: Vec::new(),
            canvas_w: 0,
            canvas_h: 0,
            minimized: false,
            maximized: false,
            restore_rect: None,
        }
    }

    /// Build an app-owned window. `canvas_w`/`canvas_h` are the drawable
    /// pixel area the owning process presents into; the window's total
    /// on-screen size is the canvas plus the shared chrome (title bar,
    /// border) so app authors never need to know about chrome geometry.
    pub fn new_app(id: u64, pid: u64, title: &str, x: u32, y: u32, canvas_w: u32, canvas_h: u32) -> Self {
        let total_w = canvas_w + 2 * CHROME_SIDE;
        let total_h = canvas_h + CHROME_TOP + CHROME_BOTTOM;
        let mut w = Self::new(id, WindowType::App(pid), title, x, y, total_w, total_h, 0x00202020);
        w.pixels = alloc::vec![0x00202020u32; (canvas_w as usize) * (canvas_h as usize)];
        w.canvas_w = canvas_w;
        w.canvas_h = canvas_h;
        w
    }

    /// Close button rect `(x, y, w, h)`. Geometry unchanged from before
    /// minimize/maximize existed, just centralised so rendering and
    /// hit-testing can't drift apart.
    pub fn close_btn_rect(&self) -> (u32, u32, u32, u32) {
        (
            self.x + self.width.saturating_sub(TITLE_BTN_SIZE + 4),
            self.y + TITLE_BTN_TOP,
            TITLE_BTN_SIZE,
            TITLE_BTN_SIZE,
        )
    }

    /// Maximize/restore button rect, immediately left of close.
    pub fn maximize_btn_rect(&self) -> (u32, u32, u32, u32) {
        let (cx, cy, cw, ch) = self.close_btn_rect();
        (cx.saturating_sub(TITLE_BTN_SIZE + TITLE_BTN_GAP), cy, cw, ch)
    }

    /// Minimize button rect, immediately left of maximize.
    pub fn minimize_btn_rect(&self) -> (u32, u32, u32, u32) {
        let (mx, my, mw, mh) = self.maximize_btn_rect();
        (mx.saturating_sub(TITLE_BTN_SIZE + TITLE_BTN_GAP), my, mw, mh)
    }

    fn point_in_rect(px: u32, py: u32, rect: (u32, u32, u32, u32)) -> bool {
        let (rx, ry, rw, rh) = rect;
        px >= rx && px < rx + rw && py >= ry && py < ry + rh
    }

    pub fn is_close_btn(&self, px: u32, py: u32) -> bool {
        Self::point_in_rect(px, py, self.close_btn_rect())
    }

    pub fn is_maximize_btn(&self, px: u32, py: u32) -> bool {
        Self::point_in_rect(px, py, self.maximize_btn_rect())
    }

    pub fn is_minimize_btn(&self, px: u32, py: u32) -> bool {
        Self::point_in_rect(px, py, self.minimize_btn_rect())
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

    pub fn render(&self, focused: bool, close_hovered: bool, maximize_hovered: bool, minimize_hovered: bool) {
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

        // Draw Close/Maximize/Minimize buttons at top-right, right to
        // left. Close turns red on hover (destructive); maximize/minimize
        // turn the standard focused-title-bar highlight so they don't read
        // as dangerous the way close does.
        let (ccx, ccy, ccw, cch) = self.close_btn_rect();
        if close_hovered {
            graphics::fill_rect(ccx, ccy, ccw, cch, 0x00FF3333);
        }
        graphics::draw_string(
            ccx + 4,
            ccy,
            "X",
            if close_hovered { 0x00FFFFFF } else { 0x00FF3333 },
            if close_hovered { 0x00FF3333 } else { title_bg }
        );

        let (mxx, mxy, mxw, mxh) = self.maximize_btn_rect();
        if maximize_hovered {
            graphics::fill_rect(mxx, mxy, mxw, mxh, 0x00304050);
        }
        graphics::draw_string(
            mxx + 4,
            mxy,
            if self.maximized { "R" } else { "M" },
            if maximize_hovered { 0x00FFFFFF } else { 0x00AAAAAA },
            if maximize_hovered { 0x00304050 } else { title_bg }
        );

        let (mnx, mny, mnw, mnh) = self.minimize_btn_rect();
        if minimize_hovered {
            graphics::fill_rect(mnx, mny, mnw, mnh, 0x00304050);
        }
        graphics::draw_string(
            mnx + 4,
            mny,
            "_",
            if minimize_hovered { 0x00FFFFFF } else { 0x00AAAAAA },
            if minimize_hovered { 0x00304050 } else { title_bg }
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
                
                graphics::draw_string(self.x + 8, self.y + 40, "Heliox is your OS agent - always on.", 0x00FFFFFF, self.bg_color);
                graphics::draw_string(self.x + 8, self.y + 54, "Choose the brain that powers it:", 0x00FFFFFF, self.bg_color);

                match step {
                    '0' => {
                        graphics::draw_string(self.x + 8, self.y + 74, "Step 1: Local or Cloud?", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 90, "local  - on-device, works offline", 0x00AAAAAA, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 104, "cloud  - OpenAI / Claude / Gemini", 0x00AAAAAA, self.bg_color);
                    }
                    'L' => {
                        graphics::draw_string(self.x + 8, self.y + 74, "Step 2: Which local brain?", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 90, "tiny    - built-in model, auto-sized", 0x00AAAAAA, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 104, "ollama  - a local Ollama server", 0x00AAAAAA, self.bg_color);
                    }
                    'H' => {
                        graphics::draw_string(self.x + 8, self.y + 74, "Step 3: Ollama host:port", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 90, "(e.g. 10.0.2.2:11434)", 0x00AAAAAA, self.bg_color);
                    }
                    'C' => {
                        graphics::draw_string(self.x + 8, self.y + 74, "Step 2: Which cloud provider?", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 90, "openai / claude / gemini", 0x00AAAAAA, self.bg_color);
                    }
                    'K' => {
                        graphics::draw_string(self.x + 8, self.y + 74, "Step 3: API Key", 0x0000FFCC, self.bg_color);
                        graphics::draw_string(self.x + 8, self.y + 90, "(from your provider's dashboard)", 0x00AAAAAA, self.bg_color);
                    }
                    _ => {}
                }
                
                // Draw Input Buffer Field for Setup
                let input_y = self.y + 128;
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
        } else if let WindowType::App(_) = self.win_type {
            // App windows own their content: blit the process's last
            // `PresentWindow`-submitted canvas verbatim, inset by the shared
            // chrome geometry so it never draws over the title bar/border.
            let ox = self.x + CHROME_SIDE;
            let oy = self.y + CHROME_TOP;
            for row in 0..self.canvas_h {
                let row_base = (row * self.canvas_w) as usize;
                for col in 0..self.canvas_w {
                    if let Some(&px) = self.pixels.get(row_base + col as usize) {
                        graphics::set_pixel(ox + col, oy + row, px & 0x00FF_FFFF);
                    }
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
