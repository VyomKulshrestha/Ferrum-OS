//! Deterministic simulation manifests, replay cursors, and fault injection.

use alloc::vec::Vec;

use crate::adapter::{AdapterFrame, AdapterId, AdapterPayload, EndpointId};
use crate::contract::{EvidenceClass, FaultProvenance, IntegrityEvidence, ObservationPolicy};
use crate::fleet::DeviceHealth;
use crate::session::{SessionDescriptor, SessionMode};

pub const MAX_REPLAY_STEPS: usize = 4_096;
pub const MAX_ACTIVE_FAULTS: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FaultTarget {
    Adapter(AdapterId),
    Endpoint(EndpointId),
    Sensor(u64),
    Controller(u64),
    Model(u64),
    Heliox,
    Network,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FaultKind {
    DropFrame,
    DuplicateFrame,
    DelayTicks(u64),
    ClockJumpForward(u64),
    ClockJumpBackward(u64),
    FreezeTelemetry,
    CorruptIntegrity,
    StuckActuator,
    TransportFailure,
    ModelTimeout,
    ProcessCrash,
    EmergencyStop,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FaultSpec {
    pub manifest_id: u64,
    pub fault_code: u32,
    pub target: FaultTarget,
    pub kind: FaultKind,
    pub starts_at_tick: u64,
    pub ends_at_tick: u64,
}

impl FaultSpec {
    pub const fn is_valid(self) -> bool {
        self.manifest_id != 0
            && self.fault_code != 0
            && self.starts_at_tick <= self.ends_at_tick
            && !matches!(self.kind, FaultKind::DelayTicks(0))
            && !matches!(self.kind, FaultKind::ClockJumpForward(0))
            && !matches!(self.kind, FaultKind::ClockJumpBackward(0))
    }

    pub const fn active_at(self, tick: u64) -> bool {
        tick >= self.starts_at_tick && tick <= self.ends_at_tick
    }

    pub const fn target_code(self) -> u64 {
        fault_target_code(self.target)
    }

    pub const fn kind_code(self) -> u64 {
        fault_kind_code(self.kind)
    }

    pub const fn kind_argument(self) -> u64 {
        fault_kind_argument(self.kind)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayAction {
    IngestFrame {
        frame: AdapterFrame,
        received_at_tick: u64,
        observation_policy: ObservationPolicy,
    },
    DeviceHealth {
        adapter_id: AdapterId,
        session_epoch: u64,
        health: DeviceHealth,
    },
    ActivateFault(FaultSpec),
    Checkpoint {
        checkpoint_id: u64,
    },
    Pause,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReplayStep {
    pub run_id: u64,
    pub step_id: u64,
    pub at_tick: u64,
    pub action: ReplayAction,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReplayManifest {
    descriptor: SessionDescriptor,
    steps: Vec<ReplayStep>,
    digest: u64,
}

impl ReplayManifest {
    pub fn new(descriptor: SessionDescriptor) -> Result<Self, ReplayError> {
        if !descriptor.is_valid() || descriptor.mode == SessionMode::Live {
            return Err(ReplayError::InvalidDescriptor);
        }
        Ok(Self {
            digest: descriptor_digest(descriptor),
            descriptor,
            steps: Vec::new(),
        })
    }

    pub const fn descriptor(&self) -> SessionDescriptor {
        self.descriptor
    }

    pub fn steps(&self) -> &[ReplayStep] {
        &self.steps
    }

    pub const fn digest(&self) -> u64 {
        self.digest
    }

    pub fn push(&mut self, at_tick: u64, action: ReplayAction) -> Result<ReplayStep, ReplayError> {
        if self.steps.len() >= MAX_REPLAY_STEPS {
            return Err(ReplayError::CapacityExceeded);
        }
        if self
            .steps
            .last()
            .is_some_and(|previous| at_tick < previous.at_tick)
        {
            return Err(ReplayError::TimeReversal);
        }
        validate_action(self.descriptor.mode, at_tick, action)?;
        let step = ReplayStep {
            run_id: self.descriptor.run_id,
            step_id: self.steps.len() as u64 + 1,
            at_tick,
            action,
        };
        self.digest = hash_step(self.digest, step);
        self.steps.push(step);
        Ok(step)
    }

    pub fn verify(&self) -> Result<(), ReplayError> {
        let mut digest = descriptor_digest(self.descriptor);
        let mut last_tick = self.descriptor.started_at_tick;
        for (index, step) in self.steps.iter().enumerate() {
            if step.run_id != self.descriptor.run_id || step.step_id != index as u64 + 1 {
                return Err(ReplayError::InvalidSequence);
            }
            if step.at_tick < last_tick {
                return Err(ReplayError::TimeReversal);
            }
            validate_action(self.descriptor.mode, step.at_tick, step.action)?;
            digest = hash_step(digest, *step);
            last_tick = step.at_tick;
        }
        if digest != self.digest {
            return Err(ReplayError::DigestMismatch);
        }
        Ok(())
    }

    pub fn fork_from_step(&self, step_id: u64, new_run_id: u64) -> Result<Self, ReplayError> {
        if step_id == 0 || step_id > self.steps.len() as u64 || new_run_id == 0 {
            return Err(ReplayError::UnknownForkStep);
        }
        let mut descriptor = self.descriptor;
        descriptor.parent_run_id = descriptor.run_id;
        descriptor.run_id = new_run_id;
        descriptor.fork_sequence = step_id;
        let mut fork = Self::new(descriptor)?;
        for step in self.steps.iter().take(step_id as usize) {
            fork.push(step.at_tick, step.action)?;
        }
        Ok(fork)
    }

    pub fn cursor(&self) -> ReplayCursor<'_> {
        ReplayCursor {
            manifest: self,
            index: 0,
        }
    }
}

#[derive(Debug)]
pub struct ReplayCursor<'a> {
    manifest: &'a ReplayManifest,
    index: usize,
}

impl ReplayCursor<'_> {
    pub fn next_step(&mut self) -> Option<ReplayStep> {
        let step = self.manifest.steps.get(self.index).copied()?;
        self.index += 1;
        Some(step)
    }

    pub const fn position(&self) -> usize {
        self.index
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameDisposition {
    Deliver {
        frame: AdapterFrame,
        received_at_tick: u64,
    },
    Duplicate {
        frame: AdapterFrame,
        received_at_tick: u64,
    },
    Drop,
    Hold,
}

#[derive(Debug, Default)]
pub struct FaultController {
    faults: Vec<FaultSpec>,
}

impl FaultController {
    pub const fn new() -> Self {
        Self { faults: Vec::new() }
    }

    pub fn activate(&mut self, fault: FaultSpec) -> Result<(), ReplayError> {
        if !fault.is_valid() {
            return Err(ReplayError::InvalidFault);
        }
        if self
            .faults
            .iter()
            .any(|existing| existing.manifest_id == fault.manifest_id)
        {
            return Err(ReplayError::DuplicateFault);
        }
        if self.faults.len() >= MAX_ACTIVE_FAULTS {
            return Err(ReplayError::CapacityExceeded);
        }
        self.faults.push(fault);
        Ok(())
    }

    pub fn expire_before(&mut self, tick: u64) {
        self.faults.retain(|fault| fault.ends_at_tick >= tick);
    }

    pub fn active_faults(&self) -> &[FaultSpec] {
        &self.faults
    }

    pub fn transform_frame(
        &self,
        mut frame: AdapterFrame,
        mut received_at_tick: u64,
        tick: u64,
    ) -> FrameDisposition {
        let mut duplicate = false;
        for fault in self.faults.iter().copied() {
            if !fault.active_at(tick) || !fault_matches_frame(fault, frame) {
                continue;
            }
            frame.metadata.fault_provenance = FaultProvenance::Injected {
                manifest_id: fault.manifest_id,
                fault_code: fault.fault_code,
            };
            match fault.kind {
                FaultKind::DropFrame => return FrameDisposition::Drop,
                FaultKind::FreezeTelemetry => return FrameDisposition::Hold,
                FaultKind::DuplicateFrame => duplicate = true,
                FaultKind::DelayTicks(delay) => {
                    received_at_tick = received_at_tick.saturating_add(delay);
                }
                FaultKind::ClockJumpForward(delta) => {
                    frame.observed_at_tick = frame.observed_at_tick.saturating_add(delta);
                    let observed_at_tick = frame.observed_at_tick;
                    update_payload_observation_tick(&mut frame, observed_at_tick);
                }
                FaultKind::ClockJumpBackward(delta) => {
                    frame.observed_at_tick = frame.observed_at_tick.saturating_sub(delta);
                    let observed_at_tick = frame.observed_at_tick;
                    update_payload_observation_tick(&mut frame, observed_at_tick);
                }
                FaultKind::CorruptIntegrity => {
                    frame.metadata.integrity = IntegrityEvidence::TransportAuthenticated([0; 32]);
                }
                FaultKind::StuckActuator
                | FaultKind::TransportFailure
                | FaultKind::ModelTimeout
                | FaultKind::ProcessCrash
                | FaultKind::EmergencyStop => {}
            }
        }
        if duplicate {
            FrameDisposition::Duplicate {
                frame,
                received_at_tick,
            }
        } else {
            FrameDisposition::Deliver {
                frame,
                received_at_tick,
            }
        }
    }

    pub fn has_active_kind(&self, kind: FaultKind, tick: u64) -> bool {
        self.faults
            .iter()
            .any(|fault| fault.active_at(tick) && same_fault_kind(fault.kind, kind))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayError {
    InvalidDescriptor,
    CapacityExceeded,
    TimeReversal,
    InvalidSequence,
    DigestMismatch,
    InvalidAction,
    InvalidFault,
    DuplicateFault,
    UnknownForkStep,
    RunMismatch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplayOutcome {
    ObservationApplied { event_id: u64 },
    DeviceHealthApplied,
    FaultActivated { manifest_id: u64 },
    FrameDropped,
    FrameHeld,
    DuplicateRejected { event_id: u64 },
    CheckpointRecorded { checkpoint_id: u64 },
    Paused,
}

fn validate_action(
    mode: SessionMode,
    at_tick: u64,
    action: ReplayAction,
) -> Result<(), ReplayError> {
    match action {
        ReplayAction::IngestFrame {
            frame,
            received_at_tick,
            observation_policy: _,
        } => {
            if received_at_tick < at_tick
                || matches!(
                    frame.metadata.evidence_class,
                    EvidenceClass::Internal | EvidenceClass::Live
                )
            {
                return Err(ReplayError::InvalidAction);
            }
            match mode {
                SessionMode::Simulation
                    if frame.metadata.evidence_class != EvidenceClass::Simulated =>
                {
                    return Err(ReplayError::InvalidAction);
                }
                SessionMode::RecordedPlayback
                    if frame.metadata.evidence_class != EvidenceClass::RecordedPlayback =>
                {
                    return Err(ReplayError::InvalidAction);
                }
                SessionMode::HardwareInLoopActuatorDisabled
                    if frame.metadata.evidence_class != EvidenceClass::HardwareInLoop =>
                {
                    return Err(ReplayError::InvalidAction);
                }
                SessionMode::Live => return Err(ReplayError::InvalidDescriptor),
                _ => {}
            }
        }
        ReplayAction::DeviceHealth { adapter_id, .. } if adapter_id.0 == 0 => {
            return Err(ReplayError::InvalidAction);
        }
        ReplayAction::ActivateFault(fault) if !fault.is_valid() => {
            return Err(ReplayError::InvalidFault);
        }
        ReplayAction::Checkpoint { checkpoint_id: 0 } => {
            return Err(ReplayError::InvalidAction);
        }
        _ => {}
    }
    Ok(())
}

fn fault_matches_frame(fault: FaultSpec, frame: AdapterFrame) -> bool {
    match fault.target {
        FaultTarget::Adapter(id) => id == frame.adapter_id,
        FaultTarget::Endpoint(id) => id == frame.endpoint_id,
        FaultTarget::Sensor(sensor_id) => matches!(
            frame.payload,
            AdapterPayload::SensorReading(reading) if reading.sensor_id == sensor_id
        ),
        FaultTarget::Controller(_)
        | FaultTarget::Model(_)
        | FaultTarget::Heliox
        | FaultTarget::Network => true,
    }
}

fn update_payload_observation_tick(frame: &mut AdapterFrame, tick: u64) {
    match &mut frame.payload {
        AdapterPayload::SensorReading(reading) => reading.observed_at_tick = tick,
        AdapterPayload::ZoneOccupancy(occupancy) => occupancy.observed_at_tick = tick,
        AdapterPayload::ActorTelemetry(_)
        | AdapterPayload::AssetTelemetry(_)
        | AdapterPayload::EmergencyStop { .. } => {}
    }
}

fn same_fault_kind(left: FaultKind, right: FaultKind) -> bool {
    core::mem::discriminant(&left) == core::mem::discriminant(&right)
}

const FNV_OFFSET: u64 = 0xcbf29ce484222325;
const FNV_PRIME: u64 = 0x100000001b3;

fn descriptor_digest(descriptor: SessionDescriptor) -> u64 {
    let mut hash = FNV_OFFSET;
    for value in [
        descriptor.run_id,
        descriptor.parent_run_id,
        descriptor.fork_sequence,
        descriptor.simulator_epoch,
        descriptor.seed,
        descriptor.started_at_tick,
        session_mode_code(descriptor.mode),
    ] {
        hash = hash_u64(hash, value);
    }
    hash
}

fn hash_step(mut hash: u64, step: ReplayStep) -> u64 {
    hash = hash_u64(hash, step.run_id);
    hash = hash_u64(hash, step.step_id);
    hash = hash_u64(hash, step.at_tick);
    match step.action {
        ReplayAction::IngestFrame {
            frame,
            received_at_tick,
            observation_policy,
        } => {
            hash = hash_u64(hash, 1);
            for value in [
                frame.adapter_id.0,
                frame.endpoint_id.0,
                frame.session_epoch,
                frame.sequence,
                frame.observed_at_tick,
                frame.metadata.source_clock_id,
                frame.metadata.clock_uncertainty_ticks,
                frame.metadata.frame_id,
                frame.metadata.expires_at_tick,
                frame.metadata.evidence_class as u64,
                received_at_tick,
                observation_policy.maximum_clock_skew_ticks,
                observation_policy.maximum_clock_uncertainty_ticks,
                observation_policy.maximum_observation_age_ticks,
            ] {
                hash = hash_u64(hash, value);
            }
            hash = hash_payload(hash, frame.payload);
        }
        ReplayAction::DeviceHealth {
            adapter_id,
            session_epoch,
            health,
        } => {
            hash = hash_u64(hash, 2);
            for value in [
                adapter_id.0,
                session_epoch,
                health.battery_permille as u64,
                health.link_quality_permille as u64,
                health.fault_code as u64,
            ] {
                hash = hash_u64(hash, value);
            }
        }
        ReplayAction::ActivateFault(fault) => {
            hash = hash_u64(hash, 3);
            hash = hash_fault(hash, fault);
        }
        ReplayAction::Checkpoint { checkpoint_id } => {
            hash = hash_u64(hash, 4);
            hash = hash_u64(hash, checkpoint_id);
        }
        ReplayAction::Pause => hash = hash_u64(hash, 5),
    }
    hash
}

fn hash_payload(mut hash: u64, payload: AdapterPayload) -> u64 {
    match payload {
        AdapterPayload::ActorTelemetry(value) => {
            hash = hash_u64(hash, 1);
            for item in [
                value.actor_id.0,
                value.position.zone_id as u64,
                value.position.x_mm as u64,
                value.position.y_mm as u64,
                value.position.z_mm as u64,
                value.battery_permille as u64,
                value.load_permille as u64,
                value.status as u64,
            ] {
                hash = hash_u64(hash, item);
            }
        }
        AdapterPayload::AssetTelemetry(value) => {
            hash = hash_u64(hash, 2);
            for item in [
                value.asset_id.0,
                value.state as u64,
                value.position.zone_id as u64,
                value.position.x_mm as u64,
                value.position.y_mm as u64,
                value.position.z_mm as u64,
            ] {
                hash = hash_u64(hash, item);
            }
        }
        AdapterPayload::SensorReading(value) => {
            hash = hash_u64(hash, 3);
            for item in [
                value.sensor_id,
                value.site_id.0,
                value.asset_id.map_or(0, |id| id.0),
                value.kind as u64,
                value.value as u64,
                value.quality_permille as u64,
                value.observed_at_tick,
            ] {
                hash = hash_u64(hash, item);
            }
        }
        AdapterPayload::ZoneOccupancy(value) => {
            hash = hash_u64(hash, 4);
            for item in [
                value.site_id.0,
                value.zone_id as u64,
                value.humans as u64,
                value.robots as u64,
                value.observed_at_tick,
            ] {
                hash = hash_u64(hash, item);
            }
        }
        AdapterPayload::EmergencyStop {
            actor_id,
            reason_code,
        } => {
            hash = hash_u64(hash, 5);
            hash = hash_u64(hash, actor_id.0);
            hash = hash_u64(hash, reason_code as u64);
        }
    }
    hash
}

fn hash_fault(mut hash: u64, fault: FaultSpec) -> u64 {
    for value in [
        fault.manifest_id,
        fault.fault_code as u64,
        fault_target_code(fault.target),
        fault_kind_code(fault.kind),
        fault_kind_argument(fault.kind),
        fault.starts_at_tick,
        fault.ends_at_tick,
    ] {
        hash = hash_u64(hash, value);
    }
    hash
}

const fn session_mode_code(mode: SessionMode) -> u64 {
    match mode {
        SessionMode::Simulation => 1,
        SessionMode::RecordedPlayback => 2,
        SessionMode::HardwareInLoopActuatorDisabled => 3,
        SessionMode::Live => 4,
    }
}

const fn fault_target_code(target: FaultTarget) -> u64 {
    match target {
        FaultTarget::Adapter(id) => 0x1000_0000_0000_0000 | id.0,
        FaultTarget::Endpoint(id) => 0x2000_0000_0000_0000 | id.0,
        FaultTarget::Sensor(id) => 0x3000_0000_0000_0000 | id,
        FaultTarget::Controller(id) => 0x4000_0000_0000_0000 | id,
        FaultTarget::Model(id) => 0x5000_0000_0000_0000 | id,
        FaultTarget::Heliox => 0x6000_0000_0000_0000,
        FaultTarget::Network => 0x7000_0000_0000_0000,
    }
}

const fn fault_kind_code(kind: FaultKind) -> u64 {
    match kind {
        FaultKind::DropFrame => 1,
        FaultKind::DuplicateFrame => 2,
        FaultKind::DelayTicks(_) => 3,
        FaultKind::ClockJumpForward(_) => 4,
        FaultKind::ClockJumpBackward(_) => 5,
        FaultKind::FreezeTelemetry => 6,
        FaultKind::CorruptIntegrity => 7,
        FaultKind::StuckActuator => 8,
        FaultKind::TransportFailure => 9,
        FaultKind::ModelTimeout => 10,
        FaultKind::ProcessCrash => 11,
        FaultKind::EmergencyStop => 12,
    }
}

const fn fault_kind_argument(kind: FaultKind) -> u64 {
    match kind {
        FaultKind::DelayTicks(value)
        | FaultKind::ClockJumpForward(value)
        | FaultKind::ClockJumpBackward(value) => value,
        _ => 0,
    }
}

fn hash_u64(mut hash: u64, value: u64) -> u64 {
    for byte in value.to_le_bytes() {
        hash = (hash ^ byte as u64).wrapping_mul(FNV_PRIME);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{AdapterId, AdapterPayload, EndpointId};
    use crate::contract::ObservationMetadata;
    use crate::domain::{AssetId, SiteId};
    use crate::twin::{SensorKind, SensorReading};

    fn frame(sequence: u64, tick: u64) -> AdapterFrame {
        AdapterFrame {
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 3,
            sequence,
            observed_at_tick: tick,
            metadata: ObservationMetadata::simulated(sequence, tick + 20),
            payload: AdapterPayload::SensorReading(SensorReading {
                sensor_id: 9,
                site_id: SiteId(1),
                asset_id: Some(AssetId(4)),
                kind: SensorKind::ProximityMillimeters,
                value: 900,
                quality_permille: 1_000,
                observed_at_tick: tick,
            }),
        }
    }

    fn ingest(sequence: u64, tick: u64) -> ReplayAction {
        ReplayAction::IngestFrame {
            frame: frame(sequence, tick),
            received_at_tick: tick,
            observation_policy: ObservationPolicy::strict(0),
        }
    }

    #[test]
    fn manifest_is_deterministic_and_forkable() {
        let descriptor = SessionDescriptor::simulator(7, 2, 42);
        let mut first = ReplayManifest::new(descriptor).unwrap();
        first.push(10, ingest(1, 10)).unwrap();
        first
            .push(11, ReplayAction::Checkpoint { checkpoint_id: 4 })
            .unwrap();
        let mut second = ReplayManifest::new(descriptor).unwrap();
        second.push(10, ingest(1, 10)).unwrap();
        second
            .push(11, ReplayAction::Checkpoint { checkpoint_id: 4 })
            .unwrap();
        assert_eq!(first.digest(), second.digest());
        assert_eq!(first.verify(), Ok(()));
        let fork = first.fork_from_step(1, 8).unwrap();
        assert_eq!(fork.steps().len(), 1);
        assert_eq!(fork.descriptor().parent_run_id, 7);
        assert_eq!(fork.verify(), Ok(()));
    }

    #[test]
    fn live_or_mislabeled_input_cannot_enter_replay() {
        let mut live = SessionDescriptor::simulator(1, 1, 1);
        live.mode = SessionMode::Live;
        assert_eq!(
            ReplayManifest::new(live),
            Err(ReplayError::InvalidDescriptor)
        );

        let mut manifest = ReplayManifest::new(SessionDescriptor::simulator(2, 1, 1)).unwrap();
        let mut mislabeled = frame(1, 10);
        mislabeled.metadata.evidence_class = EvidenceClass::RecordedPlayback;
        assert_eq!(
            manifest.push(
                10,
                ReplayAction::IngestFrame {
                    frame: mislabeled,
                    received_at_tick: 10,
                    observation_policy: ObservationPolicy::strict(0),
                }
            ),
            Err(ReplayError::InvalidAction)
        );
    }

    #[test]
    fn faults_transform_frames_without_hiding_provenance() {
        let mut controller = FaultController::new();
        controller
            .activate(FaultSpec {
                manifest_id: 3,
                fault_code: 8,
                target: FaultTarget::Sensor(9),
                kind: FaultKind::DelayTicks(5),
                starts_at_tick: 10,
                ends_at_tick: 20,
            })
            .unwrap();
        let disposition = controller.transform_frame(frame(1, 10), 10, 10);
        let FrameDisposition::Deliver {
            frame,
            received_at_tick,
        } = disposition
        else {
            panic!("delay must deliver");
        };
        assert_eq!(received_at_tick, 15);
        assert_eq!(
            frame.metadata.fault_provenance,
            FaultProvenance::Injected {
                manifest_id: 3,
                fault_code: 8
            }
        );
    }

    #[test]
    fn drop_duplicate_freeze_and_corruption_are_explicit_dispositions() {
        for (index, (kind, expected)) in [
            (FaultKind::DropFrame, FrameDisposition::Drop),
            (FaultKind::FreezeTelemetry, FrameDisposition::Hold),
        ]
        .into_iter()
        .enumerate()
        {
            let mut controller = FaultController::new();
            controller
                .activate(FaultSpec {
                    manifest_id: index as u64 + 1,
                    fault_code: 1,
                    target: FaultTarget::Adapter(AdapterId(1)),
                    kind,
                    starts_at_tick: 10,
                    ends_at_tick: 10,
                })
                .unwrap();
            assert_eq!(controller.transform_frame(frame(1, 10), 10, 10), expected);
        }

        let mut duplicate = FaultController::new();
        duplicate
            .activate(FaultSpec {
                manifest_id: 3,
                fault_code: 2,
                target: FaultTarget::Endpoint(EndpointId(2)),
                kind: FaultKind::DuplicateFrame,
                starts_at_tick: 10,
                ends_at_tick: 10,
            })
            .unwrap();
        assert!(matches!(
            duplicate.transform_frame(frame(1, 10), 10, 10),
            FrameDisposition::Duplicate { .. }
        ));

        let mut corrupt = FaultController::new();
        corrupt
            .activate(FaultSpec {
                manifest_id: 4,
                fault_code: 3,
                target: FaultTarget::Network,
                kind: FaultKind::CorruptIntegrity,
                starts_at_tick: 10,
                ends_at_tick: 10,
            })
            .unwrap();
        let FrameDisposition::Deliver { frame, .. } = corrupt.transform_frame(frame(1, 10), 10, 10)
        else {
            panic!("corruption reaches validation");
        };
        assert_eq!(
            frame.metadata.integrity,
            IntegrityEvidence::TransportAuthenticated([0; 32])
        );
    }
}
