#[allow(dead_code)]
extern crate alloc;

use alloc::string::String;
use alloc::format;

/// Domain categories for goal classification.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Domain {
    Code,     // Programming, debugging, code analysis
    Web,      // Web browsing, API calls, data fetching
    System,   // OS management, processes, devices, config
    Files,    // File operations, reading, writing, organizing
    General,  // Catch-all for unclassified goals
}

/// Classification result with confidence.
pub struct Classification {
    pub domain: Domain,
    pub confidence: f32, // 0.0 to 1.0
}

/// Per-domain performance statistics.
pub struct DomainStats {
    pub attempts: u32,
    pub successes: u32,
    pub failures: u32,
}

impl DomainStats {
    fn new() -> Self {
        DomainStats {
            attempts: 0,
            successes: 0,
            failures: 0,
        }
    }
}

/// The multi-agent router.
pub struct AgentRouter {
    stats: [(Domain, DomainStats); 5], // One per domain
}

/// Keywords for each domain.
const CODE_KEYWORDS: &[&str] = &[
    "code", "function", "debug", "compile", "program", "bug", "error", "syntax", "implement",
    "refactor",
];
const WEB_KEYWORDS: &[&str] = &[
    "browse", "url", "http", "website", "download", "api", "fetch", "scrape", "web",
];
const SYSTEM_KEYWORDS: &[&str] = &[
    "process", "memory", "device", "service", "cpu", "uptime", "status", "kill", "restart",
];
const FILES_KEYWORDS: &[&str] = &[
    "file", "directory", "read", "write", "create", "delete", "list", "folder", "disk",
];

impl AgentRouter {
    /// Create a new AgentRouter with zeroed stats for all domains.
    pub fn new() -> Self {
        AgentRouter {
            stats: [
                (Domain::Code, DomainStats::new()),
                (Domain::Web, DomainStats::new()),
                (Domain::System, DomainStats::new()),
                (Domain::Files, DomainStats::new()),
                (Domain::General, DomainStats::new()),
            ],
        }
    }

    /// Classify a goal string into a domain.
    /// Uses keyword matching:
    /// - Code: "code", "function", "debug", "compile", "program", "bug", "error", "syntax", "implement", "refactor"
    /// - Web: "browse", "url", "http", "website", "download", "api", "fetch", "scrape", "web"
    /// - System: "process", "memory", "device", "service", "cpu", "uptime", "status", "kill", "restart"
    /// - Files: "file", "directory", "read", "write", "create", "delete", "list", "folder", "disk"
    /// - General: fallback when no keywords match or tie
    pub fn classify(&self, goal: &str) -> Classification {
        let lower = to_lowercase(goal);

        let code_hits = count_keyword_hits(&lower, CODE_KEYWORDS);
        let web_hits = count_keyword_hits(&lower, WEB_KEYWORDS);
        let system_hits = count_keyword_hits(&lower, SYSTEM_KEYWORDS);
        let files_hits = count_keyword_hits(&lower, FILES_KEYWORDS);

        let max_hits = code_hits.max(web_hits).max(system_hits).max(files_hits);

        // No keywords matched
        if max_hits == 0 {
            return Classification {
                domain: Domain::General,
                confidence: 0.0,
            };
        }

        // Check for ties — count how many domains share the max
        let mut tie_count = 0u32;
        if code_hits == max_hits {
            tie_count += 1;
        }
        if web_hits == max_hits {
            tie_count += 1;
        }
        if system_hits == max_hits {
            tie_count += 1;
        }
        if files_hits == max_hits {
            tie_count += 1;
        }

        // Ties go to General
        if tie_count > 1 {
            return Classification {
                domain: Domain::General,
                confidence: 0.5,
            };
        }

        // Determine winning domain
        let domain = if code_hits == max_hits {
            Domain::Code
        } else if web_hits == max_hits {
            Domain::Web
        } else if system_hits == max_hits {
            Domain::System
        } else {
            Domain::Files
        };

        // Confidence: ratio of winning hits to total word count (capped at 1.0)
        let total_hits = code_hits + web_hits + system_hits + files_hits;
        let confidence = if total_hits > 0 {
            let c = max_hits as f32 / total_hits as f32;
            if c > 1.0 { 1.0 } else { c }
        } else {
            0.0
        };

        Classification { domain, confidence }
    }

    /// Get a specialized system prompt suffix for the given domain.
    /// This is appended to the base prompt to focus the LLM on relevant tools.
    pub fn domain_prompt(&self, domain: Domain) -> &'static str {
        match domain {
            Domain::Code => "Focus on code analysis tools. Prefer read_file, write_file, and exec_process. Write clean, working code.",
            Domain::Web => "Focus on web interaction tools. Use browse_url and http_get to fetch data. Extract relevant information from web pages.",
            Domain::System => "Focus on system management tools. Use system_info, list_processes, and service commands. Monitor system health.",
            Domain::Files => "Focus on file management tools. Use read_file, write_file, read_dir, create_directory, and delete_file efficiently.",
            Domain::General => "Use the most appropriate tools for the task. Consider all available capabilities.",
        }
    }

    /// Record a success or failure for the given domain.
    pub fn record_outcome(&mut self, domain: Domain, success: bool) {
        for (d, stats) in self.stats.iter_mut() {
            if *d == domain {
                stats.attempts += 1;
                if success {
                    stats.successes += 1;
                } else {
                    stats.failures += 1;
                }
                return;
            }
        }
    }

    /// Get the success rate for a domain (0.0 to 1.0, or -1.0 if no attempts).
    pub fn success_rate(&self, domain: Domain) -> f32 {
        for (d, stats) in self.stats.iter() {
            if *d == domain {
                if stats.attempts == 0 {
                    return -1.0;
                }
                return stats.successes as f32 / stats.attempts as f32;
            }
        }
        -1.0
    }

    /// Format all domain stats as a summary string.
    pub fn stats_summary(&self) -> String {
        let mut summary = String::from("Domain Stats:\n");

        for (domain, stats) in self.stats.iter() {
            let rate = if stats.attempts == 0 {
                String::from("N/A")
            } else {
                let pct = (stats.successes as f32 / stats.attempts as f32) * 100.0;
                format!("{:.1}%", pct)
            };

            let line = format!(
                "  {:?}: {} attempts, {} successes, {} failures (rate: {})\n",
                domain, stats.attempts, stats.successes, stats.failures, rate
            );
            summary.push_str(&line);
        }

        summary
    }
}

/// Count how many keywords from the list appear in the lowercased goal string.
fn count_keyword_hits(goal: &str, keywords: &[&str]) -> u32 {
    let mut count = 0u32;
    for keyword in keywords {
        if contains_word(goal, keyword) {
            count += 1;
        }
    }
    count
}

/// Check if a word boundary-aware keyword appears in the text.
/// Matches the keyword as a substring (case already lowered).
fn contains_word(text: &str, keyword: &str) -> bool {
    let t_bytes = text.as_bytes();
    let k_bytes = keyword.as_bytes();
    let t_len = t_bytes.len();
    let k_len = k_bytes.len();

    if k_len > t_len {
        return false;
    }

    for i in 0..=(t_len - k_len) {
        if &t_bytes[i..i + k_len] == k_bytes {
            // Check word boundaries
            let before_ok = i == 0 || !is_alphanumeric(t_bytes[i - 1]);
            let after_ok = (i + k_len) == t_len || !is_alphanumeric(t_bytes[i + k_len]);
            if before_ok && after_ok {
                return true;
            }
        }
    }

    false
}

/// Check if a byte is alphanumeric (a-z, A-Z, 0-9, _).
fn is_alphanumeric(b: u8) -> bool {
    matches!(b, b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'_')
}

/// Convert a string to lowercase using alloc.
fn to_lowercase(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    for c in s.chars() {
        for lc in c.to_lowercase() {
            result.push(lc);
        }
    }
    result
}
