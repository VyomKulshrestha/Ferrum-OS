// ============================================================================
// FerrumOS - Desktop Notification Service
// ============================================================================
// A bounded kernel broker gives isolated applications one shared notification
// history without giving them access to each other's memory or GUI windows.
// The compositor consumes snapshots only, so rendering never holds this lock.
// ============================================================================

extern crate alloc;

use alloc::collections::VecDeque;
use alloc::string::String;
use alloc::vec::Vec;
use spin::Mutex;

pub const MAX_NOTIFICATIONS: usize = 32;
pub const MAX_TITLE_BYTES: usize = 48;
pub const MAX_BODY_BYTES: usize = 160;
pub const MAX_LIST_BYTES: usize = 16 * 1024;

#[derive(Clone)]
pub struct Notification {
    pub id: u64,
    pub source_pid: u64,
    pub created_ticks: u64,
    pub title: String,
    pub body: String,
}

struct NotificationState {
    entries: VecDeque<Notification>,
    next_id: u64,
}

static NOTIFICATIONS: Mutex<NotificationState> = Mutex::new(NotificationState {
    entries: VecDeque::new(),
    next_id: 1,
});

pub fn init() {
    let mut state = NOTIFICATIONS.lock();
    state.entries.clear();
    state.next_id = 1;
}

fn clean_field(value: &str) -> String {
    value
        .chars()
        .map(|ch| if ch == '|' || ch == '\n' || ch == '\r' { ' ' } else { ch })
        .collect()
}

pub fn post(source_pid: u64, title: &str, body: &str) -> Result<u64, &'static str> {
    if title.is_empty() || title.len() > MAX_TITLE_BYTES || body.len() > MAX_BODY_BYTES {
        return Err("invalid notification size");
    }

    let created_ticks = crate::scheduler::SCHEDULER.lock().total_ticks;
    let mut state = NOTIFICATIONS.lock();
    let id = state.next_id;
    state.next_id = state.next_id.saturating_add(1);
    if state.entries.len() == MAX_NOTIFICATIONS {
        state.entries.pop_front();
    }
    state.entries.push_back(Notification {
        id,
        source_pid,
        created_ticks,
        title: clean_field(title),
        body: clean_field(body),
    });
    crate::serial_println!("[notification] posted id={} pid={} title={}", id, source_pid, title);
    Ok(id)
}

pub fn newest() -> Option<Notification> {
    NOTIFICATIONS.lock().entries.back().cloned()
}

pub fn list() -> Vec<Notification> {
    NOTIFICATIONS.lock().entries.iter().rev().cloned().collect()
}

pub fn dismiss(id: u64) -> usize {
    let mut state = NOTIFICATIONS.lock();
    let before = state.entries.len();
    if id == 0 {
        state.entries.clear();
    } else {
        state.entries.retain(|entry| entry.id != id);
    }
    before.saturating_sub(state.entries.len())
}

pub fn serialize() -> Vec<u8> {
    let mut output = String::new();
    for entry in list() {
        let line = alloc::format!(
            "{}|{}|{}|{}|{}\n",
            entry.id, entry.source_pid, entry.created_ticks, entry.title, entry.body
        );
        if output.len() + line.len() > MAX_LIST_BYTES {
            break;
        }
        output.push_str(&line);
    }
    output.as_bytes().to_vec()
}
