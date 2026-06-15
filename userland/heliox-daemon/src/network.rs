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
const SYS_LISTEN: u64 = 9;
const SYS_RECV: u64 = 11;
const SYS_SEND: u64 = 12;
const SYS_CONNECT: u64 = 14;
const SYS_CLOSE: u64 = 35;
const SYS_READ_CAMERA_FRAME: u64 = 36;
const SYS_CAMERA_INFO: u64 = 37;

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
    if (fd as i64) >= 100 {
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

/// Bind a TCP socket to a local port.
pub fn tcp_bind(fd: u64, port: u16) -> Result<(), &'static str> {
    let result = unsafe { syscall3(SYS_BIND, fd, port as u64, 0) };
    if result == 0 {
        Ok(())
    } else {
        Err("sys_bind failed")
    }
}

/// Listen on a bound TCP socket.
pub fn tcp_listen(fd: u64, backlog: u64) -> Result<(), &'static str> {
    let result = unsafe { syscall3(SYS_LISTEN, fd, backlog, 0) };
    if result == 0 {
        Ok(())
    } else {
        Err("sys_listen failed")
    }
}

/// Close a TCP socket.
pub fn tcp_close(fd: u64) -> Result<(), &'static str> {
    let result = unsafe { syscall3(SYS_CLOSE, fd, 0, 0) };
    if result == 0 {
        Ok(())
    } else {
        Err("sys_close failed")
    }
}

/// Send data through a TCP socket. Returns bytes sent.
pub fn tcp_send(fd: u64, data: &[u8]) -> Result<usize, &'static str> {
    let sent = unsafe { syscall3(SYS_SEND, fd, data.as_ptr() as u64, data.len() as u64) };
    let sent_i = sent as i64;
    if sent_i >= 0 {
        Ok(sent_i as usize)
    } else {
        Err("sys_send failed")
    }
}

/// Receive data from a TCP socket into the provided buffer. Returns bytes read.
pub fn tcp_recv(fd: u64, buf: &mut [u8]) -> Result<usize, &'static str> {
    let received = unsafe { syscall3(SYS_RECV, fd, buf.as_mut_ptr() as u64, buf.len() as u64) };
    let received_i = received as i64;
    if received_i >= 0 {
        Ok(received_i as usize)
    } else {
        Err("sys_recv failed")
    }
}

/// Read the latest camera frame into the provided buffer. Returns frame size.
pub fn read_camera_frame(buf: &mut [u8]) -> Result<usize, &'static str> {
    let size = unsafe { syscall3(SYS_READ_CAMERA_FRAME, buf.as_mut_ptr() as u64, buf.len() as u64, 0) };
    let size_i = size as i64;
    if size_i >= 0 {
        Ok(size_i as usize)
    } else {
        Err("read_camera_frame failed")
    }
}

/// Retrieve camera metadata as a JSON string in the provided buffer. Returns bytes written.
pub fn camera_info(buf: &mut [u8]) -> Result<usize, &'static str> {
    let size = unsafe { syscall3(SYS_CAMERA_INFO, buf.as_mut_ptr() as u64, buf.len() as u64, 0) };
    let size_i = size as i64;
    if size_i >= 0 {
        Ok(size_i as usize)
    } else {
        Err("camera_info failed")
    }
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

/// Perform an HTTP GET request to the given host:port/path.
/// Returns the response status code and body.
pub fn http_get(host: &str, port: u16, path: &str) -> Result<HttpResponse, &'static str> {
    let ip = resolve_host(host).ok_or("DNS resolution failed")?;
    let fd = tcp_socket()?;
    tcp_connect(fd, ip, port)?;

    let request = format!(
        "GET {} HTTP/1.1\r\nHost: {}:{}\r\nConnection: close\r\nUser-Agent: Heliox/0.1\r\n\r\n",
        path, host, port
    );

    // Send the request, retrying if the connection is not yet fully established
    let request_bytes = request.as_bytes();
    let mut sent = 0;
    let mut retries = 0;
    loop {
        match tcp_send(fd, &request_bytes[sent..]) {
            Ok(n) => {
                sent += n;
                if sent >= request_bytes.len() {
                    break;
                }
            }
            Err(_) => {
                retries += 1;
                if retries > 100 {
                    return Err("Failed to send HTTP request (handshake timeout)");
                }
                // Yield to scheduler to let kernel handle the connection handshake
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    let mut response_buf = alloc::vec![0u8; 32768];
    let mut total_received = 0;
    for _ in 0..1000 {
        match tcp_recv(fd, &mut response_buf[total_received..]) {
            Ok(n) if n > 0 => {
                total_received += n;
                if total_received >= response_buf.len() {
                    break;
                }
            }
            _ => {
                if total_received > 0 {
                    break;
                }
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    if total_received == 0 {
        return Err("No HTTP response received");
    }

    let response_str = core::str::from_utf8(&response_buf[..total_received])
        .unwrap_or("");
    parse_http_response(response_str)
}

/// Perform an HTTP POST request to the given host:port/path with a JSON body.
/// This is a minimal bare-metal HTTP/1.1 client — no TLS, no chunked encoding.
pub fn http_post(host: &str, port: u16, path: &str, json_body: &str, api_key: &str) -> Result<HttpResponse, &'static str> {
    // 1. Resolve the host
    let ip = resolve_host(host).ok_or("DNS resolution failed")?;

    // 2. Create a TCP socket
    let fd = tcp_socket()?;

    // 3. Connect to the remote server
    tcp_connect(fd, ip, port)?;

    // 4. Build the HTTP request
    let content_length = json_body.len();
    
    let auth_header = if !api_key.is_empty() {
        format!("Authorization: Bearer {}\r\n", api_key)
    } else {
        String::new()
    };
    
    let request = format!(
        "POST {} HTTP/1.1\r\nHost: {}:{}\r\nContent-Type: application/json\r\n{}Content-Length: {}\r\nConnection: close\r\n\r\n{}",
        path, host, port, auth_header, content_length, json_body
    );

    // 5. Send the request
    // Send the request, retrying if the connection is not yet fully established
    let request_bytes = request.as_bytes();
    let mut sent = 0;
    let mut retries = 0;
    loop {
        match tcp_send(fd, &request_bytes[sent..]) {
            Ok(n) => {
                sent += n;
                if sent >= request_bytes.len() {
                    break;
                }
            }
            Err(_) => {
                retries += 1;
                if retries > 100 {
                    return Err("Failed to send HTTP request (handshake timeout)");
                }
                // Yield to scheduler to let kernel handle the connection handshake
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    // 6. Receive the response (up to 8 KiB)
    let mut response_buf = alloc::vec![0u8; 32768];
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
        unsafe { crate::syscall3(0, 0, 0, 0); }
    }

    if total_received == 0 {
        return Err("no response received");
    }

    // 7. Parse the HTTP response
    let raw = core::str::from_utf8(&response_buf[..total_received])
        .map_err(|_| "invalid UTF-8 in response")?;

    parse_http_response(raw)
}

/// Perform an HTTP POST request to the given host:port/path with a binary body.
pub fn http_post_binary(
    host: &str,
    port: u16,
    path: &str,
    body: &[u8],
    content_type: &str,
    api_key: &str,
) -> Result<HttpResponse, &'static str> {
    // 1. Resolve the host
    let ip = resolve_host(host).ok_or("DNS resolution failed")?;

    // 2. Create a TCP socket
    let fd = tcp_socket()?;

    // 3. Connect to the remote server
    tcp_connect(fd, ip, port)?;

    // 4. Build the HTTP request headers
    let auth_header = if !api_key.is_empty() {
        format!("Authorization: Bearer {}\r\n", api_key)
    } else {
        String::new()
    };
    
    let headers = format!(
        "POST {} HTTP/1.1\r\nHost: {}:{}\r\nContent-Type: {}\r\n{}Content-Length: {}\r\nConnection: close\r\n\r\n",
        path, host, port, content_type, auth_header, body.len()
    );

    // 5. Send the headers
    let headers_bytes = headers.as_bytes();
    let mut sent = 0;
    let mut retries = 0;
    loop {
        match tcp_send(fd, &headers_bytes[sent..]) {
            Ok(n) => {
                sent += n;
                if sent >= headers_bytes.len() {
                    break;
                }
            }
            Err(_) => {
                retries += 1;
                if retries > 100 {
                    return Err("Failed to send HTTP request headers (handshake timeout)");
                }
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    // 6. Send the binary body
    let mut sent = 0;
    let mut retries = 0;
    while sent < body.len() {
        match tcp_send(fd, &body[sent..]) {
            Ok(n) => {
                sent += n;
                retries = 0;
            }
            Err(_) => {
                retries += 1;
                if retries > 100 {
                    return Err("Failed to send HTTP request body");
                }
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    // 7. Receive the response
    let mut response_buf = alloc::vec![0u8; 32768];
    let mut total_received = 0;
    for _ in 0..1000 {
        match tcp_recv(fd, &mut response_buf[total_received..]) {
            Ok(n) if n > 0 => {
                total_received += n;
                if total_received >= response_buf.len() {
                    break;
                }
            }
            _ => {
                if total_received > 0 {
                    break;
                }
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    if total_received == 0 {
        return Err("No HTTP response received");
    }

    // 8. Parse the HTTP response
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

/// Send a prompt to an LLM provider.
pub fn query_llm(
    provider: &str,
    prompt: &str,
    host: &str,
    port: u16,
    path: &str,
    model: &str,
    api_key: &str,
) -> Result<HttpResponse, &'static str> {
    let json = if provider == "ollama" {
        format!(
            r#"{{"model":"{}","prompt":"{}","stream":false}}"#,
            model,
            escape_json(prompt)
        )
    } else {
        // OpenAI-compatible format (used for OpenAI, Gemini, Claude via LiteLLM)
        format!(
            r#"{{"model":"{}","messages":[{{"role":"user","content":"{}"}}]}}"#,
            model,
            escape_json(prompt)
        )
    };

    http_post(host, port, path, &json, api_key)
}

/// Send a prompt to an OpenAI-compatible API running on the QEMU host.
/// Default: POST http://10.0.2.2:8080/v1/chat/completions
pub fn query_openai_compat(system_prompt: &str, user_message: &str, port: u16) -> Result<HttpResponse, &'static str> {
    let json = build_chat_payload(system_prompt, user_message);
    http_post("host", port, "/v1/chat/completions", &json, "")
}

// ============================================================================
// WebSocket Client (RFC 6455)
// ============================================================================

/// WebSocket opcodes.
const WS_OP_CONTINUATION: u8 = 0x0;
const WS_OP_TEXT: u8 = 0x1;
const WS_OP_BINARY: u8 = 0x2;
const WS_OP_CLOSE: u8 = 0x8;
const WS_OP_PING: u8 = 0x9;
const WS_OP_PONG: u8 = 0xA;

/// An active WebSocket connection over a TCP socket.
pub struct WsConnection {
    pub fd: u64,
    pub connected: bool,
}

/// A parsed WebSocket frame.
pub struct WsFrame {
    pub opcode: u8,
    pub fin: bool,
    pub payload: Vec<u8>,
}

/// Generate a simple 4-byte masking key from the tick counter.
fn ws_mask_key() -> [u8; 4] {
    // Use a deterministic but varying value — good enough for bare metal
    // where we have no RNG. The spec requires a mask but doesn't mandate
    // cryptographic randomness.
    let ticks = unsafe { core::arch::x86_64::_rdtsc() };
    let bytes = ticks.to_le_bytes();
    [bytes[0], bytes[1], bytes[2], bytes[3]]
}

/// Perform a WebSocket handshake (HTTP Upgrade) and return a connection.
///
/// The `host` is resolved via `resolve_host()`. The `path` is the WebSocket
/// endpoint (e.g., "/ws" or "/api/generate").
pub fn ws_connect(host: &str, port: u16, path: &str) -> Result<WsConnection, &'static str> {
    let ip = resolve_host(host).ok_or("ws: cannot resolve host")?;
    let fd = tcp_socket()?;
    tcp_connect(fd, ip, port)?;

    // Build the HTTP Upgrade request.
    // The Sec-WebSocket-Key is a fixed base64 string — the server will
    // respond with a derived Accept header. We don't validate the Accept
    // since we trust the local server.
    let request = format!(
        "GET {} HTTP/1.1\r\n\
         Host: {}:{}\r\n\
         Upgrade: websocket\r\n\
         Connection: Upgrade\r\n\
         Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\
         Sec-WebSocket-Version: 13\r\n\
         \r\n",
        path, host, port
    );

    tcp_send(fd, request.as_bytes())?;

    // Read the upgrade response.
    let mut buf = [0u8; 1024];
    let mut total = 0;
    for _ in 0..500 {
        match tcp_recv(fd, &mut buf[total..]) {
            Ok(n) if n > 0 => {
                total += n;
                // Check if we've received the full HTTP response headers.
                if let Some(_) = find_header_end(&buf[..total]) {
                    break;
                }
            }
            _ => {
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }

    if total == 0 {
        return Err("ws: no upgrade response");
    }

    // Verify "101 Switching Protocols" in the response.
    let response = core::str::from_utf8(&buf[..total]).unwrap_or("");
    if !response.contains("101") {
        return Err("ws: upgrade rejected (not 101)");
    }

    Ok(WsConnection { fd, connected: true })
}

/// Find the end of HTTP headers (\r\n\r\n) in a buffer.
fn find_header_end(buf: &[u8]) -> Option<usize> {
    for i in 0..buf.len().saturating_sub(3) {
        if buf[i] == b'\r' && buf[i + 1] == b'\n' && buf[i + 2] == b'\r' && buf[i + 3] == b'\n' {
            return Some(i + 4);
        }
    }
    None
}

/// Send a text message over a WebSocket connection.
///
/// The frame is masked (required for client-to-server messages in RFC 6455).
pub fn ws_send_text(conn: &WsConnection, data: &str) -> Result<(), &'static str> {
    if !conn.connected {
        return Err("ws: not connected");
    }
    ws_send_frame(conn.fd, WS_OP_TEXT, data.as_bytes())
}

/// Send a binary message over a WebSocket connection.
pub fn ws_send_binary(conn: &WsConnection, data: &[u8]) -> Result<(), &'static str> {
    if !conn.connected {
        return Err("ws: not connected");
    }
    ws_send_frame(conn.fd, WS_OP_BINARY, data)
}

/// Build and send a single WebSocket frame with client-side masking.
fn ws_send_frame(fd: u64, opcode: u8, payload: &[u8]) -> Result<(), &'static str> {
    let len = payload.len();
    let mut frame = Vec::with_capacity(14 + len); // max header + payload

    // Byte 0: FIN + opcode
    frame.push(0x80 | opcode); // FIN=1, RSV=000

    // Byte 1: MASK=1 + payload length
    let mask_key = ws_mask_key();
    if len < 126 {
        frame.push(0x80 | len as u8);
    } else if len <= 65535 {
        frame.push(0x80 | 126);
        frame.push((len >> 8) as u8);
        frame.push((len & 0xFF) as u8);
    } else {
        frame.push(0x80 | 127);
        for i in (0..8).rev() {
            frame.push(((len >> (i * 8)) & 0xFF) as u8);
        }
    }

    // Masking key (4 bytes)
    frame.extend_from_slice(&mask_key);

    // Masked payload
    for (i, &byte) in payload.iter().enumerate() {
        frame.push(byte ^ mask_key[i % 4]);
    }

    tcp_send(fd, &frame)?;
    Ok(())
}

/// Build and send a single WebSocket frame from the server (NO masking).
pub fn ws_send_frame_server(fd: u64, opcode: u8, payload: &[u8]) -> Result<(), &'static str> {
    let len = payload.len();
    let mut frame = Vec::with_capacity(10 + len); // max header + payload

    // Byte 0: FIN + opcode
    frame.push(0x80 | opcode); // FIN=1, RSV=000

    // Byte 1: MASK=0 + payload length
    if len < 126 {
        frame.push(len as u8);
    } else if len <= 65535 {
        frame.push(126);
        frame.push((len >> 8) as u8);
        frame.push((len & 0xFF) as u8);
    } else {
        frame.push(127);
        for i in (0..8).rev() {
            frame.push(((len >> (i * 8)) & 0xFF) as u8);
        }
    }

    // Unmasked payload
    frame.extend_from_slice(payload);

    tcp_send(fd, &frame)?;
    Ok(())
}

/// Send a text message from the server over a WebSocket connection (no masking).
pub fn ws_send_text_server(fd: u64, data: &str) -> Result<(), &'static str> {
    ws_send_frame_server(fd, WS_OP_TEXT, data.as_bytes())
}

/// Receive a single WebSocket frame from the connection.
///
/// Handles:
/// - Text and binary data frames
/// - Ping (auto-responds with pong)
/// - Close (marks connection as disconnected)
/// - Continuation frames (appended to payload)
pub fn ws_recv_frame(conn: &mut WsConnection) -> Result<WsFrame, &'static str> {
    if !conn.connected {
        return Err("ws: not connected");
    }

    // Read the first 2 bytes (minimum frame header).
    let mut header = [0u8; 2];
    ws_read_exact(conn.fd, &mut header, true)?;

    let fin = (header[0] & 0x80) != 0;
    let opcode = header[0] & 0x0F;
    let masked = (header[1] & 0x80) != 0;
    let len_byte = header[1] & 0x7F;

    // Determine payload length.
    let payload_len: usize = if len_byte < 126 {
        len_byte as usize
    } else if len_byte == 126 {
        let mut ext = [0u8; 2];
        ws_read_exact(conn.fd, &mut ext, false)?;
        u16::from_be_bytes(ext) as usize
    } else {
        // 127 → 8-byte extended length
        let mut ext = [0u8; 8];
        ws_read_exact(conn.fd, &mut ext, false)?;
        u64::from_be_bytes(ext) as usize
    };

    // Read optional masking key (server frames should NOT be masked,
    // but handle it gracefully).
    let mask_key = if masked {
        let mut mk = [0u8; 4];
        ws_read_exact(conn.fd, &mut mk, false)?;
        Some(mk)
    } else {
        None
    };

    // Read payload.
    let mut payload = alloc::vec![0u8; payload_len];
    if payload_len > 0 {
        ws_read_exact(conn.fd, &mut payload, false)?;
    }

    // Unmask if needed.
    if let Some(mk) = mask_key {
        for (i, byte) in payload.iter_mut().enumerate() {
            *byte ^= mk[i % 4];
        }
    }

    // Handle control frames.
    match opcode {
        WS_OP_PING => {
            // Auto-respond with pong. If received frame was masked, we are server (no masking in response).
            if masked {
                let _ = ws_send_frame_server(conn.fd, WS_OP_PONG, &payload);
            } else {
                let _ = ws_send_frame(conn.fd, WS_OP_PONG, &payload);
            }
            // Recurse to get the next data frame.
            return ws_recv_frame(conn);
        }
        WS_OP_CLOSE => {
            // Send close frame back and mark disconnected.
            if masked {
                let _ = ws_send_frame_server(conn.fd, WS_OP_CLOSE, &[]);
            } else {
                let _ = ws_send_frame(conn.fd, WS_OP_CLOSE, &[]);
            }
            conn.connected = false;
            return Ok(WsFrame {
                opcode: WS_OP_CLOSE,
                fin: true,
                payload: Vec::new(),
            });
        }
        _ => {}
    }

    Ok(WsFrame {
        opcode,
        fin,
        payload,
    })
}

/// Read exactly `buf.len()` bytes from the socket, retrying as needed.
fn ws_read_exact(fd: u64, buf: &mut [u8], allow_no_data: bool) -> Result<(), &'static str> {
    let mut offset = 0;
    let mut retries = 0;
    while offset < buf.len() {
        match tcp_recv(fd, &mut buf[offset..]) {
            Ok(n) if n > 0 => {
                offset += n;
                retries = 0;
            }
            _ => {
                if offset == 0 && allow_no_data {
                    return Err("ws: no data");
                }
                retries += 1;
                if retries > 2000 {
                    return Err("ws: read timeout");
                }
                unsafe { crate::syscall3(0, 0, 0, 0); }
            }
        }
    }
    Ok(())
}

/// Send a close frame and disconnect.
pub fn ws_close(conn: &mut WsConnection) -> Result<(), &'static str> {
    if conn.connected {
        let _ = ws_send_frame(conn.fd, WS_OP_CLOSE, &[]);
        conn.connected = false;
    }
    Ok(())
}

// ---- Server-Side Helpers ----------------------------------------------------

/// Compute the SHA-1 hash of the input bytes (no_std, zero dependency).
pub fn sha1(data: &[u8]) -> [u8; 20] {
    let mut h0 = 0x67452301u32;
    let mut h1 = 0xEFCDAB89u32;
    let mut h2 = 0x98BADCFEu32;
    let mut h3 = 0x10325476u32;
    let mut h4 = 0xC3D2E1F0u32;

    let mut msg = data.to_vec();
    let original_len_bits = (data.len() as u64) * 8;
    msg.push(0x80);
    while (msg.len() * 8) % 512 != 448 {
        msg.push(0x00);
    }
    msg.extend_from_slice(&original_len_bits.to_be_bytes());

    for chunk in msg.chunks_exact(64) {
        let mut w = [0u32; 80];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }

        let mut a = h0;
        let mut b = h1;
        let mut c = h2;
        let mut d = h3;
        let mut e = h4;

        for i in 0..80 {
            let (f, k) = match i {
                0..=19 => ((b & c) | (!b & d), 0x5A827999),
                20..=39 => (b ^ c ^ d, 0x6ED9EBA1),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8F1BBCDC),
                _ => (b ^ c ^ d, 0xCA62C1D6),
            };

            let temp = a.rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(w[i]);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temp;
        }

        h0 = h0.wrapping_add(a);
        h1 = h1.wrapping_add(b);
        h2 = h2.wrapping_add(c);
        h3 = h3.wrapping_add(d);
        h4 = h4.wrapping_add(e);
    }

    let mut out = [0u8; 20];
    out[0..4].copy_from_slice(&h0.to_be_bytes());
    out[4..8].copy_from_slice(&h1.to_be_bytes());
    out[8..12].copy_from_slice(&h2.to_be_bytes());
    out[12..16].copy_from_slice(&h3.to_be_bytes());
    out[16..20].copy_from_slice(&h4.to_be_bytes());
    out
}

/// Base64 encode the input bytes (no_std, zero dependency).
pub fn base64_encode(input: &[u8]) -> String {
    const CHARSET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut result = String::new();
    let mut i = 0;
    while i < input.len() {
        let chunk_len = input.len() - i;
        if chunk_len >= 3 {
            let n = ((input[i] as u32) << 16) | ((input[i + 1] as u32) << 8) | (input[i + 2] as u32);
            result.push(CHARSET[((n >> 18) & 63) as usize] as char);
            result.push(CHARSET[((n >> 12) & 63) as usize] as char);
            result.push(CHARSET[((n >> 6) & 63) as usize] as char);
            result.push(CHARSET[(n & 63) as usize] as char);
            i += 3;
        } else if chunk_len == 2 {
            let n = ((input[i] as u32) << 8) | (input[i + 1] as u32);
            result.push(CHARSET[((n >> 10) & 63) as usize] as char);
            result.push(CHARSET[((n >> 4) & 63) as usize] as char);
            result.push(CHARSET[((n << 2) & 63) as usize] as char);
            result.push('=');
            break;
        } else {
            let n = input[i] as u32;
            result.push(CHARSET[((n >> 2) & 63) as usize] as char);
            result.push(CHARSET[((n << 4) & 63) as usize] as char);
            result.push('=');
            result.push('=');
            break;
        }
    }
    result
}

/// Accepts a WebSocket connection on server_fd, performing the HTTP upgrade handshake.
pub fn ws_accept(server_fd: u64) -> Result<WsConnection, &'static str> {
    // Read the HTTP headers.
    let mut buf = [0u8; 2048];
    let mut total = 0;
    
    for _ in 0..1000 {
        match tcp_recv(server_fd, &mut buf[total..]) {
            Ok(n) if n > 0 => {
                total += n;
                if find_header_end(&buf[..total]).is_some() {
                    break;
                }
            }
            _ => {
                unsafe { crate::syscall3(0, 0, 0, 0); } // Yield
            }
        }
    }

    if total == 0 {
        return Err("ws_accept: no data received");
    }

    let headers = core::str::from_utf8(&buf[..total]).unwrap_or("");
    let mut key_val = "";
    
    for line in headers.lines() {
        let trimmed = line.trim();
        // Case-insensitive check for Sec-WebSocket-Key
        if trimmed.to_lowercase().starts_with("sec-websocket-key:") {
            if let Some((_, val)) = trimmed.split_once(':') {
                key_val = val.trim();
                break;
            }
        }
    }

    if key_val.is_empty() {
        return Err("ws_accept: Sec-WebSocket-Key header not found");
    }

    // Compute accept key
    let mut key_combined = String::from(key_val);
    key_combined.push_str("258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
    let hashed = sha1(key_combined.as_bytes());
    let accept_b64 = base64_encode(&hashed);

    // Write upgrade response headers
    let response = format!(
        "HTTP/1.1 101 Switching Protocols\r\n\
         Upgrade: websocket\r\n\
         Connection: Upgrade\r\n\
         Sec-WebSocket-Accept: {}\r\n\
         \r\n",
        accept_b64
    );

    tcp_send(server_fd, response.as_bytes())?;

    Ok(WsConnection {
        fd: server_fd,
        connected: true,
    })
}
