// ============================================================================
// Heliox-Daemon - Confirmation Gate
// ============================================================================
// Enforces the 5-tier permission model by gating Tier 3+ tool calls
// behind operator approval. When a destructive tool is invoked:
//
//   1. A PendingConfirmation is created and queued.
//   2. The tool returns "awaiting_confirmation" to the orchestrator.
//   3. On subsequent ticks, the orchestrator polls the gate.
//   4. The operator approves/denies via kernel shell IPC.
//   5. Once approved, the tool executes on the next attempt.
//
// Confirmations expire after `timeout_ticks` with auto-deny.
// An approval is bound to the tool name and the complete argument
// fingerprint (authority::approval_fingerprint), is single-use, and cannot
// override a denial. At most MAX_PENDING requests wait at once. For a tool
// that acts on a file, the approval is also bound to the kernel's version of
// that file when the request was made (FileVersion): a change by any process
// withdraws it, and a version the kernel cannot establish refuses the call.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;
use super::authority::PermissionTier;

/// Status of a confirmation request.
#[derive(Debug, Clone, PartialEq)]
pub enum ConfirmationStatus {
    /// Waiting for operator response. Contains the confirmation ID.
    Pending(u32),
    /// Operator approved the action.
    Approved,
    /// Operator denied the action.
    Denied,
    /// The confirmation request timed out.
    Expired,
    /// The request could not be queued (queue full or ids exhausted).
    Refused,
}

/// Most requests that may wait for the operator at once.
pub const MAX_PENDING: usize = 32;

/// The kernel's change counter for a file (FileVersion syscall): `Absent`
/// when nothing exists at the path, otherwise a non-zero version that
/// changes on every write, create or remove by any process and never
/// repeats within a boot.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileVersion {
    Absent,
    Version(u64),
}

/// Where the gate reads file versions from. `Err(())` means the kernel could
/// not establish one; the gate then refuses.
pub type FileVersionSource = fn(&str) -> Result<FileVersion, ()>;

/// The default source: no versions, so every call that needs one is refused.
/// The daemon installs the kernel's (`orchestrator::kernel_file_version`).
pub fn versions_unavailable(_path: &str) -> Result<FileVersion, ()> {
    Err(())
}

/// A single pending confirmation request.
#[derive(Debug, Clone)]
pub struct PendingConfirmation {
    pub id: u32,
    pub tool_name: String,
    /// Exact identity the approval is bound to. Matching never uses the
    /// display text.
    pub args_fingerprint: String,
    /// Escaped, truncation-marked text shown to the operator.
    pub args_summary: String,
    pub tier: PermissionTier,
    pub created_at_tick: u64,
    pub status: InternalStatus,
    /// Normalized path the action is about (`authority::subject_path`).
    /// A later change to that path revokes the request (`revoke_path`).
    pub subject: Option<String>,
    /// Kernel version of the file the action is about (`version_subject`)
    /// when the request was made. The approval holds only while the file
    /// still has this version.
    pub subject_version: Option<FileVersion>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum InternalStatus {
    Pending,
    Approved,
    Denied,
}

/// The confirmation gate manages all pending confirmation requests.
pub struct ConfirmationGate {
    requests: Vec<PendingConfirmation>,
    next_id: u32,
    /// How many ticks before a pending request auto-expires.
    timeout_ticks: u64,
    /// Source of file versions (fails closed until one is installed).
    file_versions: FileVersionSource,
}

impl ConfirmationGate {
    pub fn new(timeout_ticks: u64) -> Self {
        Self {
            requests: Vec::new(),
            next_id: 1,
            timeout_ticks,
            file_versions: versions_unavailable,
        }
    }

    /// Start issuing ids from `next_id` (the daemon seeds it at random per
    /// boot; tests use it to reach the id-exhaustion boundary).
    pub fn with_next_id(timeout_ticks: u64, next_id: u32) -> Self {
        Self { requests: Vec::new(), next_id, timeout_ticks, file_versions: versions_unavailable }
    }

    /// Read file versions from `source` (the daemon passes the kernel's).
    pub fn with_file_versions(mut self, source: FileVersionSource) -> Self {
        self.file_versions = source;
        self
    }

    /// The version `path` has now, as the installed source reports it.
    pub fn file_version(&self, path: &str) -> Result<FileVersion, ()> {
        (self.file_versions)(path)
    }

    /// Records the file version a request is bound to (set when it is made).
    pub fn set_subject_version(&mut self, id: u32, version: Option<FileVersion>) {
        if let Some(req) = self.requests.iter_mut().find(|r| r.id == id) {
            req.subject_version = version;
        }
    }

    /// Withdraws a pending or approved request for this exact call whose
    /// bound file version is not `current`. A denial stays (it is final).
    /// Returns true when one was withdrawn.
    fn withdraw_if_version_changed(&mut self, tool_name: &str, args_fingerprint: &str, current: FileVersion) -> bool {
        let before = self.requests.len();
        self.requests.retain(|r| {
            !(r.tool_name == tool_name
                && r.args_fingerprint == args_fingerprint
                && r.status != InternalStatus::Denied
                && r.subject_version != Some(current))
        });
        self.requests.len() != before
    }

    fn is_expired(&self, req: &PendingConfirmation, current_tick: u64) -> bool {
        // Saturating: a tick earlier than the request (clock rollback) is
        // age 0, never a wrapped huge age.
        current_tick.saturating_sub(req.created_at_tick) > self.timeout_ticks
    }

    /// Check if a tool already has a pending/approved confirmation for these
    /// exact arguments. If not, create a new pending request.
    ///
    /// Returns:
    /// - `Approved` if there is an approved request for this tool+args (consumed)
    /// - `Pending(id)` if there is a pending request (or a new one was just created)
    /// - `Denied` if the operator denied it (consumed)
    /// - `Expired` if it timed out
    /// - `Refused` if no new request can be queued
    pub fn check_or_request(
        &mut self,
        tool_name: &str,
        args_fingerprint: &str,
        tier: PermissionTier,
        current_tick: u64,
    ) -> ConfirmationStatus {
        self.check_or_request_with_display(tool_name, args_fingerprint, args_fingerprint, tier, current_tick)
    }

    pub fn check_or_request_with_display(
        &mut self,
        tool_name: &str,
        args_fingerprint: &str,
        args_display: &str,
        tier: PermissionTier,
        current_tick: u64,
    ) -> ConfirmationStatus {
        if let Some(index) = self.requests.iter().position(|r| {
            r.tool_name == tool_name && r.args_fingerprint == args_fingerprint
        }) {
            let req = &self.requests[index];
            if self.is_expired(req, current_tick) {
                self.requests.remove(index);
                return ConfirmationStatus::Expired;
            }
            return match req.status {
                InternalStatus::Pending => ConfirmationStatus::Pending(req.id),
                InternalStatus::Approved => {
                    // Consume the approval (one-time use)
                    self.requests.remove(index);
                    ConfirmationStatus::Approved
                }
                InternalStatus::Denied => {
                    self.requests.remove(index);
                    ConfirmationStatus::Denied
                }
            };
        }

        // No existing request: create one, if there is room and an id.
        self.cleanup_expired(current_tick);
        if self.requests.len() >= MAX_PENDING {
            return ConfirmationStatus::Refused;
        }
        let id = self.next_id;
        let Some(next) = self.next_id.checked_add(1) else {
            return ConfirmationStatus::Refused;
        };
        self.next_id = next;

        self.requests.push(PendingConfirmation {
            id,
            tool_name: String::from(tool_name),
            args_fingerprint: String::from(args_fingerprint),
            args_summary: String::from(args_display),
            tier,
            created_at_tick: current_tick,
            status: InternalStatus::Pending,
            subject: None,
            subject_version: None,
        });

        ConfirmationStatus::Pending(id)
    }

    /// Records the path a request is about (set right after it is created).
    pub fn set_subject(&mut self, id: u32, subject: Option<String>) {
        if let Some(req) = self.requests.iter_mut().find(|r| r.id == id) {
            req.subject = subject;
        }
    }

    /// The file at `path` is about to change: every pending or approved
    /// request about that path, a path beneath it or a directory above it
    /// is withdrawn. The operator approved an action on what was there; a
    /// replaced binary or file is a different action and must be asked for
    /// again. Returns how many requests were withdrawn.
    pub fn revoke_path(&mut self, path: &str) -> usize {
        let before = self.requests.len();
        self.requests.retain(|r| match &r.subject {
            Some(subject) => !super::authority::paths_overlap(subject, path),
            None => true,
        });
        before - self.requests.len()
    }

    /// Approve a pending confirmation by ID (called from kernel shell via
    /// IPC). A request the operator already denied stays denied.
    pub fn approve(&mut self, id: u32) -> bool {
        if let Some(req) = self.requests.iter_mut().find(|r| r.id == id) {
            if req.status != InternalStatus::Pending {
                return false;
            }
            req.status = InternalStatus::Approved;
            true
        } else {
            false
        }
    }

    /// Deny a confirmation by ID (called from kernel shell via IPC). Denial
    /// also withdraws an approval that has not been used yet.
    pub fn deny(&mut self, id: u32) -> bool {
        if let Some(req) = self.requests.iter_mut().find(|r| r.id == id) {
            req.status = InternalStatus::Denied;
            true
        } else {
            false
        }
    }

    /// Get all pending confirmations (for display in the kernel shell).
    pub fn pending_list(&self) -> Vec<&PendingConfirmation> {
        self.requests.iter()
            .filter(|r| r.status == InternalStatus::Pending)
            .collect()
    }

    /// Clean up expired requests.
    pub fn cleanup_expired(&mut self, current_tick: u64) {
        let timeout = self.timeout_ticks;
        self.requests
            .retain(|r| current_tick.saturating_sub(r.created_at_tick) <= timeout);
    }

    /// Format all pending confirmations for display.
    pub fn format_pending(&self) -> String {
        let pending = self.pending_list();
        if pending.is_empty() {
            return String::from("No pending confirmations.");
        }

        let mut output = String::from("Pending confirmations:\n");
        for req in &pending {
            output.push_str(&format!(
                "  [{}] {} (tier {:?}): {}\n",
                req.id, req.tool_name, req.tier, req.args_summary
            ));
        }
        output
    }
}

/// Outcome of the confirmation step for one tool call.
#[derive(Debug, Clone, PartialEq)]
pub enum Clearance {
    /// No confirmation needed, or a matching approval was consumed.
    Proceed,
    /// `display` is the short line for listings; `full_display` is every
    /// byte of the arguments, printed when the request is created.
    Awaiting { id: u32, display: String, full_display: String },
    Denied,
    Expired,
    Refused,
    /// The file the action is about changed (by any process) after the
    /// request was made; the request or approval is withdrawn and must be
    /// asked for again.
    FileChanged,
}

/// The single confirmation decision used by every execution path
/// (`tool_mapper::execute` and the orchestrator's internal tools). A
/// `Proceed` for a path-modifying tool withdraws every outstanding request
/// about that path, because the call is about to run.
pub fn clear_for_execution(
    gate: &mut ConfirmationGate,
    tool_name: &str,
    args: &[(String, super::json::JsonValue)],
    auto_approve_tier: u8,
    current_tick: u64,
) -> Clearance {
    let clearance = decide(gate, tool_name, args, auto_approve_tier, current_tick);
    if clearance == Clearance::Proceed
        && super::authority::PATH_MODIFYING_TOOLS.contains(&tool_name)
    {
        if let Some(path) = super::authority::subject_path(tool_name, args) {
            gate.revoke_path(&path);
        }
    }
    clearance
}

fn decide(
    gate: &mut ConfirmationGate,
    tool_name: &str,
    args: &[(String, super::json::JsonValue)],
    auto_approve_tier: u8,
    current_tick: u64,
) -> Clearance {
    let tier = super::authority::tool_tier(tool_name);
    if !super::authority::needs_confirmation(tier, auto_approve_tier) {
        return Clearance::Proceed;
    }
    // A call the operator cannot be shown in full is never queued.
    let Some(mut full_display) = super::authority::approval_full_display(args) else {
        return Clearance::Refused;
    };
    let fingerprint = super::authority::approval_fingerprint(args);
    // Bind to the file's version (fi1 K3). A version the kernel cannot
    // establish refuses the call: no request is made and none is used.
    let version: Option<FileVersion> = None;
    let _held_back = match super::authority::version_subject(tool_name, args) {
        Some(path) => match gate.file_version(&path) {
            Ok(version) => Some(version),
            Err(()) => return Clearance::Refused,
        },
        None => None,
    };
    if let Some(current) = version {
        if gate.withdraw_if_version_changed(tool_name, &fingerprint, current) {
            return Clearance::FileChanged;
        }
    }
    let mut display = super::authority::approval_display(args);
    // A file the tool acts on without naming it is shown too (R3-1).
    if let Some(path) = super::authority::implicit_subject(tool_name) {
        let note = alloc::format!("[acts on the file \"{}\" as it is when the action runs]", path);
        for text in [&mut full_display, &mut display] {
            if !text.is_empty() {
                text.push(' ');
            }
            text.push_str(&note);
        }
    }
    match gate.check_or_request_with_display(tool_name, &fingerprint, &display, tier, current_tick) {
        ConfirmationStatus::Approved => Clearance::Proceed,
        ConfirmationStatus::Pending(id) => {
            gate.set_subject(id, super::authority::subject_path(tool_name, args));
            // For an existing request this re-records the same version (a
            // different one was withdrawn above).
            gate.set_subject_version(id, version);
            Clearance::Awaiting { id, display, full_display }
        }
        ConfirmationStatus::Denied => Clearance::Denied,
        ConfirmationStatus::Expired => Clearance::Expired,
        ConfirmationStatus::Refused => Clearance::Refused,
    }
}
