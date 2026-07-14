extern crate alloc;

pub mod commands;
pub mod dashboard;

use alloc::string::{String, ToString};
use core::sync::atomic::{AtomicU64, Ordering};
use crate::{print, println};
use crate::interrupts;

const MAX_INPUT_LENGTH: usize = 256;

const SHELL_STACK_SIZE: usize = 64 * 1024;

#[repr(C, align(16))]
struct ShellStack([u8; SHELL_STACK_SIZE]);
static mut SHELL_STACK: ShellStack = ShellStack([0; SHELL_STACK_SIZE]);

/// Pid of the shell's registered kernel task (see
/// `scheduler::register_kernel_task`). 0 until `run()`'s first call.
static SHELL_TASK_PID: AtomicU64 = AtomicU64::new(0);

fn shell_stack_top() -> u64 {
    let base = &raw mut SHELL_STACK as u64;
    (base + SHELL_STACK_SIZE as u64) & !0xF
}

/// Entered once at boot (`main.rs`) and, if every ring-3 process later
/// exits, again via `scheduler::enter_kernel_return`'s fallback.
///
/// Dispatches the interactive shell as a genuine scheduled kernel task
/// (see `scheduler::register_kernel_task`) instead of calling
/// `shell_entry` as a bare blocking loop. A plain `loop { ...; hlt; }`
/// here - which is what this used to be - meant `ring3 init` (and
/// `pkg run`, via `process::enter_registered`) permanently abandoned the
/// shell prompt one-way to give a freshly dispatched ring-3 process its
/// first CPU cycle (see `gui::run_desktop`'s doc for the full story of
/// this class of bug, first found and fixed for the desktop). Now that
/// the shell participates in the same round-robin as everything else,
/// `enter_registered` no longer needs to abandon it either - the shell
/// and any agent it starts genuinely coexist.
pub fn run() -> ! {
    let stack_top = shell_stack_top();
    let pid = SHELL_TASK_PID.load(Ordering::SeqCst);
    let pid = if pid == 0 {
        // `Normal`, matching heliox-daemon/init's own priority - NOT
        // `High`. `schedule_next` always picks from the highest
        // non-empty priority queue first; a High-priority shell that
        // re-queues itself into that same queue every time it's
        // preempted would permanently outrank and starve every
        // Normal-priority ring-3 task, the exact opposite of the
        // coexistence this is meant to enable (found via direct testing:
        // heliox-daemon never got a single CPU cycle with this at High).
        let id = crate::scheduler::register_kernel_task(
            "shell",
            crate::scheduler::Priority::Normal,
            stack_top,
            shell_entry as u64,
        );
        SHELL_TASK_PID.store(id, Ordering::SeqCst);
        id
    } else {
        pid
    };
    crate::scheduler::claim_kernel_task_for_run(pid);
    unsafe {
        crate::scheduler::resume_task(pid);
    }
}

/// The shell kernel task's actual entry point - see `run`. Unlike
/// `gui::desktop_entry`, this never gets a "reset to a clean entry
/// point" reopen: the shell has exactly one continuous lifetime for the
/// life of the OS, so `input_buffer` (and everything else here) safely
/// persists on this task's own dedicated stack across every
/// suspend/resume cycle, the same way any other preemptible task's
/// locals do.
extern "C" fn shell_entry() -> ! {
    interrupts::init_keyboard_queue();
    print_prompt();
    let mut input_buffer = String::with_capacity(MAX_INPUT_LENGTH);
    let my_pid = SHELL_TASK_PID.load(Ordering::SeqCst);

    loop {
        if let Some(ch) = interrupts::read_keyboard() {
            match ch {
                b'\n' => {
                    println!();
                    let command = input_buffer.trim().to_string();
                    match command.as_str() {
                        "shutdown" => {
                            crate::println!("Shutting down the system...");
                            crate::acpi::shutdown();
                        }
                        "reboot" => {
                            crate::println!("Rebooting the system...");
                            crate::acpi::reboot();
                        }
                        _ => {
                            if !command.is_empty() {
                                commands::execute(&command);
                            }
                        }
                    }
                    input_buffer.clear();
                    print_prompt();
                }
                0x08 => {
                    if !input_buffer.is_empty() {
                        input_buffer.pop();
                        crate::vga::WRITER.lock().backspace();
                    }
                }
                0x1B => {
                    input_buffer.clear();
                    println!();
                    print_prompt();
                }
                _ => {
                    if input_buffer.len() < MAX_INPUT_LENGTH {
                        input_buffer.push(ch as char);
                        print!("{}", ch as char);
                    }
                }
            }
        }
        crate::scheduler::enter_kernel_task_safepoint(my_pid);
        x86_64::instructions::interrupts::enable_and_hlt();
        crate::scheduler::leave_kernel_task_safepoint();
    }
}

fn print_prompt() {
    print!("FerrumOS:~$ ");
}
