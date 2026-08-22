//! Loader and inference for the simulator-trained physical transition artifact.
//!
//! The model predicts in the compact physical state representation. Its output
//! is always shadow evidence: a serialized flag cannot promote simulator data
//! into execution authority.

use crate::safety::{EffectKind, PhysicalPrediction, PredictionSource};

pub const PHYSICAL_STATE_SIZE: usize = 16;
pub const PHYSICAL_ACTION_COUNT: usize = 7;
pub const PHYSICAL_ACTION_FEATURE_SIZE: usize = 3;
const PHYSICAL_ACTION_INPUT_SIZE: usize = PHYSICAL_ACTION_COUNT + PHYSICAL_ACTION_FEATURE_SIZE;
const HEADER_SIZE: usize = 48;
const MAX_LATENT_SIZE: usize = 128;
const MAX_HIDDEN_SIZE: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PhysicalState {
    pub values: [f32; PHYSICAL_STATE_SIZE],
}

/// Named physical observation matching the version-1 training schema.
/// Keeping this mapping in the runtime prevents callers from silently
/// swapping positional features when constructing model input.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PhysicalObservation {
    pub position_x: f32,
    pub position_y: f32,
    pub clearance: f32,
    pub human_occupancy: f32,
    pub battery: f32,
    pub link_quality: f32,
    pub health: f32,
    pub emergency_stop: bool,
    pub progress: f32,
    pub vibration: f32,
    pub fault: bool,
    pub online: bool,
    pub payload: f32,
    pub velocity: f32,
    pub geofence_margin: f32,
    pub approval: bool,
}

impl From<PhysicalObservation> for PhysicalState {
    fn from(observation: PhysicalObservation) -> Self {
        Self {
            values: [
                observation.position_x,
                observation.position_y,
                observation.clearance,
                observation.human_occupancy,
                observation.battery,
                observation.link_quality,
                observation.health,
                u8::from(observation.emergency_stop) as f32,
                observation.progress,
                observation.vibration,
                u8::from(observation.fault) as f32,
                u8::from(observation.online) as f32,
                observation.payload,
                observation.velocity,
                observation.geofence_margin,
                u8::from(observation.approval) as f32,
            ],
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum PhysicalActionKind {
    Move = 0,
    Inspect = 1,
    Diagnose = 2,
    Approve = 3,
    Repair = 4,
    Verify = 5,
    Stop = 6,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PhysicalAction {
    pub kind: PhysicalActionKind,
    pub features: [f32; PHYSICAL_ACTION_FEATURE_SIZE],
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PhysicalForecast {
    pub next_state: PhysicalState,
    pub evidence: PhysicalPrediction,
    pub lookahead_steps: u8,
    pub normalized_h3_error: f32,
    pub per_action_mean_h3_error: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PhysicalModelError {
    Truncated,
    InvalidMagic,
    UnsupportedVersion,
    SchemaMismatch,
    InvalidDimensions,
    InvalidMetric,
    InvalidWeights,
    InvalidState,
    InvalidAction,
    InvalidHorizon,
}

#[derive(Debug, Clone, Copy)]
pub struct PhysicalTransitionModel<'a> {
    bytes: &'a [u8],
    latent_size: usize,
    hidden_size: usize,
    training_samples: u32,
    normalized_h3_error: f32,
    per_action_mean_h3_error: f32,
    encoder_w_offset: usize,
    encoder_b_offset: usize,
    predictor_w1_offset: usize,
    predictor_b1_offset: usize,
    predictor_w2_offset: usize,
    predictor_b2_offset: usize,
    state_w_offset: usize,
    state_b_offset: usize,
}

impl<'a> PhysicalTransitionModel<'a> {
    pub fn from_bytes(bytes: &'a [u8]) -> Result<Self, PhysicalModelError> {
        if bytes.len() < HEADER_SIZE {
            return Err(PhysicalModelError::Truncated);
        }
        if &bytes[..4] != b"PJE1" {
            return Err(PhysicalModelError::InvalidMagic);
        }
        if read_u32(bytes, 4)? != 1 {
            return Err(PhysicalModelError::UnsupportedVersion);
        }
        let state_size = read_u32(bytes, 8)? as usize;
        let action_count = read_u32(bytes, 12)? as usize;
        let action_feature_size = read_u32(bytes, 16)? as usize;
        let latent_size = read_u32(bytes, 20)? as usize;
        let hidden_size = read_u32(bytes, 24)? as usize;
        let training_samples = read_u32(bytes, 28)?;
        let action_input_size = read_u32(bytes, 32)? as usize;
        let normalized_h3_error = read_f32(bytes, 36)?;
        let per_action_mean_h3_error = read_f32(bytes, 40)?;
        let _serialized_gating_flag = read_u32(bytes, 44)?;
        if state_size != PHYSICAL_STATE_SIZE
            || action_count != PHYSICAL_ACTION_COUNT
            || action_feature_size != PHYSICAL_ACTION_FEATURE_SIZE
            || action_input_size != PHYSICAL_ACTION_INPUT_SIZE
        {
            return Err(PhysicalModelError::SchemaMismatch);
        }
        if latent_size == 0
            || latent_size > MAX_LATENT_SIZE
            || hidden_size == 0
            || hidden_size > MAX_HIDDEN_SIZE
            || training_samples == 0
        {
            return Err(PhysicalModelError::InvalidDimensions);
        }
        if !normalized_h3_error.is_finite()
            || !per_action_mean_h3_error.is_finite()
            || normalized_h3_error < 0.0
            || per_action_mean_h3_error < 0.0
        {
            return Err(PhysicalModelError::InvalidMetric);
        }
        let encoder_w_offset = HEADER_SIZE;
        let encoder_b_offset = encoder_w_offset + PHYSICAL_STATE_SIZE * latent_size * 4;
        let predictor_w1_offset = encoder_b_offset + latent_size * 4;
        let predictor_b1_offset =
            predictor_w1_offset + (latent_size + PHYSICAL_ACTION_INPUT_SIZE) * hidden_size * 4;
        let predictor_w2_offset = predictor_b1_offset + hidden_size * 4;
        let predictor_b2_offset = predictor_w2_offset + hidden_size * latent_size * 4;
        let state_w_offset = predictor_b2_offset + latent_size * 4;
        let state_b_offset = state_w_offset + latent_size * PHYSICAL_STATE_SIZE * 4;
        if bytes.len() != state_b_offset + PHYSICAL_STATE_SIZE * 4 {
            return Err(PhysicalModelError::Truncated);
        }
        for chunk in bytes[HEADER_SIZE..].chunks_exact(4) {
            let value = f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
            if !value.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
        }
        Ok(Self {
            bytes,
            latent_size,
            hidden_size,
            training_samples,
            normalized_h3_error,
            per_action_mean_h3_error,
            encoder_w_offset,
            encoder_b_offset,
            predictor_w1_offset,
            predictor_b1_offset,
            predictor_w2_offset,
            predictor_b2_offset,
            state_w_offset,
            state_b_offset,
        })
    }

    pub const fn training_samples(&self) -> u32 {
        self.training_samples
    }

    pub const fn normalized_h3_error(&self) -> f32 {
        self.normalized_h3_error
    }

    pub const fn per_action_mean_h3_error(&self) -> f32 {
        self.per_action_mean_h3_error
    }

    pub fn predict_shadow(
        &self,
        state: PhysicalState,
        action: PhysicalAction,
    ) -> Result<PhysicalForecast, PhysicalModelError> {
        self.predict_shadow_horizon(state, action, 1)
    }

    /// Recurrently applies the learned transition for a bounded lookahead.
    /// The highest risk across the rollout is returned as advisory evidence;
    /// deterministic policy remains authoritative at every real action.
    pub fn predict_shadow_horizon(
        &self,
        state: PhysicalState,
        action: PhysicalAction,
        steps: u8,
    ) -> Result<PhysicalForecast, PhysicalModelError> {
        if !(1..=5).contains(&steps) {
            return Err(PhysicalModelError::InvalidHorizon);
        }
        validate_observation(state)?;
        let mut current = state;
        let mut worst: Option<PhysicalPrediction> = None;
        for _ in 0..steps {
            let forecast = self.predict_one_shadow(current, action)?;
            current = forecast.next_state;
            if worst
                .as_ref()
                .is_none_or(|evidence| forecast.evidence.risk_permille > evidence.risk_permille)
            {
                worst = Some(forecast.evidence);
            }
        }
        let mut evidence = worst.ok_or(PhysicalModelError::InvalidHorizon)?;
        evidence.uncertainty_permille = (self.normalized_h3_error
            * 1_000.0
            * libm::sqrtf(f32::from(steps)))
        .clamp(0.0, 1_000.0) as u16;
        Ok(PhysicalForecast {
            next_state: current,
            evidence,
            lookahead_steps: steps,
            normalized_h3_error: self.normalized_h3_error,
            per_action_mean_h3_error: self.per_action_mean_h3_error,
        })
    }

    fn predict_one_shadow(
        &self,
        state: PhysicalState,
        action: PhysicalAction,
    ) -> Result<PhysicalForecast, PhysicalModelError> {
        validate_state_bounds(state)?;
        if action
            .features
            .iter()
            .any(|value| !value.is_finite() || *value < -1.0 || *value > 1.0)
        {
            return Err(PhysicalModelError::InvalidAction);
        }
        let mut latent = [0.0f32; MAX_LATENT_SIZE];
        for (column, output) in latent[..self.latent_size].iter_mut().enumerate() {
            let mut value = self.float_at(self.encoder_b_offset, column)?;
            for (row, state_value) in state.values.iter().enumerate() {
                value += *state_value
                    * self.float_at(self.encoder_w_offset, row * self.latent_size + column)?;
            }
            if !value.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
            *output = libm::tanhf(value);
        }
        let mut predictor_input = [0.0f32; MAX_LATENT_SIZE + PHYSICAL_ACTION_INPUT_SIZE];
        predictor_input[..self.latent_size].copy_from_slice(&latent[..self.latent_size]);
        predictor_input[self.latent_size + action.kind as usize] = 1.0;
        predictor_input[self.latent_size + PHYSICAL_ACTION_COUNT
            ..self.latent_size + PHYSICAL_ACTION_INPUT_SIZE]
            .copy_from_slice(&action.features);
        let mut hidden = [0.0f32; MAX_HIDDEN_SIZE];
        for (column, output) in hidden[..self.hidden_size].iter_mut().enumerate() {
            let mut value = self.float_at(self.predictor_b1_offset, column)?;
            for (row, input_value) in predictor_input
                [..self.latent_size + PHYSICAL_ACTION_INPUT_SIZE]
                .iter()
                .enumerate()
            {
                value += *input_value
                    * self.float_at(self.predictor_w1_offset, row * self.hidden_size + column)?;
            }
            if !value.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
            *output = value.max(0.0);
        }
        let mut predicted_latent = [0.0f32; MAX_LATENT_SIZE];
        for (column, output) in predicted_latent[..self.latent_size].iter_mut().enumerate() {
            let mut value = self.float_at(self.predictor_b2_offset, column)?;
            for (row, hidden_value) in hidden[..self.hidden_size].iter().enumerate() {
                value += *hidden_value
                    * self.float_at(self.predictor_w2_offset, row * self.latent_size + column)?;
            }
            if !value.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
            *output = value;
        }
        let mut next = state.values;
        for (column, output) in next.iter_mut().enumerate() {
            let mut delta = self.float_at(self.state_b_offset, column)?;
            for (row, latent_value) in predicted_latent[..self.latent_size].iter().enumerate() {
                delta += *latent_value
                    * self.float_at(self.state_w_offset, row * PHYSICAL_STATE_SIZE + column)?;
            }
            if !delta.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
            *output = if column < 2 {
                (*output + delta).clamp(-1.25, 1.25)
            } else {
                (*output + delta).clamp(0.0, 1.0)
            };
        }
        Ok(PhysicalForecast {
            next_state: PhysicalState { values: next },
            evidence: PhysicalPrediction {
                effect: action.kind.effect(),
                risk_permille: physical_risk_permille(state, action, &next),
                uncertainty_permille: (self.normalized_h3_error * 1_000.0).clamp(0.0, 1_000.0)
                    as u16,
                source: PredictionSource::PhysicalJepa,
                model_version: 1,
                // Simulator bytes cannot promote themselves into authority.
                validated_for_gating: false,
            },
            lookahead_steps: 1,
            normalized_h3_error: self.normalized_h3_error,
            per_action_mean_h3_error: self.per_action_mean_h3_error,
        })
    }

    fn float_at(&self, base: usize, index: usize) -> Result<f32, PhysicalModelError> {
        read_f32(self.bytes, base + index * 4)
    }
}

impl PhysicalActionKind {
    const fn effect(self) -> EffectKind {
        match self {
            Self::Move => EffectKind::Move,
            Self::Inspect | Self::Diagnose | Self::Verify => EffectKind::Observe,
            Self::Approve => EffectKind::Acknowledge,
            Self::Repair => EffectKind::Actuate,
            Self::Stop => EffectKind::Stop,
        }
    }
}

fn validate_state_bounds(state: PhysicalState) -> Result<(), PhysicalModelError> {
    if state.values.iter().any(|value| !value.is_finite())
        || state.values[0] < -1.25
        || state.values[0] > 1.25
        || state.values[1] < -1.25
        || state.values[1] > 1.25
        || state.values[2..]
            .iter()
            .any(|value| *value < 0.0 || *value > 1.0)
    {
        return Err(PhysicalModelError::InvalidState);
    }
    Ok(())
}

fn validate_observation(state: PhysicalState) -> Result<(), PhysicalModelError> {
    validate_state_bounds(state)?;
    let expected_margin = (1.0 - state.values[0].abs().max(state.values[1].abs()))
        .clamp(-0.25, 1.0);
    if (state.values[14] - expected_margin).abs() > 0.02
        || [7usize, 10, 11, 15].iter().any(|index| {
            let value = state.values[*index];
            value.abs().min((value - 1.0).abs()) > 1e-6
        })
        || (state.values[7] > 0.5 && state.values[13] > 0.01)
    {
        return Err(PhysicalModelError::InvalidState);
    }
    Ok(())
}

fn physical_risk_permille(
    state: PhysicalState,
    action: PhysicalAction,
    next: &[f32; PHYSICAL_STATE_SIZE],
) -> u16 {
    let moving = action.kind == PhysicalActionKind::Move && action.features[2] > 0.1;
    let mut risk = 0u16;
    if moving && next[2] < 0.18 {
        risk = risk.max(900);
    }
    if moving && state.values[3] > 0.0 && next[13] > 0.16 {
        risk = risk.max(950);
    }
    if next[14] < 0.01 {
        risk = risk.max(1_000);
    }
    if moving && (next[4] < 0.08 || next[5] < 0.08 || state.values[11] < 0.5) {
        risk = risk.max(850);
    }
    if action.kind != PhysicalActionKind::Stop && state.values[7] > 0.5 {
        risk = risk.max(1_000);
    }
    if action.kind == PhysicalActionKind::Repair && state.values[15] < 0.5 {
        risk = risk.max(900);
    }
    risk
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, PhysicalModelError> {
    let value = bytes
        .get(offset..offset + 4)
        .ok_or(PhysicalModelError::Truncated)?;
    Ok(u32::from_le_bytes([value[0], value[1], value[2], value[3]]))
}

fn read_f32(bytes: &[u8], offset: usize) -> Result<f32, PhysicalModelError> {
    Ok(f32::from_bits(read_u32(bytes, offset)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    const ARTIFACT: &[u8] = include_bytes!("../../heliox-daemon/physical_world_model.bin");

    fn safe_state() -> PhysicalState {
        PhysicalState {
            values: [
                0.0, 0.0, 0.9, 0.0, 0.9, 0.9, 0.5, 0.0, 0.2, 0.5, 0.0, 1.0, 0.1, 0.0, 1.0, 1.0,
            ],
        }
    }

    #[test]
    fn committed_artifact_loads_and_beats_recorded_mean_baseline() {
        let model = PhysicalTransitionModel::from_bytes(ARTIFACT).unwrap();
        assert_eq!(model.training_samples(), 123_200);
        let forecast = model
            .predict_shadow(
                safe_state(),
                PhysicalAction {
                    kind: PhysicalActionKind::Move,
                    features: [0.1, 0.1, 0.3],
                },
            )
            .unwrap();
        assert!(forecast.normalized_h3_error < forecast.per_action_mean_h3_error);
        assert!(!forecast.evidence.validated_for_gating);
    }

    #[test]
    fn dangerous_forecast_is_visible_but_never_self_promotes() {
        let model = PhysicalTransitionModel::from_bytes(ARTIFACT).unwrap();
        let mut state = safe_state();
        state.values[2] = 0.12;
        state.values[3] = 0.5;
        let forecast = model
            .predict_shadow(
                state,
                PhysicalAction {
                    kind: PhysicalActionKind::Move,
                    features: [0.8, 0.8, 0.9],
                },
            )
            .unwrap();
        assert!(forecast.evidence.risk_permille >= 900);
        assert!(!forecast.evidence.validated_for_gating);
    }

    #[test]
    fn incident_checkpoint_separates_bounded_safe_and_clearance_risk_rollouts() {
        let model = PhysicalTransitionModel::from_bytes(ARTIFACT).unwrap();
        let action = PhysicalAction {
            kind: PhysicalActionKind::Move,
            features: [0.1, 0.1, 0.15],
        };
        let safe = model
            .predict_shadow_horizon(safe_state(), action, 3)
            .unwrap();
        let mut unsafe_state = safe_state();
        unsafe_state.values[2] = 0.1;
        unsafe_state.values[3] = 0.25;
        let unsafe_forecast = model
            .predict_shadow_horizon(unsafe_state, action, 3)
            .unwrap();

        assert!(safe.evidence.risk_permille < 900);
        assert!(unsafe_forecast.evidence.risk_permille >= 900);
        assert!(!safe.evidence.validated_for_gating);
        assert!(!unsafe_forecast.evidence.validated_for_gating);
    }

    #[test]
    fn h3_rollout_is_bounded_and_remains_shadow_only() {
        let model = PhysicalTransitionModel::from_bytes(ARTIFACT).unwrap();
        let action = PhysicalAction {
            kind: PhysicalActionKind::Move,
            features: [0.1, 0.1, 0.3],
        };
        let forecast = model
            .predict_shadow_horizon(safe_state(), action, 3)
            .unwrap();
        assert_eq!(forecast.lookahead_steps, 3);
        assert!(!forecast.evidence.validated_for_gating);
        assert_eq!(
            model.predict_shadow_horizon(safe_state(), action, 0),
            Err(PhysicalModelError::InvalidHorizon)
        );
        assert_eq!(
            model.predict_shadow_horizon(safe_state(), action, 6),
            Err(PhysicalModelError::InvalidHorizon)
        );
    }

    #[test]
    fn serialized_gating_flag_cannot_promote_the_model() {
        let mut promoted = ARTIFACT.to_vec();
        promoted[44..48].copy_from_slice(&1u32.to_le_bytes());
        let model = PhysicalTransitionModel::from_bytes(&promoted).unwrap();
        let forecast = model
            .predict_shadow(
                safe_state(),
                PhysicalAction {
                    kind: PhysicalActionKind::Inspect,
                    features: [0.0; 3],
                },
            )
            .unwrap();
        assert!(!forecast.evidence.validated_for_gating);
    }

    #[test]
    fn malformed_artifacts_and_nonfinite_state_fail_closed() {
        assert!(matches!(
            PhysicalTransitionModel::from_bytes(&ARTIFACT[..20]),
            Err(PhysicalModelError::Truncated)
        ));
        let model = PhysicalTransitionModel::from_bytes(ARTIFACT).unwrap();
        let mut invalid = safe_state();
        invalid.values[0] = f32::NAN;
        assert_eq!(
            model.predict_shadow(
                invalid,
                PhysicalAction {
                    kind: PhysicalActionKind::Stop,
                    features: [0.0; 3],
                },
            ),
            Err(PhysicalModelError::InvalidState)
        );

        let mut corrupt = ARTIFACT.to_vec();
        corrupt[HEADER_SIZE..HEADER_SIZE + 4].copy_from_slice(&f32::NAN.to_le_bytes());
        assert!(matches!(
            PhysicalTransitionModel::from_bytes(&corrupt),
            Err(PhysicalModelError::InvalidWeights)
        ));
    }

    #[test]
    fn inconsistent_observations_fail_closed_before_learned_inference() {
        let model = PhysicalTransitionModel::from_bytes(ARTIFACT).unwrap();
        let action = PhysicalAction {
            kind: PhysicalActionKind::Stop,
            features: [0.0; PHYSICAL_ACTION_FEATURE_SIZE],
        };

        let mut stale_margin = safe_state();
        stale_margin.values[0] = 1.2;
        assert_eq!(
            model.predict_shadow_horizon(stale_margin, action, 3),
            Err(PhysicalModelError::InvalidState)
        );

        let mut moving_under_estop = safe_state();
        moving_under_estop.values[7] = 1.0;
        moving_under_estop.values[13] = 0.4;
        assert_eq!(
            model.predict_shadow_horizon(moving_under_estop, action, 3),
            Err(PhysicalModelError::InvalidState)
        );
    }
}
