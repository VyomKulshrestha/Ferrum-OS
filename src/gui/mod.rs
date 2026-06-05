// ============================================================================
// FerrumOS - Graphical Desktop Environment (GUI)
// ============================================================================
// An in-kernel, lightweight Window Manager and Desktop Environment.
// Provides a compositing loop, window management, mouse cursor rendering,
// and basic desktop elements (taskbar, background).
// ============================================================================

pub mod window;
pub mod compositor;
pub mod desktop;
pub mod cursor;

use spin::Mutex;
use crate::devices::vga_fb::FRAMEBUFFER;

/// Global GUI State
pub struct GuiState {
    pub active: bool,
}

lazy_static::lazy_static! {
    pub static ref GUI: Mutex<GuiState> = Mutex::new(GuiState {
        active: false,
    });
}

/// Global redirect flag for command output redirection to terminal window.
pub static TERMINAL_REDIRECT: Mutex<bool> = Mutex::new(false);

pub fn is_terminal_redirect_active() -> bool {
    *TERMINAL_REDIRECT.lock()
}

struct TerminalWriter;

impl core::fmt::Write for TerminalWriter {
    fn write_str(&mut self, s: &str) -> core::fmt::Result {
        let mut state = compositor::COMPOSITOR.lock();
        if let Some(win) = state.windows.iter_mut().find(|w| w.id == 2) {
            win.content.extend_from_slice(s.as_bytes());
            if win.content.len() > 8192 {
                let start_idx = win.content.len() - 8192;
                win.content = win.content[start_idx..].to_vec();
            }
            state.needs_redraw = true;
        }
        Ok(())
    }
}

pub fn write_to_terminal_window(args: core::fmt::Arguments) {
    use core::fmt::Write;
    let mut writer = TerminalWriter;
    let _ = writer.write_fmt(args);
}

pub fn is_active() -> bool {
    GUI.lock().active
}

pub fn exit_desktop() {
    let mut state = GUI.lock();
    state.active = false;
}

/// Initialize the GUI subsystem.
pub fn init() {
    compositor::init();
    desktop::init();
    cursor::init();
    crate::serial_println!("[gui] Desktop Environment initialized");
}

/// Enter the interactive GUI loop.
/// This hijacks the current thread and drops into a loop that composites
/// windows and handles mouse events.
pub fn run_desktop() {
    {
        let mut state = GUI.lock();
        state.active = true;
    }
    
    // Clear the screen for the desktop
    if let Some(fb) = FRAMEBUFFER.lock().as_ref() {
        fb.clear(desktop::COLOR_BACKGROUND);
    }
    
    // Start desktop rendering
    desktop::render_taskbar();
    
    // Setup a few demo windows
    compositor::spawn_demo_windows();

    // Paint the first full desktop frame immediately so `desktop` visibly
    // changes the screen even before the first input/timer-driven redraw.
    compositor::render();
    cursor::save_and_draw();
    cursor::CURSOR.lock().dirty = false;
    
    crate::serial_println!("[gui] Entered Desktop loop");
    crate::serial_println!("[gui] Initial desktop frame rendered");
    
    let mut last_update_ticks = 0;
    
    // Main GUI Event Loop
    loop {
        if !GUI.lock().active {
            break;
        }
        
        // 1. Process Input Events (Mouse, Keyboard)
        cursor::process_input();
        
        // 2. Update System Monitor periodically (every 20 ticks = ~400ms)
        let current_ticks = crate::scheduler::total_ticks();
        if current_ticks - last_update_ticks >= 20 {
            compositor::update_system_monitor();
            last_update_ticks = current_ticks;
        }
        
        let needs_redraw = compositor::COMPOSITOR.lock().needs_redraw;
        let cursor_dirty = cursor::CURSOR.lock().dirty;
        
        if needs_redraw {
            // Compositor is redrawing everything, no need to restore background.
            compositor::render();
            cursor::save_and_draw();
            cursor::CURSOR.lock().dirty = false;
        } else if cursor_dirty {
            // Screen wasn't wiped, but cursor moved. Restore and redraw.
            cursor::restore_background();
            cursor::save_and_draw();
            cursor::CURSOR.lock().dirty = false;
        }
        
        // Sleep or yield to scheduler
        crate::scheduler::yield_current();
    }
    
    // Restore previous console text
    crate::graphics::redraw_console();
    crate::serial_println!("[gui] Exited Desktop loop");
}
