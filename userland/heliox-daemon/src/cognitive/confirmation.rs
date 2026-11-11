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
// override a denial. At most MAX_PENDING requests wait at once.
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
}

impl ConfirmationGate {
    pub fn new(timeout_ticks: u64) -> Self {
        Self {
            requests: Vec::new(),
            next_id: 1,
            timeout_ticks,
        }
    }

    /// Test hook: start issuing ids from `next_id`.
    pub fn with_next_id(timeout_ticks: u64, next_id: u32) -> Self {
        Self { requests: Vec::new(), next_id, timeout_ticks }
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
        });

        ConfirmationStatus::Pending(id)
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
    Awaiting { id: u32, display: String },
    Denied,
    Expired,
    Refused,
}

/// The single confirmation decision used by every execution path
/// (`tool_mapper::execute` and the orchestrator's internal tools).
pub fn clear_for_execution(
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
    let fingerprint = super::authority::approval_fingerprint(args);
    let display = super::authority::approval_display(args);
    match gate.check_or_request_with_display(tool_name, &fingerprint, &display, tier, current_tick) {
        ConfirmationStatus::Approved => Clearance::Proceed,
        ConfirmationStatus::Pending(id) => Clearance::Awaiting { id, display },
        ConfirmationStatus::Denied => Clearance::Denied,
        ConfirmationStatus::Expired => Clearance::Expired,
        ConfirmationStatus::Refused => Clearance::Refused,
    }
}
