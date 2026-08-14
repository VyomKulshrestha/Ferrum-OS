//! Bounded transition experience for the physical world model.
//!
//! Only observed post-action states are eligible for future fitting. Refused,
//! uncertain, or simulator-predicted outcomes remain auditable but cannot be
//! mistaken for ground-truth transitions.

use alloc::collections::VecDeque;

use crate::model::{PhysicalAction, PhysicalState};

pub const PHYSICAL_EXPERIENCE_CAPACITY: usize = 1_024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PhysicalOutcome {
    ExecutedObserved,
    Refused,
    DeliveryUncertain,
    SimulatorOnly,
}

impl PhysicalOutcome {
    pub const fn eligible_for_transition_fit(self) -> bool {
        matches!(self, Self::ExecutedObserved)
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PhysicalExperience {
    pub sequence: u64,
    pub observed_at_tick: u64,
    pub before: PhysicalState,
    pub action: PhysicalAction,
    pub after: Option<PhysicalState>,
    pub outcome: PhysicalOutcome,
    pub reward: f32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExperienceError {
    InvalidReward,
    MissingObservedState,
    UnexpectedObservedState,
    NonMonotonicTick,
    SequenceExhausted,
}

#[derive(Debug, Default)]
pub struct PhysicalExperienceBuffer {
    entries: VecDeque<PhysicalExperience>,
    next_sequence: u64,
    last_tick: Option<u64>,
}

impl PhysicalExperienceBuffer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = &PhysicalExperience> {
        self.entries.iter()
    }

    pub fn record(
        &mut self,
        observed_at_tick: u64,
        before: PhysicalState,
        action: PhysicalAction,
        after: Option<PhysicalState>,
        outcome: PhysicalOutcome,
        reward: f32,
    ) -> Result<u64, ExperienceError> {
        if !reward.is_finite() || !(-1.0..=1.0).contains(&reward) {
            return Err(ExperienceError::InvalidReward);
        }
        if outcome.eligible_for_transition_fit() && after.is_none() {
            return Err(ExperienceError::MissingObservedState);
        }
        if !outcome.eligible_for_transition_fit() && after.is_some() {
            return Err(ExperienceError::UnexpectedObservedState);
        }
        if self.last_tick.is_some_and(|tick| observed_at_tick < tick) {
            return Err(ExperienceError::NonMonotonicTick);
        }
        let next_sequence = self
            .next_sequence
            .checked_add(1)
            .ok_or(ExperienceError::SequenceExhausted)?;
        if self.entries.len() == PHYSICAL_EXPERIENCE_CAPACITY {
            self.entries.pop_front();
        }
        self.entries.push_back(PhysicalExperience {
            sequence: next_sequence,
            observed_at_tick,
            before,
            action,
            after,
            outcome,
            reward,
        });
        self.next_sequence = next_sequence;
        self.last_tick = Some(observed_at_tick);
        Ok(next_sequence)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{PhysicalActionKind, PHYSICAL_STATE_SIZE};

    fn state(value: f32) -> PhysicalState {
        PhysicalState {
            values: [value; PHYSICAL_STATE_SIZE],
        }
    }

    fn action() -> PhysicalAction {
        PhysicalAction {
            kind: PhysicalActionKind::Inspect,
            features: [0.0; 3],
        }
    }

    #[test]
    fn only_observed_execution_is_fit_eligible() {
        let mut buffer = PhysicalExperienceBuffer::new();
        buffer
            .record(
                1,
                state(0.1),
                action(),
                None,
                PhysicalOutcome::Refused,
                -1.0,
            )
            .unwrap();
        buffer
            .record(
                2,
                state(0.1),
                action(),
                Some(state(0.2)),
                PhysicalOutcome::ExecutedObserved,
                1.0,
            )
            .unwrap();
        assert!(!buffer
            .iter()
            .next()
            .unwrap()
            .outcome
            .eligible_for_transition_fit());
        assert!(buffer
            .iter()
            .nth(1)
            .unwrap()
            .outcome
            .eligible_for_transition_fit());
        assert_eq!(
            buffer.record(
                3,
                state(0.1),
                action(),
                Some(state(0.2)),
                PhysicalOutcome::SimulatorOnly,
                0.0
            ),
            Err(ExperienceError::UnexpectedObservedState)
        );
    }

    #[test]
    fn buffer_is_bounded_and_rejects_time_reversal() {
        let mut buffer = PhysicalExperienceBuffer::new();
        for tick in 0..=PHYSICAL_EXPERIENCE_CAPACITY as u64 {
            buffer
                .record(
                    tick,
                    state(0.1),
                    action(),
                    None,
                    PhysicalOutcome::SimulatorOnly,
                    0.0,
                )
                .unwrap();
        }
        assert_eq!(buffer.len(), PHYSICAL_EXPERIENCE_CAPACITY);
        assert_eq!(buffer.iter().next().unwrap().sequence, 2);
        assert_eq!(
            buffer.record(0, state(0.1), action(), None, PhysicalOutcome::Refused, 0.0),
            Err(ExperienceError::NonMonotonicTick)
        );
    }

    #[test]
    fn sequence_exhaustion_is_transactional() {
        let mut buffer = PhysicalExperienceBuffer::new();
        buffer.next_sequence = u64::MAX;
        assert_eq!(
            buffer.record(1, state(0.1), action(), None, PhysicalOutcome::Refused, 0.0),
            Err(ExperienceError::SequenceExhausted)
        );
        assert!(buffer.is_empty());
        assert_eq!(buffer.last_tick, None);
    }
}
