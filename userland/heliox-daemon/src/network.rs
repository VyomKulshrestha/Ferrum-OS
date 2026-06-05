// ============================================================================
// Heliox-Daemon - Bare-Metal Networking Layer
// ============================================================================
// Provides a minimal TCP client and HTTP POST builder that communicates
// with external LLM APIs using FerrumOS socket syscalls.
// ============================================================================

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;
use core::arch::asm;

// ---- Syscall Numbers (must match kernel src/syscall/mod.rs) ----------------
const SYS_SOCKET: u64 = 7;
const SYS_BIND: u64 = 8;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;
const SYS_CONNECT: u64 = 14;

// ---- Raw Syscall Interface -------------------------------------------------

#[inline(always)]
unsafe fn syscall3(number: u64, arg1: u64, arg2: u64, arg3: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        options(nostack, preserves_flags)
    );
    ret
}

// ---- Socket Wrapper API ----------------------------------------------------

/// Create a TCP socket. Returns a file descriptor on success.
pub fn tcp_socket() -> Result<u64, &'static str> {
    let fd = unsafe { syscall3(SYS_SOCKET, 2 /* AF_INET */, 1 /* SOCK_STREAM */, 0) };
    if fd >= 100 {
        Ok(fd)
    } else {
        Err("sys_socket failed")
    }
}

/// Connect a TCP socket to an IPv4 address and port.
/// `ip` is a 4-byte array (e.g. [10, 0, 2, 2] for the QEMU gateway).
pub fn tcp_connect(fd: u64, ip: [u8; 4], port: u16) -> Result<(), &'static str> {
    let ip_packed = u32::from_be_bytes(ip) as u64;
    let result = unsafe { syscall3(SYS_CONNECT, fd, ip_packed, port as u64) };
    if result == 0 {
        Ok(())
    } else {
        Err("sys_connect failed")
    }
}

/// Send data through a TCP socket. Returns bytes sent.
pub fn tcp_send(fd: u64, data: &[u8]) -> Result<usize, &'static str> {
    let sent = unsafe { syscall3(SYS_SEND, fd, data.as_ptr() as u64, data.len() as u64) };
    if sent > 0 {
        Ok(sent as usize)
    } else {
        Err("sys_send failed")
    }
}

/// Receive data from a TCP socket into the provided buffer. Returns bytes read.
pub fn tcp_recv(fd: u64, buf: &mut [u8]) -> Result<usize, &'static str> {
    let received = unsafe { syscall3(SYS_RECV, fd, buf.as_mut_ptr() as u64, buf.len() as u64) };
    Ok(received as usize)
}

// ---- DNS Resolution (Hardcoded for bare-metal) -----------------------------

/// Known host IP addresses. Since we have no DNS resolver on bare metal,
/// we hardcode the addresses of common LLM API endpoints.
/// In QEMU user-mode networking, the host machine is at 10.0.2.2.
pub fn resolve_host(host: &str) -> Option<[u8; 4]> {
    match host {
        // QEMU host gateway — used for local Ollama / LLM servers
        "host" | "localhost" | "10.0.2.2" => Some([10, 0, 2, 2]),
        // QEMU DNS server
        "dns" | "10.0.2.3" => Some([10, 0, 2, 3]),
        // Allow raw dotted-quad IPs
        _ => parse_ipv4(host),
    }
}

/// Parse a dotted-quad IPv4 string like "192.168.1.1" into bytes.
fn parse_ipv4(s: &str) -> Option<[u8; 4]> {
    let mut octets = [0u8; 4];
    let mut idx = 0;
    let mut current: u16 = 0;
    let mut has_digit = false;

    for ch in s.bytes() {
        match ch {
            b'0'..=b'9' => {
                current = current * 10 + (ch - b'0') as u16;
                if current > 255 {
                    return None;
                }
                has_digit = true;
            }
            b'.' => {
                if !has_digit || idx >= 3 {
                    return None;
                }
                octets[idx] = current as u8;
                idx += 1;
                current = 0;
                has_digit = false;
            }
            _ => return None,
        }
    }

    if has_digit && idx == 3 {
        octets[3] = current as u8;
        Some(octets)
    } else {
        None
    }
}

// ---- HTTP Client -----------------------------------------------------------

/// Result of an HTTP request.
pub struct HttpResponse {
    pub status_code: u16,
    pub body: String,
}

/// Perform an HTTP POST request to the given host:port/path with a JSON body.
/// This is a minimal bare-metal HTTP/1.1 client — no TLS, no chunked encoding.
pub fn http_post(host: &str, port: u16, path: &str, json_body: &str) -> Result<HttpResponse, &'static str> {
    // 1. Resolve the host
    let ip = resolve_host(host).ok_or("DNS resolution failed")?;

    // 2. Create a TCP socket
    let fd = tcp_socket()?;

    // 3. Connect to the remote server
    tcp_connect(fd, ip, port)?;

    // 4. Build the HTTP request
    let content_length = json_body.len();
    let request = format!(
        "POST {} HTTP/1.1\r\nHost: {}:{}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        path, host, port, content_length, json_body
    );

    // 5. Send the request
    tcp_send(fd, request.as_bytes())?;

    // 6. Receive the response (up to 8 KiB)
    let mut response_buf = alloc::vec![0u8; 8192];
    let mut total_received = 0;

    // Poll for response data (simple retry loop since sockets are non-blocking)
    for _ in 0..1000 {
        let n = tcp_recv(fd, &mut response_buf[total_received..])?;
        if n > 0 {
            total_received += n;
            // Check if we've received the full response (look for double CRLF + body)
            if total_received > 4 {
                // Simple heuristic: if Connection: close, the server will close the connection
                // For now, if we have data and a subsequent recv returns 0, we're done
                continue;
            }
        } else if total_received > 0 {
            // We had data and now recv returned 0 — response is complete
            break;
        }
        // Yield to scheduler briefly
        unsafe { asm!("hlt", options(nomem, nostack, preserves_flags)); }
    }

    if total_received == 0 {
        return Err("no response received");
    }

    // 7. Parse the HTTP response
    let raw = core::str::from_utf8(&response_buf[..total_received])
        .map_err(|_| "invalid UTF-8 in response")?;

    parse_http_response(raw)
}

/// Parse a raw HTTP response string into status code and body.
fn parse_http_response(raw: &str) -> Result<HttpResponse, &'static str> {
    // Find the status line: "HTTP/1.1 200 OK\r\n"
    let status_line_end = raw.find("\r\n").ok_or("malformed HTTP response")?;
    let status_line = &raw[..status_line_end];

    // Extract status code (starts after "HTTP/x.x ")
    let status_code = status_line
        .split(' ')
        .nth(1)
        .ok_or("no status code")?
        .parse::<u16>()
        .map_err(|_| "invalid status code")?;

    // Find the body (after \r\n\r\n)
    let body_start = raw.find("\r\n\r\n").map(|i| i + 4).unwrap_or(raw.len());
    let body = String::from(&raw[body_start..]);

    Ok(HttpResponse {
        status_code,
        body,
    })
}

// ---- LLM-Specific Helpers --------------------------------------------------

/// Build a JSON payload for an OpenAI-compatible chat completion API.
pub fn build_chat_payload(system_prompt: &str, user_message: &str) -> String {
    format!(
        r#"{{"model":"default","messages":[{{"role":"system","content":"{}"}},{{"role":"user","content":"{}"}}],"max_tokens":512}}"#,
        escape_json(system_prompt),
        escape_json(user_message)
    )
}

/// Minimal JSON string escaping for bare-metal use.
fn escape_json(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c => out.push(c),
        }
    }
    out
}

/// Send a prompt to a local Ollama server running on the QEMU host.
/// Default Ollama API: POST http://10.0.2.2:11434/api/generate
pub fn query_ollama(prompt: &str) -> Result<HttpResponse, &'static str> {
    let json = format!(
        r#"{{"model":"llama3","prompt":"{}","stream":false}}"#,
        escape_json(prompt)
    );
    http_post("host", 11434, "/api/generate", &json)
}

/// Send a prompt to an OpenAI-compatible API running on the QEMU host.
/// Default: POST http://10.0.2.2:8080/v1/chat/completions
pub fn query_openai_compat(system_prompt: &str, user_message: &str, port: u16) -> Result<HttpResponse, &'static str> {
    let json = build_chat_payload(system_prompt, user_message);
    http_post("host", port, "/v1/chat/completions", &json)
}
