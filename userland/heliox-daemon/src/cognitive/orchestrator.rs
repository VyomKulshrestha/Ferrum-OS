// ============================================================================
// Heliox-Daemon - Orchestrator (with Telemetry & Config)
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
// Telemetry: Emits structured events for each phase to the kernel audit log.
// ============================================================================

use super::planner::Planner;
use super::verifier::{Verifier, Verdict};
use super::reflector::Reflector;
use super::confirmation::ConfirmationGate;
use super::json;
use super::tool_mapper;
use super::multi_agent::AgentRouter;
use crate::config::Config;
use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;
use core::arch::asm;
use crate::memory::vector_store::{VectorStore, MemoryCategory};
use crate::network;

// Syscall numbers for telemetry and IPC
const SYS_IPC_SEND: u64 = 1;
const SYS_IPC_RECEIVE: u64 = 2;

#[inline(always)]
unsafe fn syscall3(number: u64, arg1: u64, arg2: u64, arg3: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

#[inline(always)]
unsafe fn syscall4(number: u64, arg1: u64, arg2: u64, arg3: u64, arg4: u64) -> u64 {
    let ret: u64;
    asm!(
        "int 0x80",
        inout("rax") number => ret,
        in("rdi") arg1,
        in("rsi") arg2,
        in("rdx") arg3,
        in("r10") arg4,
        out("rcx") _,
        out("r11") _,
        options(nostack, preserves_flags)
    );
    ret
}

// ---- Telemetry Definitions -------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub enum TelemetryEventKind {
    TickStart,
    ObserveComplete,
    ThinkStart,
    ThinkComplete,
    ActStart,
    ActComplete,
    VerifyResult,
    ReflectLesson,
    PlanProgress,
    ConfirmationQueued,
    SaveComplete,
    Error,
}

impl TelemetryEventKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::TickStart => "TICK_START",
            Self::ObserveComplete => "OBSERVE_COMPLETE",
            Self::ThinkStart => "THINK_START",
            Self::ThinkComplete => "THINK_COMPLETE",
            Self::ActStart => "ACT_START",
            Self::ActComplete => "ACT_COMPLETE",
            Self::VerifyResult => "VERIFY_RESULT",
            Self::ReflectLesson => "REFLECT_LESSON",
            Self::PlanProgress => "PLAN_PROGRESS",
            Self::ConfirmationQueued => "CONFIRMATION_QUEUED",
            Self::SaveComplete => "SAVE_COMPLETE",
            Self::Error => "ERROR",
        }
    }
}

#[derive(Debug, Clone)]
pub struct TelemetryEvent {
    pub tick: u64,
    pub kind: TelemetryEventKind,
    pub message: String,
}

// ---- Orchestrator ----------------------------------------------------------

/// The main orchestrator driving the ReAct agent loop.
pub struct Orchestrator {
    pub config: Config,
    planner: Planner,
    verifier: Verifier,
    reflector: Reflector,
    confirmation_gate: ConfirmationGate,
    memory: VectorStore,
    tick_count: u64,
    last_observation: String,
    last_action: Option<String>,
    last_response: Option<String>,
    
    // Telemetry ring buffer
    telemetry_buffer: Vec<TelemetryEvent>,
    
    // Stats
    total_actions: u64,
    total_failures: u64,
    
    // Multi-agent domain routing
    router: AgentRouter,
}

impl Orchestrator {
    pub fn new() -> Self {
        // Load config from disk, fallback to defaults
        let config = Config::load("/disk/heliox/config.json");

        let mut planner = Planner::new();
        // The goal will be set dynamically via IPC or ambient vision
        // planner.set_goal("Explore the system and ensure everything is functioning.");

        Self {
            planner,
            verifier: Verifier::new(),
            reflector: Reflector::new(),
            confirmation_gate: ConfirmationGate::new(config.confirmation_timeout),
            memory: VectorStore::new(),
            tick_count: 0,
            last_observation: String::new(),
            last_action: None,
            last_response: None,
            telemetry_buffer: Vec::with_capacity(32),
            total_actions: 0,
            total_failures: 0,
            router: AgentRouter::new(),
            config,
        }
    }

    /// Emit a telemetry event to the ring buffer and the kernel audit log.
    fn emit_telemetry(&mut self, kind: TelemetryEventKind, message: String) {
        let event = TelemetryEvent {
            tick: self.tick_count,
            kind: kind.clone(),
            message: message.clone(),
        };

        // Ring buffer logic (keep last 32 events)
        // Keep recent telemetry in the buffer
        if self.telemetry_buffer.len() > 100 {
            self.telemetry_buffer.remove(0);
        }
        self.telemetry_buffer.push(event);

        // Send to GUI via IPC
        let msg = format!("TELEMETRY:{}:{}", kind.as_str(), message);
        let target_svc = "gui";
        unsafe {
            syscall4(
                SYS_IPC_SEND,
                target_svc.as_ptr() as u64,
                target_svc.len() as u64,
                msg.as_ptr() as u64,
                msg.len() as u64,
            );
        }
    }

    /// Main tick function called from the daemon's main loop.
    pub fn tick(&mut self) {
        self.ipc_poll();
        self.tick_count += 1;

        if self.config.api_host == "unconfigured" {
            // Idle Setup State: Don't do any background processing until configured.
            return;
        }

        if self.tick_count % self.config.tick_interval != 0 {
            return;
        }

        self.emit_telemetry(TelemetryEventKind::TickStart, format!("Tick {}", self.tick_count));

        if self.tick_count % self.config.save_interval == 0 && self.memory.document_count() > 0 {
            if let Ok(_) = self.memory.save("/disk/heliox/memory.json") {
                self.emit_telemetry(TelemetryEventKind::SaveComplete, String::from("Memory persisted to disk"));
            }
        }

        self.confirmation_gate.cleanup_expired(self.tick_count);

        let new_lessons = self.reflector.consolidate(self.tick_count);
        for lesson in &new_lessons {
            self.memory.add(
                lesson.id.clone(),
                lesson.content.clone(),
                MemoryCategory::Lesson,
            );
            self.emit_telemetry(TelemetryEventKind::ReflectLesson, format!("New lesson learned: {}", lesson.id));
        }

        // ==================== ReAct Loop ====================

        // 1. OBSERVE
        self.observe();

        // 2. THINK
        let response = match self.think() {
            Some(r) => r,
            None => {
                self.emit_telemetry(TelemetryEventKind::Error, String::from("LLM query failed or network not ready"));
                return;
            }
        };

        // 3. ACT
        let actions = self.act(&response);

        // 4. VERIFY + REFLECT
        for (tool_name, success, output) in &actions {
            self.verify_and_reflect(tool_name, *success, output);
        }

        if actions.is_empty() {
            self.last_observation = response.clone();
            self.memory.add(
                format!("response-{}", self.tick_count),
                response,
                MemoryCategory::Interaction,
            );
            
            // Ambient Vision Mode: When idle and goal is empty/done, occasionally look at the screen
            if self.planner.current_goal().is_empty() && self.tick_count % (self.config.tick_interval * 10) == 0 {
                if let Ok(capture) = super::screen_vision::capture_screen() {
                    let text = capture.full_text();
                    if text.contains("Error") || text.contains("Failed") || text.contains("Panic") {
                        self.planner.set_goal("An error is visible on screen. Analyze and fix it.");
                        self.emit_telemetry(TelemetryEventKind::ObserveComplete, String::from("Ambient vision detected an error. New goal created."));
                    }
                }
            }
        }
    }

    fn observe(&mut self) {
        if !self.last_observation.is_empty() {
            let results = self.memory.search(&self.last_observation, 3, None);
            let results_len = results.len();
            if results_len > 0 {
                let mut ctx = String::new();
                for doc in &results {
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
                // Drop results so we can borrow self mutably again
                drop(results);
                self.planner.set_memory_context(&ctx);
                self.emit_telemetry(TelemetryEventKind::ObserveComplete, format!("RAG search found {} memories", results_len));
            }
        }

        let lessons = self.reflector.lessons_context();
        if !lessons.is_empty() {
            self.planner.set_lessons_context(&lessons);
        }

        if self.reflector.failure_count() > 0 {
            let failures_ctx = self.reflector.recent_failures_context(3);
            let mut obs = self.last_observation.clone();
            obs.push_str(&failures_ctx);
            self.planner.set_observation(&obs);
        } else {
            self.planner.set_observation(&self.last_observation);
        }

        let pending = self.confirmation_gate.format_pending();
        if pending.contains('[') {
            let mut obs = self.last_observation.clone();
            obs.push_str("\n\n");
            obs.push_str(&pending);
            self.planner.set_observation(&obs);
        }

        // Multi-agent domain routing: classify the current goal and
        // append a domain-specific prompt suffix to focus the LLM.
        let goal = self.planner.current_goal();
        let classification = self.router.classify(&goal);
        let domain_hint = self.router.domain_prompt(classification.domain);
        self.planner.set_domain_hint(domain_hint);

        self.emit_telemetry(
            TelemetryEventKind::ObserveComplete,
            format!("Domain: {:?} (conf={:.0}%)", classification.domain, classification.confidence * 100.0),
        );
    }

    fn think(&mut self) -> Option<String> {
        let prompt = self.planner.generate_prompt();
        
        self.emit_telemetry(TelemetryEventKind::ThinkStart, format!("Prompt generated ({} bytes)", prompt.len()));

        // Use config-driven LLM endpoint instead of hardcoded values
        match network::query_ollama(
            &prompt,
            &self.config.api_host,
            self.config.api_port,
            &self.config.api_path,
            &self.config.model_name,
        ) {
            Ok(response) => {
                if response.status_code == 200 {
                    self.last_response = Some(response.body.clone());
                    self.emit_telemetry(TelemetryEventKind::ThinkComplete, format!("Response received ({} bytes)", response.body.len()));
                    Some(response.body)
                } else {
                    None
                }
            }
            Err(_) => None,
        }
    }

    fn act(&mut self, response: &str) -> Vec<(String, bool, String)> {
        let mut results = Vec::new();

        let parsed = match json::parse(response) {
            Ok(p) => p,
            Err(_) => {
                self.last_response = Some(String::from(response));
                return results;
            }
        };

        // Extract the content text (handles Ollama "response" field and OpenAI format)
        let content_text = json::extract_content(&parsed);
        if let Some(ref content) = content_text {
            self.last_response = Some(content.clone());
        }

        // Try extracting tool calls from the top-level JSON (OpenAI format)
        let mut tool_calls = json::extract_tool_calls(&parsed);

        // If no tool calls found at top level, try parsing the extracted content
        // text for embedded tool call JSON (Ollama format: response text contains
        // {"tool": "...", "args": {...}})
        if tool_calls.is_empty() {
            if let Some(ref content) = content_text {
                if let Ok(content_parsed) = json::parse(content) {
                    if let Some(tool_name) = content_parsed.get("tool").and_then(|t| t.as_str()) {
                        let arguments = content_parsed.get("args")
                            .and_then(|a| a.as_object())
                            .cloned()
                            .unwrap_or_default();
                        tool_calls.push(json::ToolCall {
                            name: String::from(tool_name),
                            arguments,
                        });
                    }
                }
            }
        }

        for tc in &tool_calls {
            self.total_actions += 1;
            
            self.emit_telemetry(TelemetryEventKind::ActStart, format!("Executing tool: {}", tc.name));

            if let Some(plan) = self.planner.plan_mut() {
                if let Some(task) = plan.next_runnable() {
                    let task_id = task.id;
                    plan.start_task(task_id);
                }
            }

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
                            self.config.tick_interval, self.config.save_interval, 
                            self.config.max_retries, self.config.auto_approve_tier
                        ),
                    }
                }
                "add_subtask" => {
                    let description = super::json::find_tool_arg_string(&tc.arguments, "description")
                        .unwrap_or_default();
                    if description.is_empty() {
                        tool_mapper::ToolResult {
                            tool_name: String::from("add_subtask"),
                            success: false,
                            output: String::from("Missing 'description' argument"),
                        }
                    } else {
                        let depends_on_str = super::json::find_tool_arg_string(&tc.arguments, "depends_on")
                            .unwrap_or_default();
                        let depends_on: Vec<u32> = if depends_on_str.is_empty() {
                            Vec::new()
                        } else {
                            depends_on_str.split(',')
                                .filter_map(|s| s.trim().parse::<u32>().ok())
                                .collect()
                        };
                        let task_id = if let Some(plan) = self.planner.plan_mut() {
                            plan.add_task(&description, None, "", depends_on, Vec::new())
                        } else {
                            0
                        };
                        tool_mapper::ToolResult {
                            tool_name: String::from("add_subtask"),
                            success: task_id > 0,
                            output: format!("Subtask added with id={}: {}", task_id, description),
                        }
                    }
                }
                _ => {
                    tool_mapper::execute(
                        tc,
                        &mut self.confirmation_gate,
                        self.config.auto_approve_tier,
                        self.tick_count,
                    )
                }
            };

            if result.output.contains("Awaiting confirmation") {
                self.emit_telemetry(TelemetryEventKind::ConfirmationQueued, format!("Tool {} requires confirmation", tc.name));
            } else {
                let snippet = if result.output.len() > 64 { format!("{}...", &result.output[..64]) } else { result.output.clone() };
                self.emit_telemetry(TelemetryEventKind::ActComplete, format!("Tool {}: {} ({})", tc.name, if result.success { "success" } else { "failed" }, snippet));
            }

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
                self.emit_telemetry(TelemetryEventKind::VerifyResult, format!("Tool {} VERIFIED OK", tool_name));
                
                if let Some(plan) = self.planner.plan_mut() {
                    let task_id = plan.tasks.iter()
                        .find(|t| {
                            t.tool_name.as_deref() == Some(tool_name)
                                && matches!(t.state, super::planner::TaskState::InProgress)
                        })
                        .map(|t| t.id);
                    if let Some(id) = task_id {
                        plan.complete_task(id);
                        self.emit_telemetry(TelemetryEventKind::PlanProgress, format!("Task {} completed", id));
                    }
                }

                self.memory.add(
                    format!("action-{}-ok", self.tick_count),
                    format!("tool={} result={}", tool_name, output),
                    MemoryCategory::ToolResult,
                );
            }
            Verdict::Partial(ref reason) => {
                self.emit_telemetry(TelemetryEventKind::VerifyResult, format!("Tool {} VERIFIED PARTIAL: {}", tool_name, reason));
                
                self.memory.add(
                    format!("action-{}-partial", self.tick_count),
                    format!("tool={} partial={} result={}", tool_name, reason, output),
                    MemoryCategory::ToolResult,
                );
            }
            Verdict::Fail(ref reason) => {
                self.total_failures += 1;
                self.emit_telemetry(TelemetryEventKind::VerifyResult, format!("Tool {} VERIFIED FAIL: {}", tool_name, reason));

                self.reflector.record_failure(
                    self.tick_count,
                    tool_name,
                    reason,
                    &self.last_observation,
                );

                if self.verifier.should_abandon(self.config.max_retries) {
                    if let Some(plan) = self.planner.plan_mut() {
                        let task_id = plan.tasks.iter()
                            .find(|t| {
                                t.tool_name.as_deref() == Some(tool_name)
                                    && matches!(t.state, super::planner::TaskState::InProgress)
                            })
                            .map(|t| t.id);
                        if let Some(id) = task_id {
                            plan.fail_task(id, reason);
                            self.emit_telemetry(TelemetryEventKind::PlanProgress, format!("Task {} failed, moving on", id));
                        }
                    }

                    self.memory.add(
                        format!("action-{}-abandoned", self.tick_count),
                        format!("ABANDONED: tool={} after {} retries. reason={}", tool_name, self.config.max_retries, reason),
                        MemoryCategory::ToolResult,
                    );
                }
            }
        }
    }

    pub fn last_response(&self) -> Option<&str> {
        self.last_response.as_deref()
    }

    pub fn last_action(&self) -> Option<&str> {
        self.last_action.as_deref()
    }

    pub fn stats(&self) -> (u64, u64, u64, usize, usize) {
        (
            self.tick_count,
            self.total_actions,
            self.total_failures,
            self.reflector.lesson_count(),
            self.memory.document_count(),
        )
    }

    /// Check for incoming IPC messages (e.g., CONFIRM, DENY, GOAL)
    fn ipc_poll(&mut self) {
        let mut buf = [0u8; 1024];
        let buf_ptr = buf.as_mut_ptr() as u64;
        let buf_len = buf.len() as u64;
        let svc = "heliox";

        let bytes_received = unsafe {
            syscall4(SYS_IPC_RECEIVE, buf_ptr, buf_len, svc.as_ptr() as u64, svc.len() as u64)
        };

        if bytes_received == 0 || (bytes_received as i64) < 0 {
            return;
        }

        let msg = match core::str::from_utf8(&buf[..bytes_received as usize]) {
            Ok(s) => s,
            Err(_) => return,
        };

        // Parse CONFIRM:<id>, DENY:<id>, GOAL:<text>, CONFIG_UPDATED messages
        for line in msg.lines() {
            let trimmed = line.trim();
            if let Some(id_str) = trimmed.strip_prefix("CONFIRM:") {
                if let Ok(id) = id_str.trim().parse::<u32>() {
                    self.confirmation_gate.approve(id);
                    self.emit_telemetry(
                        TelemetryEventKind::ConfirmationQueued,
                        format!("Confirmation {} approved via IPC", id),
                    );
                }
            } else if let Some(id_str) = trimmed.strip_prefix("DENY:") {
                if let Ok(id) = id_str.trim().parse::<u32>() {
                    self.confirmation_gate.deny(id);
                    self.emit_telemetry(
                        TelemetryEventKind::ConfirmationQueued,
                        format!("Confirmation {} denied via IPC", id),
                    );
                }
            } else if let Some(goal_str) = trimmed.strip_prefix("GOAL:") {
                self.planner.set_goal(goal_str.trim());
                self.verifier.reset();
                self.reflector.reset();
                self.emit_telemetry(
                    TelemetryEventKind::TickStart,
                    format!("New goal set via IPC: {}", goal_str.trim()),
                );
            } else if trimmed == "CONFIG_UPDATED" || trimmed == "CONFIG_UPDATED:" {
                self.config = Config::load("/disk/heliox/config.json");
                self.emit_telemetry(
                    TelemetryEventKind::TickStart,
                    String::from("Configuration reloaded via IPC"),
                );
            }
        }
    }
}
