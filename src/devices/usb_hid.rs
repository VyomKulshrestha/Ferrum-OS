// ============================================================================
// FerrumOS - USB HID Class Driver
// ============================================================================
// Parses USB HID boot protocol reports for keyboard and mouse devices.
//
// USB HID boot protocol defines fixed-format reports:
//   - Keyboard: 8 bytes (modifier, reserved, keycodes[6])
//   - Mouse:    3-4 bytes (buttons, x_displacement, y_displacement)
//
// This driver converts raw HID reports into input events and forwards
// them to the unified input subsystem (`crate::input`).
// ============================================================================

extern crate alloc;
#[allow(dead_code)]

// ============================================================================
// USB HID Constants
// ============================================================================

/// USB HID class code
pub const USB_HID_CLASS: u8 = 0x03;

/// Boot interface subclass
pub const USB_HID_SUBCLASS_BOOT: u8 = 0x01;

/// Protocol code: keyboard
pub const USB_HID_PROTOCOL_KEYBOARD: u8 = 0x01;

/// Protocol code: mouse
pub const USB_HID_PROTOCOL_MOUSE: u8 = 0x02;

/// Boot protocol keyboard report length (bytes)
pub const KEYBOARD_REPORT_LEN: usize = 8;

/// Minimum boot protocol mouse report length (bytes)
pub const MOUSE_REPORT_MIN_LEN: usize = 3;

// ============================================================================
// Modifier Key Bit Flags
// ============================================================================

pub const MOD_LEFT_CTRL: u8 = 1 << 0;
pub const MOD_LEFT_SHIFT: u8 = 1 << 1;
pub const MOD_LEFT_ALT: u8 = 1 << 2;
pub const MOD_LEFT_GUI: u8 = 1 << 3;
pub const MOD_RIGHT_CTRL: u8 = 1 << 4;
pub const MOD_RIGHT_SHIFT: u8 = 1 << 5;
pub const MOD_RIGHT_ALT: u8 = 1 << 6;
pub const MOD_RIGHT_GUI: u8 = 1 << 7;

// ============================================================================
// HID Usage Code → ASCII Mapping (unshifted)
// ============================================================================
//
// Index = HID usage code. Value = ASCII character (0 = unmapped).
//
// 0x04–0x1D : a–z
// 0x1E–0x27 : 1–9, 0
// 0x28       : Enter  (0x0A)
// 0x29       : Escape (0x1B)
// 0x2A       : Backspace (0x08)
// 0x2B       : Tab    (0x09)
// 0x2C       : Space  (0x20)
// 0x2D–0x38 : - = [ ] \ ; ' , . / `
// 0x39       : CapsLock (0)
// 0x3A–0x45 : F1–F12  (0)

pub const HID_TO_ASCII: [u8; 128] = {
    let mut t = [0u8; 128];

    // Letters a-z: usage 0x04 – 0x1D
    t[0x04] = b'a'; t[0x05] = b'b'; t[0x06] = b'c'; t[0x07] = b'd';
    t[0x08] = b'e'; t[0x09] = b'f'; t[0x0A] = b'g'; t[0x0B] = b'h';
    t[0x0C] = b'i'; t[0x0D] = b'j'; t[0x0E] = b'k'; t[0x0F] = b'l';
    t[0x10] = b'm'; t[0x11] = b'n'; t[0x12] = b'o'; t[0x13] = b'p';
    t[0x14] = b'q'; t[0x15] = b'r'; t[0x16] = b's'; t[0x17] = b't';
    t[0x18] = b'u'; t[0x19] = b'v'; t[0x1A] = b'w'; t[0x1B] = b'x';
    t[0x1C] = b'y'; t[0x1D] = b'z';

    // Digits 1-9, 0: usage 0x1E – 0x27
    t[0x1E] = b'1'; t[0x1F] = b'2'; t[0x20] = b'3'; t[0x21] = b'4';
    t[0x22] = b'5'; t[0x23] = b'6'; t[0x24] = b'7'; t[0x25] = b'8';
    t[0x26] = b'9'; t[0x27] = b'0';

    // Control keys
    t[0x28] = 0x0A; // Enter
    t[0x29] = 0x1B; // Escape
    t[0x2A] = 0x08; // Backspace
    t[0x2B] = 0x09; // Tab
    t[0x2C] = 0x20; // Space

    // Symbols
    t[0x2D] = b'-';  // Hyphen
    t[0x2E] = b'=';  // Equals
    t[0x2F] = b'[';  // Left bracket
    t[0x30] = b']';  // Right bracket
    t[0x31] = b'\\'; // Backslash
    // 0x32 = non-US # (skip)
    t[0x33] = b';';  // Semicolon
    t[0x34] = b'\''; // Apostrophe
    t[0x35] = b'`';  // Grave accent
    t[0x36] = b',';  // Comma
    t[0x37] = b'.';  // Period
    t[0x38] = b'/';  // Forward slash

    // 0x39 = CapsLock, 0x3A–0x45 = F1–F12 → all 0 (already zero)

    t
};

// ============================================================================
// HID Usage Code → ASCII Mapping (shifted)
// ============================================================================

pub const HID_TO_ASCII_SHIFTED: [u8; 128] = {
    let mut t = [0u8; 128];

    // Shifted letters A-Z: usage 0x04 – 0x1D
    t[0x04] = b'A'; t[0x05] = b'B'; t[0x06] = b'C'; t[0x07] = b'D';
    t[0x08] = b'E'; t[0x09] = b'F'; t[0x0A] = b'G'; t[0x0B] = b'H';
    t[0x0C] = b'I'; t[0x0D] = b'J'; t[0x0E] = b'K'; t[0x0F] = b'L';
    t[0x10] = b'M'; t[0x11] = b'N'; t[0x12] = b'O'; t[0x13] = b'P';
    t[0x14] = b'Q'; t[0x15] = b'R'; t[0x16] = b'S'; t[0x17] = b'T';
    t[0x18] = b'U'; t[0x19] = b'V'; t[0x1A] = b'W'; t[0x1B] = b'X';
    t[0x1C] = b'Y'; t[0x1D] = b'Z';

    // Shifted digits → symbols
    t[0x1E] = b'!'; // Shift+1
    t[0x1F] = b'@'; // Shift+2
    t[0x20] = b'#'; // Shift+3
    t[0x21] = b'$'; // Shift+4
    t[0x22] = b'%'; // Shift+5
    t[0x23] = b'^'; // Shift+6
    t[0x24] = b'&'; // Shift+7
    t[0x25] = b'*'; // Shift+8
    t[0x26] = b'('; // Shift+9
    t[0x27] = b')'; // Shift+0

    // Control keys (unchanged when shifted)
    t[0x28] = 0x0A; // Enter
    t[0x29] = 0x1B; // Escape
    t[0x2A] = 0x08; // Backspace
    t[0x2B] = 0x09; // Tab
    t[0x2C] = 0x20; // Space

    // Shifted symbols
    t[0x2D] = b'_';  // Shift+Hyphen
    t[0x2E] = b'+';  // Shift+Equals
    t[0x2F] = b'{';  // Shift+Left bracket
    t[0x30] = b'}';  // Shift+Right bracket
    t[0x31] = b'|';  // Shift+Backslash
    t[0x33] = b':';  // Shift+Semicolon
    t[0x34] = b'"';  // Shift+Apostrophe
    t[0x35] = b'~';  // Shift+Grave
    t[0x36] = b'<';  // Shift+Comma
    t[0x37] = b'>';  // Shift+Period
    t[0x38] = b'?';  // Shift+Forward slash

    t
};

// ============================================================================
// Keyboard Report
// ============================================================================

/// Parsed USB HID boot protocol keyboard report.
///
/// Layout (8 bytes):
///   byte 0:    modifier flags (Ctrl, Shift, Alt, GUI — left and right)
///   byte 1:    reserved (OEM use)
///   bytes 2-7: up to 6 simultaneous keycodes (HID usage codes)
#[derive(Debug, Clone, Copy)]
pub struct KeyboardReport {
    /// Modifier bit-field (see `MOD_*` constants)
    pub modifier: u8,
    /// Currently pressed HID usage keycodes (0 = no key)
    pub keycodes: [u8; 6],
}

impl KeyboardReport {
    /// Parse an 8-byte boot protocol keyboard report.
    ///
    /// Returns `None` if the slice is too short.
    pub fn from_bytes(data: &[u8]) -> Option<Self> {
        if data.len() < KEYBOARD_REPORT_LEN {
            return None;
        }
        let mut keycodes = [0u8; 6];
        keycodes.copy_from_slice(&data[2..8]);
        Some(KeyboardReport {
            modifier: data[0],
            keycodes,
        })
    }

    /// Returns `true` if either left or right Shift is held.
    pub fn has_shift(&self) -> bool {
        self.modifier & (MOD_LEFT_SHIFT | MOD_RIGHT_SHIFT) != 0
    }

    /// Returns `true` if either left or right Ctrl is held.
    pub fn has_ctrl(&self) -> bool {
        self.modifier & (MOD_LEFT_CTRL | MOD_RIGHT_CTRL) != 0
    }

    /// Returns `true` if either left or right Alt is held.
    pub fn has_alt(&self) -> bool {
        self.modifier & (MOD_LEFT_ALT | MOD_RIGHT_ALT) != 0
    }

    /// Returns `true` if either left or right GUI (Super/Win) is held.
    pub fn has_gui(&self) -> bool {
        self.modifier & (MOD_LEFT_GUI | MOD_RIGHT_GUI) != 0
    }
}

// ============================================================================
// Mouse Report
// ============================================================================

/// Parsed USB HID boot protocol mouse report.
///
/// Layout (3–4 bytes):
///   byte 0:   button bit-field (bit 0 = left, bit 1 = right, bit 2 = middle)
///   byte 1:   X displacement (signed, -127..127)
///   byte 2:   Y displacement (signed, -127..127)
///   byte 3:   (optional) scroll wheel
#[derive(Debug, Clone, Copy)]
pub struct MouseReport {
    /// Button bit-field
    pub buttons: u8,
    /// Horizontal displacement (signed)
    pub x: i8,
    /// Vertical displacement (signed)
    pub y: i8,
}

impl MouseReport {
    /// Parse a 3+ byte boot protocol mouse report.
    ///
    /// Returns `None` if the slice is too short.
    pub fn from_bytes(data: &[u8]) -> Option<Self> {
        if data.len() < MOUSE_REPORT_MIN_LEN {
            return None;
        }
        Some(MouseReport {
            buttons: data[0],
            x: data[1] as i8,
            y: data[2] as i8,
        })
    }

    /// Returns `true` if the left button is pressed.
    pub fn left_button(&self) -> bool {
        self.buttons & 0x01 != 0
    }

    /// Returns `true` if the right button is pressed.
    pub fn right_button(&self) -> bool {
        self.buttons & 0x02 != 0
    }

    /// Returns `true` if the middle button is pressed.
    pub fn middle_button(&self) -> bool {
        self.buttons & 0x04 != 0
    }
}

// ============================================================================
// State Tracking
// ============================================================================

/// Previous keyboard report keycodes used to detect newly pressed /
/// released keys across consecutive reports.
pub static PREV_KEYBOARD: spin::Mutex<[u8; 6]> = spin::Mutex::new([0u8; 6]);

// ============================================================================
// Report Processing
// ============================================================================

/// Convert a HID usage code to ASCII, respecting the shift modifier.
fn hid_to_ascii(keycode: u8, shifted: bool) -> u8 {
    let idx = keycode as usize;
    if idx >= 128 {
        return 0;
    }
    if shifted {
        HID_TO_ASCII_SHIFTED[idx]
    } else {
        HID_TO_ASCII[idx]
    }
}

/// Process a boot-protocol keyboard report.
///
/// Compares the current keycodes against `prev_keycodes` to determine
/// which keys were newly pressed and which were released. For each
/// state change, converts the HID usage code to ASCII and injects the
/// corresponding key event into the unified input subsystem.
///
/// `data` must be an 8-byte boot protocol keyboard report.
/// `prev_keycodes` should point to the 6-byte array from the last report.
pub fn process_keyboard_report(data: &[u8], prev_keycodes: &[u8; 6]) {
    let report = match KeyboardReport::from_bytes(data) {
        Some(r) => r,
        None => {
            crate::serial_println!("[USB-HID] keyboard report too short ({} bytes)", data.len());
            return;
        }
    };

    let shifted = report.has_shift();

    // Detect newly pressed keys (present in current but not in previous)
    for &keycode in &report.keycodes {
        if keycode == 0 {
            continue;
        }
        // Check if this keycode was already pressed in the previous report
        let was_pressed = prev_keycodes.iter().any(|&prev| prev == keycode);
        if !was_pressed {
            let ascii = hid_to_ascii(keycode, shifted);
            crate::input::inject_key_event(ascii, true);
        }
    }

    // Detect released keys (present in previous but not in current)
    for &prev_keycode in prev_keycodes {
        if prev_keycode == 0 {
            continue;
        }
        let still_pressed = report.keycodes.iter().any(|&cur| cur == prev_keycode);
        if !still_pressed {
            // Use unshifted for release — the consumer only cares about
            // whether a character was released, not its shifted form.
            let ascii = hid_to_ascii(prev_keycode, false);
            crate::input::inject_key_event(ascii, false);
        }
    }

    // Update the global previous-state tracker
    *PREV_KEYBOARD.lock() = report.keycodes;
}

/// Process a boot-protocol mouse report.
///
/// Parses the button state and displacement from `data` and injects
/// a mouse event into the unified input subsystem.
pub fn process_mouse_report(data: &[u8]) {
    let report = match MouseReport::from_bytes(data) {
        Some(r) => r,
        None => {
            crate::serial_println!("[USB-HID] mouse report too short ({} bytes)", data.len());
            return;
        }
    };

    crate::input::inject_mouse_event(report.x, report.y, report.buttons);
}
