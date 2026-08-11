//! Heliox-facing physical operations service.
//!
//! The existing 41-action OS JEPA checkpoint is intentionally not reused for
//! physical state. This service exposes the independent typed runtime and its
//! simulator evaluation while physical learned evidence remains shadow-only.

use alloc::format;
use alloc::string::String;

use ferrum_physical_runtime::{
    run_maintenance_demo_with_predictions, MaintenanceDemoReport, PhysicalAction,
    PhysicalActionKind, PhysicalObservation, PhysicalTransitionModel,
};

static PHYSICAL_MODEL_BYTES: &[u8] = include_bytes!("../physical_world_model.bin");

pub const PHYSICAL_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Default)]
pub struct PhysicalService {
    completed_simulations: u64,
    last_report: Option<MaintenanceDemoReport>,
    model: Option<PhysicalTransitionModel<'static>>,
}

impl PhysicalService {
    pub fn new() -> Self {
        Self {
            completed_simulations: 0,
            last_report: None,
            model: PhysicalTransitionModel::from_bytes(PHYSICAL_MODEL_BYTES).ok(),
        }
    }

    pub fn status_json(&self) -> String {
        let last_completed = self
            .last_report
            .as_ref()
            .is_some_and(|report| report.job_completed);
        format!(
            "{{\"schema_version\":{},\"available\":true,\"mode\":\"simulator\",\"learned_gate\":\"shadow_only\",\"physical_model\":\"ema_target_jepa\",\"artifact_format\":\"PJE1\",\"lookahead_horizon\":3,\"physical_model_loaded\":{},\"os_jepa_reused\":false,\"completed_simulations\":{},\"last_job_completed\":{}}}",
            PHYSICAL_SCHEMA_VERSION,
            self.model.is_some(),
            self.completed_simulations,
            last_completed
        )
    }

    pub fn run_maintenance_simulation_json(&mut self) -> Result<String, &'static str> {
        let model = self.model.ok_or("physical model artifact rejected")?;
        let action = PhysicalAction {
            kind: PhysicalActionKind::Move,
            features: [0.1, 0.1, 0.3],
        };
        let unsafe_forecast = model
            .predict_shadow_horizon(maintenance_observation(0.1, 0.25).into(), action, 3)
            .map_err(|_| "physical model inference failed")?;
        let safe_forecast = model
            .predict_shadow_horizon(maintenance_observation(0.9, 0.0).into(), action, 3)
            .map_err(|_| "physical model inference failed")?;
        let report =
            run_maintenance_demo_with_predictions(unsafe_forecast.evidence, safe_forecast.evidence)
                .map_err(|_| "physical maintenance simulation failed")?;
        self.completed_simulations = self.completed_simulations.saturating_add(1);
        let response = format!(
            "{{\"simulation_only\":true,\"model\":\"ema_target_jepa\",\"lookahead_horizon\":3,\"job_completed\":{},\"tasks\":{},\"approval_enforced\":{},\"unsafe_motion_blocked\":{},\"safe_motion_delivered\":{},\"policy_revision\":{},\"unsafe_shadow_risk_permille\":{},\"safe_shadow_risk_permille\":{},\"task_successes\":{},\"safety_interventions\":{},\"twin_events\":{}}}",
            report.job_completed,
            report.assigned_actors.len(),
            report.approval_was_enforced,
            report.unsafe_motion_blocked,
            report.safe_motion_delivered,
            report.delivered_policy_revision,
            report.unsafe_shadow_risk_permille,
            report.safe_shadow_risk_permille,
            report.reliability.task_successes,
            report.reliability.safety_interventions,
            report.retained_twin_events,
        );
        self.last_report = Some(report);
        Ok(response)
    }
}

fn maintenance_observation(clearance: f32, human_occupancy: f32) -> PhysicalObservation {
    PhysicalObservation {
        position_x: 0.0,
        position_y: 0.0,
        clearance,
        human_occupancy,
        battery: 0.9,
        link_quality: 0.9,
        health: 0.5,
        emergency_stop: false,
        progress: 0.2,
        vibration: 0.5,
        fault: false,
        online: true,
        payload: 0.1,
        velocity: 0.0,
        geofence_margin: 1.0,
        approval: true,
    }
}
