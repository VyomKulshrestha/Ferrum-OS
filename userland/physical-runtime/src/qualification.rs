//! Evidence requirements for progressively less synthetic physical operation.
//!
//! This module evaluates completeness; it does not certify evidence or mint
//! execution authority. Hardware measurements and independent assessments must
//! enter through a future authenticated kernel-owned evidence service.

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum DeploymentStage {
    SoftwareSimulation,
    HardwareInLoopActuatorDisabled,
    SupervisedLowEnergyTrial,
    BoundedLiveOperation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum QualificationCondition {
    HazardRegister = 0,
    DeterministicSafetyAuthority = 1,
    ModelCannotIssuePermits = 2,
    ImmutableConfigurationIdentity = 3,
    ScenarioFalsification = 4,
    FaultInjectionAndReplay = 5,
    DeadlineFreshnessAndLiveliness = 6,
    ActuatorDisabledHilPath = 7,
    ApplicationRiskAssessment = 8,
    MeasuredHardwareTiming = 9,
    MeasuredStoppingPerformance = 10,
    ContactForcePressureAssessed = 11,
    IndependentEmergencyStop = 12,
    SafetyControlPerformanceVerified = 13,
    RepresentativeRobotTrials = 14,
    IndependentSafetyAssessment = 15,
    PostUpdateRegressionPlan = 16,
}

impl QualificationCondition {
    const fn bit(self) -> u32 {
        1u32 << self as u8
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DeploymentEvidenceSet(u32);

impl DeploymentEvidenceSet {
    pub const fn empty() -> Self {
        Self(0)
    }

    pub const fn with(self, condition: QualificationCondition) -> Self {
        Self(self.0 | condition.bit())
    }

    pub const fn contains(self, condition: QualificationCondition) -> bool {
        self.0 & condition.bit() != 0
    }

    pub const fn contains_all(self, required: Self) -> bool {
        self.0 & required.0 == required.0
    }

    pub const fn missing(self, required: Self) -> Self {
        Self(required.0 & !self.0)
    }

    pub const fn bits(self) -> u32 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QualificationAssessment {
    pub requested_stage: DeploymentStage,
    pub complete: bool,
    pub missing: DeploymentEvidenceSet,
}

pub const fn required_evidence(stage: DeploymentStage) -> DeploymentEvidenceSet {
    let software = DeploymentEvidenceSet::empty()
        .with(QualificationCondition::HazardRegister)
        .with(QualificationCondition::DeterministicSafetyAuthority)
        .with(QualificationCondition::ModelCannotIssuePermits)
        .with(QualificationCondition::ImmutableConfigurationIdentity)
        .with(QualificationCondition::ScenarioFalsification)
        .with(QualificationCondition::FaultInjectionAndReplay)
        .with(QualificationCondition::DeadlineFreshnessAndLiveliness)
        .with(QualificationCondition::ActuatorDisabledHilPath);
    if matches!(stage, DeploymentStage::SoftwareSimulation) {
        return software;
    }

    let hil = software
        .with(QualificationCondition::ApplicationRiskAssessment)
        .with(QualificationCondition::MeasuredHardwareTiming)
        .with(QualificationCondition::IndependentEmergencyStop);
    if matches!(stage, DeploymentStage::HardwareInLoopActuatorDisabled) {
        return hil;
    }

    let supervised = hil
        .with(QualificationCondition::MeasuredStoppingPerformance)
        .with(QualificationCondition::ContactForcePressureAssessed)
        .with(QualificationCondition::SafetyControlPerformanceVerified)
        .with(QualificationCondition::RepresentativeRobotTrials);
    if matches!(stage, DeploymentStage::SupervisedLowEnergyTrial) {
        return supervised;
    }

    supervised
        .with(QualificationCondition::IndependentSafetyAssessment)
        .with(QualificationCondition::PostUpdateRegressionPlan)
}

pub const fn assess(
    evidence: DeploymentEvidenceSet,
    stage: DeploymentStage,
) -> QualificationAssessment {
    let required = required_evidence(stage);
    let missing = evidence.missing(required);
    QualificationAssessment {
        requested_stage: stage,
        complete: evidence.contains_all(required),
        missing,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn software_evidence() -> DeploymentEvidenceSet {
        required_evidence(DeploymentStage::SoftwareSimulation)
    }

    #[test]
    fn software_evidence_does_not_claim_hardware_readiness() {
        let evidence = software_evidence();
        assert!(assess(evidence, DeploymentStage::SoftwareSimulation).complete);
        let hil = assess(evidence, DeploymentStage::HardwareInLoopActuatorDisabled);
        assert!(!hil.complete);
        assert!(hil
            .missing
            .contains(QualificationCondition::ApplicationRiskAssessment));
        assert!(hil
            .missing
            .contains(QualificationCondition::MeasuredHardwareTiming));
        assert!(hil
            .missing
            .contains(QualificationCondition::IndependentEmergencyStop));
    }

    #[test]
    fn stages_are_monotonic_and_cannot_skip_prior_evidence() {
        let live = required_evidence(DeploymentStage::BoundedLiveOperation);
        for stage in [
            DeploymentStage::SoftwareSimulation,
            DeploymentStage::HardwareInLoopActuatorDisabled,
            DeploymentStage::SupervisedLowEnergyTrial,
            DeploymentStage::BoundedLiveOperation,
        ] {
            assert!(assess(live, stage).complete);
        }

        let without_timing = DeploymentEvidenceSet(
            live.bits() & !QualificationCondition::MeasuredHardwareTiming.bit(),
        );
        assert!(!assess(without_timing, DeploymentStage::BoundedLiveOperation).complete);
    }

    #[test]
    fn contact_measurement_requires_evidence_or_documented_non_applicability() {
        let evidence = required_evidence(DeploymentStage::SupervisedLowEnergyTrial);
        let missing_contact = DeploymentEvidenceSet(
            evidence.bits() & !QualificationCondition::ContactForcePressureAssessed.bit(),
        );
        let assessment = assess(missing_contact, DeploymentStage::SupervisedLowEnergyTrial);
        assert!(!assessment.complete);
        assert!(assessment
            .missing
            .contains(QualificationCondition::ContactForcePressureAssessed));
    }

    #[test]
    fn independent_assessment_is_required_only_for_bounded_live_operation() {
        let supervised = required_evidence(DeploymentStage::SupervisedLowEnergyTrial);
        assert!(assess(supervised, DeploymentStage::SupervisedLowEnergyTrial).complete);
        let live = assess(supervised, DeploymentStage::BoundedLiveOperation);
        assert!(!live.complete);
        assert!(live
            .missing
            .contains(QualificationCondition::IndependentSafetyAssessment));
        assert!(live
            .missing
            .contains(QualificationCondition::PostUpdateRegressionPlan));
    }
}
