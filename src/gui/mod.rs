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

use alloc::vec::Vec;
use spin::Mutex;
use crate::graphics;
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
    
    crate::serial_println!("[gui] Entered Desktop loop");
    
    // Main GUI Event Loop
    loop {
        if !GUI.lock().active {
            break;
        }
        
        // 1. Process Input Events (Mouse, Keyboard)
        cursor::process_input();
        
        // 2. Render Desktop Background (or dirty rects)
        // For MVP, we'll redraw full screen or partial to avoid flickering.
        compositor::render();
        
        // 3. Render Cursor Overlay
        cursor::render();
        
        // Sleep or yield to scheduler
        crate::scheduler::yield_current();
    }
    
    // Restore previous console text
    crate::graphics::redraw_console();
    crate::serial_println!("[gui] Exited Desktop loop");
}
