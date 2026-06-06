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
use x86_64::instructions::interrupts;

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
/// windows and handles mouse events. The loop idles via `sti; hlt` so
/// it wakes on every interrupt (timer, mouse, keyboard) instead of
/// spinning at full CPU.
pub fn run_desktop() {
    {
        let mut state = GUI.lock();
        state.active = true;
    }

    // Clear the screen for the desktop
    if let Some(fb) = FRAMEBUFFER.lock().as_ref() {
        fb.clear(desktop::COLOR_BACKGROUND);
    }

    // Setup a few demo windows
    compositor::spawn_demo_windows();

    // Paint the first full desktop frame and draw the cursor on top.
    // The cursor is drawn AFTER the compositor so it always sits on
    // top of windows / taskbar.
    compositor::render();
    cursor::save_and_draw();
    cursor::CURSOR.lock().dirty = false;

    crate::serial_println!("[gui] Entered Desktop loop");
    crate::serial_println!("[gui] Initial desktop frame rendered");

    let mut last_update_ticks: u64 = 0;

    // Main GUI Event Loop
    loop {
        if !GUI.lock().active {
            break;
        }

        // 1. Process Input Events (Mouse, Keyboard). This may set
        //    `cursor.dirty` and/or `compositor.needs_redraw`.
        cursor::process_input();

        // 2. Update System Monitor periodically (every 20 ticks = ~400ms).
        let current_ticks = crate::scheduler::total_ticks();
        if current_ticks.wrapping_sub(last_update_ticks) >= 20 {
            compositor::update_system_monitor();
            last_update_ticks = current_ticks;
        }

        let needs_redraw = compositor::COMPOSITOR.lock().needs_redraw;
        let cursor_dirty = cursor::CURSOR.lock().dirty;
        let cursor_moved = cursor::CURSOR.lock().x != cursor::CURSOR.lock().old_x
            || cursor::CURSOR.lock().y != cursor::CURSOR.lock().old_y;

        if needs_redraw {
            // Full compositor redraw: clears the cursor, so we must
            // redraw it on top afterwards.
            compositor::render();
            cursor::save_and_draw();
            cursor::CURSOR.lock().dirty = false;
        } else if cursor_dirty {
            // Screen wasn't wiped, but the cursor moved. Restore the
            // old position's pixels and draw the cursor at the new
            // position.
            cursor::restore_background();
            cursor::save_and_draw();
            cursor::CURSOR.lock().dirty = false;
        } else if cursor_moved {
            // Edge case: dirty flag wasn't set but position changed
            // (shouldn't happen, but be safe).
            cursor::save_and_draw();
        }

        // 4. Poll IPC for TELEMETRY from the agent
        if let Ok(msg) = crate::ipc::receive_for_service("gui") {
            if let Ok(text) = core::str::from_utf8(msg.payload()) {
                if let Some(telemetry_str) = text.strip_prefix("TELEMETRY:") {
                    let mut state = compositor::COMPOSITOR.lock();
                    if let Some(win) = state.windows.iter_mut().find(|w| w.win_type == window::WindowType::AgentHud) {
                        let formatted = alloc::format!("{}\n", telemetry_str);
                        win.content.extend_from_slice(formatted.as_bytes());
                        // Limit buffer size
                        if win.content.len() > 8192 {
                            let start_idx = win.content.len() - 8192;
                            win.content = win.content[start_idx..].to_vec();
                        }
                        state.needs_redraw = true;
                    }
                }
            }
        }

        // 5. Idle: enable interrupts and halt the CPU until the next
        //    interrupt fires. This keeps the GUI loop at interrupt
        //    speed (~18.2 Hz for the PIT, faster for mouse/keyboard)
        //    instead of spinning at full CPU. Without this the loop
        //    runs millions of times per second and the cursor
        //    save/restore thrashes.
        interrupts::enable_and_hlt();
    }

    // Restore previous console text
    crate::graphics::redraw_console();
    crate::serial_println!("[gui] Exited Desktop loop");
}
