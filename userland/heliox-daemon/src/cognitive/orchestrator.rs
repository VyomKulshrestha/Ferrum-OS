// ============================================================================
// Heliox-Daemon - Orchestrator
// ============================================================================
// The main agent loop implementing the ReAct (Reasoning + Acting) pattern:
//
//   1. OBSERVE  — Gather context: last result, relevant memories (RAG),
//                 lessons learned, plan progress.
//   2. THINK   — Generate a prompt and query the LLM for the next action.
//   3. ACT     — Parse the LLM response and execute tool calls.
//   4. VERIFY  — Check tool results against expectations.
//   5. REFLECT — Record failures, consolidate lessons, update memory.
//   6. REPEAT  — Loop back to OBSERVE with the new observation.
//
// Retry Logic:
//   - If a tool call fails, the orchestrator retries up to MAX_RETRIES
//     times with the failure context included in the next prompt.
//   - If MAX_RETRIES is exceeded, the reflector logs a lesson and the
//     planner skips the failed task.
// ============================================================================

use super::planner::Planner;
use super::verifier::{Verifier, Verdict};
use super::reflector::Reflector;
use super::confirmation::ConfirmationGate;
use super::json;
use super::tool_mapper;
use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;
use crate::memory::vector_store::{VectorStore, MemoryCategory};
use crate::network;

/// Maximum retries for a single tool call before giving up.
const MAX_RETRIES: u32 = 3;

/// How many ticks between each LLM call (avoid flooding).
const TICK_INTERVAL: u64 = 100;

/// How many ticks between memory persistence saves.
const SAVE_INTERVAL: u64 = 1000;

/// Default auto-approve tier (0-2 are auto-approved).
const DEFAULT_AUTO_APPROVE_TIER: u8 = 2;

/// Default confirmation timeout in ticks.
const DEFAULT_CONFIRM_TIMEOUT: u64 = 600;

/// The main orchestrator driving the ReAct agent loop.
pub struct Orchestrator {
    planner: Planner,
    verifier: Verifier,
    reflector: Reflector,
    confirmation_gate: ConfirmationGate,
    memory: VectorStore,
    tick_count: u64,
    last_observation: String,
    last_action: Option<String>,
    last_response: Option<String>,
    /// Running count of total actions executed.
    total_actions: u64,
    /// Running count of total failures.
    total_failures: u64,
    /// Auto-approve tier threshold.
    auto_approve_tier: u8,
}

impl Orchestrator {
    pub fn new() -> Self {
        let mut planner = Planner::new();
        planner.set_goal("Explore the system and ensure everything is functioning.");

        Self {
            planner,
            verifier: Verifier::new(),
            reflector: Reflector::new(),
            confirmation_gate: ConfirmationGate::new(DEFAULT_CONFIRM_TIMEOUT),
            memory: VectorStore::new(),
            tick_count: 0,
            last_observation: String::new(),
            last_action: None,
            last_response: None,
            total_actions: 0,
            total_failures: 0,
            auto_approve_tier: DEFAULT_AUTO_APPROVE_TIER,
        }
    }

    /// Main tick function called from the daemon's main loop.
    pub fn tick(&mut self) {
        self.tick_count += 1;

        // Only attempt LLM calls at the configured interval
        if self.tick_count % TICK_INTERVAL != 0 {
            return;
        }

        // Periodically save vector memory to disk
        if self.tick_count % SAVE_INTERVAL == 0 && self.memory.document_count() > 0 {
            let _ = self.memory.save("/disk/heliox/memory.json");
        }

        // Clean up expired confirmations
        self.confirmation_gate.cleanup_expired(self.tick_count);

        // Periodically consolidate reflections
        let new_lessons = self.reflector.consolidate(self.tick_count);
        for lesson in &new_lessons {
            self.memory.add(
                lesson.id.clone(),
                lesson.content.clone(),
                MemoryCategory::Lesson,
            );
        }

        // ==================== ReAct Loop ====================

        // 1. OBSERVE — Build context
        self.observe();

        // 2. THINK — Generate prompt and query LLM
        let response = match self.think() {
            Some(r) => r,
            None => return, // LLM not available, try next tick
        };

        // 3. ACT — Parse and execute tool calls
        let actions = self.act(&response);

        // 4. VERIFY + REFLECT — Check results and learn
        for (tool_name, success, output) in &actions {
            self.verify_and_reflect(tool_name, *success, output);
        }

        // If no tool calls were made, store the text response as context
        if actions.is_empty() {
            self.last_observation = response.clone();
            self.memory.add(
                format!("response-{}", self.tick_count),
                response,
                MemoryCategory::Interaction,
            );
        }
    }

    /// OBSERVE phase: gather all context for the next prompt.
    fn observe(&mut self) {
        // RAG: Search vector memory for relevant context
        if !self.last_observation.is_empty() {
            let results = self.memory.search(&self.last_observation, 3, None);
            if !results.is_empty() {
                let mut ctx = String::new();
                for doc in results {
                    ctx.push_str("- [");
                    ctx.push_str(doc.category.as_str());
                    ctx.push_str("] ");
                    let content = if doc.content.len() > 200 {
                        &doc.content[..200]
                    } else {
                        &doc.content
                    };
                    ctx.push_str(content);
                    ctx.push('\n');
                }
                self.planner.set_memory_context(&ctx);
            }
        }

        // Inject lessons learned from the reflector
        let lessons = self.reflector.lessons_context();
        if !lessons.is_empty() {
            self.planner.set_lessons_context(&lessons);
        }

        // Inject recent failures if any
        if self.reflector.failure_count() > 0 {
            let failures_ctx = self.reflector.recent_failures_context(3);
            let mut obs = self.last_observation.clone();
            obs.push_str(&failures_ctx);
            self.planner.set_observation(&obs);
        } else {
            self.planner.set_observation(&self.last_observation);
        }

        // Inject pending confirmations
        let pending = self.confirmation_gate.format_pending();
        if pending.contains('[') {
            let mut obs = self.last_observation.clone();
            obs.push_str("\n\n");
            obs.push_str(&pending);
            self.planner.set_observation(&obs);
        }
    }

    /// THINK phase: generate prompt and query the LLM.
    fn think(&mut self) -> Option<String> {
        let prompt = self.planner.generate_prompt();

        match network::query_ollama(&prompt) {
            Ok(response) => {
                if response.status_code == 200 {
                    self.last_response = Some(response.body.clone());
                    Some(response.body)
                } else {
                    None
                }
            }
            Err(_) => None,
        }
    }

    /// ACT phase: parse the LLM response and execute any tool calls.
    /// Returns a list of (tool_name, success, output) tuples.
    fn act(&mut self, response: &str) -> Vec<(String, bool, String)> {
        let mut results = Vec::new();

        let parsed = match json::parse(response) {
            Ok(p) => p,
            Err(_) => {
                self.last_response = Some(String::from(response));
                return results;
            }
        };

        if let Some(content) = json::extract_content(&parsed) {
            self.last_response = Some(content);
        }

        let tool_calls = json::extract_tool_calls(&parsed);

        for tc in &tool_calls {
            self.total_actions += 1;

            // Mark the corresponding plan task as in-progress
            if let Some(plan) = self.planner.plan_mut() {
                if let Some(task) = plan.next_runnable() {
                    let task_id = task.id;
                    plan.start_task(task_id);
                }
            }

            // Handle internal tools that the orchestrator manages directly
            let result = match tc.name.as_str() {
                "query_memory" => {
                    let query = super::json::find_tool_arg_string(&tc.arguments, "query")
                        .unwrap_or(self.last_observation.clone());
                    let top_k = super::json::find_tool_arg_number(&tc.arguments, "top_k")
                        .unwrap_or(3.0) as usize;
                    let search_results = self.memory.search(&query, top_k, None);
                    let mut output = String::from("Memory search results:\n");
                    for doc in &search_results {
                        output.push_str(&format!("- [{}] {}\n", doc.category.as_str(),
                            if doc.content.len() > 200 { &doc.content[..200] } else { &doc.content }));
                    }
                    tool_mapper::ToolResult {
                        tool_name: String::from("query_memory"),
                        success: true,
                        output,
                    }
                }
                "save_memory" => {
                    let save_result = self.memory.save("/disk/heliox/memory.json");
                    tool_mapper::ToolResult {
                        tool_name: String::from("save_memory"),
                        success: save_result.is_ok(),
                        output: match save_result {
                            Ok(()) => String::from("Memory saved to /disk/heliox/memory.json"),
                            Err(e) => format!("Save failed: {}", e),
                        },
                    }
                }
                "load_memory" => {
                    let load_result = self.memory.load("/disk/heliox/memory.json");
                    tool_mapper::ToolResult {
                        tool_name: String::from("load_memory"),
                        success: load_result.is_ok(),
                        output: match load_result {
                            Ok(()) => format!("Memory loaded ({} documents)", self.memory.document_count()),
                            Err(e) => format!("Load failed: {}", e),
                        },
                    }
                }
                "set_goal" => {
                    let goal = super::json::find_tool_arg_string(&tc.arguments, "goal")
                        .unwrap_or_default();
                    if !goal.is_empty() {
                        self.planner.set_goal(&goal);
                        self.verifier.reset();
                        self.reflector.reset();
                    }
                    tool_mapper::ToolResult {
                        tool_name: String::from("set_goal"),
                        success: !goal.is_empty(),
                        output: format!("Goal set to: {}", goal),
                    }
                }
                "get_config" => {
                    tool_mapper::ToolResult {
                        tool_name: String::from("get_config"),
                        success: true,
                        output: format!(
                            "tick_interval={}, save_interval={}, max_retries={}, auto_approve_tier={}",
                            TICK_INTERVAL, SAVE_INTERVAL, MAX_RETRIES, self.auto_approve_tier
                        ),
                    }
                }
                _ => {
                    // Execute via the tool mapper (handles syscalls + confirmation gate)
                    tool_mapper::execute(
                        tc,
                        &mut self.confirmation_gate,
                        self.auto_approve_tier,
                        self.tick_count,
                    )
                }
            };

            self.last_action = Some(format!(
                "{}:{} -> {}",
                result.tool_name,
                if result.success { "ok" } else { "fail" },
                result.output
            ));

            self.last_observation = format!(
                "Executed tool '{}'. Success: {}. Output: {}",
                result.tool_name, result.success, result.output
            );

            results.push((result.tool_name, result.success, result.output));
        }

        results
    }

    /// VERIFY + REFLECT phase: validate results and learn from failures.
    fn verify_and_reflect(&mut self, tool_name: &str, success: bool, output: &str) {
        let expected_keywords: Vec<String> = if let Some(plan) = self.planner.plan() {
            plan.tasks.iter()
                .find(|t| {
                    t.tool_name.as_deref() == Some(tool_name)
                        && matches!(t.state, super::planner::TaskState::InProgress)
                })
                .map(|t| t.expected_keywords.clone())
                .unwrap_or_default()
        } else {
            Vec::new()
        };

        let kw_refs: Vec<&str> = expected_keywords.iter().map(|s| s.as_str()).collect();
        let verdict = self.verifier.verify(tool_name, success, output, &kw_refs);

        match verdict {
            Verdict::Pass => {
                if let Some(plan) = self.planner.plan_mut() {
                    let task_id = plan.tasks.iter()
                        .find(|t| {
                            t.tool_name.as_deref() == Some(tool_name)
                                && matches!(t.state, super::planner::TaskState::InProgress)
                        })
                        .map(|t| t.id);
                    if let Some(id) = task_id {
                        plan.complete_task(id);
                    }
                }

                self.memory.add(
                    format!("action-{}-ok", self.tick_count),
                    format!("tool={} result={}", tool_name, output),
                    MemoryCategory::ToolResult,
                );
            }
            Verdict::Partial(ref reason) => {
                self.memory.add(
                    format!("action-{}-partial", self.tick_count),
                    format!("tool={} partial={} result={}", tool_name, reason, output),
                    MemoryCategory::ToolResult,
                );
            }
            Verdict::Fail(ref reason) => {
                self.total_failures += 1;

                self.reflector.record_failure(
                    self.tick_count,
                    tool_name,
                    reason,
                    &self.last_observation,
                );

                if self.verifier.should_abandon(MAX_RETRIES) {
                    if let Some(plan) = self.planner.plan_mut() {
                        let task_id = plan.tasks.iter()
                            .find(|t| {
                                t.tool_name.as_deref() == Some(tool_name)
                                    && matches!(t.state, super::planner::TaskState::InProgress)
                            })
                            .map(|t| t.id);
                        if let Some(id) = task_id {
                            plan.fail_task(id, reason);
                        }
                    }

                    self.memory.add(
                        format!("action-{}-abandoned", self.tick_count),
                        format!("ABANDONED: tool={} after {} retries. reason={}", tool_name, MAX_RETRIES, reason),
                        MemoryCategory::ToolResult,
                    );
                }
            }
        }
    }

    /// Returns the last LLM response, if any.
    pub fn last_response(&self) -> Option<&str> {
        self.last_response.as_deref()
    }

    /// Returns the last tool action executed, if any.
    pub fn last_action(&self) -> Option<&str> {
        self.last_action.as_deref()
    }

    /// Returns agent statistics.
    pub fn stats(&self) -> (u64, u64, u64, usize, usize) {
        (
            self.tick_count,
            self.total_actions,
            self.total_failures,
            self.reflector.lesson_count(),
            self.memory.document_count(),
        )
    }
}
