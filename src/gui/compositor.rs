// ============================================================================
// FerrumOS - GUI Compositor
// ============================================================================

use alloc::vec::Vec;
use spin::Mutex;
use crate::gui::window::Window;
use crate::gui::desktop;
use crate::gui::cursor;

/// Identifier of the taskbar button currently under the
/// cursor, if any. Used by `render_taskbar` to highlight the
/// hovered button.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HoverTarget {
    None,
    TerminalButton,
    SysMonButton,
    JarvisButton,
    ExitButton,
    /// Close button of the window with this id.
    WindowClose(u64),
}

pub struct CompositorState {
    pub windows: Vec<Window>,
    pub focused_idx: Option<usize>,
    pub drag_active: bool,
    pub drag_start_mx: u32,
    pub drag_start_my: u32,
    pub drag_start_wx: u32,
    pub drag_start_wy: u32,
    pub needs_redraw: bool,
    /// What the cursor is currently hovering over. Used by
    /// the taskbar to highlight buttons and by the window
    /// close button to turn red.
    pub hover: HoverTarget,
    /// Which taskbar button is currently being pressed (left
    /// mouse held down on it).
    pub pressed: HoverTarget,
}

lazy_static::lazy_static! {
    pub static ref COMPOSITOR: Mutex<CompositorState> = Mutex::new(CompositorState {
        windows: Vec::new(),
        focused_idx: None,
        drag_active: false,
        drag_start_mx: 0,
        drag_start_my: 0,
        drag_start_wx: 0,
        drag_start_wy: 0,
        needs_redraw: true,
        hover: HoverTarget::None,
        pressed: HoverTarget::None,
    });
}

lazy_static::lazy_static! {
    pub static ref CPU_HISTORY: Mutex<[u8; 20]> = Mutex::new([0; 20]);
}

struct TerminalWriterHelper<'a> {
    content: &'a mut Vec<u8>,
}

impl<'a> core::fmt::Write for TerminalWriterHelper<'a> {
    fn write_str(&mut self, s: &str) -> core::fmt::Result {
        self.content.extend_from_slice(s.as_bytes());
        Ok(())
    }
}

pub fn update_system_monitor() {
    let mut state = COMPOSITOR.lock();

    // 1. Get memory usage and task counts
    let (used, _) = crate::memory::heap::heap_stats();
    let total = crate::memory::heap::HEAP_SIZE;
    let mem_mb = used / (1024 * 1024);
    let total_mb = total / (1024 * 1024);
    let tasks_count = crate::scheduler::list_tasks().len();

    // Estimate CPU usage based on active tasks and system ticks
    let ticks = crate::scheduler::total_ticks();
    let rand_val = (ticks % 7) as u8;
    let cpu_load = ((tasks_count * 2) as u8 + rand_val + 2).min(100);

    // 2. Update CPU history
    {
        let mut history = CPU_HISTORY.lock();
        for i in 0..19 {
            history[i] = history[i + 1];
        }
        history[19] = cpu_load;
    }

    // 3. Format window contents
    if let Some(win) = state.windows.iter_mut().find(|w| w.id == 1) {
        win.content.clear();
        use core::fmt::Write;
        let mut writer = TerminalWriterHelper { content: &mut win.content };
        let _ = write!(
            &mut writer,
            "CPU Usage: {}%\nMemory: {}MB / {}MB\nTasks: {} Active\n\n  --- CPU Load History ---",
            cpu_load, mem_mb, total_mb, tasks_count
        );
        state.needs_redraw = true;
    }
}

pub fn spawn_terminal() {
    let mut state = COMPOSITOR.lock();
    if let Some(idx) = state.windows.iter().position(|w| w.id == 2) {
        let w = state.windows.remove(idx);
        state.windows.push(w);
        let new_idx = state.windows.len() - 1;
        state.focused_idx = Some(new_idx);
    } else {
        let mut w2 = Window::new(2, crate::gui::window::WindowType::Terminal, "TERMINAL", 450, 150, 400, 400, 0x001A1A1A);
        w2.content.extend_from_slice(b"FerrumOS:~$ ");
        state.windows.push(w2);
        state.focused_idx = Some(state.windows.len() - 1);
    }
    state.needs_redraw = true;
}

pub fn spawn_sys_mon() {
    let mut state = COMPOSITOR.lock();
    if let Some(idx) = state.windows.iter().position(|w| w.id == 1) {
        let w = state.windows.remove(idx);
        state.windows.push(w);
        let new_idx = state.windows.len() - 1;
        state.focused_idx = Some(new_idx);
    } else {
        let mut w1 = Window::new(1, crate::gui::window::WindowType::SystemMonitor, "SYSTEM MONITOR", 100, 100, 300, 200, 0x001E1E1E);
        w1.content.extend_from_slice(b"CPU Usage: 0%\nMemory: 0MB / 0MB\nTasks: 0 Active\n\n  --- CPU Load History ---");
        state.windows.push(w1);
        state.focused_idx = Some(state.windows.len() - 1);
    }
    state.needs_redraw = true;
}

pub fn init() {
    // Nothing to do for MVP init, structures are lazy_static
}

pub fn spawn_agent_hud(is_setup: bool) {
    let mut state = COMPOSITOR.lock();
    if let Some(idx) = state.windows.iter().position(|w| w.id == 3) {
        let w = state.windows.remove(idx);
        state.windows.push(w);
        let new_idx = state.windows.len() - 1;
        state.focused_idx = Some(new_idx);
    } else {
        // ID 3 = Agent HUD
        let mut w3 = Window::new(3, crate::gui::window::WindowType::AgentHud, "Agent HUD", 200, 200, 400, 300, 0x000F111A);
        if is_setup {
            w3.content.extend_from_slice(b"NEEDS_CONFIG_0\n");
        } else {
            w3.content.extend_from_slice(b"Agent initialized. Ambient mode active.\n");
        }
        state.windows.push(w3);
        state.focused_idx = Some(state.windows.len() - 1);
    }
    state.needs_redraw = true;
}

pub fn spawn_demo_windows() {
    let mut state = COMPOSITOR.lock();
    // Remember what was focused before resetting the demo windows, so a
    // pre-existing app window that had focus keeps it (matched by id,
    // since indices shift once the demo windows are pushed back on).
    let previously_focused_id = state.focused_idx.and_then(|i| state.windows.get(i)).map(|w| w.id);

    // Reset the kernel-drawn demo windows only. App windows (owned by a
    // userland process, e.g. via CreateWindow) are not part of this fixed
    // demo set and must survive re-entering the desktop, the same way a
    // real desktop doesn't close your open apps when it redraws.
    state.windows.retain(|w| matches!(w.win_type, crate::gui::window::WindowType::App(_)));

    let mut w1 = Window::new(1, crate::gui::window::WindowType::SystemMonitor, "SYSTEM MONITOR", 100, 100, 300, 200, 0x001E1E1E);
    w1.content.extend_from_slice(b"CPU Usage: 14%\nMemory: 256MB / 4096MB\nTasks: 5 Active\n\n[Graph Placeholder]");

    let mut w2 = Window::new(2, crate::gui::window::WindowType::Terminal, "TERMINAL", 450, 150, 400, 400, 0x001A1A1A);
    w2.content.extend_from_slice(b"FerrumOS:~$ ");

    state.windows.push(w1);
    state.windows.push(w2);
    // Keep focus on a pre-existing app window if it had it; otherwise
    // default to the terminal, by actual index rather than a hardcoded
    // position (pre-existing app windows shift where it lands in the vec).
    state.focused_idx = previously_focused_id
        .and_then(|id| state.windows.iter().position(|w| w.id == id))
        .or_else(|| state.windows.iter().position(|w| w.id == 2));
    state.needs_redraw = true;

    drop(state);

    // Check if agent needs config
    if let Err(_) = crate::fs::read_file("/disk/heliox/config.json") {
        spawn_agent_hud(true); // missing config -> setup state
    }
}

pub fn render() {
    let (hover, pressed, cursor_x, cursor_y, cursor_left) = {
        let state = COMPOSITOR.lock();
        if !state.needs_redraw {
            return;
        }
        let cursor = crate::gui::cursor::CURSOR.lock();
        (
            state.hover,
            state.pressed,
            cursor.x,
            cursor.y,
            cursor.left_down,
        )
    };

    // 1. Clear to Desktop Background
    desktop::render_background();

    // 2. Draw Windows from back to front. The hover state
    //    tells the window renderer whether the close button
    //    is being hovered so it can change colour.
    let mut state = COMPOSITOR.lock();
    let focused_idx = state.focused_idx;
    for (i, window) in state.windows.iter().enumerate() {
        let focused = focused_idx == Some(i);
        let close_hovered = matches!(hover, HoverTarget::WindowClose(id) if id == window.id);
        window.render(focused, close_hovered);
    }
    drop(state);

    // 3. Draw Taskbar (with hover/press state for the
    //    buttons).
    desktop::render_taskbar(hover, pressed, cursor_x, cursor_y, cursor_left);

    // Draw HUD overlay on top of taskbar/windows (but below cursor)
    draw_hud_overlay();

    // 4. Mark the cursor as dirty so the main loop redraws
    //    it on top of the new content.
    cursor::mark_dirty();

    COMPOSITOR.lock().needs_redraw = false;
}

/// Helper to hit test overlapping windows, returning window ID and title.
pub fn hit_test(mx: u32, my: u32) -> (u64, alloc::string::String) {
    hit_test_exclude(mx, my, false)
}

/// Helper to hit test overlapping windows, with option to exclude Agent HUD.
pub fn hit_test_exclude(mx: u32, my: u32, exclude_hud: bool) -> (u64, alloc::string::String) {
    let state = COMPOSITOR.lock();
    for window in state.windows.iter().rev() {
        if exclude_hud && window.win_type == crate::gui::window::WindowType::AgentHud {
            continue;
        }
        if window.contains_point(mx, my) {
            return (window.id, window.title.clone());
        }
    }
    (0, alloc::string::String::from("desktop"))
}


/// Render the transparent HUD overlay (waveform + pointing landmarks + suggestions).
pub fn draw_hud_overlay() {
    if !crate::syscall::hud::HUD_ENABLED.load(core::sync::atomic::Ordering::SeqCst) {
        return;
    }
    let state = crate::syscall::hud::HUD_STATE.lock();
    let visible = (state.flags & 1) != 0;
    if !visible {
        return;
    }
    let listening = (state.flags & 2) != 0;
    let pointing = (state.flags & 4) != 0;

    // 1. Draw Waveform Panel at the bottom (just above the dock)
    let start_x = 256u32;
    let base_y = 700u32;
    // Translucent panel background for the waveform (XRGB black, alpha=120)
    crate::graphics::fill_rect_alpha(start_x - 10, base_y - 85, 512 + 20, 95, 0x0011111d, 120);
    
    for i in 0..64 {
        let amp = state.waveform[i] as u32;
        let h = (amp * 80) / 255;
        let x = start_x + (i as u32) * 8;
        let color = if listening { 0x0000FFFF } else { 0x00777777 }; // Cyan if listening, Gray if not
        if h > 0 {
            for dx in 0..6 {
                crate::graphics::draw_line(x + dx, base_y - h, x + dx, base_y, color);
            }
        }
    }

    // 2. Draw Pointing Reticle & Landmarks
    if pointing {
        let px = state.point_x as u32;
        let py = state.point_y as u32;
        // Draw crosshair lines
        crate::graphics::fill_rect_alpha(px.saturating_sub(10), py.saturating_sub(1), 20, 2, 0x00FF0000, 180);
        crate::graphics::fill_rect_alpha(px.saturating_sub(1), py.saturating_sub(10), 2, 20, 0x00FF0000, 180);
        
        // Landmark dots
        for i in 0..state.landmark_count as usize {
            if i < 8 {
                let lx = state.landmarks[i][0] as u32;
                let ly = state.landmarks[i][1] as u32;
                if lx > 0 || ly > 0 {
                    crate::graphics::fill_rect_alpha(lx.saturating_sub(2), ly.saturating_sub(2), 5, 5, 0x0000FF00, 220);
                }
            }
        }
    }

    // 3. Draw Suggestion Bubble at the top
    let len = state.suggestion_len as usize;
    if len > 0 && len <= 128 {
        if let Ok(text) = core::str::from_utf8(&state.suggestion[..len]) {
            let text_width = (text.len() as u32) * 8;
            let bubble_w = text_width + 20;
            let bubble_h = 32;
            let bubble_x = (1024 - bubble_w) / 2;
            let bubble_y = 80;
            
            crate::graphics::fill_rect_alpha(bubble_x, bubble_y, bubble_w, bubble_h, 0x001A1A2E, 160);
            
            // Draw border lines
            crate::graphics::fill_rect_alpha(bubble_x, bubble_y, bubble_w, 1, 0x004E4FEB, 180);
            crate::graphics::fill_rect_alpha(bubble_x, bubble_y + bubble_h - 1, bubble_w, 1, 0x004E4FEB, 180);
            crate::graphics::fill_rect_alpha(bubble_x, bubble_y, 1, bubble_h, 0x004E4FEB, 180);
            crate::graphics::fill_rect_alpha(bubble_x + bubble_w - 1, bubble_y, 1, bubble_h, 0x004E4FEB, 180);
            
            crate::graphics::draw_string(bubble_x + 10, bubble_y + 8, text, 0x0000FFFF, 0x001A1A2E);
        }
    }
}

pub fn handle_mouse_down(mx: u32, my: u32) {
    // Check if clicked the Dock area
    // Dock is at dock_x to dock_x + dock_w.
    // dock_x = (fb_width - 400) / 2 = 312
    // dock_y = fb_height - 50 = 718
    if my >= 718 && my <= 758 && mx >= 312 && mx <= 712 {
        let mut state = COMPOSITOR.lock();
        let target = hit_test_taskbar(mx, my);
        state.pressed = target;
        state.needs_redraw = true;
        return;
    }

    // Call hit_test to find clicked window id
    let (clicked_win_id, _) = hit_test(mx, my);

    let mut state = COMPOSITOR.lock();
    let mut clicked_idx = None;
    if clicked_win_id != 0 {
        for (i, window) in state.windows.iter().enumerate() {
            if window.id == clicked_win_id {
                clicked_idx = Some(i);
                break;
            }
        }
    }

    if let Some(idx) = clicked_idx {
        // Move to front (make it top-most)
        let w = state.windows.remove(idx);
        let win_id = w.id;
        state.windows.push(w);
        let new_idx = state.windows.len() - 1;
        state.focused_idx = Some(new_idx);

        let win = &state.windows[new_idx];

        // Check if clicked the close button [X] (top right: x + width - 20 to x + width - 4)
        let is_close_btn = mx >= win.x + win.width - 20 && mx <= win.x + win.width - 4 &&
                            my >= win.y + 2 && my <= win.y + 18;

        if is_close_btn {
            let closed = state.windows.pop(); // Since we just pushed it to the end, pop removes it!
            if let Some(w) = closed {
                if let crate::gui::window::WindowType::App(_) = w.win_type {
                    crate::gui::app_window::on_window_closed(w.id);
                }
            }
            state.focused_idx = if !state.windows.is_empty() {
                Some(state.windows.len() - 1)
            } else {
                None
            };
            state.pressed = HoverTarget::None;
            state.needs_redraw = true;
            return;
        }

        // Check if clicked title bar for dragging
        let is_title_bar = win.is_title_bar(mx, my);
        let win_x = win.x;
        let win_y = win.y;
        let win_type = win.win_type;

        if is_title_bar {
            state.drag_active = true;
            state.drag_start_mx = mx;
            state.drag_start_my = my;
            state.drag_start_wx = win_x;
            state.drag_start_wy = win_y;
        } else if let crate::gui::window::WindowType::App(_) = win_type {
            // A click inside an app window's canvas (not the title bar or
            // close button): forward it as a window-relative mouse-down
            // event so the owning process can react to it.
            let rel_x = mx.saturating_sub(win_x + crate::gui::window::CHROME_SIDE);
            let rel_y = my.saturating_sub(win_y + crate::gui::window::CHROME_TOP);
            crate::gui::app_window::push_input(
                win_id,
                crate::gui::app_window::AppInputEvent { tag: 3, a: 0, b: 1, c: rel_x, d: rel_y },
            );
        }

        let _ = win_id; // suppress unused warning
        state.needs_redraw = true;
    } else {
        // Clicked desktop background
        state.focused_idx = None;
        state.pressed = HoverTarget::None;
    }
}

pub fn handle_mouse_move(mx: u32, my: u32) {
    let mut state = COMPOSITOR.lock();

    // Update hover state for visual feedback.
    let new_hover = if my >= 718 && my <= 758 && mx >= 312 && mx <= 712 {
        hit_test_taskbar(mx, my)
    } else {
        // Check if hovering the close button of the focused window.
        if let Some(idx) = state.focused_idx {
            if let Some(win) = state.windows.get(idx) {
                if mx >= win.x + win.width - 20 && mx <= win.x + win.width - 4
                    && my >= win.y + 2 && my <= win.y + 18
                {
                    HoverTarget::WindowClose(win.id)
                } else {
                    HoverTarget::None
                }
            } else {
                HoverTarget::None
            }
        } else {
            HoverTarget::None
        }
    };
    if new_hover != state.hover {
        state.hover = new_hover;
        state.needs_redraw = true;
    }

    if state.drag_active {
        if let Some(idx) = state.focused_idx {
            // Calculate delta
            let dx = mx as i32 - state.drag_start_mx as i32;
            let dy = my as i32 - state.drag_start_my as i32;

            // Update window position
            let start_wx = state.drag_start_wx;
            let start_wy = state.drag_start_wy;
            let win = &mut state.windows[idx];
            win.x = (start_wx as i32 + dx).max(0) as u32;
            win.y = (start_wy as i32 + dy).max(0) as u32;

            state.needs_redraw = true;
        }
    }
}

/// Hit-test the taskbar at `(mx, my)`. Returns the button
/// under the cursor, or `HoverTarget::None` if no button.
fn hit_test_taskbar(mx: u32, my: u32) -> HoverTarget {
    // Dock layout (must match `desktop::render_taskbar`):
    //   dock_x = 312, dock_y = 718, dock_w = 400, dock_h = 40
    if mx >= 327 && mx <= 427 && my >= 726 && my <= 750 {
        HoverTarget::TerminalButton
    } else if mx >= 437 && mx <= 537 && my >= 726 && my <= 750 {
        HoverTarget::SysMonButton
    } else if mx >= 547 && mx <= 647 && my >= 726 && my <= 750 {
        HoverTarget::JarvisButton
    } else {
        HoverTarget::None
    }
}

pub fn handle_mouse_up(mx: u32, my: u32) {
    let mut state = COMPOSITOR.lock();

    // If we were pressing a taskbar button, fire its action
    // when the mouse is released over it. This is how every
    // desktop dock works.
    if state.pressed != HoverTarget::None {
        let released_on = hit_test_taskbar(mx, my);
        let pressed = state.pressed;
        state.pressed = HoverTarget::None;

        if pressed == released_on {
            match pressed {
                HoverTarget::TerminalButton => {
                    drop(state);
                    spawn_terminal();
                    return;
                }
                HoverTarget::SysMonButton => {
                    drop(state);
                    spawn_sys_mon();
                    return;
                }
                HoverTarget::JarvisButton => {
                    drop(state);
                    spawn_agent_hud(false); // Assume false for now, window content holds true state
                    return;
                }
                HoverTarget::ExitButton => {
                    drop(state);
                    crate::gui::exit_desktop();
                    return;
                }
                _ => {}
            }
        }
        state.needs_redraw = true;
    }

    state.drag_active = false;
}

pub fn handle_key_press(ascii: u8) {
    let mut state = COMPOSITOR.lock();
    let focused_idx = state.focused_idx;

    if let Some(idx) = focused_idx {
        if idx < state.windows.len() {
            let win_type = state.windows[idx].win_type;
            
            if win_type == crate::gui::window::WindowType::Terminal {
                let win = &mut state.windows[idx];
                match ascii {
                    b'\n' => {
                        let command_trimmed = {
                            let content_str = core::str::from_utf8(&win.content).unwrap_or("");
                            let command = if let Some(last_prompt_idx) = content_str.rfind("FerrumOS:~$ ") {
                                &content_str[last_prompt_idx + 12..]
                            } else {
                                content_str
                            };
                            alloc::string::String::from(command.trim())
                        };

                        win.content.push(b'\n');

                        if command_trimmed == "exit" {
                            drop(state);
                            crate::gui::exit_desktop();
                            return;
                        }

                        if command_trimmed == "clear" {
                            win.content.clear();
                            win.content.extend_from_slice(b"FerrumOS:~$ ");
                            state.needs_redraw = true;
                            return;
                        }

                        if !command_trimmed.is_empty() {
                            drop(state);
                            *crate::gui::TERMINAL_REDIRECT.lock() = true;
                            crate::shell::commands::execute(&command_trimmed);
                            *crate::gui::TERMINAL_REDIRECT.lock() = false;
                            state = COMPOSITOR.lock();
                        }

                        if let Some(w) = state.windows.iter_mut().find(|w| w.win_type == crate::gui::window::WindowType::Terminal) {
                            if w.content.last() == Some(&b'\n') {
                                w.content.extend_from_slice(b"FerrumOS:~$ ");
                            } else {
                                w.content.extend_from_slice(b"\nFerrumOS:~$ ");
                            }
                        }
                        state.needs_redraw = true;
                    }
                    0x08 => {
                        if win.content.len() >= 12 {
                            let len = win.content.len();
                            let suffix = &win.content[len - 12..];
                            if suffix == b"FerrumOS:~$ " {
                                return;
                            }
                        }
                        if !win.content.is_empty() {
                            win.content.pop();
                            state.needs_redraw = true;
                        }
                    }
                    0x1B => {
                        let content_str = core::str::from_utf8(&win.content).unwrap_or("");
                        if let Some(last_prompt_idx) = content_str.rfind("FerrumOS:~$ ") {
                            win.content.truncate(last_prompt_idx + 12);
                            state.needs_redraw = true;
                        }
                    }
                    _ => {
                        if ascii.is_ascii_graphic() || ascii == b' ' {
                            win.content.push(ascii);
                            state.needs_redraw = true;
                        }
                    }
                }
            } else if win_type == crate::gui::window::WindowType::AgentHud {
                let win = &mut state.windows[idx];
                
                // If it's the Setup Screen
                let content_str = core::str::from_utf8(&win.content).unwrap_or("");
                let is_setup = content_str.starts_with("NEEDS_CONFIG_");
                if is_setup {
                    match ascii {
                        b'\n' => {
                            let text = win.input_buffer.clone();
                            win.input_buffer.clear();
                            
                            let content_str_again = core::str::from_utf8(&win.content).unwrap_or("");
                            let step = content_str_again.chars().nth(13).unwrap_or('0');
                            
                            match step {
                                '0' => {
                                    win.content[13] = b'1';
                                    let add = alloc::format!("PROV={}\n", text);
                                    win.content.extend_from_slice(add.as_bytes());
                                }
                                '1' => {
                                    win.content[13] = b'2';
                                    let add = alloc::format!("HOST={}\n", text);
                                    win.content.extend_from_slice(add.as_bytes());
                                }
                                '2' => {
                                    let add = alloc::format!("KEY={}\n", text);
                                    win.content.extend_from_slice(add.as_bytes());
                                    
                                    // Parse collected config
                                    let final_str = core::str::from_utf8(&win.content).unwrap_or("");
                                    let prov = final_str.lines().find(|l| l.starts_with("PROV=")).map(|l| &l[5..]).unwrap_or("ollama");
                                    let host = final_str.lines().find(|l| l.starts_with("HOST=")).map(|l| &l[5..]).unwrap_or("10.0.2.2:11434");
                                    let key = final_str.lines().find(|l| l.starts_with("KEY=")).map(|l| &l[4..]).unwrap_or("");
                                    
                                    let host_parts: alloc::vec::Vec<&str> = host.split(':').collect();
                                    let h = host_parts.get(0).unwrap_or(&"10.0.2.2");
                                    let p = host_parts.get(1).unwrap_or(&"11434");
                                    
                                    let config_json = alloc::format!(
                                        r#"{{ "provider": "{}", "api_host": "{}", "api_port": {}, "api_key": "{}", "model_name": "{}" }}"#,
                                        prov, h, p, key, if prov == "ollama" { "llama3" } else { "default" }
                                    );
                                    
                                    crate::fs::create_file("/disk/heliox/config.json", &config_json).ok();
                                    win.content.clear();
                                    win.content.extend_from_slice(b"Agent initialized. Ambient mode active.\n");
                                    
                                    // Send IPC wake up
                                    let _ = crate::ipc::send(crate::ipc::Message::new(
                                        0,
                                        crate::ipc::Endpoint::new("heliox", "default"),
                                        crate::ipc::MessageKind::Event,
                                        "ipc:send:*",
                                        b"CONFIG_UPDATED:",
                                    ).unwrap(), &alloc::vec![alloc::string::String::from("cap:system:all")]);
                                }
                                _ => {}
                            }
                            state.needs_redraw = true;
                            return;
                        }
                        0x08 => {
                            if !win.input_buffer.is_empty() {
                                win.input_buffer.pop();
                                state.needs_redraw = true;
                            }
                        }
                        _ => {
                            if ascii.is_ascii_graphic() || ascii == b' ' {
                                win.input_buffer.push(ascii as char);
                                state.needs_redraw = true;
                            }
                        }
                    }
                    return;
                }
                
                // Normal HUD Input
                match ascii {
                    b'\n' => {
                        let text = win.input_buffer.clone();
                        win.input_buffer.clear();
                        
                        let msg_str = alloc::format!("GOAL:{}", text);
                        if let Ok(msg) = crate::ipc::Message::new(
                            0,
                            crate::ipc::Endpoint::new("heliox", "default"),
                            crate::ipc::MessageKind::Event,
                            "ipc:send:*",
                            msg_str.as_bytes(),
                        ) {
                            let _ = crate::ipc::send(msg, &alloc::vec![alloc::string::String::from("cap:system:all")]);
                        }
                        
                        state.needs_redraw = true;
                    }
                    0x08 => {
                        if !win.input_buffer.is_empty() {
                            win.input_buffer.pop();
                            state.needs_redraw = true;
                        }
                    }
                    _ => {
                        if ascii.is_ascii_graphic() || ascii == b' ' {
                            win.input_buffer.push(ascii as char);
                            state.needs_redraw = true;
                        }
                    }
                }
            } else if let crate::gui::window::WindowType::App(_) = win_type {
                let window_id = state.windows[idx].id;
                crate::gui::app_window::push_input(
                    window_id,
                    crate::gui::app_window::AppInputEvent { tag: 0, a: ascii as u32, b: 0, c: 0, d: 0 },
                );
            }
        }
    }
}
