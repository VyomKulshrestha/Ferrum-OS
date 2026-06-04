// ============================================================================
// FerrumOS - Heliox-OS Integration Boundary
// ============================================================================
// This module is the deterministic kernel-side bridge for Heliox-OS style
// agent runtimes. It does NOT execute AI, planners, vector search, or semantic
// memory in kernel space. It registers the wire contracts, capability policy,
// service manifests, and stub surfaces that a userspace Heliox runtime (or a
// Heliox-compatible host daemon) can attach to.
//
// The contracts here mirror the public surface of the Heliox-OS daemon as
// documented in:
//   - IPC_MESSAGE_FORMATS.md (JSON-RPC 2.0 over WebSocket)
//   - schemas/action_plan.schema.json
//   - daemon/pilot/actions.py (ActionType, permission tiers)
//
// The goal is that, when Heliox-OS is ported to FerrumOS userspace, the
// kernel already knows the protocol, the tier policy, the service topology,
// and the audit surface. The runtime services above this boundary can be
// swapped, audited, or sandboxed without re-plumbing the kernel.
// ============================================================================

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;
use spin::Mutex;

// ============================================================================
// Protocol Constants
// ============================================================================

/// Heliox-OS JSON-RPC 2.0 transport contract.
///
/// The Heliox daemon talks to its Tauri front-end over a local WebSocket at
/// `ws://127.0.0.1:8785` with JSON-RPC 2.0 envelopes. FerrumOS does not run a
/// network stack yet, so the kernel records this contract as the future
/// transport target and exposes the same envelope semantics through the
/// capability-checked kernel IPC broker.
pub const HELIOX_TRANSPORT: &str = "ws://127.0.0.1:8785";
pub const HELIOX_PROTOCOL: &str = "jsonrpc/2.0";
pub const HELIOX_VERSION: &str = "heliox-0.7.1-compat";

/// Reserved channel for Heliox-OS bridge IPC traffic.
pub const HELIOX_SERVICE: &str = "runtime.heliox";
pub const HELIOX_CHANNEL: &str = "bridge";
pub const HELIOX_RESOURCE: &str = "heliox:bridge";

/// Capability tokens required to control the Heliox bridge.
pub const HELIOX_BRIDGE_CAP: &str = "cap:heliox:bridge";
pub const HELIOX_EXECUTE_CAP: &str = "cap:heliox:execute";
pub const HELIOX_VOICE_CAP: &str = "cap:heliox:voice";
pub const HELIOX_GESTURE_CAP: &str = "cap:heliox:gesture";
pub const HELIOX_SCREEN_CAP: &str = "cap:heliox:screen";
pub const HELIOX_PERSONA_CAP: &str = "cap:heliox:persona";

// ============================================================================
// JSON-RPC 2.0 Envelope
// ============================================================================

/// JSON-RPC 2.0 envelope kind.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EnvelopeKind {
    Request,
    Response,
    Error,
    Notification,
}

/// JSON-RPC 2.0 envelope.
///
/// Heliox-OS uses four envelope shapes:
/// - request:   `{ "jsonrpc": "2.0", "method", "params", "id" }`
/// - response:  `{ "jsonrpc": "2.0", "result", "id" }`
/// - error:     `{ "jsonrpc": "2.0", "error": { "code", "message" }, "id" }`
/// - notif:     `{ "jsonrpc": "2.0", "method", "params" }`
///
/// FerrumOS does not parse JSON in the kernel. It records the envelope shape
/// and routes the deterministic metadata through the kernel IPC broker. The
/// actual JSON serialisation belongs in the future userspace Heliox runtime.
#[derive(Debug, Clone)]
pub struct Envelope {
    pub kind: EnvelopeKind,
    pub method: String,
    pub id: u64,
    pub has_params: bool,
    pub error_code: i64,
}

impl Envelope {
    pub fn request(method: &str, id: u64) -> Self {
        Self {
            kind: EnvelopeKind::Request,
            method: method.to_string(),
            id,
            has_params: true,
            error_code: 0,
        }
    }

    pub fn notification(method: &str) -> Self {
        Self {
            kind: EnvelopeKind::Notification,
            method: method.to_string(),
            id: 0,
            has_params: true,
            error_code: 0,
        }
    }

    pub fn response(id: u64) -> Self {
        Self {
            kind: EnvelopeKind::Response,
            method: String::new(),
            id,
            has_params: false,
            error_code: 0,
        }
    }

    pub fn error(id: u64, code: i64) -> Self {
        Self {
            kind: EnvelopeKind::Error,
            method: String::new(),
            id,
            has_params: false,
            error_code: code,
        }
    }

    pub fn kind_name(&self) -> &'static str {
        match self.kind {
            EnvelopeKind::Request => "request",
            EnvelopeKind::Response => "response",
            EnvelopeKind::Error => "error",
            EnvelopeKind::Notification => "notification",
        }
    }
}

/// Standard JSON-RPC 2.0 error codes used by Heliox-OS.
pub mod error_codes {
    pub const PARSE_ERROR: i64 = -32700;
    pub const INVALID_REQUEST: i64 = -32600;
    pub const METHOD_NOT_FOUND: i64 = -32601;
    pub const INVALID_PARAMS: i64 = -32602;
    pub const INTERNAL_ERROR: i64 = -32603;
}

// ============================================================================
// Method Registry
// ============================================================================

/// Method classification for the Heliox JSON-RPC surface.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MethodClass {
    /// Synchronous request from UI to daemon, expects a `result` or `error`.
    Request,
    /// Asynchronous broadcast from daemon to UI, never carries an `id`.
    Notification,
}

/// Stable method descriptor for the Heliox JSON-RPC surface.
#[derive(Debug, Clone)]
pub struct MethodSpec {
    pub name: &'static str,
    pub class: MethodClass,
    pub description: &'static str,
    /// Capability required to invoke the method.
    pub required_capability: &'static str,
}

const METHODS: &[MethodSpec] = &[
    // ---- Core pipeline ----
    MethodSpec { name: "execute", class: MethodClass::Request, description: "Run the full ReAct pipeline for a user command", required_capability: HELIOX_EXECUTE_CAP },
    MethodSpec { name: "confirm", class: MethodClass::Request, description: "Resolve a pending confirmation gate", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Configuration ----
    MethodSpec { name: "get_config", class: MethodClass::Request, description: "Return the daemon's full runtime configuration", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "update_config", class: MethodClass::Request, description: "Update one config section", required_capability: HELIOX_BRIDGE_CAP },
    // ---- History & memory ----
    MethodSpec { name: "get_history", class: MethodClass::Request, description: "Retrieve past interactions from the memory store", required_capability: HELIOX_BRIDGE_CAP },
    // ---- API key management ----
    MethodSpec { name: "store_api_key", class: MethodClass::Request, description: "Store an API key in the encrypted vault", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "delete_api_key", class: MethodClass::Request, description: "Delete a stored API key", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "list_api_keys", class: MethodClass::Request, description: "List all providers with stored keys", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Health & discovery ----
    MethodSpec { name: "ping", class: MethodClass::Request, description: "Check connectivity", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "health", class: MethodClass::Request, description: "Check all model backend health", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "system_status", class: MethodClass::Request, description: "Return platform information", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "capabilities", class: MethodClass::Request, description: "List all available action types", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "list_ollama_models", class: MethodClass::Request, description: "Discover locally available Ollama models", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Agent routing & orchestration ----
    MethodSpec { name: "agent_routing", class: MethodClass::Request, description: "Dry-run routing analysis for a given input", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "agent_stats", class: MethodClass::Request, description: "Performance statistics for registered specialist agents", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "agent_capabilities", class: MethodClass::Request, description: "Capabilities of every registered agent", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "agent_spawn", class: MethodClass::Request, description: "Dynamically spawn a new specialist agent", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Multimodal input ----
    MethodSpec { name: "voice_event", class: MethodClass::Request, description: "Feed a voice transcript to the fusion engine", required_capability: HELIOX_VOICE_CAP },
    MethodSpec { name: "gesture_event", class: MethodClass::Request, description: "Feed a gesture event to the fusion engine", required_capability: HELIOX_GESTURE_CAP },
    MethodSpec { name: "multimodal_stats", class: MethodClass::Request, description: "Fusion engine statistics", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Reasoning visualization ----
    MethodSpec { name: "reasoning_log", class: MethodClass::Request, description: "Return the full reasoning event log", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "reasoning_stats", class: MethodClass::Request, description: "Reasoning emitter statistics", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Task decomposition & simulation ----
    MethodSpec { name: "decompose_task", class: MethodClass::Request, description: "Break a complex goal into a dependency-ordered tree", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "simulate_plan", class: MethodClass::Request, description: "Dry-analyze a pending plan for impact", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Prompt improvement ----
    MethodSpec { name: "prompt_strategies", class: MethodClass::Request, description: "Return proven prompt strategies", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "prompt_stats", class: MethodClass::Request, description: "Prompt improvement statistics", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Plugin ecosystem ----
    MethodSpec { name: "plugin_list", class: MethodClass::Request, description: "List all loaded plugins and their stats", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "plugin_tools", class: MethodClass::Request, description: "List all tools exposed by loaded plugins", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "plugin_toggle", class: MethodClass::Request, description: "Enable or disable a plugin by name", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Subconscious / persona ----
    MethodSpec { name: "persona_rules", class: MethodClass::Request, description: "Return all learned persona rules and preferences", required_capability: HELIOX_PERSONA_CAP },
    MethodSpec { name: "persona_consolidate", class: MethodClass::Request, description: "Force a consolidation cycle", required_capability: HELIOX_PERSONA_CAP },
    MethodSpec { name: "persona_add_preference", class: MethodClass::Request, description: "Manually record a user preference", required_capability: HELIOX_PERSONA_CAP },
    MethodSpec { name: "subconscious_stats", class: MethodClass::Request, description: "Subconscious agent statistics", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Screen vision ----
    MethodSpec { name: "screen_context", class: MethodClass::Request, description: "Return the current screen context summary", required_capability: HELIOX_SCREEN_CAP },
    MethodSpec { name: "screen_current_app", class: MethodClass::Request, description: "Return the currently active application", required_capability: HELIOX_SCREEN_CAP },
    MethodSpec { name: "screen_vision_stats", class: MethodClass::Request, description: "Screen vision statistics", required_capability: HELIOX_SCREEN_CAP },
    MethodSpec { name: "screen_vision_toggle", class: MethodClass::Request, description: "Start or stop the screen vision agent", required_capability: HELIOX_SCREEN_CAP },
    // ---- Cognitive intelligence ----
    MethodSpec { name: "cognitive_stats", class: MethodClass::Request, description: "Statistics for all cognitive subsystems", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "cognitive_state", class: MethodClass::Request, description: "Current predicted cognitive state", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "attention_toggle", class: MethodClass::Request, description: "Enable or disable attention-aware notification scoring", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "stress_gate_toggle", class: MethodClass::Request, description: "Enable or disable stress-aware task gating", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "intent_predictor_toggle", class: MethodClass::Request, description: "Enable or disable JARVIS-mode intent prediction", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "tribe_model_toggle", class: MethodClass::Request, description: "Load, unload, or query the TRIBE v2 local model", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Voice listener ----
    MethodSpec { name: "voice_listener_start", class: MethodClass::Request, description: "Start the continuous wake-word voice listener", required_capability: HELIOX_VOICE_CAP },
    MethodSpec { name: "voice_listener_stop", class: MethodClass::Request, description: "Stop the voice listener", required_capability: HELIOX_VOICE_CAP },
    MethodSpec { name: "voice_listener_stats", class: MethodClass::Request, description: "Voice listener statistics", required_capability: HELIOX_VOICE_CAP },
    // ---- Autonomous executor ----
    MethodSpec { name: "autonomous_submit", class: MethodClass::Request, description: "Submit a goal for fire-and-forget background execution", required_capability: HELIOX_EXECUTE_CAP },
    MethodSpec { name: "autonomous_cancel", class: MethodClass::Request, description: "Cancel a running autonomous job", required_capability: HELIOX_EXECUTE_CAP },
    MethodSpec { name: "autonomous_jobs", class: MethodClass::Request, description: "List all autonomous jobs", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "autonomous_job", class: MethodClass::Request, description: "Get a single autonomous job by ID", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Proactive suggestions ----
    MethodSpec { name: "proactive_start", class: MethodClass::Request, description: "Start the proactive suggestion engine", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "proactive_stop", class: MethodClass::Request, description: "Stop the proactive suggestion engine", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "proactive_stats", class: MethodClass::Request, description: "Proactive engine statistics", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "proactive_accept", class: MethodClass::Request, description: "Accept and execute a proactive suggestion", required_capability: HELIOX_EXECUTE_CAP },
    MethodSpec { name: "proactive_dismiss", class: MethodClass::Request, description: "Dismiss a proactive suggestion", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Background tasks ----
    MethodSpec { name: "background_tasks", class: MethodClass::Request, description: "List all registered background monitoring tasks", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "background_start", class: MethodClass::Request, description: "Start a background monitoring task", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "background_stop", class: MethodClass::Request, description: "Stop a background monitoring task", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "reflection_stats", class: MethodClass::Request, description: "Self-improvement reflection statistics", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Git conflict resolver ----
    MethodSpec { name: "resolve_git_conflict", class: MethodClass::Request, description: "Parse a conflict file and return resolution candidates", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "apply_git_resolution", class: MethodClass::Request, description: "Apply a git conflict resolution block atomically", required_capability: HELIOX_BRIDGE_CAP },
    // ---- Daemon -> UI notifications ----
    MethodSpec { name: "status", class: MethodClass::Notification, description: "Current pipeline stage during execute", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "agent_routing", class: MethodClass::Notification, description: "Which specialist agents were selected", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "plan_preview", class: MethodClass::Notification, description: "Full plan generated by the planner", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "confirm_required", class: MethodClass::Notification, description: "Sent when one or more actions require explicit approval", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "action_start", class: MethodClass::Notification, description: "Fired immediately before each action is executed", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "action_complete", class: MethodClass::Notification, description: "Fired after each action finishes", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "orchestrator_routing", class: MethodClass::Notification, description: "Multi-agent orchestrator assignment", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "reasoning_event", class: MethodClass::Notification, description: "Granular thought-visualization telemetry", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "voice_command", class: MethodClass::Notification, description: "Voice listener recognized a command", required_capability: HELIOX_VOICE_CAP },
    MethodSpec { name: "voice_status", class: MethodClass::Notification, description: "Voice listener lifecycle updates", required_capability: HELIOX_VOICE_CAP },
    MethodSpec { name: "voice_result", class: MethodClass::Notification, description: "Result of a voice-triggered command execution", required_capability: HELIOX_VOICE_CAP },
    MethodSpec { name: "multimodal_intent", class: MethodClass::Notification, description: "Fused voice + gesture intent", required_capability: HELIOX_BRIDGE_CAP },
    MethodSpec { name: "feature_announcement", class: MethodClass::Notification, description: "Emitted on startup when new capabilities arrive", required_capability: HELIOX_BRIDGE_CAP },
];

/// Number of registered Heliox methods.
pub fn method_count() -> usize {
    METHODS.len()
}

/// Number of methods in a class.
pub fn method_count_by_class(class: MethodClass) -> usize {
    METHODS.iter().filter(|m| m.class == class).count()
}

/// Return the full method table.
pub fn list_methods() -> Vec<MethodSpec> {
    METHODS.to_vec()
}

/// Find a method by name.
pub fn find_method(name: &str) -> Option<MethodSpec> {
    METHODS.iter().find(|m| m.name == name).cloned()
}

// ============================================================================
// Permission Tier Model (matches Heliox-OS ActionType tiering)
// ============================================================================

/// Heliox-OS 5-tier permission model.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PermissionTier {
    /// Read-only actions.
    Tier0ReadOnly,
    /// User write actions.
    Tier1UserWrite,
    /// System-modifying actions.
    Tier2SystemModify,
    /// Destructive actions.
    Tier3Destructive,
    /// Root-critical actions.
    Tier4RootCritical,
}

impl PermissionTier {
    pub fn index(self) -> u8 {
        match self {
            Self::Tier0ReadOnly => 0,
            Self::Tier1UserWrite => 1,
            Self::Tier2SystemModify => 2,
            Self::Tier3Destructive => 3,
            Self::Tier4RootCritical => 4,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Self::Tier0ReadOnly => "Tier 0 - Read Only",
            Self::Tier1UserWrite => "Tier 1 - User Write",
            Self::Tier2SystemModify => "Tier 2 - System Modify",
            Self::Tier3Destructive => "Tier 3 - Destructive",
            Self::Tier4RootCritical => "Tier 4 - Root Critical",
        }
    }

    /// Whether this tier auto-executes or requires confirmation under the
    /// default Heliox-OS security profile.
    pub fn requires_confirmation(self) -> bool {
        matches!(self, Self::Tier2SystemModify | Self::Tier3Destructive | Self::Tier4RootCritical)
    }
}

/// Catalog of Heliox-OS action types grouped by permission tier.
#[derive(Debug, Clone)]
pub struct ActionCategory {
    pub tier: PermissionTier,
    pub actions: &'static [&'static str],
}

const TIER_0_ACTIONS: &[&str] = &[
    "file_read", "file_list", "file_search", "directory_summary", "package_search",
    "service_status", "gnome_setting_read", "open_url", "open_application", "notify",
    "process_list", "process_info", "clipboard_read", "system_info", "disk_usage",
    "memory_usage", "cpu_usage", "network_info", "battery_info", "env_get", "env_list",
    "window_list", "volume_get", "brightness_get", "screenshot", "wifi_list", "disk_list",
    "user_list", "user_info", "schedule_list", "mouse_position", "screen_ocr",
    "screen_find_text", "screen_analyze", "screen_element_map", "browser_extract",
    "browser_extract_table", "browser_extract_links", "browser_screenshot",
    "browser_list_tabs", "browser_page_info", "trigger_list", "file_parse",
    "file_search_content", "api_scrape", "registry_read",
];

const TIER_1_ACTIONS: &[&str] = &[
    "file_write", "file_move", "file_copy", "git_resolve", "clipboard_write",
    "keyboard_type", "keyboard_press", "keyboard_hotkey", "keyboard_hold",
    "mouse_click", "mouse_double_click", "mouse_right_click", "mouse_move",
    "mouse_drag", "mouse_scroll", "volume_set", "volume_mute", "brightness_set",
    "window_focus", "window_minimize", "window_maximize", "browser_navigate",
    "browser_click", "browser_type", "browser_select", "browser_hover",
    "browser_scroll", "browser_execute_js", "browser_fill_form", "browser_new_tab",
    "browser_close_tab", "browser_switch_tab", "browser_back", "browser_forward",
    "browser_refresh", "browser_wait", "browser_close", "env_set", "download_file",
    "api_request", "api_github", "code_execute", "code_generate_and_run",
    "trigger_create", "trigger_start", "trigger_stop",
];

const TIER_2_ACTIONS: &[&str] = &[
    "package_install", "package_update", "service_start", "service_stop",
    "service_restart", "service_enable", "service_disable", "gnome_setting_write",
    "shell_command", "shell_script", "schedule_create", "file_permissions",
    "wifi_connect", "wifi_disconnect", "disk_mount", "registry_write",
    "api_send_email", "api_webhook", "api_slack", "api_discord",
];

const TIER_3_ACTIONS: &[&str] = &[
    "file_delete", "package_remove", "process_kill", "power_shutdown",
    "power_restart", "power_logout", "schedule_delete", "disk_unmount",
    "window_close", "trigger_delete", "browser_click_text",
];

const TIER_4_ACTIONS: &[&str] = &[
    "power_sleep", "power_lock", "dbus_call",
];

const ACTION_CATEGORIES: &[ActionCategory] = &[
    ActionCategory { tier: PermissionTier::Tier0ReadOnly, actions: TIER_0_ACTIONS },
    ActionCategory { tier: PermissionTier::Tier1UserWrite, actions: TIER_1_ACTIONS },
    ActionCategory { tier: PermissionTier::Tier2SystemModify, actions: TIER_2_ACTIONS },
    ActionCategory { tier: PermissionTier::Tier3Destructive, actions: TIER_3_ACTIONS },
    ActionCategory { tier: PermissionTier::Tier4RootCritical, actions: TIER_4_ACTIONS },
];

/// Total number of registered Heliox action types.
pub fn action_count() -> usize {
    ACTION_CATEGORIES.iter().map(|c| c.actions.len()).sum()
}

/// Return the action category table.
pub fn list_action_categories() -> Vec<ActionCategory> {
    ACTION_CATEGORIES.to_vec()
}

/// Look up the permission tier of an action by name.
pub fn tier_for_action(action: &str) -> Option<PermissionTier> {
    ACTION_CATEGORIES
        .iter()
        .find(|category| category.actions.iter().any(|a| *a == action))
        .map(|category| category.tier)
}

// ============================================================================
// Heliox Runtime Service Catalog
// ============================================================================

/// Logical runtime service slot that the Heliox bridge expects to find above
/// the kernel. FerrumOS registers each of these as a sandboxed runtime service
/// manifest at boot so the topology already matches the Heliox runtime
/// architecture before userspace services exist.
#[derive(Debug, Clone)]
pub struct RuntimeSlot {
    pub name: &'static str,
    pub description: &'static str,
    pub required_capability: &'static str,
}

const RUNTIME_SLOTS: &[RuntimeSlot] = &[
    RuntimeSlot { name: "runtime.heliox.bridge", description: "Heliox-OS JSON-RPC bridge service", required_capability: HELIOX_BRIDGE_CAP },
    RuntimeSlot { name: "runtime.heliox.input", description: "Voice, gesture, and multimodal event intake", required_capability: HELIOX_VOICE_CAP },
    RuntimeSlot { name: "runtime.heliox.inference", description: "Local model inference (Ollama, TRIBE, cloud LLM)", required_capability: HELIOX_EXECUTE_CAP },
    RuntimeSlot { name: "runtime.heliox.memory", description: "Semantic memory and vector store (ChromaDB-class)", required_capability: HELIOX_BRIDGE_CAP },
    RuntimeSlot { name: "runtime.heliox.orchestrator", description: "Multi-agent planner, orchestrator, verifier, reflector", required_capability: HELIOX_EXECUTE_CAP },
    RuntimeSlot { name: "runtime.heliox.screen", description: "Screen vision and active app detection", required_capability: HELIOX_SCREEN_CAP },
    RuntimeSlot { name: "runtime.heliox.persona", description: "Subconscious persona learning and consolidation", required_capability: HELIOX_PERSONA_CAP },
    RuntimeSlot { name: "runtime.heliox.plugins", description: "Plugin registry and Ed25519 signature verification", required_capability: HELIOX_BRIDGE_CAP },
    RuntimeSlot { name: "runtime.heliox.audit", description: "Audit exporter for Heliox-OS lifecycle events", required_capability: HELIOX_BRIDGE_CAP },
];

/// Return the Heliox runtime service slots.
pub fn runtime_slots() -> Vec<RuntimeSlot> {
    RUNTIME_SLOTS.to_vec()
}

// ============================================================================
// Bridge State
// ============================================================================

/// Multinodal fusion class for voice/gesture intents.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FusionType {
    VoiceGesture,
    VoiceOnly,
    GestureOnly,
    Single,
}

impl FusionType {
    pub fn name(self) -> &'static str {
        match self {
            Self::VoiceGesture => "voice_gesture",
            Self::VoiceOnly => "voice_only",
            Self::GestureOnly => "gesture_only",
            Self::Single => "single",
        }
    }
}

/// Voice listener state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceListenerState {
    Stopped,
    Listening,
    Processing,
    Error,
}

impl VoiceListenerState {
    pub fn name(self) -> &'static str {
        match self {
            Self::Stopped => "stopped",
            Self::Listening => "listening",
            Self::Processing => "processing",
            Self::Error => "error",
        }
    }
}

/// Screen vision state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScreenVisionState {
    Disabled,
    Enabled,
}

/// Persona rule category.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersonaCategory {
    Preference,
    Habit,
    Constraint,
    Style,
}

impl PersonaCategory {
    pub fn name(self) -> &'static str {
        match self {
            Self::Preference => "preference",
            Self::Habit => "habit",
            Self::Constraint => "constraint",
            Self::Style => "style",
        }
    }
}

/// Reasoning pipeline phase (matches Heliox `status` notification values).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PipelinePhase {
    ReceivingInput,
    RecallingMemory,
    RoutingAgents,
    Planning,
    Replanning,
    Executing,
    Verifying,
    Retrying,
}

impl PipelinePhase {
    pub fn name(self) -> &'static str {
        match self {
            Self::ReceivingInput => "receiving input",
            Self::RecallingMemory => "recalling memory",
            Self::RoutingAgents => "routing agents",
            Self::Planning => "planning",
            Self::Replanning => "re-planning (attempt 2)",
            Self::Executing => "executing",
            Self::Verifying => "verifying",
            Self::Retrying => "retrying - previous attempt failed",
        }
    }
}

/// Reasoning event type (matches Heliox `reasoning_event` envelope).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReasoningEventType {
    PhaseStart,
    PhaseComplete,
    PhaseError,
    Thought,
    Decision,
    Data,
    Progress,
    Metric,
}

impl ReasoningEventType {
    pub fn name(self) -> &'static str {
        match self {
            Self::PhaseStart => "phase_start",
            Self::PhaseComplete => "phase_complete",
            Self::PhaseError => "phase_error",
            Self::Thought => "thought",
            Self::Decision => "decision",
            Self::Data => "data",
            Self::Progress => "progress",
            Self::Metric => "metric",
        }
    }
}

/// Pending confirmation gate.
#[derive(Debug, Clone)]
pub struct PendingConfirmation {
    pub plan_id: String,
    pub actions: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct MultimodalIntent {
    pub command: String,
    pub voice_component: String,
    pub gesture_component: String,
    pub fusion_type: FusionType,
}

#[derive(Debug, Clone)]
pub struct PersonaRule {
    pub key: String,
    pub value: String,
    pub category: PersonaCategory,
    pub confidence: u8,
}

struct HelioxState {
    service_ids: Vec<u64>,
    voice_listener: VoiceListenerState,
    voice_events_received: u64,
    gesture_events_received: u64,
    voice_commands: u64,
    multimodal_intents: u64,
    screen_vision: ScreenVisionState,
    screen_frames: u64,
    persona_rules: Vec<PersonaRule>,
    pending_confirmations: Vec<PendingConfirmation>,
    last_envelope: Option<Envelope>,
    envelopes_seen: u64,
    methods_invoked: u64,
    methods_denied: u64,
    last_execute_input: String,
    last_pipeline_phase: Option<PipelinePhase>,
}

impl HelioxState {
    const fn new() -> Self {
        Self {
            service_ids: Vec::new(),
            voice_listener: VoiceListenerState::Stopped,
            voice_events_received: 0,
            gesture_events_received: 0,
            voice_commands: 0,
            multimodal_intents: 0,
            screen_vision: ScreenVisionState::Disabled,
            screen_frames: 0,
            persona_rules: Vec::new(),
            pending_confirmations: Vec::new(),
            last_envelope: None,
            envelopes_seen: 0,
            methods_invoked: 0,
            methods_denied: 0,
            last_execute_input: String::new(),
            last_pipeline_phase: None,
        }
    }
}

static HELIOX: Mutex<HelioxState> = Mutex::new(helix_state_new_const());

const fn helix_state_new_const() -> HelioxState {
    HelioxState::new()
}

/// Initialize the Heliox bridge: register the capability tokens, register the
/// runtime service manifests, and seed the bridge state.
pub fn init() {
    use crate::services::{register_manifest, SandboxProfile, ServiceLayer, ServiceManifest};

    // Register capability tokens for Heliox-specific authority.
    let _ = crate::security::register_capability(
        HELIOX_BRIDGE_CAP,
        "Heliox bridge control",
        "heliox:*",
        false,
    );
    let _ = crate::security::register_capability(
        HELIOX_EXECUTE_CAP,
        "Heliox execute / autonomous submission",
        "heliox:execute",
        false,
    );
    let _ = crate::security::register_capability(
        HELIOX_VOICE_CAP,
        "Heliox voice event intake",
        "heliox:voice:*",
        false,
    );
    let _ = crate::security::register_capability(
        HELIOX_GESTURE_CAP,
        "Heliox gesture event intake",
        "heliox:gesture:*",
        false,
    );
    let _ = crate::security::register_capability(
        HELIOX_SCREEN_CAP,
        "Heliox screen vision control",
        "heliox:screen:*",
        false,
    );
    let _ = crate::security::register_capability(
        HELIOX_PERSONA_CAP,
        "Heliox persona learning control",
        "heliox:persona:*",
        false,
    );

    // Register one sandboxed runtime service manifest per Heliox slot.
    let mut state = HELIOX.lock();
    state.service_ids.clear();
    for slot in RUNTIME_SLOTS {
        let id = register_manifest(ServiceManifest::new(
            slot.name,
            slot.description,
            ServiceLayer::Runtime,
            alloc::vec![String::from(slot.required_capability)],
            SandboxProfile::runtime_default(),
        ));
        state.service_ids.push(id);
    }
}

/// Snapshot of the Heliox bridge state.
#[derive(Debug, Clone)]
pub struct BridgeStatus {
    pub transport: &'static str,
    pub protocol: &'static str,
    pub version: &'static str,
    pub services_registered: usize,
    pub methods: usize,
    pub actions: usize,
    pub voice_listener: VoiceListenerState,
    pub voice_events: u64,
    pub gesture_events: u64,
    pub voice_commands: u64,
    pub multimodal_intents: u64,
    pub screen_vision: ScreenVisionState,
    pub screen_frames: u64,
    pub persona_rules: usize,
    pub pending_confirmations: usize,
    pub envelopes_seen: u64,
    pub methods_invoked: u64,
    pub methods_denied: u64,
    pub last_pipeline_phase: Option<PipelinePhase>,
}

/// Return a snapshot of bridge state.
pub fn status() -> BridgeStatus {
    let state = HELIOX.lock();
    BridgeStatus {
        transport: HELIOX_TRANSPORT,
        protocol: HELIOX_PROTOCOL,
        version: HELIOX_VERSION,
        services_registered: state.service_ids.len(),
        methods: method_count(),
        actions: action_count(),
        voice_listener: state.voice_listener,
        voice_events: state.voice_events_received,
        gesture_events: state.gesture_events_received,
        voice_commands: state.voice_commands,
        multimodal_intents: state.multimodal_intents,
        screen_vision: state.screen_vision,
        screen_frames: state.screen_frames,
        persona_rules: state.persona_rules.len(),
        pending_confirmations: state.pending_confirmations.len(),
        envelopes_seen: state.envelopes_seen,
        methods_invoked: state.methods_invoked,
        methods_denied: state.methods_denied,
        last_pipeline_phase: state.last_pipeline_phase,
    }
}

/// Authorize a method invocation against the caller's held capabilities.
pub fn authorize_method(method_name: &str, held_capabilities: &[String]) -> Result<(), String> {
    let method = find_method(method_name)
        .ok_or_else(|| alloc::format!("method not found: {}", method_name))?;

    if !crate::security::holds_capability_token(held_capabilities, method.required_capability) {
        let mut state = HELIOX.lock();
        state.methods_denied += 1;
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::PermissionDenied,
            &alloc::format!(
                "heliox method {} denied; caller lacks {}",
                method_name, method.required_capability
            ),
        );
        return Err(alloc::format!(
            "missing capability {}",
            method.required_capability
        ));
    }

    Ok(())
}

/// Submit a Heliox JSON-RPC request envelope to the kernel bridge.
pub fn submit_request(
    method_name: &str,
    input: &str,
    held_capabilities: &[String],
) -> Result<Envelope, String> {
    if let Err(err) = authorize_method(method_name, held_capabilities) {
        return Err(err);
    }

    let method = find_method(method_name)
        .ok_or_else(|| alloc::format!("method not found: {}", method_name))?;
    if method.class != MethodClass::Request {
        return Err(alloc::format!(
            "{} is a notification, not a request",
            method_name
        ));
    }

    let id = next_envelope_id();
    let envelope = Envelope::request(method_name, id);

    let mut state = HELIOX.lock();
    state.envelopes_seen += 1;
    state.methods_invoked += 1;
    state.last_envelope = Some(envelope.clone());

    // Dispatch the deterministic kernel-side effects. AI / model / planner
    // work belongs in userspace services and is intentionally stubbed here.
    match method_name {
        "execute" | "autonomous_submit" => {
            state.last_execute_input = String::from(input);
            state.last_pipeline_phase = Some(PipelinePhase::ReceivingInput);
        }
        "voice_event" => {
            state.voice_events_received += 1;
            if !input.is_empty() {
                state.voice_commands += 1;
            }
        }
        "gesture_event" => {
            state.gesture_events_received += 1;
        }
        "screen_context" | "screen_current_app" => {
            state.screen_frames += 1;
        }
        "persona_add_preference" => {
            if let Some((key, value)) = input.split_once('=') {
                state.persona_rules.push(PersonaRule {
                    key: String::from(key.trim()),
                    value: String::from(value.trim()),
                    category: PersonaCategory::Preference,
                    confidence: 100,
                });
            }
        }
        "voice_listener_start" => {
            state.voice_listener = VoiceListenerState::Listening;
        }
        "voice_listener_stop" => {
            state.voice_listener = VoiceListenerState::Stopped;
        }
        "screen_vision_toggle" => {
            state.screen_vision = match input {
                "on" | "true" | "1" => ScreenVisionState::Enabled,
                "off" | "false" | "0" => ScreenVisionState::Disabled,
                _ => state.screen_vision,
            };
        }
        "confirm" => {
            state
                .pending_confirmations
                .retain(|p| !input.is_empty() && p.plan_id != input);
        }
        _ => {}
    }

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &alloc::format!("heliox envelope dispatched: {}", method_name),
    );

    Ok(envelope)
}

/// Submit a deterministic Heliox notification envelope.
pub fn submit_notification(method_name: &str) -> Result<Envelope, String> {
    let method = find_method(method_name)
        .ok_or_else(|| alloc::format!("notification not found: {}", method_name))?;
    if method.class != MethodClass::Notification {
        return Err(alloc::format!(
            "{} is a request, not a notification",
            method_name
        ));
    }

    let envelope = Envelope::notification(method_name);

    let mut state = HELIOX.lock();
    state.envelopes_seen += 1;
    state.last_envelope = Some(envelope.clone());

    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &alloc::format!("heliox notification prepared: {}", method_name),
    );

    Ok(envelope)
}

/// Emit a fused multimodal intent.
pub fn record_multimodal_intent(
    voice: &str,
    gesture: &str,
    fusion: FusionType,
) -> MultimodalIntent {
    let intent = MultimodalIntent {
        command: alloc::format!("{} {}", voice, gesture),
        voice_component: String::from(voice),
        gesture_component: String::from(gesture),
        fusion_type: fusion,
    };
    HELIOX.lock().multimodal_intents += 1;
    intent
}

/// Record a pending confirmation gate from the planner.
pub fn record_pending_confirmation(plan_id: &str, actions: Vec<String>) {
    HELIOX.lock()
        .pending_confirmations
        .push(PendingConfirmation {
            plan_id: String::from(plan_id),
            actions,
        });
}

/// Update the recorded pipeline phase (e.g. when the planner advances).
pub fn record_pipeline_phase(phase: PipelinePhase) {
    HELIOX.lock().last_pipeline_phase = Some(phase);
}

/// List recorded persona rules.
pub fn persona_rules() -> Vec<PersonaRule> {
    HELIOX.lock().persona_rules.clone()
}

/// List pending confirmation gates.
pub fn pending_confirmations() -> Vec<PendingConfirmation> {
    HELIOX.lock().pending_confirmations.clone()
}

fn next_envelope_id() -> u64 {
    use core::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(1);
    NEXT.fetch_add(1, Ordering::SeqCst)
}
