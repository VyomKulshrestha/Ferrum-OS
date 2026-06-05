// ============================================================================
// Heliox-Daemon - Reflector
// ============================================================================
// Self-improvement module. The reflector observes the agent's performance
// over time and:
//   1. Tracks failure patterns (which tools fail, why, how often)
//   2. Stores "lessons learned" in vector memory
//   3. Periodically consolidates observations into actionable insights
//   4. Provides context to the planner/orchestrator to avoid repeating mistakes
//
// This replaces the original Heliox-OS Python reflector that used
// ChromaDB + GPT-4 for self-reflection.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;

/// A record of a single failure event.
#[derive(Debug, Clone)]
pub struct FailureRecord {
    pub tick: u64,
    pub tool_name: String,
    pub error: String,
    pub context: String,
}

/// A consolidated lesson learned from repeated failures.
#[derive(Debug, Clone)]
pub struct Lesson {
    pub id: String,
    pub content: String,
    pub source_failures: u32,
    pub created_at_tick: u64,
}

/// The Reflector tracks failures and generates lessons.
pub struct Reflector {
    /// Recent failure records (sliding window).
    failures: Vec<FailureRecord>,
    /// Consolidated lessons learned.
    lessons: Vec<Lesson>,
    /// Maximum number of failures to keep in the sliding window.
    max_failures: usize,
    /// Counter for generating unique lesson IDs.
    lesson_counter: u32,
    /// Tick interval for periodic consolidation.
    consolidation_interval: u64,
    /// Last tick at which consolidation was performed.
    last_consolidation: u64,
}

impl Reflector {
    pub fn new() -> Self {
        Self {
            failures: Vec::new(),
            lessons: Vec::new(),
            max_failures: 50,
            lesson_counter: 0,
            consolidation_interval: 500,
            last_consolidation: 0,
        }
    }

    /// Record a failure event.
    pub fn record_failure(
        &mut self,
        tick: u64,
        tool_name: &str,
        error: &str,
        context: &str,
    ) {
        self.failures.push(FailureRecord {
            tick,
            tool_name: String::from(tool_name),
            error: String::from(error),
            context: String::from(context),
        });

        // Trim old failures if we exceed the window
        if self.failures.len() > self.max_failures {
            self.failures.remove(0);
        }
    }

    /// Periodic consolidation: analyze failure patterns and generate lessons.
    /// Returns newly generated lessons (if any).
    pub fn consolidate(&mut self, current_tick: u64) -> Vec<Lesson> {
        if current_tick - self.last_consolidation < self.consolidation_interval {
            return Vec::new();
        }
        self.last_consolidation = current_tick;

        let mut new_lessons = Vec::new();

        // Pattern 1: Repeated failures of the same tool
        let tool_names: Vec<String> = self.failures.iter()
            .map(|f| f.tool_name.clone())
            .collect();

        // Count occurrences of each tool name
        let mut tool_counts: Vec<(String, u32)> = Vec::new();
        for name in &tool_names {
            if let Some(entry) = tool_counts.iter_mut().find(|(n, _)| n == name) {
                entry.1 += 1;
            } else {
                tool_counts.push((name.clone(), 1));
            }
        }

        for (tool, count) in &tool_counts {
            if *count >= 3 {
                // Check if we already have a lesson for this tool
                let already_learned = self.lessons.iter().any(|l| {
                    l.content.contains(tool.as_str())
                });
                if !already_learned {
                    self.lesson_counter += 1;
                    let lesson = Lesson {
                        id: format!("lesson-{}", self.lesson_counter),
                        content: format!(
                            "Tool '{}' has failed {} times. Consider: (1) checking preconditions before calling it, \
                             (2) using an alternative approach, (3) verifying the environment supports this operation.",
                            tool, count
                        ),
                        source_failures: *count,
                        created_at_tick: current_tick,
                    };
                    new_lessons.push(lesson.clone());
                    self.lessons.push(lesson);
                }
            }
        }

        // Pattern 2: Rapid consecutive failures (more than 5 failures in 50 ticks)
        let recent_cutoff = current_tick.saturating_sub(50);
        let recent_failures = self.failures.iter()
            .filter(|f| f.tick >= recent_cutoff)
            .count();

        if recent_failures >= 5 {
            let already_has_rapid_lesson = self.lessons.iter().any(|l| {
                l.content.contains("rapid consecutive failures")
            });
            if !already_has_rapid_lesson {
                self.lesson_counter += 1;
                let lesson = Lesson {
                    id: format!("lesson-{}", self.lesson_counter),
                    content: String::from(
                        "Detected rapid consecutive failures. The current approach may be \
                         fundamentally flawed. Consider: (1) stepping back and re-planning, \
                         (2) checking system prerequisites, (3) trying a completely different strategy."
                    ),
                    source_failures: recent_failures as u32,
                    created_at_tick: current_tick,
                };
                new_lessons.push(lesson.clone());
                self.lessons.push(lesson);
            }
        }

        new_lessons
    }

    /// Get all lessons as a formatted string suitable for injection into prompts.
    pub fn lessons_context(&self) -> String {
        if self.lessons.is_empty() {
            return String::new();
        }

        let mut ctx = String::from("\n\nLessons Learned (from past failures):\n");
        for lesson in &self.lessons {
            ctx.push_str("- ");
            ctx.push_str(&lesson.content);
            ctx.push('\n');
        }
        ctx
    }

    /// Get a summary of recent failures for prompt context.
    pub fn recent_failures_context(&self, max_entries: usize) -> String {
        if self.failures.is_empty() {
            return String::new();
        }

        let mut ctx = String::from("\n\nRecent Failures:\n");
        let start = if self.failures.len() > max_entries {
            self.failures.len() - max_entries
        } else {
            0
        };
        for failure in &self.failures[start..] {
            ctx.push_str(&format!(
                "- [tick {}] {}: {}\n",
                failure.tick, failure.tool_name, failure.error
            ));
        }
        ctx
    }

    /// Total number of recorded failures.
    pub fn failure_count(&self) -> usize {
        self.failures.len()
    }

    /// Total number of lessons learned.
    pub fn lesson_count(&self) -> usize {
        self.lessons.len()
    }

    /// Reset the reflector (e.g., when starting a completely new goal).
    pub fn reset(&mut self) {
        self.failures.clear();
        // We keep lessons — they persist across goals.
    }
}
