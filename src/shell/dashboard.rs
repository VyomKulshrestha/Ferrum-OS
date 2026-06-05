// ============================================================================
// FerrumOS - TUI System Dashboard
// ============================================================================
// Full-screen status dashboard rendered on the VGA framebuffer using the
// existing drawing primitives from `crate::graphics`. Displays system info,
// heap memory usage, scheduler tasks, and registered devices in styled
// panels.
//
// Entry point: `run_dashboard()` — clears the screen, draws all panels,
// then polls for ESC (0x1B) to return to the shell.
// ============================================================================

#![allow(dead_code)]

extern crate alloc;

use alloc::format;
use alloc::string::String;
use alloc::vec::Vec;

use crate::graphics::{
    self, fill_rect, draw_string, draw_char,
    COLOR_BLACK, COLOR_WHITE, COLOR_GREEN, COLOR_CYAN, COLOR_RED, COLOR_YELLOW,
};

// ============================================================================
// Screen & Font Constants
// ============================================================================

const SCREEN_W: u32 = 1024;
const SCREEN_H: u32 = 768;

const CHAR_W: u32 = 8;
const CHAR_H: u32 = 16;

const COLS: u32 = SCREEN_W / CHAR_W;   // 128
const ROWS: u32 = SCREEN_H / CHAR_H;   // 48

// ============================================================================
// Color Palette
// ============================================================================

const COLOR_HEADER_BG: u32    = 0x1A1A2E;
const COLOR_PANEL_BG: u32     = 0x16213E;
const COLOR_PANEL_BORDER: u32 = 0x0F3460;
const COLOR_LABEL: u32        = 0xA0A0A0;
const COLOR_VALUE: u32        = COLOR_WHITE;
const COLOR_FOOTER: u32       = COLOR_YELLOW;

// ============================================================================
// Helper: draw a horizontal line of box-drawing characters
// ============================================================================

/// Draw a horizontal line using `─` (0xC4) between two endpoints.
fn draw_hline(x: u32, y: u32, w: u32, color: u32) {
    let mut cx = x;
    let end = x + w;
    while cx < end {
        draw_char(cx, y, 0xC4, color, COLOR_PANEL_BG);
        cx += CHAR_W;
    }
}

/// Draw a vertical line using `│` (0xB3) between two endpoints.
fn draw_vline(x: u32, y0: u32, y1: u32, color: u32) {
    let mut cy = y0;
    while cy < y1 {
        draw_char(x, cy, 0xB3, color, COLOR_PANEL_BG);
        cy += CHAR_H;
    }
}

// ============================================================================
// Helper: draw a styled panel
// ============================================================================

/// Draw a panel with a title, background fill, and colored border lines.
///
/// `px`, `py` are pixel coordinates of the top-left corner; `pw`, `ph` are
/// pixel dimensions. `title` is rendered in the top-left of the panel.
fn draw_panel(px: u32, py: u32, pw: u32, ph: u32, title: &str) {
    // Background fill
    fill_rect(px, py, pw, ph, COLOR_PANEL_BG);

    // Border lines (top, bottom, left, right) using filled rects (2px thick)
    fill_rect(px, py, pw, 2, COLOR_PANEL_BORDER);           // top
    fill_rect(px, py + ph - 2, pw, 2, COLOR_PANEL_BORDER);  // bottom
    fill_rect(px, py, 2, ph, COLOR_PANEL_BORDER);           // left
    fill_rect(px + pw - 2, py, 2, ph, COLOR_PANEL_BORDER);  // right

    // Title bar accent
    fill_rect(px, py, pw, CHAR_H + 4, COLOR_PANEL_BORDER);

    // Title text (inset a few pixels)
    let title_str = format!(" {} ", title);
    draw_string(px + 8, py + 2, &title_str, COLOR_CYAN, COLOR_PANEL_BORDER);
}

// ============================================================================
// Helper: format bytes into a human-readable string
// ============================================================================

fn format_bytes(bytes: usize) -> String {
    if bytes >= 1024 * 1024 {
        let mb = bytes / (1024 * 1024);
        let kb_rem = (bytes % (1024 * 1024)) / 1024;
        format!("{}.{}M", mb, kb_rem / 100)
    } else if bytes >= 1024 {
        format!("{}K", bytes / 1024)
    } else {
        format!("{}B", bytes)
    }
}

// ============================================================================
// Helper: format numbers with commas
// ============================================================================

fn format_with_commas(n: usize) -> String {
    let s = format!("{}", n);
    let bytes = s.as_bytes();
    let len = bytes.len();
    if len <= 3 {
        return s;
    }
    let mut result = String::with_capacity(len + len / 3);
    for (i, &b) in bytes.iter().enumerate() {
        if i > 0 && (len - i) % 3 == 0 {
            result.push(',');
        }
        result.push(b as char);
    }
    result
}

// ============================================================================
// Helper: state name & color for TaskState
// ============================================================================

fn task_state_name(state: crate::scheduler::TaskState) -> &'static str {
    match state {
        crate::scheduler::TaskState::Ready   => "Ready",
        crate::scheduler::TaskState::Running => "Running",
        crate::scheduler::TaskState::Blocked => "Blocked",
        crate::scheduler::TaskState::Dead    => "Dead",
    }
}

fn task_state_color(state: crate::scheduler::TaskState) -> u32 {
    match state {
        crate::scheduler::TaskState::Running => COLOR_GREEN,
        crate::scheduler::TaskState::Ready   => COLOR_CYAN,
        crate::scheduler::TaskState::Blocked => COLOR_YELLOW,
        crate::scheduler::TaskState::Dead    => COLOR_RED,
    }
}

// ============================================================================
// Helper: state name & color for DeviceState
// ============================================================================

fn device_state_name(state: crate::devices::DeviceState) -> &'static str {
    match state {
        crate::devices::DeviceState::Online   => "Online",
        crate::devices::DeviceState::Planned  => "Planned",
        crate::devices::DeviceState::Disabled => "Disabled",
    }
}

fn device_state_color(state: crate::devices::DeviceState) -> u32 {
    match state {
        crate::devices::DeviceState::Online   => COLOR_GREEN,
        crate::devices::DeviceState::Planned  => COLOR_YELLOW,
        crate::devices::DeviceState::Disabled => COLOR_RED,
    }
}

// ============================================================================
// Helper: device class name
// ============================================================================

fn device_class_name(class: crate::devices::DeviceClass) -> &'static str {
    match class {
        crate::devices::DeviceClass::Display => "Display",
        crate::devices::DeviceClass::Serial  => "Serial",
        crate::devices::DeviceClass::Input   => "Input",
        crate::devices::DeviceClass::Timer   => "Timer",
        crate::devices::DeviceClass::Storage => "Storage",
        crate::devices::DeviceClass::Network => "Network",
        crate::devices::DeviceClass::Audio   => "Audio",
        crate::devices::DeviceClass::Camera  => "Camera",
    }
}

// ============================================================================
// Helper: pad/truncate a string to a fixed width
// ============================================================================

fn pad(s: &str, width: usize) -> String {
    if s.len() >= width {
        String::from(&s[..width])
    } else {
        let mut padded = String::from(s);
        for _ in 0..(width - s.len()) {
            padded.push(' ');
        }
        padded
    }
}

// ============================================================================
// Panel: System Info
// ============================================================================

fn draw_system_info_panel(px: u32, py: u32, pw: u32, ph: u32) {
    draw_panel(px, py, pw, ph, "\u{00FE} System Info");

    let content_y = py + CHAR_H + 8;
    let label_x = px + 12;
    let value_x = px + 12 + 10 * CHAR_W; // after 10-char label

    // Kernel
    draw_string(label_x, content_y, "Kernel:", COLOR_LABEL, COLOR_PANEL_BG);
    draw_string(value_x, content_y, "FerrumOS v0.3", COLOR_VALUE, COLOR_PANEL_BG);

    // Uptime
    let ticks = crate::scheduler::total_ticks();
    let uptime_str = format!("{} ticks", ticks);
    draw_string(label_x, content_y + CHAR_H + 4, "Uptime:", COLOR_LABEL, COLOR_PANEL_BG);
    draw_string(value_x, content_y + CHAR_H + 4, &uptime_str, COLOR_VALUE, COLOR_PANEL_BG);

    // CPUs
    draw_string(label_x, content_y + 2 * (CHAR_H + 4), "CPUs:", COLOR_LABEL, COLOR_PANEL_BG);
    draw_string(value_x, content_y + 2 * (CHAR_H + 4), "1", COLOR_VALUE, COLOR_PANEL_BG);

    // Active tasks
    let active = crate::scheduler::active_task_count();
    let tasks_str = format!("{} active", active);
    draw_string(label_x, content_y + 3 * (CHAR_H + 4), "Tasks:", COLOR_LABEL, COLOR_PANEL_BG);
    draw_string(value_x, content_y + 3 * (CHAR_H + 4), &tasks_str, COLOR_GREEN, COLOR_PANEL_BG);
}

// ============================================================================
// Panel: Memory
// ============================================================================

fn draw_memory_panel(px: u32, py: u32, pw: u32, ph: u32) {
    draw_panel(px, py, pw, ph, "\u{00FE} Memory");

    let content_y = py + CHAR_H + 8;
    let label_x = px + 12;

    let (used, free) = crate::memory::heap::heap_stats();
    let total = crate::memory::heap::HEAP_SIZE;

    // Progress bar label
    draw_string(label_x, content_y, "Heap:", COLOR_LABEL, COLOR_PANEL_BG);

    // Draw text progress bar
    let bar_x = label_x + 6 * CHAR_W;
    let bar_width: usize = 20; // characters
    let filled = if total > 0 { (used * bar_width) / total } else { 0 };
    let empty = bar_width - filled;

    // Filled portion (█ = 0xDB)
    for i in 0..filled {
        draw_char(bar_x + (i as u32) * CHAR_W, content_y, 0xDB, COLOR_GREEN, COLOR_PANEL_BG);
    }
    // Empty portion (░ = 0xB0)
    for i in 0..empty {
        draw_char(bar_x + ((filled + i) as u32) * CHAR_W, content_y, 0xB0, 0x444444, COLOR_PANEL_BG);
    }

    // Percentage and summary after bar
    let pct = if total > 0 { (used * 100) / total } else { 0 };
    let summary = format!(" {}/{} ({}%)", format_bytes(used), format_bytes(total), pct);
    draw_string(
        bar_x + (bar_width as u32) * CHAR_W,
        content_y,
        &summary,
        COLOR_VALUE,
        COLOR_PANEL_BG,
    );

    // Used bytes line
    let used_str = format!("Used: {} bytes", format_with_commas(used));
    draw_string(label_x, content_y + CHAR_H + 4, &used_str, COLOR_VALUE, COLOR_PANEL_BG);

    // Free bytes line
    let free_str = format!("Free: {} bytes", format_with_commas(free));
    draw_string(label_x, content_y + 2 * (CHAR_H + 4), &free_str, COLOR_VALUE, COLOR_PANEL_BG);

    // Total line
    let total_str = format!("Total: {} bytes", format_with_commas(total));
    draw_string(label_x, content_y + 3 * (CHAR_H + 4), &total_str, COLOR_LABEL, COLOR_PANEL_BG);
}

// ============================================================================
// Panel: Processes (Scheduler Tasks)
// ============================================================================

fn draw_processes_panel(px: u32, py: u32, pw: u32, ph: u32) {
    draw_panel(px, py, pw, ph, "\u{00FE} Processes");

    let content_y = py + CHAR_H + 8;
    let col_x = px + 12;

    // Column widths (in characters)
    let col_pid_w: u32 = 6;
    let col_name_w: u32 = 20;
    let col_state_w: u32 = 12;
    let col_pri_w: u32 = 10;
    let col_ticks_w: u32 = 12;

    // Header row
    let header_y = content_y;
    draw_string(col_x, header_y, &pad("PID", col_pid_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + col_pid_w * CHAR_W, header_y, &pad("Name", col_name_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + (col_pid_w + col_name_w) * CHAR_W, header_y, &pad("State", col_state_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + (col_pid_w + col_name_w + col_state_w) * CHAR_W, header_y, &pad("Priority", col_pri_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + (col_pid_w + col_name_w + col_state_w + col_pri_w) * CHAR_W, header_y, &pad("Ticks", col_ticks_w as usize), COLOR_CYAN, COLOR_PANEL_BG);

    // Separator line
    let sep_y = header_y + CHAR_H + 2;
    let line_len = (col_pid_w + col_name_w + col_state_w + col_pri_w + col_ticks_w) as u32 * CHAR_W;
    fill_rect(col_x, sep_y, line_len, 1, COLOR_PANEL_BORDER);

    // Task rows
    let tasks = crate::scheduler::list_tasks();
    let max_rows = ((ph - (CHAR_H + 8 + CHAR_H + 6)) / (CHAR_H + 2)) as usize;
    let row_start_y = sep_y + 4;

    for (i, task) in tasks.iter().enumerate() {
        if i >= max_rows {
            break;
        }
        let row_y = row_start_y + (i as u32) * (CHAR_H + 2);

        // PID
        let pid_str = format!("{}", task.id);
        draw_string(col_x, row_y, &pad(&pid_str, col_pid_w as usize), COLOR_VALUE, COLOR_PANEL_BG);

        // Name
        draw_string(col_x + col_pid_w * CHAR_W, row_y, &pad(&task.name, col_name_w as usize), COLOR_VALUE, COLOR_PANEL_BG);

        // State (colored)
        let state_name = task_state_name(task.state);
        let state_color = task_state_color(task.state);
        draw_string(col_x + (col_pid_w + col_name_w) * CHAR_W, row_y, &pad(state_name, col_state_w as usize), state_color, COLOR_PANEL_BG);

        // Priority
        let pri_name = match task.priority {
            crate::scheduler::Priority::Idle   => "Idle",
            crate::scheduler::Priority::Normal => "Normal",
            crate::scheduler::Priority::High   => "High",
            crate::scheduler::Priority::System => "System",
        };
        draw_string(col_x + (col_pid_w + col_name_w + col_state_w) * CHAR_W, row_y, &pad(pri_name, col_pri_w as usize), COLOR_LABEL, COLOR_PANEL_BG);

        // Ticks
        let ticks_str = format!("{}", task.ticks);
        draw_string(col_x + (col_pid_w + col_name_w + col_state_w + col_pri_w) * CHAR_W, row_y, &pad(&ticks_str, col_ticks_w as usize), COLOR_VALUE, COLOR_PANEL_BG);
    }
}

// ============================================================================
// Panel: Devices
// ============================================================================

fn draw_devices_panel(px: u32, py: u32, pw: u32, ph: u32) {
    draw_panel(px, py, pw, ph, "\u{00FE} Devices");

    let content_y = py + CHAR_H + 8;
    let col_x = px + 12;

    // Column widths (in characters)
    let col_name_w: u32 = 20;
    let col_class_w: u32 = 12;
    let col_state_w: u32 = 12;
    let col_driver_w: u32 = 16;

    // Header row
    let header_y = content_y;
    draw_string(col_x, header_y, &pad("Name", col_name_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + col_name_w * CHAR_W, header_y, &pad("Class", col_class_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + (col_name_w + col_class_w) * CHAR_W, header_y, &pad("State", col_state_w as usize), COLOR_CYAN, COLOR_PANEL_BG);
    draw_string(col_x + (col_name_w + col_class_w + col_state_w) * CHAR_W, header_y, &pad("Driver", col_driver_w as usize), COLOR_CYAN, COLOR_PANEL_BG);

    // Separator line
    let sep_y = header_y + CHAR_H + 2;
    let line_len = (col_name_w + col_class_w + col_state_w + col_driver_w) as u32 * CHAR_W;
    fill_rect(col_x, sep_y, line_len, 1, COLOR_PANEL_BORDER);

    // Device rows
    let devices = crate::devices::list_devices();
    let max_rows = ((ph - (CHAR_H + 8 + CHAR_H + 6)) / (CHAR_H + 2)) as usize;
    let row_start_y = sep_y + 4;

    for (i, dev) in devices.iter().enumerate() {
        if i >= max_rows {
            break;
        }
        let row_y = row_start_y + (i as u32) * (CHAR_H + 2);

        // Name
        draw_string(col_x, row_y, &pad(&dev.name, col_name_w as usize), COLOR_VALUE, COLOR_PANEL_BG);

        // Class
        let class_name = device_class_name(dev.class);
        draw_string(col_x + col_name_w * CHAR_W, row_y, &pad(class_name, col_class_w as usize), COLOR_LABEL, COLOR_PANEL_BG);

        // State (colored)
        let state_name = device_state_name(dev.state);
        let state_color = device_state_color(dev.state);
        draw_string(col_x + (col_name_w + col_class_w) * CHAR_W, row_y, &pad(state_name, col_state_w as usize), state_color, COLOR_PANEL_BG);

        // Driver
        draw_string(col_x + (col_name_w + col_class_w + col_state_w) * CHAR_W, row_y, &pad(&dev.driver, col_driver_w as usize), COLOR_LABEL, COLOR_PANEL_BG);
    }
}

// ============================================================================
// Header Bar
// ============================================================================

fn draw_header() {
    // Full-width header bar
    fill_rect(0, 0, SCREEN_W, 32, COLOR_HEADER_BG);

    // Accent stripe at very top (2px)
    fill_rect(0, 0, SCREEN_W, 2, COLOR_PANEL_BORDER);

    // Title centered
    let title = "FerrumOS System Dashboard";
    let title_px_w = title.len() as u32 * CHAR_W;
    let title_x = (SCREEN_W - title_px_w) / 2;
    draw_string(title_x, 8, title, COLOR_CYAN, COLOR_HEADER_BG);
}

// ============================================================================
// Footer
// ============================================================================

fn draw_footer() {
    let footer_y = SCREEN_H - CHAR_H - 12;

    // Subtle separator line
    fill_rect(20, footer_y - 4, SCREEN_W - 40, 1, COLOR_PANEL_BORDER);

    // Footer text
    draw_string(20, footer_y, "[ESC]", COLOR_YELLOW, COLOR_BLACK);
    draw_string(20 + 6 * CHAR_W, footer_y, "Return to shell", COLOR_LABEL, COLOR_BLACK);

    // Right-aligned version info
    let version = "v0.3.0";
    let ver_x = SCREEN_W - (version.len() as u32 * CHAR_W) - 20;
    draw_string(ver_x, footer_y, version, 0x555555, COLOR_BLACK);
}

// ============================================================================
// Public Entry Point
// ============================================================================

/// Run the full-screen TUI dashboard.
///
/// Draws all panels with live kernel data, then enters a spin-loop
/// waiting for the ESC key (0x1B) to return to the shell. On exit,
/// clears the screen.
pub fn run_dashboard() {
    // ── Guard: framebuffer must be initialized ─────────────────────
    if !graphics::is_initialized() {
        crate::serial_println!("[dashboard] framebuffer not initialized, aborting");
        return;
    }

    crate::serial_println!("[dashboard] launching system dashboard");

    // ── Clear the entire screen ────────────────────────────────────
    fill_rect(0, 0, SCREEN_W, SCREEN_H, COLOR_BLACK);

    // ── Header bar ─────────────────────────────────────────────────
    draw_header();

    // ── Layout constants ───────────────────────────────────────────
    let margin: u32 = 20;
    let panel_gap: u32 = 16;
    let top_row_y: u32 = 40;
    let top_row_h: u32 = 5 * CHAR_H + 12;               // ~92px

    // Top row: two panels side by side
    let half_w = (SCREEN_W - 2 * margin - panel_gap) / 2;

    // System Info (left)
    draw_system_info_panel(margin, top_row_y, half_w, top_row_h);

    // Memory (right)
    draw_memory_panel(margin + half_w + panel_gap, top_row_y, half_w, top_row_h);

    // ── Processes panel (full width) ───────────────────────────────
    let proc_y = top_row_y + top_row_h + panel_gap;
    let proc_h: u32 = 10 * CHAR_H;                       // ~160px
    let full_w = SCREEN_W - 2 * margin;
    draw_processes_panel(margin, proc_y, full_w, proc_h);

    // ── Devices panel (full width) ─────────────────────────────────
    let dev_y = proc_y + proc_h + panel_gap;
    let dev_h: u32 = 10 * CHAR_H;                        // ~160px
    draw_devices_panel(margin, dev_y, full_w, dev_h);

    // ── Footer ─────────────────────────────────────────────────────
    draw_footer();

    // ── Input loop: wait for ESC ───────────────────────────────────
    loop {
        if let Some(key) = crate::interrupts::read_keyboard() {
            if key == 0x1B {
                break;
            }
        }
        core::hint::spin_loop();
    }

    // ── Exit: Restore previous console state ───────────────────────
    crate::serial_println!("[dashboard] exiting dashboard");
    crate::graphics::redraw_console();
}
