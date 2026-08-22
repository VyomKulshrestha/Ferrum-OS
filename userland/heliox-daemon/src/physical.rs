//! Heliox-facing physical operations service.
//!
//! The existing 41-action OS JEPA checkpoint is intentionally not reused for
//! physical state. This service exposes the independent typed runtime and its
//! simulator evaluation. The selected checkpoint may add caution only inside
//! a digest-bound simulation session; live and HIL paths remain shadow-only.

use alloc::format;
use alloc::string::String;

use ferrum_physical_runtime::{
    run_maintenance_demo_with_predictions, run_simulation_caution_demo, MaintenanceDemoReport,
    PhysicalAction, PhysicalActionKind, PhysicalObservation, PhysicalTransitionModel,
};

static PHYSICAL_MODEL_BYTES: &[u8] = include_bytes!("../physical_world_model.bin");

pub const PHYSICAL_SCHEMA_VERSION: u32 = 4;
const PHYSICAL_MODEL_SHA256: [u8; 32] = [
    0xf2, 0x67, 0xdc, 0x09, 0x2f, 0x9f, 0xb2, 0xab, 0x75, 0x2b, 0x6d, 0x5e, 0xf6, 0xc5, 0xdc, 0x60,
    0xcb, 0x79, 0x9e, 0x15, 0xca, 0x67, 0x9d, 0xa5, 0x2b, 0xc5, 0xe7, 0x07, 0xcc, 0x66, 0xee, 0x60,
];

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
        let (training_samples, normalized_h3_error_ppm, mean_h3_error_ppm) = self
            .model
            .map(|model| {
                (
                    model.training_samples(),
                    (model.normalized_h3_error() * 1_000_000.0) as u32,
                    (model.per_action_mean_h3_error() * 1_000_000.0) as u32,
                )
            })
            .unwrap_or((0, 0, 0));
        format!(
            "{{\"schema_version\":{},\"available\":true,\"mode\":\"simulator\",\"learned_gate\":\"simulation_caution\",\"live_learned_gate\":\"shadow_only\",\"learned_authority\":\"increase_severity_only\",\"permit_authority\":\"deterministic_supervisor\",\"physical_model\":\"ema_target_jepa\",\"artifact_format\":\"PJE1\",\"model_revision\":\"physical-jepa-stress-v3\",\"model_sha256\":\"f267dc092f9fb2ab752b6d5ef6c5dc60cb799e15ca679da52bc5e707cc66ee60\",\"lookahead_horizon\":3,\"physical_model_loaded\":{},\"training_samples\":{},\"normalized_h3_error_ppm\":{},\"per_action_mean_h3_error_ppm\":{},\"held_out_rows\":14400,\"held_out_false_negatives\":8,\"held_out_false_positives\":133,\"incident_rows\":7680,\"incident_false_negatives\":1,\"incident_false_positives\":56,\"stress_rows\":16000,\"stress_false_negatives\":1,\"stress_false_positives\":101,\"ood_rows\":4096,\"ood_invalid_observations_rejected\":682,\"ood_false_negatives\":0,\"ood_false_positives\":18,\"os_jepa_reused\":false,\"completed_simulations\":{},\"last_job_completed\":{}}}",
            PHYSICAL_SCHEMA_VERSION,
            self.model.is_some(),
            training_samples,
            normalized_h3_error_ppm,
            mean_h3_error_ppm,
            self.completed_simulations,
            last_completed
        )
    }

    pub fn run_maintenance_simulation_json(&mut self) -> Result<String, &'static str> {
        let model = self.model.ok_or("physical model artifact rejected")?;
        let action = PhysicalAction {
            kind: PhysicalActionKind::Move,
            // The reference vertical uses a deliberately bounded low-speed
            // move. The unsafe probe still crosses the clearance threshold,
            // while the safe probe remains below the advisory risk threshold.
            features: [0.1, 0.1, 0.15],
        };
        let unsafe_forecast = model
            .predict_shadow_horizon(maintenance_observation(0.1, 0.25).into(), action, 3)
            .map_err(|_| "physical model inference failed")?;
        let safe_forecast = model
            .predict_shadow_horizon(maintenance_observation(0.9, 0.0).into(), action, 3)
            .map_err(|_| "physical model inference failed")?;
        let caution_report = run_simulation_caution_demo(
            unsafe_forecast.evidence,
            safe_forecast.evidence,
            PHYSICAL_MODEL_SHA256,
        )
        .map_err(|_| "physical simulation-caution evaluation failed")?;
        let report =
            run_maintenance_demo_with_predictions(unsafe_forecast.evidence, safe_forecast.evidence)
                .map_err(|_| "physical maintenance simulation failed")?;
        self.completed_simulations = self.completed_simulations.saturating_add(1);
        let response = format!(
            "{{\"simulation_only\":true,\"model\":\"ema_target_jepa\",\"lookahead_horizon\":3,\"job_completed\":{},\"tasks\":{},\"approval_enforced\":{},\"unsafe_motion_blocked\":{},\"safe_motion_delivered\":{},\"policy_revision\":{},\"unsafe_shadow_risk_permille\":{},\"safe_shadow_risk_permille\":{},\"task_successes\":{},\"safety_interventions\":{},\"twin_events\":{},\"gate_evaluation\":{{\"rules_only_allowed\":{},\"shadow_only_allowed\":{},\"rules_plus_jepa_blocked\":{},\"rejected_command_received_permit\":{},\"bounded_safe_command_delivered\":{},\"risky_prediction_permille\":{},\"safe_prediction_permille\":{},\"evidence_records\":{},\"evidence_checksum\":{}}},\"live_learned_gate\":\"shadow_only\",\"permit_authority\":\"deterministic_supervisor\"}}",
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
            caution_report.rules_only_allowed,
            caution_report.shadow_only_allowed,
            caution_report.rules_plus_jepa_blocked,
            caution_report.rejected_command_received_permit,
            caution_report.bounded_safe_command_delivered,
            caution_report.risky_prediction_permille,
            caution_report.safe_prediction_permille,
            caution_report.evidence_records,
            caution_report.evidence_checksum,
        );
        self.last_report = Some(report);
        Ok(response)
    }

    /// Read-only JEPA shadow forecast for a neural work-order proposal. This
    /// method cannot mint a permit, invoke an adapter, or mutate simulation
    /// state; the deterministic physical supervisor remains authoritative.
    pub fn preview_neural_work_order_json(&self) -> Result<String, &'static str> {
        let model = self.model.ok_or("physical model artifact rejected")?;
        let action = PhysicalAction {
            kind: PhysicalActionKind::Move,
            features: [0.1, 0.1, 0.3],
        };
        let forecast = model
            .predict_shadow_horizon(maintenance_observation(0.5, 0.15).into(), action, 3)
            .map_err(|_| "physical model inference failed")?;
        Ok(format!(
            "{{\"proposal_only\":true,\"permit_issued\":false,\"adapter_invoked\":false,\"model\":\"ema_target_jepa\",\"lookahead_horizon\":3,\"shadow_risk_permille\":{},\"deterministic_supervisor\":\"required\",\"separate_non_neural_confirmation\":true}}",
            forecast.evidence.risk_permille,
        ))
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
