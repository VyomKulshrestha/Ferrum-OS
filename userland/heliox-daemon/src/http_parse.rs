// ============================================================================
// Heliox-Daemon - HTTP response framing (no syscalls; host-tested)
// ============================================================================
// Reading, framing and decoding of HTTP/1.1 responses for the daemon's HTTP
// and HTTPS clients in `network.rs`, kept free of syscalls so the host tests
// (`userland/heliox-gate-tests/tests/http.rs`) compile this file as it is.
//
// Limits, all explicit errors rather than silent truncation:
// - a response (headers and body) is at most `MAX_HTTP_RESPONSE` bytes;
// - a body with Content-Length must arrive whole;
// - a chunked body must end with its terminal chunk; chunk arithmetic is
//   checked (a chunk size of usize::MAX - offset used to wrap `chunk_end + 2`
//   and panic the daemon on one crafted response);
// - a WebSocket frame payload is at most `MAX_WS_PAYLOAD` bytes.
// ============================================================================

use alloc::string::String;
use alloc::vec::Vec;

/// Largest HTTP response the daemon reads (headers and body). Responses used
/// to be cut at 32 KiB and parsed as if complete.
pub const MAX_HTTP_RESPONSE: usize = 1024 * 1024;

/// Largest WebSocket frame payload the daemon accepts. The 64-bit length
/// from the frame header went straight to an allocation: one frame from any
/// client of the bridge port aborted the daemon.
pub const MAX_WS_PAYLOAD: u64 = 1024 * 1024;

/// Result of an HTTP request.
#[derive(Debug)]
pub struct HttpResponse {
    pub status_code: u16,
    pub body: String,
}

/// Read a response with `recv` until the peer closes, the declared
/// Content-Length has arrived, or `MAX_HTTP_RESPONSE` is exceeded (an error).
/// `recv` returns Ok(0) at end of stream and Err("blocked") when no data is
/// ready yet, after which `wait` is called.
pub fn receive_response<R, W>(mut recv: R, mut wait: W) -> Result<Vec<u8>, &'static str>
where
    R: FnMut(&mut [u8]) -> Result<usize, &'static str>,
    W: FnMut(),
{
    const STEP: usize = 16 * 1024;
    let mut data: Vec<u8> = Vec::new();
    let mut len = 0usize;
    // Total length once the headers declare a Content-Length.
    let mut expected: Option<u64> = None;
    let mut headers_done = false;
    loop {
        if len == data.len() {
            if data.len() >= MAX_HTTP_RESPONSE {
                // One more byte tells "exactly at the limit, then closed"
                // apart from "longer than the limit".
                let mut probe = [0u8; 1];
                loop {
                    match recv(&mut probe) {
                        Ok(0) => return Ok(data),
                        Ok(_) => return Err("HTTP response larger than the 1 MiB limit"),
                        Err("blocked") => wait(),
                        Err(e) => return Err(e),
                    }
                }
            }
            let grow = STEP.min(MAX_HTTP_RESPONSE - data.len());
            data.try_reserve_exact(grow).map_err(|_| "out of memory for HTTP response")?;
            data.resize(data.len() + grow, 0);
        }
        match recv(&mut data[len..]) {
            Ok(0) => break,
            Ok(n) => {
                let start = len;
                len = len.checked_add(n).filter(|l| *l <= data.len()).ok_or("receive overran its buffer")?;
                if !headers_done {
                    // Search only the new bytes (and three before them).
                    let from = start.saturating_sub(3);
                    if let Some(at) = find(&data[from..len], b"\r\n\r\n") {
                        headers_done = true;
                        let header_end = from + at;
                        if let Ok(headers) = core::str::from_utf8(&data[..header_end]) {
                            if let Ok(Framing::Length(n)) = framing(headers) {
                                expected = Some(header_end as u64 + 4 + n);
                            }
                        }
                    }
                }
                if expected.is_some_and(|total| len as u64 >= total) {
                    break;
                }
            }
            Err("blocked") => wait(),
            Err(e) => return Err(e),
        }
    }
    data.truncate(len);
    if data.is_empty() {
        return Err("no HTTP response received");
    }
    Ok(data)
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

enum Framing {
    Chunked,
    Length(u64),
    Close,
}

/// How the body is delimited, from the header block (status line excluded
/// or not; it has no colon-separated name we look for).
fn framing(headers: &str) -> Result<Framing, &'static str> {
    let mut length: Option<u64> = None;
    let mut chunked = false;
    for line in headers.split("\r\n").skip(1) {
        let Some((name, value)) = line.split_once(':') else { continue };
        let name = name.trim();
        let value = value.trim();
        if name.eq_ignore_ascii_case("transfer-encoding") {
            if value.split(',').any(|v| v.trim().eq_ignore_ascii_case("chunked")) {
                chunked = true;
            }
        } else if name.eq_ignore_ascii_case("content-length") {
            if value.is_empty() || value.len() > 19 || !value.bytes().all(|b| b.is_ascii_digit()) {
                return Err("invalid Content-Length");
            }
            let n: u64 = value.parse().map_err(|_| "invalid Content-Length")?;
            if length.is_some_and(|previous| previous != n) {
                return Err("conflicting Content-Length headers");
            }
            length = Some(n);
        }
    }
    Ok(if chunked {
        // Transfer-Encoding overrides Content-Length (RFC 9112 6.3).
        Framing::Chunked
    } else if let Some(n) = length {
        Framing::Length(n)
    } else {
        Framing::Close
    })
}

/// Decode a chunked body. Every offset is checked; a missing terminal chunk,
/// a truncated chunk or a body over the response limit is an error.
pub fn decode_chunked_body(encoded: &[u8]) -> Result<Vec<u8>, &'static str> {
    let mut decoded = Vec::new();
    let mut offset = 0usize;
    loop {
        if offset >= encoded.len() {
            return Err("missing terminal HTTP chunk");
        }
        // A chunk-size line is short; do not scan an unbounded line.
        let window = &encoded[offset..encoded.len().min(offset + 1024)];
        let line_len = find(window, b"\r\n").ok_or("malformed chunk size")?;
        let size_line = core::str::from_utf8(&window[..line_len]).map_err(|_| "invalid chunk size")?;
        let size_text = size_line.split(';').next().unwrap_or("").trim();
        if size_text.is_empty() || size_text.len() > 16 {
            return Err("invalid chunk size");
        }
        let size = usize::from_str_radix(size_text, 16).map_err(|_| "invalid chunk size")?;
        offset += line_len + 2;
        if size == 0 {
            return Ok(decoded);
        }
        let chunk_end = offset.checked_add(size).ok_or("chunk size overflow")?;
        let after = chunk_end.checked_add(2).ok_or("chunk size overflow")?;
        if after > encoded.len() || &encoded[chunk_end..after] != b"\r\n" {
            return Err("truncated chunked body");
        }
        if decoded.len() + size > MAX_HTTP_RESPONSE {
            return Err("chunked body larger than the 1 MiB limit");
        }
        decoded.extend_from_slice(&encoded[offset..chunk_end]);
        offset = after;
    }
}

/// Parse a complete raw response into status code and body. The status line
/// must be HTTP/1.x with a three-digit code; a body shorter than its
/// Content-Length is an error, a longer one is cut at the declared length.
pub fn parse_http_response(raw: &[u8]) -> Result<HttpResponse, &'static str> {
    let header_end = find(raw, b"\r\n\r\n").ok_or("missing HTTP header terminator")?;
    let headers = core::str::from_utf8(&raw[..header_end]).map_err(|_| "invalid HTTP headers")?;
    let status_line = headers.split("\r\n").next().unwrap_or("");
    let mut parts = status_line.splitn(3, ' ');
    let version = parts.next().unwrap_or("");
    let code = parts.next().ok_or("no status code")?;
    if !version.starts_with("HTTP/1.") || code.len() != 3 || !code.bytes().all(|b| b.is_ascii_digit()) {
        return Err("malformed HTTP status line");
    }
    let status_code: u16 = code.parse().map_err(|_| "invalid status code")?;
    if !(100..=599).contains(&status_code) {
        return Err("invalid status code");
    }
    let body = &raw[header_end + 4..];
    let body = match framing(headers)? {
        Framing::Chunked => decode_chunked_body(body)?,
        Framing::Length(n) => {
            if (body.len() as u64) < n {
                return Err("truncated HTTP body");
            }
            Vec::from(&body[..n as usize])
        }
        Framing::Close => Vec::from(body),
    };
    let body = String::from_utf8(body).map_err(|_| "invalid UTF-8 in HTTP body")?;
    Ok(HttpResponse { status_code, body })
}

/// Check a WebSocket frame's declared payload length.
pub fn ws_payload_len(declared: u64) -> Result<usize, &'static str> {
    if declared > MAX_WS_PAYLOAD {
        return Err("ws: frame larger than the 1 MiB limit");
    }
    Ok(declared as usize)
}
