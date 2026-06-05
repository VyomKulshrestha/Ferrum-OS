#[allow(dead_code)]
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;

/// Result of browsing a URL.
pub struct BrowseResult {
    pub title: Option<String>,
    pub text: String,
    pub links: Vec<String>,
    pub status_code: u16,
}

/// Strip all HTML tags from a string, returning plain text.
/// - Remove everything between < and > (including the brackets)
/// - Decode common HTML entities: &amp; → &, &lt; → <, &gt; → >,
///   &quot; → ", &apos; → ', &#39; → ', &nbsp; → space
/// - Insert newlines before block-level tags: <p>, <div>, <br>, <br/>,
///   <h1>-<h6>, <li>, <tr>
/// - Collapse multiple consecutive newlines into max 2
/// - Trim leading/trailing whitespace
pub fn strip_html(html: &str) -> String {
    let mut result = String::new();
    let bytes = html.as_bytes();
    let len = bytes.len();
    let mut i = 0;

    while i < len {
        if bytes[i] == b'<' {
            // Check for block-level tags and insert newlines before them
            let tag_start = i;
            let mut tag_end = i + 1;
            while tag_end < len && bytes[tag_end] != b'>' {
                tag_end += 1;
            }
            if tag_end < len {
                let tag_content = &html[tag_start + 1..tag_end];
                let tag_lower = to_lowercase_alloc(tag_content);
                let tag_name = tag_lower.split_whitespace().next().unwrap_or("");
                let tag_name = tag_name.trim_start_matches('/');

                if is_block_tag(tag_name) {
                    result.push('\n');
                }

                i = tag_end + 1;
            } else {
                // Unclosed tag, skip the '<'
                i += 1;
            }
        } else if bytes[i] == b'&' {
            // Decode HTML entities
            let entity_start = i;
            let mut entity_end = i + 1;
            while entity_end < len && bytes[entity_end] != b';' && (entity_end - entity_start) < 10 {
                entity_end += 1;
            }
            if entity_end < len && bytes[entity_end] == b';' {
                let entity = &html[entity_start..entity_end + 1];
                match entity {
                    "&amp;" => result.push('&'),
                    "&lt;" => result.push('<'),
                    "&gt;" => result.push('>'),
                    "&quot;" => result.push('"'),
                    "&apos;" => result.push('\''),
                    "&#39;" => result.push('\''),
                    "&nbsp;" => result.push(' '),
                    _ => {
                        // Unknown entity, keep as-is
                        result.push_str(entity);
                    }
                }
                i = entity_end + 1;
            } else {
                result.push('&');
                i += 1;
            }
        } else {
            result.push(bytes[i] as char);
            i += 1;
        }
    }

    // Collapse multiple consecutive newlines into max 2
    let mut collapsed = String::new();
    let mut newline_count = 0;
    for ch in result.chars() {
        if ch == '\n' {
            newline_count += 1;
            if newline_count <= 2 {
                collapsed.push('\n');
            }
        } else {
            newline_count = 0;
            collapsed.push(ch);
        }
    }

    // Trim leading/trailing whitespace
    let trimmed = collapsed.trim();
    String::from(trimmed)
}

/// Check if a tag name is a block-level element.
fn is_block_tag(tag: &str) -> bool {
    matches!(
        tag,
        "p" | "div" | "br" | "br/" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6" | "li" | "tr"
    )
}

/// Convert a string to lowercase using alloc.
fn to_lowercase_alloc(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    for c in s.chars() {
        for lc in c.to_lowercase() {
            result.push(lc);
        }
    }
    result
}

/// Extract the content of the <title> tag from HTML.
/// Returns None if no title tag found.
pub fn extract_title(html: &str) -> Option<String> {
    let lower = to_lowercase_alloc(html);

    let start_tag = "<title>";
    let end_tag = "</title>";

    let start_idx = find_substr(&lower, start_tag)?;
    let content_start = start_idx + start_tag.len();
    let end_idx = find_substr(&lower[content_start..], end_tag)?;

    let title = &html[content_start..content_start + end_idx];
    let trimmed = title.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(String::from(trimmed))
    }
}

/// Find the byte offset of a substring within a string.
fn find_substr(haystack: &str, needle: &str) -> Option<usize> {
    let h_bytes = haystack.as_bytes();
    let n_bytes = needle.as_bytes();
    if n_bytes.len() > h_bytes.len() {
        return None;
    }
    for i in 0..=(h_bytes.len() - n_bytes.len()) {
        if &h_bytes[i..i + n_bytes.len()] == n_bytes {
            return Some(i);
        }
    }
    None
}

/// Extract all href URLs from <a> tags.
/// Returns a Vec of URL strings.
pub fn extract_links(html: &str) -> Vec<String> {
    let mut links = Vec::new();
    let bytes = html.as_bytes();
    let len = bytes.len();
    let mut i = 0;

    while i < len {
        // Look for <a or <A
        if bytes[i] == b'<' && i + 1 < len && (bytes[i + 1] == b'a' || bytes[i + 1] == b'A') {
            // Make sure it's actually an <a tag (followed by space or >)
            if i + 2 < len && (bytes[i + 2] == b' ' || bytes[i + 2] == b'>' || bytes[i + 2] == b'\t' || bytes[i + 2] == b'\n') {
                // Find the end of this tag
                let tag_start = i;
                let mut tag_end = i + 2;
                while tag_end < len && bytes[tag_end] != b'>' {
                    tag_end += 1;
                }
                if tag_end < len {
                    let tag_content = &html[tag_start..tag_end + 1];
                    if let Some(href) = extract_href(tag_content) {
                        links.push(href);
                    }
                    i = tag_end + 1;
                } else {
                    i += 1;
                }
            } else {
                i += 1;
            }
        } else {
            i += 1;
        }
    }

    links
}

/// Extract the href attribute value from an <a> tag string.
fn extract_href(tag: &str) -> Option<String> {
    let lower = to_lowercase_alloc(tag);

    let href_patterns = ["href=\"", "href='", "href = \"", "href = '"];

    for pattern in &href_patterns {
        if let Some(start) = find_substr(&lower, pattern) {
            let quote_char = if pattern.ends_with('"') { b'"' } else { b'\'' };
            let value_start = start + pattern.len();
            let rest = &tag[value_start..];
            let rest_bytes = rest.as_bytes();
            let mut end = 0;
            while end < rest_bytes.len() && rest_bytes[end] != quote_char {
                end += 1;
            }
            if end < rest_bytes.len() {
                let url = &rest[..end];
                let trimmed = url.trim();
                if !trimmed.is_empty() {
                    return Some(String::from(trimmed));
                }
            }
        }
    }

    None
}

/// Parse a URL into (host, port, path) components.
/// Only supports http:// scheme.
fn parse_url(url: &str) -> Result<(String, u16, String), &'static str> {
    let url = url.trim();

    if !url.starts_with("http://") {
        return Err("only http:// URLs are supported");
    }

    let without_scheme = &url[7..]; // skip "http://"

    // Split host+port from path
    let (host_port, path) = match find_substr(without_scheme, "/") {
        Some(idx) => (&without_scheme[..idx], String::from(&without_scheme[idx..])),
        None => (without_scheme, String::from("/")),
    };

    // Split host from port
    let (host, port) = match find_substr(host_port, ":") {
        Some(idx) => {
            let host = &host_port[..idx];
            let port_str = &host_port[idx + 1..];
            let port = parse_u16(port_str).ok_or("invalid port number")?;
            (String::from(host), port)
        }
        None => (String::from(host_port), 80u16),
    };

    if host.is_empty() {
        return Err("empty host");
    }

    Ok((host, port, path))
}

/// Parse a string to u16 without std.
fn parse_u16(s: &str) -> Option<u16> {
    let mut result: u16 = 0;
    if s.is_empty() {
        return None;
    }
    for b in s.bytes() {
        if b < b'0' || b > b'9' {
            return None;
        }
        result = result.checked_mul(10)?;
        result = result.checked_add((b - b'0') as u16)?;
    }
    Some(result)
}

/// Fetch a URL via HTTP GET and return the response body.
/// Uses crate::network::http_get(host, port, path) which is already available.
/// Parse the URL to extract host, port (default 80), and path.
/// Returns (status_code, body_text).
pub fn fetch_url(url: &str) -> Result<(u16, String), &'static str> {
    let (host, port, path) = parse_url(url)?;

    // Verify the host can be resolved before calling http_get
    if crate::network::resolve_host(&host).is_none() {
        return Err("cannot resolve host");
    }

    let response = crate::network::http_get(&host, port, &path)?;

    Ok((response.status_code, response.body))
}

/// Fetch a URL and extract clean text content.
/// Combines fetch_url + strip_html.
/// Returns: title (if any) + clean text body.
pub fn browse(url: &str) -> Result<BrowseResult, &'static str> {
    let (status_code, body) = fetch_url(url)?;

    let title = extract_title(&body);
    let links = extract_links(&body);
    let text = strip_html(&body);

    Ok(BrowseResult {
        title,
        text,
        links,
        status_code,
    })
}
