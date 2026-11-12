//! fi1 kernel round 3: the daemon's HTTP response framing
//! (`heliox-daemon/src/http_parse.rs`, compiled from its own source).

use heliox_gate_tests::http_parse::{
    decode_chunked_body, parse_http_response, receive_response, ws_payload_len, MAX_HTTP_RESPONSE,
};

/// Feed `data` to `receive_response` in pieces of `step` bytes, with a
/// "blocked" before every piece, then end of stream.
fn receive(data: &[u8], step: usize) -> Result<Vec<u8>, &'static str> {
    let mut at = 0;
    let mut blocked = false;
    receive_response(
        |buf| {
            blocked = !blocked;
            if blocked {
                return Err("blocked");
            }
            let n = step.min(buf.len()).min(data.len() - at);
            buf[..n].copy_from_slice(&data[at..at + n]);
            at += n;
            Ok(n)
        },
        || {},
    )
}

#[test]
fn chunk_size_that_wraps_the_offset_is_an_error_not_a_panic() {
    // Body starts after "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n".
    // A chunk size of usize::MAX - offset made chunk_end = usize::MAX and
    // chunk_end + 2 wrapped to 1 (release build), so the bounds test passed
    // and the slice panicked.
    let offset_after_size_line = 18; // "ffffffffffffffed\r\n"
    let size = usize::MAX - offset_after_size_line;
    let body = format!("{:x}\r\nab\r\n0\r\n\r\n", size);
    assert_eq!(body.find("\r\n").unwrap() + 2, offset_after_size_line);
    assert!(decode_chunked_body(body.as_bytes()).is_err());
    for size in [usize::MAX, usize::MAX - 1, usize::MAX - 2, usize::MAX / 2] {
        let body = format!("{:x}\r\nab\r\n0\r\n\r\n", size);
        assert!(decode_chunked_body(body.as_bytes()).is_err(), "size {size:x}");
    }
}

#[test]
fn chunked_bodies_decode_and_malformed_ones_are_refused() {
    assert_eq!(decode_chunked_body(b"3\r\nabc\r\n2;x=y\r\nde\r\n0\r\n\r\n").unwrap(), b"abcde");
    assert!(decode_chunked_body(b"3\r\nabc\r\n").is_err(), "no terminal chunk");
    assert!(decode_chunked_body(b"5\r\nabc\r\n0\r\n\r\n").is_err(), "short chunk");
    assert!(decode_chunked_body(b"3\r\nabcXY0\r\n\r\n").is_err(), "no CRLF after data");
    assert!(decode_chunked_body(b"zz\r\nab\r\n0\r\n\r\n").is_err(), "not hex");
    assert!(decode_chunked_body(b"\r\n").is_err(), "empty size");
    assert!(decode_chunked_body(b"00000000000000003\r\nabc\r\n0\r\n\r\n").is_err(), "17 hex digits");
    assert!(decode_chunked_body(b"").is_err());
}

#[test]
fn a_response_longer_than_the_limit_is_an_error_not_a_truncated_body() {
    let body = "x".repeat(MAX_HTTP_RESPONSE);
    let raw = format!("HTTP/1.1 200 OK\r\n\r\n{}", body);
    assert_eq!(receive(raw.as_bytes(), 1500).unwrap_err(), "HTTP response larger than the 1 MiB limit");
    // 40 KiB used to be cut at 32 KiB and parsed as a complete body.
    let body = "y".repeat(40 * 1024);
    let raw = format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{}", body.len(), body);
    let got = receive(raw.as_bytes(), 1460).unwrap();
    assert_eq!(parse_http_response(&got).unwrap().body.len(), 40 * 1024);
    // Exactly at the limit, then closed: accepted.
    let head = "HTTP/1.1 200 OK\r\n\r\n";
    let raw = format!("{}{}", head, "z".repeat(MAX_HTTP_RESPONSE - head.len()));
    assert_eq!(receive(raw.as_bytes(), 4096).unwrap().len(), MAX_HTTP_RESPONSE);
}

#[test]
fn content_length_frames_the_body() {
    let r = parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhelloEXTRA").unwrap();
    assert_eq!((r.status_code, r.body.as_str()), (200, "hello"));
    assert_eq!(
        parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nhello").unwrap_err(),
        "truncated HTTP body"
    );
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nContent-Length: 6\r\n\r\nhello!").is_err());
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\nx").is_err());
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 99999999999999999999\r\n\r\nx").is_err());
    // Repeated identical values are fine; chunked wins over Content-Length.
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\ncontent-length: 2\r\n\r\nok").is_ok());
    let r = parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\nTransfer-Encoding: chunked\r\n\r\n2\r\nok\r\n0\r\n\r\n").unwrap();
    assert_eq!(r.body, "ok");
    // The receive loop stops at the declared length without waiting for close.
    let mut calls = 0;
    let raw = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok";
    let got = receive_response(
        |buf| {
            calls += 1;
            if calls > 1 {
                panic!("read past a complete Content-Length response");
            }
            buf[..raw.len()].copy_from_slice(raw);
            Ok(raw.len())
        },
        || {},
    )
    .unwrap();
    assert_eq!(&got[..], &raw[..]);
}

#[test]
fn status_line_and_headers_are_checked() {
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\n\r\nbody").is_ok());
    assert!(parse_http_response(b"HTTP/1.0 404 Not Found\r\n\r\n").is_ok());
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\nX: y").is_err(), "no header terminator");
    assert!(parse_http_response(b"HTTP/2 200\r\n\r\n").is_err());
    assert!(parse_http_response(b"HTTP/1.1 20 OK\r\n\r\n").is_err());
    assert!(parse_http_response(b"HTTP/1.1 999 X\r\n\r\n").is_err());
    assert!(parse_http_response(b"garbage\r\n\r\n").is_err());
    assert!(parse_http_response(b"HTTP/1.1 200 OK\r\n\r\n\xff\xfe").is_err(), "invalid UTF-8 body is an error");
    // A redirect is reported, not followed.
    let r = parse_http_response(b"HTTP/1.1 302 Found\r\nLocation: http://elsewhere/\r\n\r\n").unwrap();
    assert_eq!(r.status_code, 302);
}

#[test]
fn an_empty_stream_and_reader_errors_are_errors() {
    assert!(receive(b"", 10).is_err());
    let mut first = true;
    let r = receive_response(
        |_buf| {
            if first {
                first = false;
                Err("connection reset")
            } else {
                Ok(0)
            }
        },
        || {},
    );
    assert_eq!(r.unwrap_err(), "connection reset");
}

#[test]
fn websocket_frame_length_is_bounded() {
    assert_eq!(ws_payload_len(125).unwrap(), 125);
    assert_eq!(ws_payload_len(1024 * 1024).unwrap(), 1024 * 1024);
    assert!(ws_payload_len(1024 * 1024 + 1).is_err());
    assert!(ws_payload_len(u64::MAX).is_err());
}

#[test]
fn the_daemon_uses_the_bounded_paths() {
    let net = heliox_gate_tests::NETWORK_SOURCE;
    assert!(!net.contains("vec![0u8; 32768]"), "fixed 32 KiB response buffers are gone");
    assert_eq!(net.matches("receive_response(").count(), 4, "http_get, http_post, http_post_binary, TLS");
    assert!(net.contains("crate::http_parse::ws_payload_len("));
    assert!(!net.contains("return ws_recv_frame(conn)"), "pings no longer recurse");
}
