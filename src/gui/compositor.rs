// ============================================================================
// FerrumOS - GUI Compositor
// ============================================================================

use alloc::vec::Vec;
use spin::Mutex;
use crate::gui::window::Window;
use crate::gui::desktop;

pub struct CompositorState {
    pub windows: Vec<Window>,
    pub focused_idx: Option<usize>,
    pub drag_active: bool,
    pub drag_start_mx: u32,
    pub drag_start_my: u32,
    pub drag_start_wx: u32,
    pub drag_start_wy: u32,
    pub needs_redraw: bool,
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
        let mut w2 = Window::new(2, "TERMINAL", 450, 150, 400, 300, 0x001A1A1A);
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
        let mut w1 = Window::new(1, "SYSTEM MONITOR", 100, 100, 300, 200, 0x001E1E1E);
        w1.content.extend_from_slice(b"CPU Usage: 0%\nMemory: 0MB / 0MB\nTasks: 0 Active\n\n  --- CPU Load History ---");
        state.windows.push(w1);
        state.focused_idx = Some(state.windows.len() - 1);
    }
    state.needs_redraw = true;
}

pub fn init() {
    // Nothing to do for MVP init, structures are lazy_static
}

pub fn spawn_demo_windows() {
    let mut state = COMPOSITOR.lock();
    state.windows.clear();
    
    let mut w1 = Window::new(1, "SYSTEM MONITOR", 100, 100, 300, 200, 0x001E1E1E);
    w1.content.extend_from_slice(b"CPU Usage: 14%\nMemory: 256MB / 4096MB\nTasks: 5 Active\n\n[Graph Placeholder]");
    
    let mut w2 = Window::new(2, "TERMINAL", 450, 150, 400, 300, 0x001A1A1A);
    w2.content.extend_from_slice(b"FerrumOS:~$ ");
    
    state.windows.push(w1);
    state.windows.push(w2);
    state.focused_idx = Some(1); // Focus the terminal window by default
    state.needs_redraw = true;
}

pub fn render() {
    let mut state = COMPOSITOR.lock();
    if !state.needs_redraw {
        return;
    }
    
    // 1. Clear to Desktop Background
    desktop::render_background();
    
    // 2. Draw Windows from back to front
    for (i, window) in state.windows.iter().enumerate() {
        let focused = state.focused_idx == Some(i);
        window.render(focused);
    }
    
    // 3. Draw Taskbar
    desktop::render_taskbar();
    
    state.needs_redraw = false;
}

pub fn handle_mouse_down(mx: u32, my: u32) {
    let mut state = COMPOSITOR.lock();
    
    // Check if clicked the Dock area
    // Dock is at dock_x to dock_x + dock_w.
    // dock_x = (fb_width - 400) / 2 = 312
    // dock_y = fb_height - 50 = 718
    if my >= 718 && my <= 758 && mx >= 312 && mx <= 712 {
        drop(state);
        if mx >= 327 && mx <= 427 {
            spawn_terminal();
        } else if mx >= 442 && mx <= 542 {
            spawn_sys_mon();
        } else if mx >= 557 && mx <= 617 {
            crate::gui::exit_desktop();
        }
        return;
    }
    
    // Find window that was clicked (top-most first, which is end of array)
    let mut clicked_idx = None;
    for (i, window) in state.windows.iter().enumerate().rev() {
        if window.contains_point(mx, my) {
            clicked_idx = Some(i);
            break;
        }
    }
    
    if let Some(idx) = clicked_idx {
        // Move to front (make it top-most)
        let w = state.windows.remove(idx);
        state.windows.push(w);
        let new_idx = state.windows.len() - 1;
        state.focused_idx = Some(new_idx);
        
        let win = &state.windows[new_idx];
        
        // Check if clicked the close button [X] (top right: x + width - 20 to x + width - 4)
        let is_close_btn = mx >= win.x + win.width - 20 && mx <= win.x + win.width - 4 &&
                            my >= win.y + 2 && my <= win.y + 18;
        
        if is_close_btn {
            state.windows.pop(); // Since we just pushed it to the end, pop removes it!
            state.focused_idx = if !state.windows.is_empty() {
                Some(state.windows.len() - 1)
            } else {
                None
            };
            state.needs_redraw = true;
            return;
        }
        
        // Check if clicked title bar for dragging
        let is_title_bar = win.is_title_bar(mx, my);
        let win_x = win.x;
        let win_y = win.y;
        
        if is_title_bar {
            state.drag_active = true;
            state.drag_start_mx = mx;
            state.drag_start_my = my;
            state.drag_start_wx = win_x;
            state.drag_start_wy = win_y;
        }
        
        state.needs_redraw = true;
    } else {
        // Clicked desktop background
        state.focused_idx = None;
    }
}

pub fn handle_mouse_move(mx: u32, my: u32) {
    let mut state = COMPOSITOR.lock();
    
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
    } else {
        // Do not trigger a full redraw! Cursor rendering handles its own save/restore.
    }
}

pub fn handle_mouse_up() {
    let mut state = COMPOSITOR.lock();
    state.drag_active = false;
}

pub fn handle_key_press(ascii: u8) {
    let mut state = COMPOSITOR.lock();
    let focused_idx = state.focused_idx;
    
    if let Some(idx) = focused_idx {
        if idx < state.windows.len() && state.windows[idx].id == 2 {
            let win = &mut state.windows[idx];
            match ascii {
                b'\n' => {
                    // 1. Extract command after the last prompt into an owned String
                    let command_trimmed = {
                        let content_str = match core::str::from_utf8(&win.content) {
                            Ok(s) => s,
                            Err(_) => "",
                        };
                        
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
                        // Drop lock to prevent deadlocking when commands write to stdout
                        drop(state);
                        
                        // Set redirect active
                        *crate::gui::TERMINAL_REDIRECT.lock() = true;
                        
                        // Execute command
                        crate::shell::commands::execute(&command_trimmed);
                        
                        // Clear redirect
                        *crate::gui::TERMINAL_REDIRECT.lock() = false;
                        
                        // Re-acquire lock
                        state = COMPOSITOR.lock();
                    }
                    
                    // Re-fetch window pointer to be safe
                    if let Some(w) = state.windows.iter_mut().find(|w| w.id == 2) {
                        if w.content.last() == Some(&b'\n') {
                            w.content.extend_from_slice(b"FerrumOS:~$ ");
                        } else {
                            w.content.extend_from_slice(b"\nFerrumOS:~$ ");
                        }
                    }
                    state.needs_redraw = true;
                }
                0x08 => {
                    // Backspace - check if we are deleting prompt
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
                    // Escape - clear input line
                    let content_str = match core::str::from_utf8(&win.content) {
                        Ok(s) => s,
                        Err(_) => "",
                    };
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
        }
    }
}
