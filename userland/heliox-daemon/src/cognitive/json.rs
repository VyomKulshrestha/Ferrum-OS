// ============================================================================
// Heliox-Daemon - Lightweight no_std JSON Parser
// ============================================================================
// A minimal JSON parser for bare-metal environments. Handles the subset
// of JSON needed to parse LLM API responses (objects, arrays, strings,
// numbers, booleans, null).
// ============================================================================

use alloc::string::String;
use alloc::vec::Vec;

/// A JSON value.
#[derive(Debug, Clone)]
pub enum JsonValue {
    Null,
    Bool(bool),
    Number(f64),
    Str(String),
    Array(Vec<JsonValue>),
    Object(Vec<(String, JsonValue)>),
}

impl JsonValue {
    /// Get a value by key if this is an object.
    pub fn get(&self, key: &str) -> Option<&JsonValue> {
        if let JsonValue::Object(pairs) = self {
            for (k, v) in pairs {
                if k == key {
                    return Some(v);
                }
            }
        }
        None
    }

    /// Get as string slice.
    pub fn as_str(&self) -> Option<&str> {
        if let JsonValue::Str(s) = self {
            Some(s)
        } else {
            None
        }
    }

    /// Get as f64.
    pub fn as_f64(&self) -> Option<f64> {
        if let JsonValue::Number(n) = self {
            Some(*n)
        } else {
            None
        }
    }

    /// Get as boolean.
    pub fn as_bool(&self) -> Option<bool> {
        if let JsonValue::Bool(b) = self {
            Some(*b)
        } else {
            None
        }
    }

    /// Get as array.
    pub fn as_array(&self) -> Option<&Vec<JsonValue>> {
        if let JsonValue::Array(a) = self {
            Some(a)
        } else {
            None
        }
    }

    /// Get as object pairs.
    pub fn as_object(&self) -> Option<&Vec<(String, JsonValue)>> {
        if let JsonValue::Object(o) = self {
            Some(o)
        } else {
            None
        }
    }

    /// Check if this value is null.
    pub fn is_null(&self) -> bool {
        matches!(self, JsonValue::Null)
    }
}

// ---- Parser ----------------------------------------------------------------

struct Parser<'a> {
    input: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn new(input: &'a str) -> Self {
        Self {
            input: input.as_bytes(),
            pos: 0,
        }
    }

    fn peek(&self) -> Option<u8> {
        if self.pos < self.input.len() {
            Some(self.input[self.pos])
        } else {
            None
        }
    }

    fn advance(&mut self) -> Option<u8> {
        if self.pos < self.input.len() {
            let ch = self.input[self.pos];
            self.pos += 1;
            Some(ch)
        } else {
            None
        }
    }

    fn skip_whitespace(&mut self) {
        while let Some(ch) = self.peek() {
            if ch == b' ' || ch == b'\t' || ch == b'\n' || ch == b'\r' {
                self.pos += 1;
            } else {
                break;
            }
        }
    }

    fn expect(&mut self, expected: u8) -> Result<(), &'static str> {
        self.skip_whitespace();
        match self.advance() {
            Some(ch) if ch == expected => Ok(()),
            _ => Err("unexpected character"),
        }
    }

    fn parse_value(&mut self) -> Result<JsonValue, &'static str> {
        self.skip_whitespace();
        match self.peek() {
            Some(b'"') => self.parse_string().map(JsonValue::Str),
            Some(b'{') => self.parse_object(),
            Some(b'[') => self.parse_array(),
            Some(b't') => self.parse_literal(b"true", JsonValue::Bool(true)),
            Some(b'f') => self.parse_literal(b"false", JsonValue::Bool(false)),
            Some(b'n') => self.parse_literal(b"null", JsonValue::Null),
            Some(ch) if ch == b'-' || ch.is_ascii_digit() => self.parse_number(),
            _ => Err("unexpected token"),
        }
    }

    fn parse_string(&mut self) -> Result<String, &'static str> {
        self.expect(b'"')?;
        let mut s = String::new();
        loop {
            match self.advance() {
                Some(b'"') => return Ok(s),
                Some(b'\\') => {
                    match self.advance() {
                        Some(b'"') => s.push('"'),
                        Some(b'\\') => s.push('\\'),
                        Some(b'/') => s.push('/'),
                        Some(b'n') => s.push('\n'),
                        Some(b'r') => s.push('\r'),
                        Some(b't') => s.push('\t'),
                        Some(b'u') => {
                            // Parse \uXXXX — skip for now, emit replacement char
                            for _ in 0..4 {
                                self.advance();
                            }
                            s.push('\u{FFFD}');
                        }
                        _ => return Err("invalid escape"),
                    }
                }
                Some(ch) => s.push(ch as char),
                None => return Err("unterminated string"),
            }
        }
    }

    fn parse_number(&mut self) -> Result<JsonValue, &'static str> {
        let start = self.pos;
        // Consume sign
        if self.peek() == Some(b'-') {
            self.pos += 1;
        }
        // Consume digits
        while let Some(ch) = self.peek() {
            if ch.is_ascii_digit() || ch == b'.' || ch == b'e' || ch == b'E' || ch == b'+' || ch == b'-' {
                // Avoid consuming a leading '-' that's part of the next token
                if (ch == b'+' || ch == b'-') && self.pos > start + 1 {
                    let prev = self.input[self.pos - 1];
                    if prev != b'e' && prev != b'E' {
                        break;
                    }
                }
                self.pos += 1;
            } else {
                break;
            }
        }
        let num_str = core::str::from_utf8(&self.input[start..self.pos])
            .map_err(|_| "invalid number")?;
        // Simple integer/float parsing without std
        let val = parse_f64(num_str).ok_or("invalid number")?;
        Ok(JsonValue::Number(val))
    }

    fn parse_object(&mut self) -> Result<JsonValue, &'static str> {
        self.expect(b'{')?;
        let mut pairs = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(JsonValue::Object(pairs));
        }
        loop {
            self.skip_whitespace();
            let key = self.parse_string()?;
            self.expect(b':')?;
            let value = self.parse_value()?;
            pairs.push((key, value));
            self.skip_whitespace();
            match self.peek() {
                Some(b',') => { self.pos += 1; }
                Some(b'}') => { self.pos += 1; return Ok(JsonValue::Object(pairs)); }
                _ => return Err("expected , or }"),
            }
        }
    }

    fn parse_array(&mut self) -> Result<JsonValue, &'static str> {
        self.expect(b'[')?;
        let mut items = Vec::new();
        self.skip_whitespace();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(JsonValue::Array(items));
        }
        loop {
            let value = self.parse_value()?;
            items.push(value);
            self.skip_whitespace();
            match self.peek() {
                Some(b',') => { self.pos += 1; }
                Some(b']') => { self.pos += 1; return Ok(JsonValue::Array(items)); }
                _ => return Err("expected , or ]"),
            }
        }
    }

    fn parse_literal(&mut self, expected: &[u8], value: JsonValue) -> Result<JsonValue, &'static str> {
        for &byte in expected {
            match self.advance() {
                Some(ch) if ch == byte => {}
                _ => return Err("invalid literal"),
            }
        }
        Ok(value)
    }
}

/// Parse a JSON string into a JsonValue.
pub fn parse(input: &str) -> Result<JsonValue, &'static str> {
    let mut parser = Parser::new(input);
    let value = parser.parse_value()?;
    Ok(value)
}

// ---- f64 parsing (no_std) --------------------------------------------------

/// Parse a floating point number from a string without std.
fn parse_f64(s: &str) -> Option<f64> {
    let bytes = s.as_bytes();
    if bytes.is_empty() {
        return None;
    }

    let mut i = 0;
    let negative = if bytes[0] == b'-' {
        i += 1;
        true
    } else {
        false
    };

    // Integer part
    let mut int_part: f64 = 0.0;
    while i < bytes.len() && bytes[i].is_ascii_digit() {
        int_part = int_part * 10.0 + (bytes[i] - b'0') as f64;
        i += 1;
    }

    // Fractional part
    let mut frac_part: f64 = 0.0;
    if i < bytes.len() && bytes[i] == b'.' {
        i += 1;
        let mut divisor: f64 = 10.0;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            frac_part += (bytes[i] - b'0') as f64 / divisor;
            divisor *= 10.0;
            i += 1;
        }
    }

    let mut result = int_part + frac_part;

    // Exponent part
    if i < bytes.len() && (bytes[i] == b'e' || bytes[i] == b'E') {
        i += 1;
        let exp_negative = if i < bytes.len() && bytes[i] == b'-' {
            i += 1;
            true
        } else {
            if i < bytes.len() && bytes[i] == b'+' {
                i += 1;
            }
            false
        };
        let mut exp: i32 = 0;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            exp = exp * 10 + (bytes[i] - b'0') as i32;
            i += 1;
        }
        if exp_negative {
            exp = -exp;
        }
        // Apply exponent via repeated multiply/divide
        if exp > 0 {
            for _ in 0..exp {
                result *= 10.0;
            }
        } else {
            for _ in 0..(-exp) {
                result /= 10.0;
            }
        }
    }

    if negative {
        result = -result;
    }

    Some(result)
}

// ---- LLM Response Helpers --------------------------------------------------

/// A parsed tool call from an LLM response.
#[derive(Debug, Clone)]
pub struct ToolCall {
    pub name: String,
    pub arguments: Vec<(String, JsonValue)>,
}

/// Extract tool calls from an OpenAI-compatible chat completion response.
/// Expected structure:
/// ```json
/// { "choices": [{ "message": { "tool_calls": [{ "function": { "name": "...", "arguments": "{...}" } }] } }] }
/// ```
pub fn extract_tool_calls(response: &JsonValue) -> Vec<ToolCall> {
    let mut calls = Vec::new();

    let choices = match response.get("choices").and_then(|c| c.as_array()) {
        Some(c) => c,
        None => return calls,
    };

    for choice in choices {
        let message = match choice.get("message") {
            Some(m) => m,
            None => continue,
        };

        // Check for tool_calls array
        if let Some(tool_calls) = message.get("tool_calls").and_then(|t| t.as_array()) {
            for tc in tool_calls {
                if let Some(func) = tc.get("function") {
                    let name = func.get("name")
                        .and_then(|n| n.as_str())
                        .unwrap_or("")
                        .into();
                    
                    // Arguments may be a JSON string that needs re-parsing
                    let arguments = match func.get("arguments") {
                        Some(JsonValue::Str(args_str)) => {
                            // Re-parse the arguments string as JSON
                            match parse(args_str) {
                                Ok(JsonValue::Object(pairs)) => pairs,
                                _ => Vec::new(),
                            }
                        }
                        Some(JsonValue::Object(pairs)) => pairs.clone(),
                        _ => Vec::new(),
                    };

                    calls.push(ToolCall { name, arguments });
                }
            }
        }

        // Also handle simple content-based tool calls (Ollama format)
        // Look for {"tool": "name", "args": {...}} in the content
        if let Some(content) = message.get("content").and_then(|c| c.as_str()) {
            if let Ok(parsed) = parse(content) {
                if let Some(tool_name) = parsed.get("tool").and_then(|t| t.as_str()) {
                    let arguments = parsed.get("args")
                        .and_then(|a| a.as_object())
                        .cloned()
                        .unwrap_or_default();
                    calls.push(ToolCall {
                        name: String::from(tool_name),
                        arguments,
                    });
                }
            }
        }
    }

    calls
}

/// Extract the plain text response content from an Ollama API response.
/// Expected: `{ "response": "..." }` or `{ "choices": [{ "message": { "content": "..." } }] }`
pub fn extract_content(response: &JsonValue) -> Option<String> {
    // Ollama format
    if let Some(resp) = response.get("response").and_then(|r| r.as_str()) {
        return Some(String::from(resp));
    }
    // OpenAI format
    if let Some(choices) = response.get("choices").and_then(|c| c.as_array()) {
        if let Some(first) = choices.first() {
            if let Some(content) = first.get("message")
                .and_then(|m| m.get("content"))
                .and_then(|c| c.as_str())
            {
                return Some(String::from(content));
            }
        }
    }
    None
}

/// Helper: extract a string argument from a list of tool arguments.
pub fn find_tool_arg_string(args: &[(String, JsonValue)], key: &str) -> Option<String> {
    for (k, v) in args {
        if k == key {
            return v.as_str().map(String::from);
        }
    }
    None
}

/// Helper: extract a numeric argument from a list of tool arguments.
pub fn find_tool_arg_number(args: &[(String, JsonValue)], key: &str) -> Option<f64> {
    for (k, v) in args {
        if k == key {
            return v.as_f64();
        }
    }
    None
}
