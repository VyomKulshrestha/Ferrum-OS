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
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;
use super::tool_mapper::PermissionTier;

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
}

/// A single pending confirmation request.
#[derive(Debug, Clone)]
pub struct PendingConfirmation {
    pub id: u32,
    pub tool_name: String,
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

    /// Check if a tool already has a pending/approved confirmation.
    /// If not, create a new pending request.
    ///
    /// Returns:
    /// - `Approved` if there is an approved request for this tool+args
    /// - `Pending(id)` if there is a pending request (or a new one was just created)
    /// - `Denied` if the operator denied it
    /// - `Expired` if it timed out
    pub fn check_or_request(
        &mut self,
        tool_name: &str,
        args_summary: &str,
        tier: PermissionTier,
        current_tick: u64,
    ) -> ConfirmationStatus {
        // Look for an existing request for this tool
        if let Some(req) = self.requests.iter_mut().find(|r| {
            r.tool_name == tool_name && r.args_summary == args_summary
        }) {
            // Check expiration
            if current_tick - req.created_at_tick > self.timeout_ticks {
                let id = req.id;
                self.requests.retain(|r| r.id != id);
                return ConfirmationStatus::Expired;
            }

            return match req.status {
                InternalStatus::Pending => ConfirmationStatus::Pending(req.id),
                InternalStatus::Approved => {
                    // Consume the approval (one-time use)
                    let id = req.id;
                    self.requests.retain(|r| r.id != id);
                    ConfirmationStatus::Approved
                }
                InternalStatus::Denied => {
                    let id = req.id;
                    self.requests.retain(|r| r.id != id);
                    ConfirmationStatus::Denied
                }
            };
        }

        // No existing request — create a new one
        let id = self.next_id;
        self.next_id += 1;

        self.requests.push(PendingConfirmation {
            id,
            tool_name: String::from(tool_name),
            args_summary: String::from(args_summary),
            tier,
            created_at_tick: current_tick,
            status: InternalStatus::Pending,
        });

        ConfirmationStatus::Pending(id)
    }

    /// Approve a confirmation by ID (called from kernel shell via IPC).
    pub fn approve(&mut self, id: u32) -> bool {
        if let Some(req) = self.requests.iter_mut().find(|r| r.id == id) {
            req.status = InternalStatus::Approved;
            true
        } else {
            false
        }
    }

    /// Deny a confirmation by ID (called from kernel shell via IPC).
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
        self.requests.retain(|r| {
            current_tick - r.created_at_tick <= self.timeout_ticks
        });
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
