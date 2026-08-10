//! Loader and inference for the simulator-trained physical transition artifact.
//!
//! The model predicts in the compact physical state representation. Its output
//! is always shadow evidence: a serialized flag cannot promote simulator data
//! into execution authority.

use crate::safety::{EffectKind, PhysicalPrediction, PredictionSource};

pub const PHYSICAL_STATE_SIZE: usize = 16;
pub const PHYSICAL_ACTION_COUNT: usize = 7;
pub const PHYSICAL_ACTION_FEATURE_SIZE: usize = 3;
const PHYSICAL_INPUT_SIZE: usize =
    PHYSICAL_STATE_SIZE + PHYSICAL_ACTION_COUNT + PHYSICAL_ACTION_FEATURE_SIZE;
const HEADER_SIZE: usize = 44;
const MAX_HIDDEN_SIZE: usize = 128;

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
}

#[derive(Debug, Clone, Copy)]
pub struct PhysicalTransitionModel<'a> {
    bytes: &'a [u8],
    hidden_size: usize,
    training_samples: u32,
    normalized_h3_error: f32,
    per_action_mean_h3_error: f32,
    w1_offset: usize,
    b1_offset: usize,
    w2_offset: usize,
    b2_offset: usize,
}

impl<'a> PhysicalTransitionModel<'a> {
    pub fn from_bytes(bytes: &'a [u8]) -> Result<Self, PhysicalModelError> {
        if bytes.len() < HEADER_SIZE {
            return Err(PhysicalModelError::Truncated);
        }
        if &bytes[..4] != b"PWM1" {
            return Err(PhysicalModelError::InvalidMagic);
        }
        if read_u32(bytes, 4)? != 1 {
            return Err(PhysicalModelError::UnsupportedVersion);
        }
        let state_size = read_u32(bytes, 8)? as usize;
        let action_count = read_u32(bytes, 12)? as usize;
        let action_feature_size = read_u32(bytes, 16)? as usize;
        let hidden_size = read_u32(bytes, 20)? as usize;
        let training_samples = read_u32(bytes, 24)?;
        let input_size = read_u32(bytes, 28)? as usize;
        let normalized_h3_error = read_f32(bytes, 32)?;
        let per_action_mean_h3_error = read_f32(bytes, 36)?;
        let _serialized_gating_flag = read_u32(bytes, 40)?;
        if state_size != PHYSICAL_STATE_SIZE
            || action_count != PHYSICAL_ACTION_COUNT
            || action_feature_size != PHYSICAL_ACTION_FEATURE_SIZE
            || input_size != PHYSICAL_INPUT_SIZE
        {
            return Err(PhysicalModelError::SchemaMismatch);
        }
        if hidden_size == 0 || hidden_size > MAX_HIDDEN_SIZE || training_samples == 0 {
            return Err(PhysicalModelError::InvalidDimensions);
        }
        if !normalized_h3_error.is_finite()
            || !per_action_mean_h3_error.is_finite()
            || normalized_h3_error < 0.0
            || per_action_mean_h3_error < 0.0
        {
            return Err(PhysicalModelError::InvalidMetric);
        }
        let w1_offset = HEADER_SIZE;
        let b1_offset = w1_offset + PHYSICAL_INPUT_SIZE * hidden_size * 4;
        let w2_offset = b1_offset + hidden_size * 4;
        let b2_offset = w2_offset + hidden_size * PHYSICAL_STATE_SIZE * 4;
        if bytes.len() != b2_offset + PHYSICAL_STATE_SIZE * 4 {
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
            hidden_size,
            training_samples,
            normalized_h3_error,
            per_action_mean_h3_error,
            w1_offset,
            b1_offset,
            w2_offset,
            b2_offset,
        })
    }

    pub const fn training_samples(&self) -> u32 {
        self.training_samples
    }

    pub const fn normalized_h3_error(&self) -> f32 {
        self.normalized_h3_error
    }

    pub fn predict_shadow(
        &self,
        state: PhysicalState,
        action: PhysicalAction,
    ) -> Result<PhysicalForecast, PhysicalModelError> {
        validate_state(state)?;
        if action
            .features
            .iter()
            .any(|value| !value.is_finite() || *value < -1.0 || *value > 1.0)
        {
            return Err(PhysicalModelError::InvalidAction);
        }
        let mut input = [0.0f32; PHYSICAL_INPUT_SIZE];
        input[..PHYSICAL_STATE_SIZE].copy_from_slice(&state.values);
        input[PHYSICAL_STATE_SIZE + action.kind as usize] = 1.0;
        input[PHYSICAL_STATE_SIZE + PHYSICAL_ACTION_COUNT..].copy_from_slice(&action.features);
        let mut hidden = [0.0f32; MAX_HIDDEN_SIZE];
        for (column, output) in hidden[..self.hidden_size].iter_mut().enumerate() {
            let mut value = self.float_at(self.b1_offset, column)?;
            for (row, input_value) in input.iter().enumerate() {
                value += *input_value
                    * self.float_at(self.w1_offset, row * self.hidden_size + column)?;
            }
            if !value.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
            *output = value.max(0.0);
        }
        let mut next = state.values;
        for (column, output) in next.iter_mut().enumerate() {
            let mut delta = self.float_at(self.b2_offset, column)?;
            for (row, hidden_value) in hidden[..self.hidden_size].iter().enumerate() {
                delta += *hidden_value
                    * self.float_at(self.w2_offset, row * PHYSICAL_STATE_SIZE + column)?;
            }
            if !delta.is_finite() {
                return Err(PhysicalModelError::InvalidWeights);
            }
            *output = (*output + delta).clamp(-1.25, 1.25);
        }
        Ok(PhysicalForecast {
            next_state: PhysicalState { values: next },
            evidence: PhysicalPrediction {
                effect: action.kind.effect(),
                risk_permille: physical_risk_permille(state, action, &next),
                uncertainty_permille: (self.normalized_h3_error * 1_000.0).clamp(0.0, 1_000.0)
                    as u16,
                source: PredictionSource::Simulator,
                model_version: 1,
                // Simulator bytes cannot promote themselves into authority.
                validated_for_gating: false,
            },
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

fn validate_state(state: PhysicalState) -> Result<(), PhysicalModelError> {
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
        assert_eq!(model.training_samples(), 10_500);
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
}
