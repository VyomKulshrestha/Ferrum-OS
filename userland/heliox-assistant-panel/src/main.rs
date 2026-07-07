// ============================================================================
// FerrumOS - Heliox Assistant Panel (real app-window replacement for the
// kernel-hardcoded WindowType::AgentHud)
// ============================================================================
// Two things AgentHud used to do in kernel code now happen here as an
// ordinary userland process on the D1 app-window framework:
//   1. First-run setup wizard (Local/Cloud -> which brain) - identical
//      phase state machine to the one that used to live in
//      src/gui/window.rs + src/gui/compositor.rs, just driving this app's
//      own canvas instead of the kernel's `graphics` module.
//   2. A real chat history: user turns typed here, agent turns delivered
//      over IPC from heliox-daemon's orchestrator (`emit_chat`, "CHAT:"
//      messages on the "assistant" service) - with a visible "thinking"
//      state and a visible error state, instead of a raw telemetry dump.
#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;
use core::panic::PanicInfo;
use ferrumgui::{Canvas, InputEvent};
use linked_list_allocator::LockedHeap;

#[global_allocator]
static ALLOCATOR: LockedHeap = LockedHeap::empty();

static mut HEAP: [u8; 2 * 1024 * 1024] = [0; 2 * 1024 * 1024];

const CANVAS_W: u32 = 480;
const CANVAS_H: u32 = 360;
const INPUT_H: u32 = 22;
const STATUS_H: u32 = 16;
const LINE_H: u32 = ferrumgui::font::FONT_HEIGHT as u32 + 3;

const CONFIG_PATH: &str = "/disk/heliox/config.json";
const MAX_CHARS_PER_LINE: usize = ((CANVAS_W - 16) / ferrumgui::font::FONT_WIDTH) as usize;

enum Mode {
    /// First-run wizard. The `char` mirrors the phase codes the old
    /// kernel-drawn wizard used: '0' local/cloud, 'L' which local brain,
    /// 'H' ollama host:port, 'C' which cloud provider, 'K' API key.
    Setup(char),
    Chat,
}

struct ChatLine {
    speaker: String,
    text: String,
}

struct State {
    mode: Mode,
    input: String,
    history: Vec<ChatLine>,
    thinking: bool,
    error: Option<String>,
    /// Provider chosen mid-way through the Cloud branch (phase 'C' -> 'K'),
    /// carried across the two steps the same way the old wizard stashed it
    /// in the window's content buffer.
    pending_provider: String,
}

impl State {
    fn new(needs_setup: bool) -> Self {
        State {
            mode: if needs_setup { Mode::Setup('0') } else { Mode::Chat },
            input: String::new(),
            history: Vec::new(),
            thinking: false,
            error: None,
            pending_provider: String::new(),
        }
    }
}

fn finish_setup(state: &mut State, provider: &str, host: &str, port: u16, api_key: &str, model_name: &str) {
    let config_json = format!(
        r#"{{ "provider": "{}", "api_host": "{}", "api_port": {}, "api_key": "{}", "model_name": "{}" }}"#,
        provider, host, port, api_key, model_name
    );
    ferrumgui::write_file(CONFIG_PATH, config_json.as_bytes());
    ferrumgui::ipc_send("heliox", b"CONFIG_UPDATED:");
    state.mode = Mode::Chat;
    state.history.push(ChatLine {
        speaker: String::from("System"),
        text: format!("Agent initialized. Ambient mode active. (provider: {})", provider),
    });
}

/// Advance the setup wizard on Enter. Mirrors the phase transitions that
/// used to live in compositor.rs's handle_key_press for WindowType::AgentHud.
fn handle_setup_enter(state: &mut State, phase: char) {
    let choice = state.input.trim().to_ascii_lowercase();
    state.input.clear();
    match phase {
        '0' if choice == "local" => state.mode = Mode::Setup('L'),
        '0' if choice == "cloud" => state.mode = Mode::Setup('C'),
        '0' => {}
        'L' if choice == "tiny" || choice == "local" => {
            finish_setup(state, "local", "unconfigured", 0, "", "default");
        }
        'L' if choice == "ollama" => state.mode = Mode::Setup('H'),
        'L' => {}
        'H' => {
            let parts: Vec<&str> = choice.split(':').collect();
            let host = parts.first().copied().unwrap_or("10.0.2.2");
            let port: u16 = parts.get(1).and_then(|s| s.parse().ok()).unwrap_or(11434);
            finish_setup(state, "ollama", host, port, "", "llama3");
        }
        'C' if choice == "openai" || choice == "claude" || choice == "gemini" => {
            state.pending_provider = choice;
            state.mode = Mode::Setup('K');
        }
        'C' => {}
        'K' => {
            let (host, port, model) = match state.pending_provider.as_str() {
                "claude" => ("api.anthropic.com", 443, "claude-3-haiku-20240307"),
                "gemini" => ("generativelanguage.googleapis.com", 443, "gemini-1.5-flash"),
                _ => ("api.openai.com", 443, "gpt-4o-mini"),
            };
            let provider = state.pending_provider.clone();
            // `choice` was already lowercased above, which would mangle an
            // API key's casing - re-read the original, untrimmed-case input.
            let api_key_raw = state.input.trim().to_string();
            finish_setup(state, &provider, host, port, &api_key_raw, model);
        }
        _ => {}
    }
}

fn wrap_text(text: &str, out: &mut Vec<String>) {
    let mut line = String::new();
    for word in text.split(' ') {
        if line.len() + word.len() + 1 > MAX_CHARS_PER_LINE {
            if !line.is_empty() {
                out.push(line.clone());
                line.clear();
            }
        }
        if !line.is_empty() {
            line.push(' ');
        }
        line.push_str(word);
        while line.len() > MAX_CHARS_PER_LINE {
            let (head, tail) = line.split_at(MAX_CHARS_PER_LINE);
            out.push(String::from(head));
            line = String::from(tail);
        }
    }
    out.push(line);
}

fn redraw(canvas: &mut Canvas, state: &State) {
    canvas.clear(0x0F, 0x11, 0x1A);

    match &state.mode {
        Mode::Setup(phase) => {
            canvas.draw_string(8, 8, "Heliox is your OS agent - always on.", 0xFF, 0xFF, 0xFF);
            canvas.draw_string(8, 22, "Choose the brain that powers it:", 0xFF, 0xFF, 0xFF);
            let (title, l1, l2): (&str, &str, &str) = match phase {
                '0' => ("Step 1: Local or Cloud?", "local  - on-device, works offline", "cloud  - OpenAI / Claude / Gemini"),
                'L' => ("Step 2: Which local brain?", "tiny    - built-in model, auto-sized", "ollama  - a local Ollama server"),
                'H' => ("Step 3: Ollama host:port", "(e.g. 10.0.2.2:11434)", ""),
                'C' => ("Step 2: Which cloud provider?", "openai / claude / gemini", ""),
                'K' => ("Step 3: API Key", "(from your provider's dashboard)", ""),
                _ => ("", "", ""),
            };
            canvas.draw_string(8, 42, title, 0x00, 0xCC, 0xFF);
            canvas.draw_string(8, 58, l1, 0xAA, 0xAA, 0xAA);
            if !l2.is_empty() {
                canvas.draw_string(8, 72, l2, 0xAA, 0xAA, 0xAA);
            }

            let input_y = CANVAS_H - INPUT_H;
            canvas.fill_rect(4, input_y, CANVAS_W - 8, INPUT_H - 2, 0x1A, 0x1A, 0x1A);
            canvas.draw_string(8, input_y + 4, ">", 0xFF, 0xFF, 0xFF);
            canvas.draw_string(24, input_y + 4, &state.input, 0xFF, 0xFF, 0xFF);
        }
        Mode::Chat => {
            // Status line
            let status_text = if let Some(err) = &state.error {
                format!("Error: {}", err)
            } else if state.thinking {
                String::from("Heliox is thinking...")
            } else {
                String::from("Heliox - ready")
            };
            let status_color = if state.error.is_some() {
                (0xFF, 0x66, 0x66)
            } else if state.thinking {
                (0xFF, 0xCC, 0x00)
            } else {
                (0x00, 0xFF, 0xCC)
            };
            canvas.fill_rect(0, 0, CANVAS_W, STATUS_H, 0x18, 0x1A, 0x22);
            canvas.draw_string(6, 2, &status_text, status_color.0, status_color.1, status_color.2);

            // Chat history, word-wrapped, bottom-anchored (most recent visible).
            let mut wrapped: Vec<(String, bool)> = Vec::new(); // (line, is_first_line_of_entry)
            for entry in &state.history {
                let mut lines = Vec::new();
                let full = format!("{}: {}", entry.speaker, entry.text);
                wrap_text(&full, &mut lines);
                for (i, l) in lines.into_iter().enumerate() {
                    wrapped.push((l, i == 0));
                }
                wrapped.push((String::new(), false)); // blank line between turns
            }
            let visible_rows = ((CANVAS_H - STATUS_H - INPUT_H - 8) / LINE_H) as usize;
            let start = wrapped.len().saturating_sub(visible_rows);
            let mut cy = STATUS_H + 6;
            for (line, is_header) in &wrapped[start..] {
                let color = if *is_header { (0x00, 0xFF, 0xCC) } else { (0xDD, 0xDD, 0xDD) };
                canvas.draw_string(8, cy, line, color.0, color.1, color.2);
                cy += LINE_H;
            }

            // Input box
            let input_y = CANVAS_H - INPUT_H;
            canvas.fill_rect(0, input_y, CANVAS_W, INPUT_H, 0x1A, 0x1A, 0x1A);
            canvas.draw_string(4, input_y + 4, ">", 0xFF, 0xFF, 0xFF);
            canvas.draw_string(20, input_y + 4, &state.input, 0xFF, 0xFF, 0xFF);
        }
    }
}

/// Parse one "CHAT:<role>:<state>:<content>" IPC message. Returns
/// (role, state, content) or None if malformed.
fn parse_chat_message(raw: &str) -> Option<(&str, &str, &str)> {
    let rest = raw.strip_prefix("CHAT:")?;
    let mut parts = rest.splitn(3, ':');
    let role = parts.next()?;
    let state = parts.next()?;
    let content = parts.next().unwrap_or("");
    Some((role, state, content))
}

#[no_mangle]
pub extern "C" fn _start() -> ! {
    unsafe {
        ALLOCATOR.lock().init(core::ptr::addr_of_mut!(HEAP) as *mut u8, HEAP.len());
    }

    ferrumgui::write_console("[heliox-assistant-panel] alive in ring 3\n");

    let needs_setup = ferrumgui::read_file(CONFIG_PATH, 4096).is_none();
    let mut state = State::new(needs_setup);
    if !needs_setup {
        state.history.push(ChatLine {
            speaker: String::from("System"),
            text: String::from("Ambient mode active. Type a message below."),
        });
    }

    let window_id = ferrumgui::create_window("Heliox Assistant", CANVAS_W, CANVAS_H);
    ferrumgui::write_console("[heliox-assistant-panel] window created id=");
    ferrumgui::write_int(window_id as i64);
    ferrumgui::write_console("\n");

    let mut canvas = Canvas::new(CANVAS_W, CANVAS_H);
    redraw(&mut canvas, &state);
    canvas.present(window_id);

    loop {
        let mut dirty = false;

        while let Some(InputEvent { tag, a, .. }) = ferrumgui::poll_window_input(window_id) {
            if tag != 0 {
                continue; // only keypresses matter for this app
            }
            let ascii = a as u8;
            match ascii {
                b'\n' | b'\r' => {
                    match state.mode {
                        Mode::Setup(phase) => handle_setup_enter(&mut state, phase),
                        Mode::Chat => {
                            let text = state.input.trim().to_string();
                            state.input.clear();
                            if !text.is_empty() {
                                state.history.push(ChatLine { speaker: String::from("You"), text: text.clone() });
                                let goal_msg = format!("GOAL:{}", text);
                                ferrumgui::ipc_send("heliox", goal_msg.as_bytes());
                                state.error = None;
                            }
                        }
                    }
                    dirty = true;
                }
                0x08 => {
                    if !state.input.is_empty() {
                        state.input.pop();
                        dirty = true;
                    }
                }
                _ if ascii.is_ascii_graphic() || ascii == b' ' => {
                    state.input.push(ascii as char);
                    dirty = true;
                }
                _ => {}
            }
        }

        // Drain every queued chat update from heliox-daemon this frame,
        // not just one - a single sleep(30) tick can outlast a burst of
        // thinking/done messages under load.
        while let Some(raw) = ferrumgui::ipc_receive("assistant", 4096) {
            if let Ok(text) = core::str::from_utf8(&raw) {
                if let Some((role, msg_state, content)) = parse_chat_message(text) {
                    match (role, msg_state) {
                        ("agent", "thinking") => {
                            state.thinking = true;
                            state.error = None;
                        }
                        ("agent", "done") => {
                            state.thinking = false;
                            if !content.is_empty() {
                                state.history.push(ChatLine { speaker: String::from("Heliox"), text: String::from(content) });
                            }
                        }
                        ("agent", "error") => {
                            state.thinking = false;
                            state.error = Some(String::from(content));
                        }
                        _ => {}
                    }
                    dirty = true;
                }
            }
        }

        if dirty {
            redraw(&mut canvas, &state);
            canvas.present(window_id);
        }

        ferrumgui::sleep(30);
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    ferrumgui::exit(1);
}
