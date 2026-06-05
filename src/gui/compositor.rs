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

pub fn init() {
    // Nothing to do for MVP init, structures are lazy_static
}

pub fn spawn_demo_windows() {
    let mut state = COMPOSITOR.lock();
    state.windows.clear();
    
    let mut w1 = Window::new(1, "SYSTEM MONITOR", 100, 100, 300, 200, 0x001E1E1E);
    w1.content.extend_from_slice(b"CPU Usage: 14%\nMemory: 256MB / 4096MB\nTasks: 5 Active\n\n[Graph Placeholder]");
    
    let mut w2 = Window::new(2, "TERMINAL", 450, 150, 400, 300, 0x001A1A1A);
    w2.content.extend_from_slice(b"FerrumOS:~$ echo hello\nhello\nFerrumOS:~$ _");
    
    state.windows.push(w1);
    state.windows.push(w2);
    state.focused_idx = Some(1);
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
        
        // Check if clicked title bar for dragging
        let is_title_bar = state.windows[new_idx].is_title_bar(mx, my);
        let win_x = state.windows[new_idx].x;
        let win_y = state.windows[new_idx].y;
        
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
