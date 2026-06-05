// ============================================================================
// Heliox Daemon - Screen Vision (Cognitive Module)
// ============================================================================
// Reads the kernel's shadow text buffer through the ReadTextBuffer syscall
// to give the agent a structured view of what is currently on screen.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;

/// Syscall number for `ReadTextBuffer`.
const SYS_READ_TEXT_BUFFER: u64 = 20;

/// Size of the userspace buffer used to receive the text dump (16 KB).
const CAPTURE_BUF_SIZE: usize = 16 * 1024;

/// A snapshot of the screen's text content at a point in time.
pub struct ScreenCapture {
    /// Each row of text currently displayed on screen.
    pub rows: Vec<String>,
    /// Number of columns (width of the widest row, or 0).
    pub width: usize,
    /// Number of rows that contain at least some content.
    pub height: usize,
}

impl ScreenCapture {
    /// Joins all rows with newlines into a single string.
    pub fn full_text(&self) -> String {
        let mut out = String::new();
        for (i, row) in self.rows.iter().enumerate() {
            if i > 0 {
                out.push('\n');
            }
            out.push_str(row);
        }
        out
    }

    /// Returns a specific line by zero-based row index.
    pub fn line(&self, row: usize) -> Option<&str> {
        self.rows.get(row).map(|s| s.as_str())
    }

    /// Returns `true` if any row contains non-whitespace content.
    pub fn has_content(&self) -> bool {
        self.rows.iter().any(|r| !r.trim().is_empty())
    }

    /// Searches all rows for `needle` and returns the first match as
    /// `(row, col)` (both zero-based).
    pub fn find_text(&self, needle: &str) -> Option<(usize, usize)> {
        for (row_idx, row) in self.rows.iter().enumerate() {
            if let Some(col) = row.find(needle) {
                return Some((row_idx, col));
            }
        }
        None
    }

    /// Returns the last non-empty line — useful for reading the most recent
    /// shell prompt or command output.
    pub fn last_line(&self) -> Option<&str> {
        self.rows
            .iter()
            .rev()
            .find(|r| !r.trim().is_empty())
            .map(|s| s.as_str())
    }
}

/// Capture the current screen contents by issuing the `ReadTextBuffer` syscall.
///
/// Returns a [`ScreenCapture`] on success, or a static error string if the
/// syscall fails or the console is not initialised.
pub fn capture_screen() -> Result<ScreenCapture, &'static str> {
    let mut buf = alloc::vec![0u8; CAPTURE_BUF_SIZE];
    let buf_ptr = buf.as_mut_ptr() as u64;
    let buf_len = buf.len() as u64;

    // Issue the syscall.  The kernel returns the number of bytes written
    // (in the low bits) or a negative status code on error.
    let ret = unsafe {
        crate::syscall4(SYS_READ_TEXT_BUFFER, buf_ptr, buf_len, 0, 0)
    };

    // A negative (sign-extended) return indicates an error.
    if ret == 0 || (ret as i64) < 0 {
        return Err("ReadTextBuffer syscall failed or console not initialised");
    }

    let bytes_written = ret as usize;
    let text = core::str::from_utf8(&buf[..bytes_written])
        .map_err(|_| "ReadTextBuffer returned invalid UTF-8")?;

    // Parse into rows (the kernel separates rows with '\n').
    let rows: Vec<String> = text
        .split('\n')
        .filter(|line| !line.is_empty())
        .map(|line| String::from(line))
        .collect();

    let width = rows.iter().map(|r| r.len()).max().unwrap_or(0);
    let height = rows.iter().filter(|r| !r.trim().is_empty()).count();

    Ok(ScreenCapture {
        rows,
        width,
        height,
    })
}
