//! Heliox-facing physical operations service.
//!
//! The existing 41-action OS JEPA checkpoint is intentionally not reused for
//! physical state. This service exposes the independent typed runtime and its
//! simulator evaluation while physical learned evidence remains shadow-only.

use alloc::format;
use alloc::string::String;

use ferrum_physical_runtime::{run_maintenance_demo, MaintenanceDemoReport};

pub const PHYSICAL_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Default)]
pub struct PhysicalService {
    completed_simulations: u64,
    last_report: Option<MaintenanceDemoReport>,
}

impl PhysicalService {
    pub const fn new() -> Self {
        Self {
            completed_simulations: 0,
            last_report: None,
        }
    }

    pub fn status_json(&self) -> String {
        let last_completed = self
            .last_report
            .as_ref()
            .is_some_and(|report| report.job_completed);
        format!(
            "{{\"schema_version\":{},\"available\":true,\"mode\":\"simulator\",\"learned_gate\":\"shadow_only\",\"os_jepa_reused\":false,\"completed_simulations\":{},\"last_job_completed\":{}}}",
            PHYSICAL_SCHEMA_VERSION,
            self.completed_simulations,
            last_completed
        )
    }

    pub fn run_maintenance_simulation_json(&mut self) -> Result<String, &'static str> {
        let report =
            run_maintenance_demo().map_err(|_| "physical maintenance simulation failed")?;
        self.completed_simulations = self.completed_simulations.saturating_add(1);
        let response = format!(
            "{{\"simulation_only\":true,\"job_completed\":{},\"tasks\":{},\"approval_enforced\":{},\"unsafe_motion_blocked\":{},\"safe_motion_delivered\":{},\"policy_revision\":{},\"shadow_risk_permille\":{},\"task_successes\":{},\"safety_interventions\":{},\"twin_events\":{}}}",
            report.job_completed,
            report.assigned_actors.len(),
            report.approval_was_enforced,
            report.unsafe_motion_blocked,
            report.safe_motion_delivered,
            report.delivered_policy_revision,
            report.shadow_prediction_risk_permille,
            report.reliability.task_successes,
            report.reliability.safety_interventions,
            report.retained_twin_events,
        );
        self.last_report = Some(report);
        Ok(response)
    }
}
