// ============================================================================
// FerrumOS - Unified Input Subsystem
// ============================================================================
// Central event queue and injection API for all input sources:
//   - PS/2 keyboard (via interrupt handler)
//   - USB HID keyboard / mouse (via `crate::devices::usb_hid`)
//   - Synthetic / agent-injected input (via syscall surface)
//
// Events are stored in a fixed-size ring buffer and consumed by the
// shell, graphics console, or future window manager through the
// polling API.
// ============================================================================

extern crate alloc;
#[allow(dead_code)]

use spin::Mutex;

// ============================================================================
// Input Event Types
// ============================================================================

/// Discriminated union of all input event kinds.
#[derive(Debug, Clone, Copy)]
pub enum InputEventType {
    /// A key was pressed. Payload is the ASCII code (0 = non-printable).
    KeyPress(u8),
    /// A key was released. Payload is the ASCII code.
    KeyRelease(u8),
    /// Relative mouse movement (dx, dy).
    MouseMove(i16, i16),
    /// Mouse button state change (button_id, pressed).
    MouseButton(u8, bool),
}

/// A single input event with a coarse timestamp.
#[derive(Debug, Clone, Copy)]
pub struct InputEvent {
    /// What happened.
    pub event_type: InputEventType,
    /// Monotonic tick count at the time the event was recorded.
    /// Sourced from the PIT tick counter when available.
    pub timestamp: u64,
}

// ============================================================================
// Event Queue — fixed-size ring buffer (256 entries)
// ============================================================================

const QUEUE_CAPACITY: usize = 256;

pub struct EventQueue {
    events: [Option<InputEvent>; QUEUE_CAPACITY],
    /// Index of the next event to read.
    head: usize,
    /// Index of the next free slot to write.
    tail: usize,
    /// Number of events currently buffered.
    count: usize,
}

impl EventQueue {
    /// Create an empty event queue. Usable in `const` context so we
    /// can initialise the global `EVENT_QUEUE` at compile time.
    const fn new() -> Self {
        // Use a manual array init because `Option<InputEvent>` does not
        // implement `Copy` in const context with complex inner types;
        // however `None` is trivially const.
        const NONE_EVENT: Option<InputEvent> = None;
        EventQueue {
            events: [NONE_EVENT; QUEUE_CAPACITY],
            head: 0,
            tail: 0,
            count: 0,
        }
    }

    /// Push an event into the queue. Returns `false` if the queue is
    /// full and the event was dropped.
    fn push(&mut self, event: InputEvent) -> bool {
        if self.count >= QUEUE_CAPACITY {
            // Queue full — drop the oldest event to make room so that
            // the most recent input is never lost.
            self.head = (self.head + 1) % QUEUE_CAPACITY;
            self.count -= 1;
        }
        self.events[self.tail] = Some(event);
        self.tail = (self.tail + 1) % QUEUE_CAPACITY;
        self.count += 1;
        true
    }

    /// Pop the oldest event from the queue.
    pub fn pop(&mut self) -> Option<InputEvent> {
        if self.count == 0 {
            return None;
        }
        let event = self.events[self.head].take();
        self.head = (self.head + 1) % QUEUE_CAPACITY;
        self.count -= 1;
        event
    }

    /// Number of events currently queued.
    fn len(&self) -> usize {
        self.count
    }

    /// Returns `true` if the queue contains no events.
    fn is_empty(&self) -> bool {
        self.count == 0
    }
}

/// Global event queue protected by a spinlock.
pub static EVENT_QUEUE: Mutex<EventQueue> = Mutex::new(EventQueue::new());
pub static DAEMON_EVENT_QUEUE: Mutex<EventQueue> = Mutex::new(EventQueue::new());

// ============================================================================
// Timestamp helper
// ============================================================================

/// Obtain a coarse monotonic timestamp. Uses the scheduler tick count
/// when the scheduler is initialised, otherwise returns 0.
fn now_ticks() -> u64 {
    // The scheduler exposes a tick counter incremented by the PIT
    // interrupt handler. Using it avoids a direct dependency on
    // hardware timers.
    crate::scheduler::total_ticks()
}

// ============================================================================
// Internal Event Injection (called by hardware drivers)
// ============================================================================

/// Inject a key press or release event.
///
/// Called by the USB HID keyboard driver (`crate::devices::usb_hid`)
/// and potentially by the PS/2 keyboard handler to funnel all key
/// events through a single queue.
///
/// If `pressed` is `true` and `ascii` is non-zero the keystroke is
/// also forwarded to the legacy keyboard queue so the interactive
/// shell can see it.
pub fn inject_key_event(ascii: u8, pressed: bool) {
    let event_type = if pressed {
        InputEventType::KeyPress(ascii)
    } else {
        InputEventType::KeyRelease(ascii)
    };

    let event = InputEvent {
        event_type,
        timestamp: now_ticks(),
    };

    EVENT_QUEUE.lock().push(event);
    DAEMON_EVENT_QUEUE.lock().push(event);

    // Bridge into the shell's keyboard buffer for pressed,
    // printable keys so that the existing shell input path works
    // without modification.
    if pressed && ascii != 0 {
        feed_to_shell(ascii);
    }
}

/// Inject mouse movement and button events.
///
/// Called by the USB HID mouse driver. Generates a `MouseMove` event
/// if displacement is non-zero and individual `MouseButton` events
/// for each of the three standard buttons.
pub fn inject_mouse_event(dx: i16, dy: i16, buttons: u8) {
    let ts = now_ticks();
    static PREV_BUTTONS: spin::Mutex<u8> = spin::Mutex::new(0);

    // Displacement event
    if dx != 0 || dy != 0 {
        let event = InputEvent {
            event_type: InputEventType::MouseMove(dx, dy),
            timestamp: ts,
        };
        EVENT_QUEUE.lock().push(event);
        DAEMON_EVENT_QUEUE.lock().push(event);
    }

    let mut prev = PREV_BUTTONS.lock();
    // Button events — only emit if button state changed
    for bit in 0u8..3 {
        let mask = 1 << bit;
        let pressed = buttons & mask != 0;
        let prev_pressed = *prev & mask != 0;
        
        if pressed != prev_pressed {
            let event = InputEvent {
                event_type: InputEventType::MouseButton(bit, pressed),
                timestamp: ts,
            };
            EVENT_QUEUE.lock().push(event);
            DAEMON_EVENT_QUEUE.lock().push(event);
        }
    }
    *prev = buttons;
}

// ============================================================================
// Agent-facing Input Injection (called from syscalls / agent runtime)
// ============================================================================

/// Inject a single key press followed by an immediate release.
///
/// Useful for synthetic / agent-generated keystrokes.
pub fn inject_key(ascii: u8) {
    inject_key_event(ascii, true);
    inject_key_event(ascii, false);
}

/// Inject an entire string as a sequence of key press+release events.
///
/// Each byte of the UTF-8 string is injected individually. Non-ASCII
/// bytes are silently forwarded (the consumer can ignore them).
pub fn inject_string(s: &str) {
    for byte in s.bytes() {
        inject_key(byte);
    }
}

/// Inject a relative mouse movement event.
pub fn inject_mouse_move(dx: i16, dy: i16) {
    let event = InputEvent {
        event_type: InputEventType::MouseMove(dx, dy),
        timestamp: now_ticks(),
    };
    EVENT_QUEUE.lock().push(event);
}

/// Inject a mouse button click (press + release).
pub fn inject_mouse_click(button: u8) {
    let ts = now_ticks();

    let press = InputEvent {
        event_type: InputEventType::MouseButton(button, true),
        timestamp: ts,
    };
    let release = InputEvent {
        event_type: InputEventType::MouseButton(button, false),
        timestamp: ts,
    };

    let mut queue = EVENT_QUEUE.lock();
    queue.push(press);
    queue.push(release);
}

// ============================================================================
// Event Polling (for consumers)
// ============================================================================

/// Drain up to `buf.len()` events from the queue into `buf`.
///
/// Returns the number of events actually written. The events are
/// returned in FIFO order (oldest first).
pub fn poll_events(buf: &mut [InputEvent]) -> usize {
    let mut queue = EVENT_QUEUE.lock();
    let mut count = 0;
    for slot in buf.iter_mut() {
        match queue.pop() {
            Some(ev) => {
                *slot = ev;
                count += 1;
            }
            None => break,
        }
    }
    count
}

/// Returns the number of events currently waiting in the queue.
pub fn pending_count() -> usize {
    EVENT_QUEUE.lock().len()
}

/// Returns `true` if the event queue is empty.
pub fn is_empty() -> bool {
    EVENT_QUEUE.lock().is_empty()
}

// ============================================================================
// Shell Bridge
// ============================================================================

/// Forward a synthetic keystroke into the legacy keyboard queue so
/// the interactive shell sees injected keys.
///
/// Calls `crate::interrupts::push_keyboard()` which pushes the ASCII
/// byte into the same VecDeque that the PS/2 keyboard interrupt
/// handler uses. The shell's `read_keyboard()` poll loop then picks
/// it up seamlessly.
fn feed_to_shell(ascii: u8) {
    crate::interrupts::push_keyboard(ascii);
}
