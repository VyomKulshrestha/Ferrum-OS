// ============================================================================
// Heliox-Daemon - Verifier
// ============================================================================
// Post-execution validation module. After each tool execution, the verifier
// compares the expected outcome (from the plan) against the actual result
// and produces a verification verdict.
//
// Verification Strategies:
//   - Exit code check: did the tool report success?
//   - Output pattern match: does the output contain expected keywords?
//   - Side-effect check: did the expected file/state change happen?
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;

/// The result of a verification check.
#[derive(Debug, Clone, PartialEq)]
pub enum Verdict {
    /// The action succeeded and the result matches expectations.
    Pass,
    /// The action succeeded but the result is ambiguous or partially correct.
    Partial(String),
    /// The action failed or the result does not match expectations.
    Fail(String),
}

/// A single verification record.
#[derive(Debug, Clone)]
pub struct VerificationRecord {
    pub tool_name: String,
    pub expected: String,
    pub actual: String,
    pub verdict: Verdict,
}

/// The Verifier checks tool execution results against expectations.
pub struct Verifier {
    /// History of all verification records for the current goal.
    history: Vec<VerificationRecord>,
    /// Consecutive failure count (resets on Pass).
    consecutive_failures: u32,
}

impl Verifier {
    pub fn new() -> Self {
        Self {
            history: Vec::new(),
            consecutive_failures: 0,
        }
    }

    /// Verify a tool execution result.
    ///
    /// `tool_name`: the name of the tool that was executed.
    /// `success`: whether the tool reported success.
    /// `output`: the output string from the tool.
    /// `expected_keywords`: optional keywords that should appear in the output.
    pub fn verify(
        &mut self,
        tool_name: &str,
        success: bool,
        output: &str,
        expected_keywords: &[&str],
    ) -> Verdict {
        let verdict = if !success {
            Verdict::Fail(format!("Tool '{}' reported failure", tool_name))
        } else if expected_keywords.is_empty() {
            // No expectations beyond success
            Verdict::Pass
        } else {
            // Check if expected keywords are present in the output
            let mut found = 0;
            for kw in expected_keywords {
                if output.contains(kw) {
                    found += 1;
                }
            }
            if found == expected_keywords.len() {
                Verdict::Pass
            } else if found > 0 {
                Verdict::Partial(format!(
                    "Found {}/{} expected keywords in output",
                    found,
                    expected_keywords.len()
                ))
            } else {
                Verdict::Fail(format!(
                    "None of the expected keywords found in output"
                ))
            }
        };

        // Update consecutive failure tracking
        match &verdict {
            Verdict::Pass => self.consecutive_failures = 0,
            Verdict::Partial(_) => {} // don't reset, don't increment
            Verdict::Fail(_) => self.consecutive_failures += 1,
        }

        let record = VerificationRecord {
            tool_name: String::from(tool_name),
            expected: if expected_keywords.is_empty() {
                String::from("(any success)")
            } else {
                let mut s = String::new();
                for (i, kw) in expected_keywords.iter().enumerate() {
                    if i > 0 { s.push_str(", "); }
                    s.push_str(kw);
                }
                s
            },
            actual: String::from(output),
            verdict: verdict.clone(),
        };
        self.history.push(record);

        verdict
    }

    /// Returns the number of consecutive failures.
    pub fn consecutive_failures(&self) -> u32 {
        self.consecutive_failures
    }

    /// Returns true if the agent should retry (consecutive failures < threshold).
    pub fn should_retry(&self, max_retries: u32) -> bool {
        self.consecutive_failures > 0 && self.consecutive_failures < max_retries
    }

    /// Returns true if the agent should abandon the current approach
    /// (too many consecutive failures).
    pub fn should_abandon(&self, max_retries: u32) -> bool {
        self.consecutive_failures >= max_retries
    }

    /// Get the last verification record.
    pub fn last_record(&self) -> Option<&VerificationRecord> {
        self.history.last()
    }

    /// Get a summary of all verification history for this goal.
    pub fn summary(&self) -> String {
        let total = self.history.len();
        let passes = self.history.iter().filter(|r| r.verdict == Verdict::Pass).count();
        let fails = self.history.iter().filter(|r| matches!(r.verdict, Verdict::Fail(_))).count();
        let partials = total - passes - fails;
        format!(
            "Verification: {}/{} pass, {} partial, {} fail",
            passes, total, partials, fails
        )
    }

    /// Reset the verifier for a new goal.
    pub fn reset(&mut self) {
        self.history.clear();
        self.consecutive_failures = 0;
    }
}
