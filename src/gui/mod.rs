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
pub mod app_window;

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
    compositor::spawn_demo_windows();
    crate::serial_println!("[gui] Desktop Environment initialized");
}

const DESKTOP_STACK_SIZE: usize = 64 * 1024;

#[repr(C, align(16))]
struct DesktopStack([u8; DESKTOP_STACK_SIZE]);
static mut DESKTOP_STACK: DesktopStack = DesktopStack([0; DESKTOP_STACK_SIZE]);

/// Pid of the desktop's registered kernel task (see
/// `scheduler::register_kernel_task`). 0 means "never launched yet".
static DESKTOP_TASK_PID: core::sync::atomic::AtomicU64 = core::sync::atomic::AtomicU64::new(0);

fn desktop_stack_top() -> u64 {
    let base = &raw mut DESKTOP_STACK as u64;
    (base + DESKTOP_STACK_SIZE as u64) & !0xF
}

/// Enter the interactive GUI loop.
///
/// Dispatches into `desktop_entry` as a genuine scheduled kernel task
/// (see `scheduler::register_kernel_task`) rather than calling it as a
/// plain blocking function - a bare `loop { ...; hlt; }` running
/// directly here was found to completely starve every ring-3 task
/// (including `heliox-daemon`'s background ticking, and any freshly
/// Start-menu-launched app, which would register as Ready but never
/// get its first CPU cycle) for as long as the desktop stayed open.
/// The timer interrupt's preemption logic only ever acted when the
/// *interrupted* context was ring-3; registering this loop as a
/// kernel task and marking its own `hlt` point as a known-safe
/// preemption point (`enter_kernel_task_safepoint`, called from
/// `desktop_entry`) lets the same round-robin ring-3 tasks already
/// use also give this loop, and everything else, fair turns.
///
/// Never returns to the caller (mirrors `ring3`'s one-way dispatch) -
/// the shell's own loop resumes fresh later via
/// `scheduler::enter_kernel_return` once the desktop exits.
pub fn run_desktop() -> ! {
    let stack_top = desktop_stack_top();
    let pid = DESKTOP_TASK_PID.load(core::sync::atomic::Ordering::SeqCst);
    let pid = if pid == 0 {
        let id = crate::scheduler::register_kernel_task(
            "desktop",
            crate::scheduler::Priority::Normal,
            stack_top,
            desktop_entry as u64,
        );
        DESKTOP_TASK_PID.store(id, core::sync::atomic::Ordering::SeqCst);
        id
    } else {
        // Reopening after a previous session exited - reset to a
        // clean entry point rather than resuming whatever stale
        // mid-loop point it was last preempted at (see
        // `reset_kernel_task_entry`'s doc).
        crate::scheduler::reset_kernel_task_entry(pid, stack_top, desktop_entry as u64);
        pid
    };
    crate::scheduler::claim_kernel_task_for_run(pid);
    unsafe {
        crate::scheduler::resume_task(pid);
    }
}

/// The desktop kernel task's actual entry point - see `run_desktop`.
extern "C" fn desktop_entry() -> ! {
    {
        let mut state = GUI.lock();
        state.active = true;
    }

    // Initialize double buffering
    if let Some(fb) = FRAMEBUFFER.lock().as_mut() {
        fb.init_back_buffer();
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

    if let Some(fb) = FRAMEBUFFER.lock().as_ref() {
        fb.swap_buffers();
    }

    crate::serial_println!("[gui] Entered Desktop loop");
    crate::serial_println!("[gui] Initial desktop frame rendered");

    let mut last_update_ticks: u64 = 0;
    let my_pid = DESKTOP_TASK_PID.load(core::sync::atomic::Ordering::SeqCst);

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

        // 3. Render and Cursor Update
        let needs_redraw = compositor::COMPOSITOR.lock().needs_redraw;
        let (cursor_dirty, cursor_moved) = {
            let cursor = cursor::CURSOR.lock();
            let moved = cursor.x != cursor.old_x || cursor.y != cursor.old_y;
            (cursor.dirty, moved)
        };

        if needs_redraw {
            // Full compositor redraw: clears the cursor, so we must
            // redraw it on top afterwards.
            compositor::render();
            cursor::save_and_draw();
            cursor::CURSOR.lock().dirty = false;
            if let Some(fb) = FRAMEBUFFER.lock().as_ref() {
                fb.swap_buffers();
            }
        } else if cursor_dirty {
            // Screen wasn't wiped, but the cursor moved. Restore the
            // old position's pixels and draw the cursor at the new
            // position.
            cursor::restore_background();
            cursor::save_and_draw();
            cursor::CURSOR.lock().dirty = false;
            if let Some(fb) = FRAMEBUFFER.lock().as_ref() {
                fb.swap_buffers();
            }
        } else if cursor_moved {
            // Edge case: dirty flag wasn't set but position changed
            // (shouldn't happen, but be safe).
            cursor::save_and_draw();
            if let Some(fb) = FRAMEBUFFER.lock().as_ref() {
                fb.swap_buffers();
            }
        }

        // 4. Idle: mark this exact point as safe to preempt, then
        //    enable interrupts and halt until the next one fires.
        //    This keeps the loop at interrupt speed (~18.2 Hz for the
        //    PIT, faster for mouse/keyboard) instead of spinning at
        //    full CPU, AND - the actual fix - lets ring-3 tasks
        //    (heliox-daemon, spawned apps) actually run in between
        //    frames instead of being starved for the desktop's whole
        //    lifetime.
        crate::scheduler::enter_kernel_task_safepoint(my_pid);
        interrupts::enable_and_hlt();
        crate::scheduler::leave_kernel_task_safepoint();
    }

    // Free the back buffer
    if let Some(fb) = FRAMEBUFFER.lock().as_mut() {
        fb.free_back_buffer();
    }

    // Restore previous console text
    crate::graphics::redraw_console();
    crate::serial_println!("[gui] Exited Desktop loop");

    // Hand control back to a fresh shell prompt. This task's own
    // stack is abandoned here (see `enter_kernel_return`'s doc,
    // exactly the pattern already used when a user process dies) -
    // the next `desktop` command resets this same task to a clean
    // entry point rather than resuming from here.
    unsafe {
        crate::scheduler::enter_kernel_return();
    }
}
