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
use crate::physical::PhysicalService;
use crate::neural::{NeuralCommit, NeuralService};

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
    pub confirmation_gate: ConfirmationGate,
    memory: VectorStore,
    tick_count: u64,
    last_observation: String,
    last_fused_goal: String,
    last_intent_goal: String,
    last_action: Option<String>,
    last_response: Option<String>,
    
    // Telemetry ring buffer
    telemetry_buffer: Vec<TelemetryEvent>,
    
    // Stats
    total_actions: u64,
    total_failures: u64,
    
    // Multi-agent domain routing
    router: AgentRouter,
    pub pending_gesture: Option<u8>,
    pub paused: bool,

    // World model (Phase 1, see model.md) - tracks the previous tool
    // call's name/outcome so the *next* call's OsSnapshot can carry it
    // as historical context (the encoder's one-hot last_action_id
    // feature), separate from `last_action` above (a human-readable
    // summary string, not machine-stable enough to feed an encoder).
    wm_last_action_name: String,
    wm_last_action_failed: bool,
    wm_last_suggestion: String,

    // Independent physical-state schema, model, and simulator runtime. It is
    // deliberately not encoded into the published 41-action OS JEPA ABI.
    physical_service: PhysicalService,
    neural_service: NeuralService,
}

impl Orchestrator {
    pub fn push_gesture(&mut self, gesture_id: u8) {
        self.pending_gesture = Some(gesture_id);
    }

    pub fn set_paused(&mut self, p: bool) {
        self.paused = p;
    }

    pub fn current_goal(&self) -> String {
        self.planner.current_goal()
    }

    pub fn tick_count(&self) -> u64 {
        self.tick_count
    }

    /// Total recorded telemetry events and the most recent one, backing
    /// the `agent_stats` JSON-RPC method. `TelemetryEvent`'s own fields
    /// stay private - this returns owned/copy data instead of leaking a
    /// reference to the internal ring buffer.
    pub fn telemetry_summary(&self) -> (usize, Option<(u64, &'static str, String)>) {
        let count = self.telemetry_buffer.len();
        let last = self.telemetry_buffer.last().map(|ev| (ev.tick, ev.kind.as_str(), ev.message.clone()));
        (count, last)
    }

    pub fn set_goal(&mut self, goal: &str) {
        self.planner.set_goal(goal);
        self.verifier.reset();
        self.reflector.reset();
        self.wm_last_suggestion.clear();
        self.emit_telemetry(
            TelemetryEventKind::TickStart,
            format!("New goal set: {}", goal),
        );
    }

    /// Accept a transcript from the in-guest voice capture/STT path.
    ///
    /// Voice input only updates planner intent. It is deliberately not parsed
    /// as a tool call here: any resulting action must still be proposed by the
    /// normal ReAct loop and pass the world-model, permission-tier,
    /// confirmation, and capability-gated syscall boundaries.
    pub fn handle_voice_event(&mut self, transcript: &str) -> bool {
        let goal = transcript.trim();
        if goal.is_empty() {
            return false;
        }

        self.set_goal(goal);
        let message = format!("[heliox-daemon] voice event accepted: {}\n", goal);
        unsafe {
            syscall3(34, 1, message.as_ptr() as u64, message.len() as u64);
        }
        true
    }

    /// Read-only simulation for a paired external model that wants to inspect
    /// risk before requesting execution. It does not append experience data,
    /// alter planner state, or invoke a syscall-producing tool.
    pub fn preview_world_model_action(
        &self,
        tc: &super::json::ToolCall,
    ) -> super::world_model::GateDecision {
        let snapshot = super::world_model::observation::capture_snapshot(
            self.tick_count,
            &self.wm_last_action_name,
            self.wm_last_action_failed,
        );
        super::world_model::evaluate_action(&snapshot, tc)
    }

    pub fn world_model_suggestion(&self) -> String {
        self.wm_last_suggestion.clone()
    }

    pub fn physical_status_json(&self) -> String {
        self.physical_service.status_json()
    }

    pub fn run_physical_maintenance_simulation(&mut self) -> Result<String, &'static str> {
        self.physical_service.run_maintenance_simulation_json()
    }

    pub fn neural_pair(&mut self, token: &[u8], control_mode: &str) -> Result<(), ferrum_neural_protocol::NeuralError> {
        let result = self.neural_service.pair(token, control_mode);
        if result.is_ok() {
            crate::cognitive::fusion::clear_neural_history();
        }
        self.audit_neural_event(if result.is_ok() { "paired session established" } else { "pairing rejected" });
        result
    }

    pub fn neural_calibrate(
        &mut self,
        transport: ferrum_neural_protocol::NeuralTransport,
        sample_rate_hz: u16,
        channel_count: u8,
        calibration_id: [u8; 32],
        now_ns: u64,
    ) -> Result<(), ferrum_neural_protocol::NeuralError> {
        let result = self.neural_service.calibrate(transport, sample_rate_hz, channel_count, calibration_id, now_ns);
        self.audit_neural_event(if result.is_ok() { "calibration accepted" } else { "calibration rejected" });
        result
    }

    pub fn neural_status_json(&self, now_ns: u64) -> String {
        let mut status = self.neural_service.status_json(now_ns);
        let (retained, latest) = crate::cognitive::fusion::neural_history_summary();
        let latest_json = match latest {
            Some(event) => format!(
                "{{\"tick\":{},\"class\":\"{}\",\"scope\":\"{}\"}}",
                event.monotonic_tick,
                neural_class_name(event.class),
                neural_scope_name(event.scope),
            ),
            None => String::from("null"),
        };
        if status.pop() == Some('}') {
            status.push_str(&format!(
                ",\"fusion\":{{\"raw_eeg_retained\":false,\"retained_intents\":{},\"latest\":{}}}}}",
                retained, latest_json,
            ));
        }
        status
    }

    pub fn neural_preview(
        &mut self,
        wire: &[u8; ferrum_neural_protocol::NEURAL_INTENT_WIRE_BYTES],
        now_ns: u64,
    ) -> Result<ferrum_neural_protocol::NeuralPreview, ferrum_neural_protocol::NeuralError> {
        let result = self.neural_service.preview(wire, now_ns);
        if let Ok(preview) = result {
            crate::cognitive::fusion::note_neural_intent(
                now_ns / 1_000_000,
                preview.class,
                preview.scope,
            );
        }
        self.audit_neural_event(if result.is_ok() { "intent preview accepted" } else { "intent preview rejected and disarmed" });
        result
    }

    pub fn neural_commit(
        &mut self,
        intent_id: [u8; 16],
        now_ns: u64,
    ) -> Result<NeuralCommit, ferrum_neural_protocol::NeuralError> {
        let result = self.neural_service.commit(intent_id, now_ns);
        self.audit_neural_event(if result.is_ok() { "safe UI intent committed" } else { "intent commit rejected" });
        result
    }

    pub fn neural_physical_preview_json(&self) -> Result<String, &'static str> {
        self.physical_service.preview_neural_work_order_json()
    }

    pub fn neural_set_control_mode(&mut self, mode: &str) {
        self.neural_service.set_control_mode(mode);
        self.audit_neural_event("control mode changed and session disarmed");
    }

    pub fn neural_disconnect(&mut self) {
        self.neural_service.disconnect();
        crate::cognitive::fusion::clear_neural_history();
        self.audit_neural_event("session disconnected and disarmed");
    }

    pub fn neural_disarm(&mut self) {
        self.neural_service.disarm();
        self.audit_neural_event("session disarmed");
    }

    fn audit_neural_event(&self, event: &str) {
        let message = format!("neural: {}", event);
        unsafe {
            syscall3(6, message.as_ptr() as u64, message.len() as u64, 0);
        }
    }

    /// Execute a public JSON-RPC tool through the same predictive gate and
    /// dataset recorder as ReAct-generated actions.
    pub fn execute_tool_with_world_model(
        &mut self,
        tc: &super::json::ToolCall,
    ) -> tool_mapper::ToolResult {
        self.total_actions += 1;
        self.dispatch_with_world_model(tc)
    }

    /// Run one provider-backed ReAct cycle for a supplied goal, ignoring the
    /// normal tick cadence. The hybrid host collector uses this to associate
    /// one prompt/response episode with the exact transition rows it caused.
    /// Provider selection remains entirely inside `think()`.
    pub fn run_goal_once(
        &mut self,
        goal: &str,
    ) -> Result<(String, Vec<(String, bool, String)>), &'static str> {
        self.tick_count += 1;
        self.set_goal(goal);
        self.observe();
        self.emit_chat("agent", "thinking", "");
        let response = self.think().ok_or("LLM query failed or network not ready")?;
        let actions = self.act(&response);
        let chat_text = self.last_response.clone().unwrap_or_else(|| response.clone());
        self.emit_chat("agent", "done", &chat_text);
        for (tool_name, success, output) in &actions {
            self.verify_and_reflect(tool_name, *success, output);
        }
        Ok((chat_text, actions))
    }

    pub fn new() -> Self {
        // Load config from disk, fallback to defaults
        let config = Config::load("/disk/heliox/config.json");

        let world_model_load_start_tick = crate::cognitive::fusion::get_uptime_ticks();
        let world_model_load_start_tsc = unsafe { core::arch::x86_64::_rdtsc() };
        // World model Phase 2: load a learned transition model if one
        // was trained and staged onto this appliance disk
        // (scripts/train_world_model.py). Purely optional - a boot with
        // no weights file (or no disk at all) just keeps using Phase 1's
        // rule table, silently, since `transition::predict_next_state`
        // checks `learned::is_loaded()` internally.
        super::world_model::learned::try_load();
        // Layer 3.2: same optional-load pattern - a boot with no staged
        // encoder weights just leaves the embedding's tail slots at
        // zero, exactly as Phase 1's encoder always left them.
        super::world_model::encoder_learned::try_load();
        let world_model_load_cycles = unsafe { core::arch::x86_64::_rdtsc() }
            .saturating_sub(world_model_load_start_tsc);
        let world_model_load_ticks = crate::cognitive::fusion::get_uptime_ticks()
            .saturating_sub(world_model_load_start_tick);
        let world_model_load_marker = format!(
            "[heliox-daemon] [world-model-load-v1] cycles={} ticks={} encoder_loaded={} transition_loaded={}\n",
            world_model_load_cycles,
            world_model_load_ticks,
            if super::world_model::encoder_learned::is_loaded() { 1 } else { 0 },
            if super::world_model::learned::is_loaded() { 1 } else { 0 },
        );
        unsafe {
            syscall3(
                34,
                1,
                world_model_load_marker.as_ptr() as u64,
                world_model_load_marker.len() as u64,
            );
        }

        let mut planner = Planner::new();
        // The goal will be set dynamically via IPC or ambient vision
        // planner.set_goal("Explore the system and ensure everything is functioning.");

        // Durable memory is part of the agent runtime, not an opt-in tool call.
        // Previous builds periodically saved memory.json but always started
        // with an empty VectorStore, so a daemon restart silently forgot the
        // context it had just persisted unless the model happened to call
        // load_memory itself. Load it before the first observation instead.
        let mut memory = VectorStore::new();
        let memory_loaded = memory.load("/disk/heliox/memory.json").is_ok();
        if memory_loaded {
            let msg = format!(
                "[heliox-daemon] restored {} durable memories\n",
                memory.document_count()
            );
            unsafe {
                syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64);
            }
        }

        Self {
            planner,
            verifier: Verifier::new(),
            reflector: Reflector::new(),
            confirmation_gate: ConfirmationGate::new(config.confirmation_timeout),
            memory,
            tick_count: 0,
            last_observation: String::new(),
            last_fused_goal: String::new(),
            last_intent_goal: String::new(),
            last_action: None,
            last_response: None,
            telemetry_buffer: Vec::with_capacity(32),
            total_actions: 0,
            total_failures: 0,
            router: AgentRouter::new(),
            config,
            pending_gesture: None,
            paused: false,
            wm_last_action_name: String::new(),
            wm_last_action_failed: false,
            wm_last_suggestion: String::new(),
            physical_service: PhysicalService::new(),
            neural_service: NeuralService::default(),
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
        // No longer forwarded over IPC to a "gui" listener - the kernel-
        // hardcoded AgentHud window that read it is retired in favor of
        // heliox-assistant-panel, a real app that gets its own focused
        // "CHAT:" stream (see emit_chat below) instead of the full,
        // high-volume internal telemetry firehose. The ring buffer above
        // is what backs the agent_stats/get_history JSON-RPC methods.
    }

    /// Send a chat-relevant update to heliox-assistant-panel (the real
    /// app-window-based assistant UI, not the old kernel-hardcoded AgentHud
    /// window). Distinct from `emit_telemetry` above: telemetry is a
    /// high-volume internal event stream; chat is specifically the
    /// user-visible conversation turns (thinking / done / error), sent to
    /// its own "assistant" service so the two don't compete for the same
    /// consumer or flood the chat UI with unrelated internal noise.
    ///
    /// `content` is truncated to fit within `ipc::MAX_PAYLOAD_BYTES` minus
    /// the "CHAT:<role>:<state>:" prefix - IPC messages are bounded, unlike
    /// a file, so an unusually long generation is clipped rather than
    /// silently dropped by `IpcSend`'s own size check.
    fn emit_chat(&self, role: &str, state: &str, content: &str) {
        let prefix_len = 5 + role.len() + 1 + state.len() + 1; // "CHAT:" + role + ":" + state + ":"
        let max_content = 4096usize.saturating_sub(prefix_len).saturating_sub(1);
        let truncated: &str = if content.len() > max_content {
            let mut end = max_content;
            while end > 0 && !content.is_char_boundary(end) {
                end -= 1;
            }
            &content[..end]
        } else {
            content
        };
        let msg = format!("CHAT:{}:{}:{}", role, state, truncated);
        let target_svc = "assistant";
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
        // Control messages must remain live even while cognitive work is
        // paused, otherwise an operator cannot confirm/deny or resume it.
        self.ipc_poll();
        if self.paused {
            return;
        }
        self.tick_count += 1;

        if self.config.api_host == "unconfigured" && !self.config.provider.starts_with("local") {
            // Idle Setup State: Don't do any background processing until configured.
            return;
        }

        // Run spatial/deictic fusion immediately if a new goal has been set
        let goal = self.planner.current_goal();
        if goal != self.last_fused_goal {
            self.observe();
        }

        if goal != self.last_intent_goal {
            if let Some(intent) = super::intent_adapter::resolve(&goal) {
                self.last_intent_goal = goal.clone();
                self.emit_telemetry(
                    TelemetryEventKind::ThinkComplete,
                    format!("Deterministic OS intent adapter selected {}", intent.tool_name),
                );
                self.emit_chat("agent", "thinking", "");
                let actions = self.act(&intent.provider_response);
                self.emit_chat(
                    "agent",
                    "done",
                    "Request mapped to a capability-gated OS action.",
                );
                for (tool_name, success, output) in &actions {
                    self.verify_and_reflect(tool_name, *success, output);
                }
                return;
            }
        }

        // A configured provider is not itself an instruction to act.  The
        // periodic ambient tick previously entered full model inference with
        // an empty goal immediately after first-run setup, consuming the
        // cooperative CPU before the assistant could accept its first real
        // request.  Idle explicitly until a user, voice or controller source
        // supplies a goal; non-empty goals retain the existing ReAct cadence.
        if goal.trim().is_empty() {
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
        self.emit_chat("agent", "thinking", "");
        let response = match self.think() {
            Some(r) => r,
            None => {
                self.emit_telemetry(TelemetryEventKind::Error, String::from("LLM query failed or network not ready"));
                self.emit_chat("agent", "error", "LLM query failed or network not ready");
                return;
            }
        };

        // 3. ACT
        let actions = self.act(&response);
        // `act()` parses `response` (raw JSON from the provider - an Ollama
        // `{"response":...}` wrapper for local, or the full API body for
        // cloud) and extracts the human-readable text into
        // `self.last_response`. That's what belongs in the chat panel, not
        // the raw JSON `response` itself.
        let chat_text = self.last_response.clone().unwrap_or_else(|| response.clone());
        self.emit_chat("agent", "done", &chat_text);

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

    /// Poll control IPC at an external request boundary.
    ///
    /// A connected WebSocket may block the main loop after its normal
    /// tick-time poll. The frame that wakes it must observe a shell/UI approval
    /// already in the IPC queue before executing the retried tool.
    pub fn poll_control(&mut self) {
        self.ipc_poll();
    }

    fn observe(&mut self) {
        let goal = self.planner.current_goal();
        if goal != self.last_fused_goal {
            let ticks = crate::cognitive::fusion::get_uptime_ticks();
            if let Some(intent) = crate::cognitive::fusion::resolve_spatial_intent(&goal, ticks) {
                let log_msg = format!("[heliox-daemon] spatial fusion resolved: {} {} (at {},{})\n", intent.verb, intent.target_label, intent.sx, intent.sy);
                unsafe {
                    syscall3(34, 1, log_msg.as_ptr() as u64, log_msg.len() as u64);
                }
                let mut obs = format!("[FUSED] {} {} (at {},{})\n", intent.verb, intent.target_label, intent.sx, intent.sy);
                obs.push_str(&self.last_observation);
                self.last_observation = obs;
                self.last_fused_goal = goal;
            }
        }

        if let Some(g_id) = self.pending_gesture {
            let name = match g_id {
                1 => "Fist",
                2 => "OpenPalm",
                3 => "Pointing",
                4 => "Peace",
                5 => "ThreeFingers",
                6 => "FourFingers",
                7 => "ThumbsUp",
                _ => "None",
            };
            let mut obs = self.last_observation.clone();
            if !obs.is_empty() {
                obs.push_str("\n\n");
            }
            obs.push_str("[GESTURE] User is showing: ");
            obs.push_str(name);
            self.last_observation = obs;
            self.pending_gesture = None;
        }

        // Retrieval must be anchored in the user's current goal too. On a
        // fresh goal `last_observation` can be empty (or still describe the
        // previous goal), which previously left durable memories unused until
        // after the first action.
        let goal = self.planner.current_goal();
        let mut retrieval_query = goal.clone();
        if !self.last_observation.is_empty() {
            if !retrieval_query.is_empty() {
                retrieval_query.push('\n');
            }
            retrieval_query.push_str(&self.last_observation);
        }
        if !retrieval_query.is_empty() {
            let results = self.memory.search(&retrieval_query, 3, None);
            let results_len = results.len();
            let mut ctx = String::new();
            for doc in &results {
                ctx.push_str("- [");
                ctx.push_str(doc.category.as_str());
                ctx.push_str("] ");
                let content = if doc.content.len() > 200 {
                    let mut end = 200;
                    while end > 0 && !doc.content.is_char_boundary(end) {
                        end -= 1;
                    }
                    &doc.content[..end]
                } else {
                    &doc.content
                };
                ctx.push_str(content);
                ctx.push('\n');
            }
            // Drop references into the memory store before mutating planner.
            drop(results);
            self.planner.set_memory_context(&ctx);
            if results_len > 0 {
                self.emit_telemetry(
                    TelemetryEventKind::ObserveComplete,
                    format!("RAG search found {} memories", results_len),
                );
            }
        } else {
            self.planner.set_memory_context("");
        }

        let lessons = self.reflector.lessons_context();
        self.planner.set_lessons_context(&lessons);

        // Build one coherent observation so pending confirmations do not
        // overwrite failure context. The world model already captures screen
        // text around actions; include the same live OS view in every actual
        // reasoning prompt rather than only in the rare idle-anomaly branch.
        let mut observation = self.last_observation.clone();
        if let Ok(capture) = super::screen_vision::capture_screen() {
            let screen = capture.full_text();
            if !screen.trim().is_empty() {
                const MAX_SCREEN_CONTEXT_BYTES: usize = 4096;
                let mut start = screen.len().saturating_sub(MAX_SCREEN_CONTEXT_BYTES);
                while start < screen.len() && !screen.is_char_boundary(start) {
                    start += 1;
                }
                if !observation.is_empty() {
                    observation.push_str("\n\n");
                }
                observation.push_str("[CURRENT SCREEN]\n");
                observation.push_str(&screen[start..]);
            }
        }

        if self.reflector.failure_count() > 0 {
            observation.push_str(&self.reflector.recent_failures_context(3));
        }

        let pending = self.confirmation_gate.format_pending();
        if pending.contains('[') {
            observation.push_str("\n\n");
            observation.push_str(&pending);
        }
        self.planner.set_observation(&observation);

        // Multi-agent domain routing: classify the current goal and
        // append a domain-specific prompt suffix to focus the LLM.
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

        if self.config.provider.starts_with("local") {
            match crate::cognitive::inference::run_local_inference(&prompt, &self.config.provider) {
                Ok(res) => {
                    self.last_response = Some(res.clone());
                    self.emit_telemetry(TelemetryEventKind::ThinkComplete, format!("Local response generated ({} bytes)", res.len()));
                    let json_res = format!(r#"{{"response":"{}"}}"#, res);
                    Some(json_res)
                }
                Err(_) => None,
            }
        } else {
            match network::query_llm(
                &self.config.provider,
                &prompt,
                &self.config.api_host,
                self.config.api_port,
                &self.config.api_path,
                &self.config.model_name,
                &self.config.api_key,
            ) {
                Ok(response) => {
                    if response.status_code == 200 {
                        self.last_response = Some(response.body.clone());
                        self.emit_telemetry(TelemetryEventKind::ThinkComplete, format!("Response received ({} bytes)", response.body.len()));
                        // emit_telemetry only forwards to the GUI over IPC; mirror
                        // the message to the console/serial too so a successful
                        // cloud round-trip is observable without a GUI attached
                        // (e.g. from the serial log in headless/CI runs).
                        let console_msg = format!(
                            "[heliox-daemon] Response received ({} bytes)\n",
                            response.body.len()
                        );
                        unsafe {
                            syscall3(34, 1, console_msg.as_ptr() as u64, console_msg.len() as u64);
                        }
                        Some(response.body)
                    } else {
                        let console_msg = format!(
                            "[heliox-daemon] [ ERROR ] LLM query returned status {}\n",
                            response.status_code
                        );
                        unsafe {
                            syscall3(34, 1, console_msg.as_ptr() as u64, console_msg.len() as u64);
                        }
                        None
                    }
                }
                Err(e) => {
                    let console_msg = format!("[heliox-daemon] [ ERROR ] LLM query failed: {}\n", e);
                    unsafe {
                        syscall3(34, 1, console_msg.as_ptr() as u64, console_msg.len() as u64);
                    }
                    None
                }
            }
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

            let result = self.dispatch_with_world_model(tc);

            if result.output.contains("Awaiting confirmation") {
                self.emit_telemetry(TelemetryEventKind::ConfirmationQueued, format!("Tool {} requires confirmation", tc.name));
                let message = format!(
                    "[heliox-daemon] tool {} awaiting operator confirmation\n",
                    tc.name
                );
                unsafe {
                    syscall3(34, 1, message.as_ptr() as u64, message.len() as u64);
                }
            } else {
                let snippet = if result.output.len() > 64 {
                    let mut end = 64;
                    while end > 0 && !result.output.is_char_boundary(end) {
                        end -= 1;
                    }
                    format!("{}...", &result.output[..end])
                } else {
                    result.output.clone()
                };
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

    /// Executes a canonical Heliox action after the world-model gate passes.
    /// Keeping every action behind one dispatcher ensures internal memory/
    /// planner tools and ordinary syscall-backed tools share the same
    /// observation and training path.
    fn execute_action(&mut self, tc: &super::json::ToolCall) -> tool_mapper::ToolResult {
        match tc.name.as_str() {
            "query_memory" => {
                let query = super::json::find_tool_arg_string(&tc.arguments, "query")
                    .unwrap_or(self.last_observation.clone());
                let top_k = super::json::find_tool_arg_number(&tc.arguments, "top_k")
                    .unwrap_or(3.0) as usize;
                let search_results = self.memory.search(&query, top_k, None);
                let mut output = String::from("Memory search results:\n");
                for doc in &search_results {
                    let mut end = core::cmp::min(doc.content.len(), 200);
                    while end > 0 && !doc.content.is_char_boundary(end) {
                        end -= 1;
                    }
                    output.push_str(&format!("- [{}] {}\n", doc.category.as_str(), &doc.content[..end]));
                }
                tool_mapper::ToolResult {
                    tool_name: String::from("query_memory"),
                    success: true,
                    output,
                }
            }
            "save_memory" => {
                // `content` is optional so existing callers can still use
                // this as a plain checkpoint operation. Supplying it makes
                // deliberate user/provider context durable without inventing
                // another action outside the canonical world-model surface.
                if let Some(content) = super::json::find_tool_arg_string(&tc.arguments, "content") {
                    if !content.trim().is_empty() {
                        let id = super::json::find_tool_arg_string(&tc.arguments, "id")
                            .unwrap_or_else(|| format!("memory-{}", self.tick_count));
                        let category = super::json::find_tool_arg_string(&tc.arguments, "category")
                            .map(|value| MemoryCategory::from_str(&value))
                            .unwrap_or(MemoryCategory::Interaction);
                        self.memory.add(id, content, category);
                    }
                }
                let save_result = self.memory.save("/disk/heliox/memory.json");
                tool_mapper::ToolResult {
                    tool_name: String::from("save_memory"),
                    success: save_result.is_ok(),
                    output: match save_result {
                        Ok(()) => format!(
                            "Memory saved to /disk/heliox/memory.json ({} documents)",
                            self.memory.document_count()
                        ),
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
            "get_config" => tool_mapper::ToolResult {
                tool_name: String::from("get_config"),
                success: true,
                output: format!(
                    "tick_interval={}, save_interval={}, max_retries={}, auto_approve_tier={}",
                    self.config.tick_interval, self.config.save_interval,
                    self.config.max_retries, self.config.auto_approve_tier
                ),
            },
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
            "physical_status" => tool_mapper::ToolResult {
                tool_name: String::from("physical_status"),
                success: true,
                output: self.physical_status_json(),
            },
            "physical_maintenance_demo" => {
                let confirmed = tc.arguments.iter().any(|(key, value)| {
                    key == "confirm_simulation"
                        && matches!(value, super::json::JsonValue::Bool(true))
                });
                if !confirmed {
                    tool_mapper::ToolResult {
                        tool_name: String::from("physical_maintenance_demo"),
                        success: false,
                        output: String::from("confirm_simulation=true is required"),
                    }
                } else {
                    match self.run_physical_maintenance_simulation() {
                        Ok(output) => tool_mapper::ToolResult {
                            tool_name: String::from("physical_maintenance_demo"),
                            success: true,
                            output,
                        },
                        Err(message) => tool_mapper::ToolResult {
                            tool_name: String::from("physical_maintenance_demo"),
                            success: false,
                            output: String::from(message),
                        },
                    }
                }
            }
            _ => tool_mapper::execute(
                tc,
                &mut self.confirmation_gate,
                self.config.auto_approve_tier,
                self.tick_count,
            ),
        }
    }

    /// World model (Phase 1, see model.md): captures a snapshot, predicts
    /// this action's effect, and blocks the real dispatch if the
    /// prediction looks bad - a second, predictive check that runs
    /// *before*, and independently of, `tool_mapper::execute`'s own
    /// internal Tier 3/4 `ConfirmationGate` check. Either way, records an
    /// experience tuple: a predicted-and-refused action is training
    /// signal too, not just an allowed one.
    fn dispatch_with_world_model(&mut self, tc: &super::json::ToolCall) -> tool_mapper::ToolResult {
        // Physical actions have their own observation schema, transition
        // artifact, deterministic interlocks, and audit path. Sending them
        // through the fixed 41-action OS model would create action_id=255
        // training rows and pretend computer-state features describe a site.
        if tc.name == "physical_status" || tc.name == "physical_maintenance_demo" {
            return self.execute_action(tc);
        }

        use super::world_model::{self, encoder, experience, observation};
        use experience::ExperienceTuple;

        let total_started_cycles = unsafe { core::arch::x86_64::_rdtsc() };
        let state_before = observation::capture_snapshot(
            self.tick_count,
            &self.wm_last_action_name,
            self.wm_last_action_failed,
        );
        let decision = world_model::evaluate_action(&state_before, tc);
        let gate_finished_cycles = unsafe { core::arch::x86_64::_rdtsc() };
        let gate_cycles = gate_finished_cycles.saturating_sub(total_started_cycles);

        if decision.allowed {
            self.wm_last_suggestion.clear();
        } else {
            self.wm_last_suggestion = decision.suggestion.clone();
        }

        let result = if !decision.allowed {
            let msg = format!(
                "[heliox-daemon] [world-model] BLOCKED tool '{}': risk={:.2} lookahead_steps={} ({}) suggestion={}\n",
                tc.name, decision.risk, decision.lookahead_steps, decision.reason, decision.suggestion
            );
            unsafe {
                syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64);
            }
            tool_mapper::ToolResult {
                tool_name: tc.name.clone(),
                success: false,
                output: format!(
                    "Blocked by world-model safety gate: {}. Suggested alternative: {}",
                    decision.reason,
                    decision.suggestion
                ),
            }
        } else {
            self.execute_action(tc)
        };
        let execution_attempted = decision.allowed
            && !result.output.contains("Awaiting confirmation")
            && !result.output.contains("Action denied by operator")
            && !result.output.contains("Confirmation request expired");

        let state_after = observation::capture_snapshot(self.tick_count, &tc.name, !result.success);

        // Reward: derived from what's directly observable at this point
        // (the tool's own success/failure and, for file-creating tools,
        // that it succeeded). "Goal achieved" (+1.0) needs
        // verify_and_reflect's plan-completion signal, which fires later
        // and for the whole tick rather than per-call - tying that back
        // into the most recent tuple is a natural, documented Phase 1.5
        // follow-up, not implemented here.
        let reward: f32 = if result.output.contains("Awaiting confirmation") {
            -0.2
        } else if !result.success {
            -0.5
        } else if tc.name == "write_file" || tc.name == "create_directory" {
            0.3
        } else {
            0.0
        };

        let before_embedding = encoder::encode(&state_before);
        let after_embedding = encoder::encode(&state_after);
        experience::record_experience(&ExperienceTuple {
            tick: self.tick_count,
            action_id: world_model::tool_id(&tc.name),
            success: result.success,
            reward,
            risk: decision.risk,
            proc_count_before: encoder::proc_count(&before_embedding),
            proc_count_after: encoder::proc_count(&after_embedding),
            heap_fraction_before: encoder::heap_fraction(&before_embedding),
            heap_fraction_after: encoder::heap_fraction(&after_embedding),
            disk_usage_before: encoder::disk_usage_fraction(&before_embedding),
            disk_usage_after: encoder::disk_usage_fraction(&after_embedding),
        });

        // Directly observable per-call signal for verification (and for
        // anyone tailing the serial log) - deliberately not gated behind
        // the interactive shell regaining control, which a fast-ticking
        // daemon (low tick_interval) can starve for a long time once
        // ring3 init hands off (see scripts/verify_world_model.mjs's
        // comment on why it doesn't type further shell commands after that).
        let tuple_msg = format!(
            "[heliox-daemon] [world-model] recorded experience tuple: tick={} action={} reward={:.2}\n",
            self.tick_count, tc.name, reward
        );
        unsafe {
            syscall3(34, 1, tuple_msg.as_ptr() as u64, tuple_msg.len() as u64);
        }

        // Full-embedding export for offline training (see
        // world_model::emit_dataset_row's doc comment) - the compact
        // exp.bin record above can't hold these.
        world_model::emit_dataset_row(
            self.tick_count,
            &before_embedding,
            tc,
            &after_embedding,
            reward,
            result.success,
            execution_attempted,
            decision.risk,
        );

        self.wm_last_action_name = tc.name.clone();
        self.wm_last_action_failed = !result.success;

        // Privacy-bounded natural-use telemetry. It deliberately excludes
        // prompts, arguments, paths, model/provider identity, and output text;
        // the host-side research collector can measure gate load and operator
        // friction without recording user content. TSC cycles are reported as
        // raw guest measurements and converted to time only by a separately
        // calibrated in-guest benchmark.
        let confirmation = if !decision.allowed {
            "gate_blocked"
        } else if result.output.contains("Awaiting confirmation") {
            "awaiting"
        } else if result.output.contains("Action denied by operator") {
            "denied"
        } else if result.output.contains("Confirmation request expired") {
            "expired"
        } else {
            "not_pending"
        };
        let total_cycles = unsafe { core::arch::x86_64::_rdtsc() }
            .saturating_sub(total_started_cycles);
        let telemetry = format!(
            "[heliox-daemon] [world-model-telemetry-v1] tick={} action={} allowed={} risk={:.4} lookahead={} gate_cycles={} total_cycles={} executed={} success={} confirmation={}\n",
            self.tick_count,
            tc.name,
            if decision.allowed { 1 } else { 0 },
            decision.risk,
            decision.lookahead_steps,
            gate_cycles,
            total_cycles,
            if execution_attempted { 1 } else { 0 },
            if result.success { 1 } else { 0 },
            confirmation,
        );
        unsafe {
            syscall3(34, 1, telemetry.as_ptr() as u64, telemetry.len() as u64);
        }

        result
    }

    /// Runs `count` synthetic-but-real actions through the exact same
    /// `dispatch_with_world_model` path production traffic uses (real
    /// syscalls, real snapshots, real gate decisions) without waiting on
    /// an LLM/HTTP round-trip to propose each one - a fast way to
    /// collect a real training dataset (see
    /// `world_model::synthetic_action`'s doc comment) for offline
    /// training, triggered by `main.rs`'s `check_and_trigger_world_model_collect`.
    pub fn run_data_collection(&mut self, count: u32) {
        for i in 0..count {
            self.tick_count += 1;
            let tc = super::world_model::synthetic_action(i);
            let _ = self.dispatch_with_world_model(&tc);
        }
        let msg = format!("[heliox-daemon] [world-model] data collection complete: {} actions\n", count);
        unsafe {
            syscall3(34, 1, msg.as_ptr() as u64, msg.len() as u64);
        }
    }

    /// Measures the real in-guest capture + encoder + transition + safety path
    /// at H=1..5. The proposed actions are never dispatched. A PIT-based TSC
    /// calibration converts per-call cycle samples to microseconds on this
    /// specific guest run; both values are retained because virtualized TSC
    /// frequency is host/accelerator dependent.
    pub fn run_world_model_benchmark(&mut self, iterations: u32) {
        use super::world_model::{self, observation};

        let iterations = iterations.clamp(20, 2_000);
        let memory_before = observation::capture_snapshot(
            self.tick_count,
            &self.wm_last_action_name,
            self.wm_last_action_failed,
        );
        // Warm file-backed weights, allocator paths, and the observation
        // syscalls before any horizon is measured. Without this, H=1 alone
        // pays the initial page/cache cost and cannot be compared fairly.
        for index in 0..64u32 {
            let action = world_model::synthetic_action(index);
            let state = observation::capture_snapshot(
                self.tick_count.saturating_add(index as u64),
                &self.wm_last_action_name,
                self.wm_last_action_failed,
            );
            let _ = world_model::evaluate_action_with_horizon(&state, &action, 5);
        }
        for horizon in 1..=5u32 {
            let mut cycle_samples = alloc::vec::Vec::with_capacity(iterations as usize);
            let mut tick_samples = alloc::vec::Vec::with_capacity(iterations as usize);
            let mut blocked = 0u32;
            let batch_start_tick = crate::cognitive::fusion::get_uptime_ticks();
            for index in 0..iterations {
                let action = world_model::synthetic_action(index);
                let started_tick = crate::cognitive::fusion::get_uptime_ticks();
                let started = unsafe { core::arch::x86_64::_rdtsc() };
                let state = observation::capture_snapshot(
                    self.tick_count.saturating_add(index as u64),
                    &self.wm_last_action_name,
                    self.wm_last_action_failed,
                );
                let decision = world_model::evaluate_action_with_horizon(&state, &action, horizon);
                let elapsed = unsafe { core::arch::x86_64::_rdtsc() }.saturating_sub(started);
                let elapsed_ticks = crate::cognitive::fusion::get_uptime_ticks()
                    .saturating_sub(started_tick);
                cycle_samples.push(elapsed);
                tick_samples.push(elapsed_ticks);
                if !decision.allowed {
                    blocked = blocked.saturating_add(1);
                }
            }
            let batch_end_tick = crate::cognitive::fusion::get_uptime_ticks();
            cycle_samples.sort_unstable();
            tick_samples.sort_unstable();
            let middle = cycle_samples.len() / 2;
            let p95_index = (cycle_samples.len().saturating_sub(1) * 95) / 100;
            let p99_index = (cycle_samples.len().saturating_sub(1) * 99) / 100;
            let median_cycles = cycle_samples[middle];
            let p95_cycles = cycle_samples[p95_index];
            let p99_cycles = cycle_samples[p99_index];
            let max_cycles = cycle_samples.last().copied().unwrap_or(0);
            let median_us = tick_samples[middle].saturating_mul(1_000);
            let p95_us = tick_samples[p95_index].saturating_mul(1_000);
            let p99_us = tick_samples[p99_index].saturating_mul(1_000);
            let max_us = tick_samples.last().copied().unwrap_or(0).saturating_mul(1_000);
            let batch_ticks = batch_end_tick.saturating_sub(batch_start_tick);
            let mean_us = batch_ticks.saturating_mul(1_000) / iterations as u64;
            let marker = format!(
                "[heliox-daemon] [world-model-benchmark-v3] horizon={} iterations={} batch_ticks={} mean_us={} median_us={} p95_us={} p99_us={} max_us={} median_cycles={} p95_cycles={} p99_cycles={} max_cycles={} blocked={}\n",
                horizon,
                iterations,
                batch_ticks,
                mean_us,
                median_us,
                p95_us,
                p99_us,
                max_us,
                median_cycles,
                p95_cycles,
                p99_cycles,
                max_cycles,
                blocked,
            );
            unsafe {
                syscall3(34, 1, marker.as_ptr() as u64, marker.len() as u64);
            }
        }
        let memory_after = observation::capture_snapshot(
            self.tick_count,
            &self.wm_last_action_name,
            self.wm_last_action_failed,
        );
        let memory_marker = format!(
            "[heliox-daemon] [world-model-benchmark-memory-v1] heap_before={} heap_after={} heap_delta={} encoder_file_bytes=129344 transition_file_bytes=643616 runtime_parameters=193229 encoder_loaded={} transition_loaded={}\n",
            memory_before.heap_used,
            memory_after.heap_used,
            memory_after.heap_used.saturating_sub(memory_before.heap_used),
            if world_model::encoder_learned::is_loaded() { 1 } else { 0 },
            if world_model::learned::is_loaded() { 1 } else { 0 },
        );
        unsafe {
            syscall3(34, 1, memory_marker.as_ptr() as u64, memory_marker.len() as u64);
        }
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
                let console_msg = format!("[heliox-daemon] New goal set via IPC: {}\n", goal_str.trim());
                const SYS_WRITE: u64 = 34;
                const FD_CONSOLE: u64 = 1;
                unsafe {
                    syscall3(SYS_WRITE, FD_CONSOLE, console_msg.as_ptr() as u64, console_msg.len() as u64);
                }
            } else if trimmed == "NEURAL_ARM" || trimmed == "NEURAL_ARM:" {
                let outcome = self.neural_service.arm_from_non_neural_input();
                self.audit_neural_event(if outcome.is_ok() {
                    "safe UI armed from local non-neural input"
                } else {
                    "local neural arm rejected"
                });
                let message = if outcome.is_ok() {
                    String::from("Neural safe UI armed from local non-neural input")
                } else {
                    String::from("Neural arm rejected: pair and calibrate first")
                };
                self.emit_telemetry(TelemetryEventKind::ConfirmationQueued, message.clone());
                let console_msg = format!("[heliox-daemon] {}\n", message);
                unsafe {
                    syscall3(34, 1, console_msg.as_ptr() as u64, console_msg.len() as u64);
                }
            } else if trimmed == "NEURAL_DISARM" || trimmed == "NEURAL_DISARM:" {
                self.neural_disarm();
                self.emit_telemetry(
                    TelemetryEventKind::ConfirmationQueued,
                    String::from("Neural input disarmed from local non-neural input"),
                );
                let console_msg = "[heliox-daemon] neural input disarmed\n";
                unsafe {
                    syscall3(34, 1, console_msg.as_ptr() as u64, console_msg.len() as u64);
                }
            } else if trimmed == "CONFIG_UPDATED" || trimmed == "CONFIG_UPDATED:" {
                self.config = Config::load("/disk/heliox/config.json");
                self.emit_telemetry(
                    TelemetryEventKind::TickStart,
                    String::from("Configuration reloaded via IPC"),
                );
                // emit_telemetry only reaches the GUI's IPC channel, never
                // the console/serial log - the same observability gap
                // already fixed for LLM query results (orchestrator's
                // think()). Print directly too so this is externally
                // observable without inspecting internal daemon state.
                let console_msg = format!(
                    "[heliox-daemon] config reloaded via IPC, active provider: {}\n",
                    self.config.provider
                );
                const SYS_WRITE: u64 = 34;
                const FD_CONSOLE: u64 = 1;
                unsafe {
                    syscall3(SYS_WRITE, FD_CONSOLE, console_msg.as_ptr() as u64, console_msg.len() as u64);
                }
            }
        }
    }
}

fn neural_class_name(class: ferrum_neural_protocol::NeuralClass) -> &'static str {
    match class {
        ferrum_neural_protocol::NeuralClass::Cancel => "cancel",
        ferrum_neural_protocol::NeuralClass::FocusLeft => "focus_left",
        ferrum_neural_protocol::NeuralClass::FocusRight => "focus_right",
        ferrum_neural_protocol::NeuralClass::Select => "select",
    }
}

fn neural_scope_name(scope: ferrum_neural_protocol::NeuralScope) -> &'static str {
    match scope {
        ferrum_neural_protocol::NeuralScope::Observe => "observe",
        ferrum_neural_protocol::NeuralScope::Navigate => "navigate",
        ferrum_neural_protocol::NeuralScope::SafeDesktop => "safe_desktop",
        ferrum_neural_protocol::NeuralScope::PhysicalGoal => "physical_goal",
    }
}
