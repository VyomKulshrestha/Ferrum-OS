//! Deterministic session identity and append-only evidence records.
//!
//! The checksum chain detects accidental mutation and makes simulator runs
//! reproducible. It is not a cryptographic signature and must not be used as
//! authentication evidence at a transport boundary.

use alloc::collections::VecDeque;

pub const MAX_EVIDENCE_RECORDS: usize = 8_192;
pub const EVIDENCE_RECORD_WIRE_SIZE: usize = 80;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionMode {
    Simulation,
    RecordedPlayback,
    HardwareInLoopActuatorDisabled,
    Live,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SessionDescriptor {
    pub run_id: u64,
    pub parent_run_id: u64,
    pub fork_sequence: u64,
    pub simulator_epoch: u64,
    pub seed: u64,
    pub started_at_tick: u64,
    pub mode: SessionMode,
    pub topology_sha256: [u8; 32],
    pub policy_sha256: [u8; 32],
    pub model_sha256: [u8; 32],
}

impl SessionDescriptor {
    pub const fn simulator(run_id: u64, simulator_epoch: u64, seed: u64) -> Self {
        Self {
            run_id,
            parent_run_id: 0,
            fork_sequence: 0,
            simulator_epoch,
            seed,
            started_at_tick: 0,
            mode: SessionMode::Simulation,
            topology_sha256: [0; 32],
            policy_sha256: [0; 32],
            model_sha256: [0; 32],
        }
    }

    pub const fn is_valid(self) -> bool {
        self.run_id != 0
            && self.simulator_epoch != 0
            && (self.parent_run_id == 0 || self.fork_sequence != 0)
            && (self.parent_run_id != self.run_id)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum EvidenceKind {
    ObservationAccepted = 1,
    IntentResolved = 2,
    PredictionObserved = 3,
    SafetyDecision = 4,
    ConfirmationObserved = 5,
    PermitIssued = 6,
    DeliveryAcknowledged = 7,
    DeliveryUncertain = 8,
    FaultInjected = 9,
    EmergencyStopObserved = 10,
    OperatorAction = 11,
    Checkpoint = 12,
}

impl EvidenceKind {
    fn from_byte(value: u8) -> Result<Self, SessionError> {
        match value {
            1 => Ok(Self::ObservationAccepted),
            2 => Ok(Self::IntentResolved),
            3 => Ok(Self::PredictionObserved),
            4 => Ok(Self::SafetyDecision),
            5 => Ok(Self::ConfirmationObserved),
            6 => Ok(Self::PermitIssued),
            7 => Ok(Self::DeliveryAcknowledged),
            8 => Ok(Self::DeliveryUncertain),
            9 => Ok(Self::FaultInjected),
            10 => Ok(Self::EmergencyStopObserved),
            11 => Ok(Self::OperatorAction),
            12 => Ok(Self::Checkpoint),
            _ => Err(SessionError::InvalidWireRecord),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EvidenceRecord {
    pub sequence: u64,
    pub tick: u64,
    pub kind: EvidenceKind,
    pub subject_id: u64,
    pub detail0: u64,
    pub detail1: u64,
    pub detail2: u64,
    pub detail3: u64,
    pub previous_checksum: u64,
    pub checksum: u64,
}

impl EvidenceRecord {
    pub fn encode(self) -> [u8; EVIDENCE_RECORD_WIRE_SIZE] {
        let mut output = [0u8; EVIDENCE_RECORD_WIRE_SIZE];
        output[0..8].copy_from_slice(&self.sequence.to_le_bytes());
        output[8..16].copy_from_slice(&self.tick.to_le_bytes());
        output[16] = self.kind as u8;
        write_u64(&mut output, 24, self.subject_id);
        write_u64(&mut output, 32, self.detail0);
        write_u64(&mut output, 40, self.detail1);
        write_u64(&mut output, 48, self.detail2);
        write_u64(&mut output, 56, self.detail3);
        write_u64(&mut output, 64, self.previous_checksum);
        write_u64(&mut output, 72, self.checksum);
        output
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, SessionError> {
        if bytes.len() != EVIDENCE_RECORD_WIRE_SIZE || bytes[17..24].iter().any(|byte| *byte != 0) {
            return Err(SessionError::InvalidWireRecord);
        }
        let record = Self {
            sequence: read_u64(bytes, 0)?,
            tick: read_u64(bytes, 8)?,
            kind: EvidenceKind::from_byte(bytes[16])?,
            subject_id: read_u64(bytes, 24)?,
            detail0: read_u64(bytes, 32)?,
            detail1: read_u64(bytes, 40)?,
            detail2: read_u64(bytes, 48)?,
            detail3: read_u64(bytes, 56)?,
            previous_checksum: read_u64(bytes, 64)?,
            checksum: read_u64(bytes, 72)?,
        };
        if record.sequence == 0 || record.checksum != checksum_record(record) {
            return Err(SessionError::InvalidWireRecord);
        }
        Ok(record)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionError {
    InvalidDescriptor,
    CapacityExceeded,
    TimeReversal,
    InvalidSequence,
    InvalidChecksumChain,
    InvalidWireRecord,
    ForkForbidden,
    UnknownForkSequence,
}

#[derive(Debug, Clone)]
pub struct EvidenceLog {
    descriptor: SessionDescriptor,
    records: VecDeque<EvidenceRecord>,
    last_tick: u64,
    last_checksum: u64,
}

impl EvidenceLog {
    pub fn new(descriptor: SessionDescriptor) -> Result<Self, SessionError> {
        if !descriptor.is_valid() {
            return Err(SessionError::InvalidDescriptor);
        }
        Ok(Self {
            last_tick: descriptor.started_at_tick,
            descriptor,
            records: VecDeque::new(),
            last_checksum: descriptor_checksum(descriptor),
        })
    }

    pub const fn descriptor(&self) -> SessionDescriptor {
        self.descriptor
    }

    pub fn records(&self) -> &VecDeque<EvidenceRecord> {
        &self.records
    }

    pub const fn final_checksum(&self) -> u64 {
        self.last_checksum
    }

    pub fn reserve(&self, additional: usize) -> Result<(), SessionError> {
        if self.records.len().saturating_add(additional) > MAX_EVIDENCE_RECORDS {
            return Err(SessionError::CapacityExceeded);
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn append(
        &mut self,
        tick: u64,
        kind: EvidenceKind,
        subject_id: u64,
        detail0: u64,
        detail1: u64,
        detail2: u64,
        detail3: u64,
    ) -> Result<EvidenceRecord, SessionError> {
        self.reserve(1)?;
        if tick < self.last_tick {
            return Err(SessionError::TimeReversal);
        }
        let mut record = EvidenceRecord {
            sequence: self.records.len() as u64 + 1,
            tick,
            kind,
            subject_id,
            detail0,
            detail1,
            detail2,
            detail3,
            previous_checksum: self.last_checksum,
            checksum: 0,
        };
        record.checksum = checksum_record(record);
        self.records.push_back(record);
        self.last_tick = tick;
        self.last_checksum = record.checksum;
        Ok(record)
    }

    pub fn verify(&self) -> Result<(), SessionError> {
        let mut expected_sequence = 1u64;
        let mut previous_checksum = descriptor_checksum(self.descriptor);
        let mut previous_tick = self.descriptor.started_at_tick;
        for record in &self.records {
            if record.sequence != expected_sequence {
                return Err(SessionError::InvalidSequence);
            }
            if record.tick < previous_tick {
                return Err(SessionError::TimeReversal);
            }
            if record.previous_checksum != previous_checksum
                || record.checksum != checksum_record(*record)
            {
                return Err(SessionError::InvalidChecksumChain);
            }
            expected_sequence = expected_sequence.saturating_add(1);
            previous_checksum = record.checksum;
            previous_tick = record.tick;
        }
        if previous_checksum != self.last_checksum {
            return Err(SessionError::InvalidChecksumChain);
        }
        Ok(())
    }

    pub fn fork_from(&self, fork_sequence: u64, new_run_id: u64) -> Result<Self, SessionError> {
        if self.descriptor.mode == SessionMode::Live || new_run_id == 0 {
            return Err(SessionError::ForkForbidden);
        }
        if fork_sequence == 0 || fork_sequence > self.records.len() as u64 {
            return Err(SessionError::UnknownForkSequence);
        }
        let mut descriptor = self.descriptor;
        descriptor.parent_run_id = self.descriptor.run_id;
        descriptor.run_id = new_run_id;
        descriptor.fork_sequence = fork_sequence;
        if !descriptor.is_valid() {
            return Err(SessionError::InvalidDescriptor);
        }
        let mut fork = Self::new(descriptor)?;
        for record in self.records.iter().take(fork_sequence as usize) {
            fork.append(
                record.tick,
                record.kind,
                record.subject_id,
                record.detail0,
                record.detail1,
                record.detail2,
                record.detail3,
            )?;
        }
        Ok(fork)
    }
}

fn descriptor_checksum(descriptor: SessionDescriptor) -> u64 {
    let mut hash = FNV_OFFSET;
    hash = hash_u64(hash, descriptor.run_id);
    hash = hash_u64(hash, descriptor.parent_run_id);
    hash = hash_u64(hash, descriptor.fork_sequence);
    hash = hash_u64(hash, descriptor.simulator_epoch);
    hash = hash_u64(hash, descriptor.seed);
    hash = hash_u64(hash, descriptor.started_at_tick);
    hash = hash_u64(hash, descriptor.mode as u64);
    for digest in [
        descriptor.topology_sha256,
        descriptor.policy_sha256,
        descriptor.model_sha256,
    ] {
        for byte in digest {
            hash = hash_byte(hash, byte);
        }
    }
    hash
}

fn checksum_record(record: EvidenceRecord) -> u64 {
    let mut hash = FNV_OFFSET;
    for value in [
        record.previous_checksum,
        record.sequence,
        record.tick,
        record.kind as u64,
        record.subject_id,
        record.detail0,
        record.detail1,
        record.detail2,
        record.detail3,
    ] {
        hash = hash_u64(hash, value);
    }
    hash
}

const FNV_OFFSET: u64 = 0xcbf29ce484222325;
const FNV_PRIME: u64 = 0x100000001b3;

fn hash_u64(mut hash: u64, value: u64) -> u64 {
    for byte in value.to_le_bytes() {
        hash = hash_byte(hash, byte);
    }
    hash
}

const fn hash_byte(hash: u64, byte: u8) -> u64 {
    (hash ^ byte as u64).wrapping_mul(FNV_PRIME)
}

fn write_u64(output: &mut [u8], offset: usize, value: u64) {
    output[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

fn read_u64(bytes: &[u8], offset: usize) -> Result<u64, SessionError> {
    let raw: [u8; 8] = bytes
        .get(offset..offset + 8)
        .ok_or(SessionError::InvalidWireRecord)?
        .try_into()
        .map_err(|_| SessionError::InvalidWireRecord)?;
    Ok(u64::from_le_bytes(raw))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn log() -> EvidenceLog {
        EvidenceLog::new(SessionDescriptor::simulator(7, 3, 42)).unwrap()
    }

    #[test]
    fn records_round_trip_with_a_stable_checksum_chain() {
        let mut log = log();
        let first = log
            .append(10, EvidenceKind::ObservationAccepted, 1, 2, 3, 4, 5)
            .unwrap();
        let second = log
            .append(11, EvidenceKind::SafetyDecision, 6, 7, 8, 9, 10)
            .unwrap();
        assert_eq!(second.previous_checksum, first.checksum);
        assert_eq!(EvidenceRecord::decode(&first.encode()), Ok(first));
        assert_eq!(EvidenceRecord::decode(&second.encode()), Ok(second));
        assert_eq!(log.verify(), Ok(()));
    }

    #[test]
    fn every_wire_byte_is_checked_or_reserved() {
        let mut log = log();
        let record = log
            .append(10, EvidenceKind::ObservationAccepted, 1, 2, 3, 4, 5)
            .unwrap();
        let encoded = record.encode();
        for index in 0..encoded.len() {
            let mut changed = encoded;
            changed[index] ^= 0x80;
            assert!(EvidenceRecord::decode(&changed).is_err(), "byte {index}");
        }
    }

    #[test]
    fn time_reversal_and_capacity_fail_without_mutation() {
        let mut log = log();
        log.append(10, EvidenceKind::ObservationAccepted, 1, 0, 0, 0, 0)
            .unwrap();
        assert_eq!(
            log.append(9, EvidenceKind::OperatorAction, 2, 0, 0, 0, 0),
            Err(SessionError::TimeReversal)
        );
        assert_eq!(log.records().len(), 1);
        assert_eq!(
            log.reserve(MAX_EVIDENCE_RECORDS),
            Err(SessionError::CapacityExceeded)
        );
    }

    #[test]
    fn simulation_can_fork_but_live_evidence_cannot() {
        let mut log = log();
        log.append(10, EvidenceKind::Checkpoint, 1, 0, 0, 0, 0)
            .unwrap();
        let fork = log.fork_from(1, 8).unwrap();
        assert_eq!(fork.descriptor().parent_run_id, 7);
        assert_eq!(fork.descriptor().fork_sequence, 1);
        assert_eq!(fork.records().len(), 1);
        assert_eq!(fork.verify(), Ok(()));

        let mut descriptor = SessionDescriptor::simulator(9, 4, 43);
        descriptor.mode = SessionMode::Live;
        let mut live = EvidenceLog::new(descriptor).unwrap();
        live.append(10, EvidenceKind::Checkpoint, 1, 0, 0, 0, 0)
            .unwrap();
        assert!(matches!(
            live.fork_from(1, 10),
            Err(SessionError::ForkForbidden)
        ));
    }
}
