extern crate alloc;

mod commands;

use alloc::string::{String, ToString};
use crate::{print, println};
use crate::interrupts;

const MAX_INPUT_LENGTH: usize = 256;

pub fn run() -> ! {
    interrupts::init_keyboard_queue();
    print_prompt();
    let mut input_buffer = String::with_capacity(MAX_INPUT_LENGTH);
    
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
        x86_64::instructions::hlt();
    }
}

fn print_prompt() {
    print!("FerrumOS:~$ ");
}
