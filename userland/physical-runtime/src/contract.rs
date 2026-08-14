//! Versioned cyber-physical observation and command metadata.
//!
//! Transport adapters and simulators share this logical contract. The contract
//! does not claim that they share a low-level driver, clock, or trust boundary.

use crate::adapter::{AdapterProtocol, EndpointCapability};

pub const CYBER_PHYSICAL_SCHEMA_VERSION: u16 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum EvidenceClass {
    Internal,
    Simulated,
    RecordedPlayback,
    HardwareInLoop,
    Live,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FaultProvenance {
    None,
    Injected { manifest_id: u64, fault_code: u32 },
    Observed { fault_code: u32 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntegrityEvidence {
    KernelGenerated,
    SimulatorFixture,
    TransportAuthenticated([u8; 32]),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConfirmationProvenance {
    NotRequired,
    LocalHuman { confirmation_id: u64 },
    ExternalSupervisor { confirmation_id: u64 },
}

impl ConfirmationProvenance {
    pub const fn is_human_verified(self) -> bool {
        matches!(
            self,
            Self::LocalHuman { confirmation_id } | Self::ExternalSupervisor { confirmation_id }
                if confirmation_id != 0
        )
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ObservationPolicy {
    pub maximum_clock_skew_ticks: u64,
    pub maximum_clock_uncertainty_ticks: u64,
    pub maximum_observation_age_ticks: u64,
}

impl ObservationPolicy {
    pub const fn strict(maximum_clock_skew_ticks: u64) -> Self {
        Self {
            maximum_clock_skew_ticks,
            maximum_clock_uncertainty_ticks: maximum_clock_skew_ticks,
            maximum_observation_age_ticks: maximum_clock_skew_ticks,
        }
    }

    pub const fn is_valid(self) -> bool {
        true
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ObservationMetadata {
    pub schema_version: u16,
    pub source_clock_id: u64,
    pub clock_uncertainty_ticks: u64,
    pub frame_id: u64,
    pub expires_at_tick: u64,
    pub evidence_class: EvidenceClass,
    pub fault_provenance: FaultProvenance,
    pub integrity: IntegrityEvidence,
}

impl ObservationMetadata {
    pub const fn simulated(frame_id: u64, expires_at_tick: u64) -> Self {
        Self {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            source_clock_id: 1,
            clock_uncertainty_ticks: 0,
            frame_id,
            expires_at_tick,
            evidence_class: EvidenceClass::Simulated,
            fault_provenance: FaultProvenance::None,
            integrity: IntegrityEvidence::SimulatorFixture,
        }
    }

    pub const fn internal(frame_id: u64, expires_at_tick: u64) -> Self {
        Self {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            source_clock_id: u64::MAX,
            clock_uncertainty_ticks: 0,
            frame_id,
            expires_at_tick,
            evidence_class: EvidenceClass::Internal,
            fault_provenance: FaultProvenance::None,
            integrity: IntegrityEvidence::KernelGenerated,
        }
    }

    pub fn validate_adapter(
        self,
        protocol: AdapterProtocol,
        observed_at_tick: u64,
        received_at_tick: u64,
        policy: ObservationPolicy,
    ) -> Result<(), ContractError> {
        if !policy.is_valid() {
            return Err(ContractError::InvalidPolicy);
        }
        if self.schema_version != CYBER_PHYSICAL_SCHEMA_VERSION {
            return Err(ContractError::UnsupportedSchema);
        }
        if self.source_clock_id == 0 || self.frame_id == 0 || self.expires_at_tick == 0 {
            return Err(ContractError::InvalidIdentity);
        }
        if self.clock_uncertainty_ticks > policy.maximum_clock_uncertainty_ticks {
            return Err(ContractError::ClockUncertain);
        }
        if observed_at_tick > received_at_tick
            && observed_at_tick - received_at_tick > policy.maximum_clock_skew_ticks
        {
            return Err(ContractError::FutureObservation);
        }
        if received_at_tick >= observed_at_tick
            && received_at_tick - observed_at_tick > policy.maximum_observation_age_ticks
        {
            return Err(ContractError::StaleObservation);
        }
        if received_at_tick > self.expires_at_tick || observed_at_tick > self.expires_at_tick {
            return Err(ContractError::ExpiredObservation);
        }
        if self.evidence_class == EvidenceClass::Internal {
            return Err(ContractError::InvalidEvidenceBoundary);
        }
        if matches!(self.fault_provenance, FaultProvenance::Injected { .. })
            && self.evidence_class == EvidenceClass::Live
        {
            return Err(ContractError::InvalidEvidenceBoundary);
        }

        match (protocol, self.evidence_class, self.integrity) {
            (
                AdapterProtocol::Simulator,
                EvidenceClass::Simulated | EvidenceClass::RecordedPlayback,
                IntegrityEvidence::SimulatorFixture,
            ) => Ok(()),
            (
                _,
                EvidenceClass::HardwareInLoop | EvidenceClass::Live,
                IntegrityEvidence::TransportAuthenticated(digest),
            ) if digest.iter().any(|byte| *byte != 0) => Ok(()),
            _ => Err(ContractError::InvalidEvidenceBoundary),
        }
    }

    pub fn validate_internal(
        self,
        observed_at_tick: u64,
        received_at_tick: u64,
    ) -> Result<(), ContractError> {
        if self.schema_version != CYBER_PHYSICAL_SCHEMA_VERSION
            || self.source_clock_id == 0
            || self.frame_id == 0
            || self.expires_at_tick < received_at_tick
            || observed_at_tick > received_at_tick
            || self.evidence_class != EvidenceClass::Internal
            || self.integrity != IntegrityEvidence::KernelGenerated
            || self.fault_provenance != FaultProvenance::None
        {
            return Err(ContractError::InvalidInternalEvent);
        }
        Ok(())
    }

    pub fn validate_event(
        self,
        observed_at_tick: u64,
        received_at_tick: u64,
        maximum_clock_skew_ticks: u64,
    ) -> Result<(), ContractError> {
        if self.evidence_class == EvidenceClass::Internal {
            return self.validate_internal(observed_at_tick, received_at_tick);
        }
        if self.schema_version != CYBER_PHYSICAL_SCHEMA_VERSION
            || self.source_clock_id == 0
            || self.frame_id == 0
            || self.expires_at_tick == 0
        {
            return Err(ContractError::UnsupportedSchema);
        }
        if observed_at_tick > received_at_tick
            && observed_at_tick - received_at_tick > maximum_clock_skew_ticks
        {
            return Err(ContractError::FutureObservation);
        }
        if received_at_tick > self.expires_at_tick {
            return Err(ContractError::ExpiredObservation);
        }
        if self.integrity == IntegrityEvidence::KernelGenerated {
            return Err(ContractError::InvalidEvidenceBoundary);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CommandMetadata {
    pub schema_version: u16,
    pub issued_at_tick: u64,
    pub expected_policy_revision: u64,
    pub expected_twin_event_id: u64,
    pub requested_capability: EndpointCapability,
    pub confirmation: ConfirmationProvenance,
    pub integrity: IntegrityEvidence,
}

impl CommandMetadata {
    pub const fn kernel(
        issued_at_tick: u64,
        expected_policy_revision: u64,
        expected_twin_event_id: u64,
        requested_capability: EndpointCapability,
        confirmation: ConfirmationProvenance,
    ) -> Self {
        Self {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            issued_at_tick,
            expected_policy_revision,
            expected_twin_event_id,
            requested_capability,
            confirmation,
            integrity: IntegrityEvidence::KernelGenerated,
        }
    }

    pub fn validate(
        self,
        current_tick: u64,
        deadline_tick: u64,
        required_capability: EndpointCapability,
    ) -> Result<(), ContractError> {
        if self.schema_version != CYBER_PHYSICAL_SCHEMA_VERSION {
            return Err(ContractError::UnsupportedSchema);
        }
        let emergency_stop = self.requested_capability == EndpointCapability::EmergencyStop;
        if self.issued_at_tick > current_tick
            || current_tick > deadline_tick
            || (!emergency_stop && self.expected_policy_revision == 0)
            || (!emergency_stop && self.expected_twin_event_id == 0)
        {
            return Err(ContractError::InvalidCommandTime);
        }
        if self.requested_capability != required_capability {
            return Err(ContractError::CapabilityMismatch);
        }
        if self.integrity != IntegrityEvidence::KernelGenerated {
            return Err(ContractError::InvalidCommandAuthority);
        }
        if matches!(
            self.confirmation,
            ConfirmationProvenance::LocalHuman { confirmation_id: 0 }
                | ConfirmationProvenance::ExternalSupervisor { confirmation_id: 0 }
        ) {
            return Err(ContractError::InvalidConfirmation);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContractError {
    InvalidPolicy,
    UnsupportedSchema,
    InvalidIdentity,
    ClockUncertain,
    FutureObservation,
    StaleObservation,
    ExpiredObservation,
    InvalidEvidenceBoundary,
    InvalidInternalEvent,
    InvalidCommandTime,
    CapabilityMismatch,
    InvalidCommandAuthority,
    InvalidConfirmation,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn simulator_metadata_is_bounded_and_cannot_claim_live_evidence() {
        let policy = ObservationPolicy {
            maximum_clock_skew_ticks: 2,
            maximum_clock_uncertainty_ticks: 1,
            maximum_observation_age_ticks: 10,
        };
        let valid = ObservationMetadata::simulated(1, 20);
        assert_eq!(
            valid.validate_adapter(AdapterProtocol::Simulator, 10, 11, policy),
            Ok(())
        );

        let mut forged = valid;
        forged.evidence_class = EvidenceClass::Live;
        assert_eq!(
            forged.validate_adapter(AdapterProtocol::Simulator, 10, 11, policy),
            Err(ContractError::InvalidEvidenceBoundary)
        );
    }

    #[test]
    fn stale_uncertain_and_expired_observations_fail_closed() {
        let policy = ObservationPolicy {
            maximum_clock_skew_ticks: 1,
            maximum_clock_uncertainty_ticks: 1,
            maximum_observation_age_ticks: 3,
        };
        let mut metadata = ObservationMetadata::simulated(1, 20);
        assert_eq!(
            metadata.validate_adapter(AdapterProtocol::Simulator, 10, 14, policy),
            Err(ContractError::StaleObservation)
        );
        metadata.clock_uncertainty_ticks = 2;
        assert_eq!(
            metadata.validate_adapter(AdapterProtocol::Simulator, 10, 11, policy),
            Err(ContractError::ClockUncertain)
        );
        metadata.clock_uncertainty_ticks = 0;
        metadata.expires_at_tick = 10;
        assert_eq!(
            metadata.validate_adapter(AdapterProtocol::Simulator, 10, 11, policy),
            Err(ContractError::ExpiredObservation)
        );
    }

    #[test]
    fn live_transport_requires_authenticated_integrity() {
        let policy = ObservationPolicy {
            maximum_clock_skew_ticks: 2,
            maximum_clock_uncertainty_ticks: 2,
            maximum_observation_age_ticks: 5,
        };
        let live = ObservationMetadata {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            source_clock_id: 9,
            clock_uncertainty_ticks: 1,
            frame_id: 4,
            expires_at_tick: 20,
            evidence_class: EvidenceClass::Live,
            fault_provenance: FaultProvenance::None,
            integrity: IntegrityEvidence::TransportAuthenticated([3; 32]),
        };
        assert_eq!(
            live.validate_adapter(AdapterProtocol::Mqtt, 10, 11, policy),
            Ok(())
        );

        let mut untrusted = live;
        untrusted.integrity = IntegrityEvidence::TransportAuthenticated([0; 32]);
        assert_eq!(
            untrusted.validate_adapter(AdapterProtocol::Mqtt, 10, 11, policy),
            Err(ContractError::InvalidEvidenceBoundary)
        );
    }

    #[test]
    fn injected_fault_cannot_be_labeled_live() {
        let policy = ObservationPolicy {
            maximum_clock_skew_ticks: 2,
            maximum_clock_uncertainty_ticks: 2,
            maximum_observation_age_ticks: 5,
        };
        let live = ObservationMetadata {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            source_clock_id: 9,
            clock_uncertainty_ticks: 1,
            frame_id: 4,
            expires_at_tick: 20,
            evidence_class: EvidenceClass::Live,
            fault_provenance: FaultProvenance::Injected {
                manifest_id: 1,
                fault_code: 7,
            },
            integrity: IntegrityEvidence::TransportAuthenticated([3; 32]),
        };
        assert_eq!(
            live.validate_adapter(AdapterProtocol::Mqtt, 10, 11, policy),
            Err(ContractError::InvalidEvidenceBoundary)
        );
    }

    #[test]
    fn command_metadata_binds_capability_revisions_and_authority() {
        let metadata = CommandMetadata::kernel(
            10,
            2,
            8,
            EndpointCapability::Move,
            ConfirmationProvenance::LocalHuman {
                confirmation_id: 11,
            },
        );
        assert_eq!(metadata.validate(10, 20, EndpointCapability::Move), Ok(()));
        assert_eq!(
            metadata.validate(10, 20, EndpointCapability::Actuate),
            Err(ContractError::CapabilityMismatch)
        );
    }

    #[test]
    fn clock_boundaries_are_overflow_safe() {
        let policy = ObservationPolicy {
            maximum_clock_skew_ticks: 10,
            maximum_clock_uncertainty_ticks: 1,
            maximum_observation_age_ticks: 10,
        };
        let metadata = ObservationMetadata::simulated(1, u64::MAX);

        assert_eq!(
            metadata.validate_adapter(AdapterProtocol::Simulator, u64::MAX, u64::MAX - 5, policy),
            Ok(())
        );
        assert_eq!(
            metadata.validate_adapter(AdapterProtocol::Simulator, u64::MAX, u64::MAX - 11, policy,),
            Err(ContractError::FutureObservation)
        );
        assert_eq!(
            metadata.validate_event(u64::MAX, u64::MAX - 11, 10),
            Err(ContractError::FutureObservation)
        );
    }
}
