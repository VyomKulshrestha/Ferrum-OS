//! Simulator-backed maintenance vertical used for integration and evaluation.

use alloc::string::ToString;
use alloc::vec;
use alloc::vec::Vec;

use crate::adapter::{
    AdapterCommand, AdapterError, AdapterFrame, AdapterId, AdapterIdentity, AdapterPayload,
    AdapterProtocol, AdapterRegistry, AdapterState, CommandKind, Endpoint, EndpointCapability,
    EndpointCapabilitySet, EndpointId, EndpointKind, SimulatedAdapter,
};
use crate::contract::{CommandMetadata, ConfirmationProvenance, ObservationMetadata};
use crate::domain::{
    Actor, ActorId, ActorKind, ActorStatus, Asset, AssetId, AssetState, Capability, CapabilitySet,
    DomainError, Position, Qualification, QualificationSet, Site, SiteId,
};
use crate::fleet::{DeviceHealth, DeviceLifecycle, FleetDevice, FleetError};
use crate::privacy::{
    DataAccessRequest, DataKind, PrivacyError, ProcessingPurpose, Representation, RetentionPolicy,
    TenantId,
};
use crate::reliability::ReliabilitySnapshot;
use crate::runtime::{PhysicalRuntime, RuntimeError};
use crate::safety::{
    EffectKind, Geofence, PhysicalPrediction, PredictionSource, SafetyContext, SafetyError,
    SafetyPolicy, SafetyVerdict,
};
use crate::session::{EvidenceKind, SessionDescriptor};
use crate::twin::{AssetTelemetry, SensorKind, SensorReading};
use crate::work::{
    ActorConstraint, DispatchError, JobId, JobState, Priority, TaskId, TaskStatus, WorkOrder,
    WorkTask,
};

pub const MAINTENANCE_SITE_ID: SiteId = SiteId(1);
pub const MAINTENANCE_ASSET_ID: AssetId = AssetId(50);
pub const MAINTENANCE_JOB_ID: JobId = JobId(100);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MaintenanceDemoReport {
    pub job_completed: bool,
    pub assigned_actors: Vec<ActorId>,
    pub approval_was_enforced: bool,
    pub unsafe_motion_blocked: bool,
    pub safe_motion_delivered: bool,
    pub delivered_policy_revision: u64,
    pub unsafe_shadow_risk_permille: u16,
    pub safe_shadow_risk_permille: u16,
    pub final_asset_state: AssetState,
    pub privacy_representation: Representation,
    pub reliability: ReliabilitySnapshot,
    pub retained_twin_events: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SimulationCautionDemoReport {
    pub rules_only_allowed: bool,
    pub shadow_only_allowed: bool,
    pub rules_plus_jepa_blocked: bool,
    pub rejected_command_received_permit: bool,
    pub bounded_safe_command_delivered: bool,
    pub risky_prediction_permille: u16,
    pub safe_prediction_permille: u16,
    pub evidence_records: usize,
    pub evidence_checksum: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MaintenanceDemoError {
    Domain(DomainError),
    Adapter(AdapterError),
    Fleet(FleetError),
    Privacy(PrivacyError),
    Runtime(RuntimeError),
    Invariant,
}

pub fn run_maintenance_demo() -> Result<MaintenanceDemoReport, MaintenanceDemoError> {
    let unsafe_prediction = PhysicalPrediction {
        effect: EffectKind::Move,
        risk_permille: 950,
        uncertainty_permille: 300,
        source: PredictionSource::Simulator,
        model_version: 1,
        validated_for_gating: false,
    };
    let safe_prediction = PhysicalPrediction {
        risk_permille: 0,
        ..unsafe_prediction
    };
    run_maintenance_demo_with_predictions(unsafe_prediction, safe_prediction)
}

pub fn run_maintenance_demo_with_predictions(
    unsafe_prediction: PhysicalPrediction,
    safe_prediction: PhysicalPrediction,
) -> Result<MaintenanceDemoReport, MaintenanceDemoError> {
    let (mut runtime, mut driver) = build_runtime()?;
    runtime
        .submit_work_order(maintenance_order())
        .map_err(MaintenanceDemoError::Runtime)?;

    runtime
        .ingest_adapter_frame(proximity_frame(1, 100, 100), 100, 0)
        .map_err(MaintenanceDemoError::Runtime)?;
    if unsafe_prediction.validated_for_gating || safe_prediction.validated_for_gating {
        return Err(MaintenanceDemoError::Invariant);
    }
    let blocked_context = current_context(&runtime);
    let unsafe_motion_blocked = runtime.authorize_and_queue_command(
        motion_command(1, 1_001, blocked_context, 100),
        blocked_context,
        &[unsafe_prediction],
        100,
    ) == Err(RuntimeError::Safety(SafetyError::Blocked));

    runtime
        .ingest_adapter_frame(proximity_frame(2, 900, 101), 101, 0)
        .map_err(MaintenanceDemoError::Runtime)?;
    let safe_context = current_context(&runtime);
    let preview = runtime
        .preview_command(
            &motion_command(2, 1_002, safe_context, 101),
            safe_context,
            &[safe_prediction],
            101,
        )
        .map_err(MaintenanceDemoError::Runtime)?;
    if preview.verdict != SafetyVerdict::Allow
        || preview.maximum_shadow_risk_permille != safe_prediction.risk_permille
    {
        return Err(MaintenanceDemoError::Invariant);
    }
    let routed = runtime
        .authorize_and_queue_command(
            motion_command(2, 1_002, safe_context, 101),
            safe_context,
            &[safe_prediction],
            101,
        )
        .map_err(MaintenanceDemoError::Runtime)?;
    let delivered = runtime
        .deliver_next(AdapterId(1), &mut driver, 101)
        .map_err(MaintenanceDemoError::Runtime)?;
    let safe_motion_delivered = delivered == Some(routed) && driver.commands().len() == 1;

    let mut assignments = Vec::new();
    let mut approval_was_enforced = false;
    let mut tick = 110;
    for task_number in 1..=5 {
        let receipt = runtime
            .dispatch_next(tick, 1_000)
            .map_err(MaintenanceDemoError::Runtime)?;
        assignments.push(receipt.actor_id);
        let requires_approval = task_number == 3;
        if requires_approval {
            approval_was_enforced = runtime.start_task(receipt, receipt.revision, false, tick)
                == Err(RuntimeError::Dispatch(DispatchError::HumanApprovalRequired));
        }
        let running_revision = runtime
            .start_task(
                receipt,
                receipt.revision,
                requires_approval,
                tick.saturating_add(1),
            )
            .map_err(MaintenanceDemoError::Runtime)?;
        runtime
            .complete_task(receipt, running_revision, 10, tick.saturating_add(10))
            .map_err(MaintenanceDemoError::Runtime)?;
        tick = tick.saturating_add(20);
    }

    // The simulator reports the repaired asset state; the runtime does not
    // directly mutate the twin to manufacture a successful outcome.
    runtime
        .ingest_adapter_frame(asset_frame(3, AssetState::Operational, tick), tick, 0)
        .map_err(MaintenanceDemoError::Runtime)?;

    let privacy_representation = runtime
        .evaluate_data_access(
            DataAccessRequest {
                request_id: 1,
                tenant_id: TenantId(7),
                site_id: MAINTENANCE_SITE_ID,
                subject_actor_id: None,
                data_kind: DataKind::OperationalTelemetry,
                purpose: ProcessingPurpose::Maintenance,
                raw_content_requested: false,
                observed_at_tick: tick,
            },
            tick,
        )
        .representation;

    let order = runtime
        .work()
        .order(MAINTENANCE_JOB_ID)
        .ok_or(MaintenanceDemoError::Invariant)?;
    let final_asset_state = runtime
        .domain()
        .asset(MAINTENANCE_ASSET_ID)
        .ok_or(MaintenanceDemoError::Invariant)?
        .state;
    let reliability = runtime
        .reliability()
        .snapshot(MAINTENANCE_SITE_ID)
        .map_err(|error| MaintenanceDemoError::Runtime(RuntimeError::Reliability(error)))?;

    Ok(MaintenanceDemoReport {
        job_completed: order.state == JobState::Completed,
        assigned_actors: assignments,
        approval_was_enforced,
        unsafe_motion_blocked,
        safe_motion_delivered,
        delivered_policy_revision: routed.policy_revision,
        unsafe_shadow_risk_permille: unsafe_prediction.risk_permille,
        safe_shadow_risk_permille: preview.maximum_shadow_risk_permille,
        final_asset_state,
        privacy_representation,
        reliability,
        retained_twin_events: runtime.twin().snapshot().retained_events,
    })
}

/// Exercises the promoted learned-caution path without weakening physical
/// authority. The same safe present-state command is evaluated under rules,
/// shadow JEPA, and the session-bound combined policy. A risky learned rollout
/// may block only the simulator command; a rejected command receives no permit.
pub fn run_simulation_caution_demo(
    risky_prediction: PhysicalPrediction,
    safe_prediction: PhysicalPrediction,
    model_sha256: [u8; 32],
) -> Result<SimulationCautionDemoReport, MaintenanceDemoError> {
    if risky_prediction.validated_for_gating
        || safe_prediction.validated_for_gating
        || risky_prediction.source != PredictionSource::PhysicalJepa
        || safe_prediction.source != PredictionSource::PhysicalJepa
        || risky_prediction.model_version == 0
        || risky_prediction.model_version != safe_prediction.model_version
    {
        return Err(MaintenanceDemoError::Invariant);
    }
    let mut descriptor = SessionDescriptor::simulator(2, 1, 42);
    descriptor.model_sha256 = model_sha256;
    let (mut runtime, mut driver) = build_runtime_with_session(descriptor)?;
    runtime
        .ingest_adapter_frame(proximity_frame(1, 900, 100), 100, 0)
        .map_err(MaintenanceDemoError::Runtime)?;
    let context = current_context(&runtime);

    let rules_only = runtime
        .preview_command(&motion_command(10, 2_010, context, 100), context, &[], 100)
        .map_err(MaintenanceDemoError::Runtime)?;
    let shadow_only = runtime
        .preview_command(
            &motion_command(11, 2_011, context, 100),
            context,
            &[risky_prediction],
            100,
        )
        .map_err(MaintenanceDemoError::Runtime)?;
    let grant = runtime
        .simulation_caution_grant(model_sha256, risky_prediction.model_version)
        .map_err(MaintenanceDemoError::Runtime)?;
    let combined = runtime
        .preview_command_with_simulation_caution(
            &motion_command(12, 2_012, context, 100),
            context,
            &[risky_prediction],
            100,
            grant,
        )
        .map_err(MaintenanceDemoError::Runtime)?;
    let permits_before = runtime
        .evidence()
        .records()
        .iter()
        .filter(|record| record.kind == EvidenceKind::PermitIssued)
        .count();
    let rejected = runtime.authorize_and_queue_command_with_simulation_caution(
        motion_command(13, 2_013, context, 100),
        context,
        &[risky_prediction],
        100,
        grant,
    ) == Err(RuntimeError::Safety(SafetyError::Blocked));
    let permits_after_rejection = runtime
        .evidence()
        .records()
        .iter()
        .filter(|record| record.kind == EvidenceKind::PermitIssued)
        .count();

    let safe_context = current_context(&runtime);
    let routed = runtime
        .authorize_and_queue_command_with_simulation_caution(
            motion_command(14, 2_014, safe_context, 100),
            safe_context,
            &[safe_prediction],
            100,
            grant,
        )
        .map_err(MaintenanceDemoError::Runtime)?;
    let delivered = runtime
        .deliver_next(AdapterId(1), &mut driver, 100)
        .map_err(MaintenanceDemoError::Runtime)?;
    let report = SimulationCautionDemoReport {
        rules_only_allowed: rules_only.verdict == SafetyVerdict::Allow,
        shadow_only_allowed: shadow_only.verdict == SafetyVerdict::Allow,
        rules_plus_jepa_blocked: rejected && combined.verdict == SafetyVerdict::Block,
        rejected_command_received_permit: permits_after_rejection != permits_before,
        bounded_safe_command_delivered: delivered == Some(routed) && driver.commands().len() == 1,
        risky_prediction_permille: risky_prediction.risk_permille,
        safe_prediction_permille: safe_prediction.risk_permille,
        evidence_records: runtime.evidence().records().len(),
        evidence_checksum: runtime.evidence().final_checksum(),
    };
    if !report.rules_only_allowed
        || !report.shadow_only_allowed
        || !report.rules_plus_jepa_blocked
        || report.rejected_command_received_permit
        || !report.bounded_safe_command_delivered
        || runtime.evidence().verify().is_err()
    {
        return Err(MaintenanceDemoError::Invariant);
    }
    Ok(report)
}

fn build_runtime() -> Result<(PhysicalRuntime, SimulatedAdapter), MaintenanceDemoError> {
    build_runtime_with_session(SessionDescriptor::simulator(1, 1, 42))
}

fn build_runtime_with_session(
    descriptor: SessionDescriptor,
) -> Result<(PhysicalRuntime, SimulatedAdapter), MaintenanceDemoError> {
    let mut runtime =
        PhysicalRuntime::new_with_session(descriptor).map_err(MaintenanceDemoError::Runtime)?;
    runtime
        .domain_mut()
        .register_site(Site {
            id: MAINTENANCE_SITE_ID,
            name: "Maintenance Plant".to_string(),
            emergency_zone_id: 99,
        })
        .map_err(MaintenanceDemoError::Domain)?;
    runtime
        .domain_mut()
        .register_asset(Asset {
            id: MAINTENANCE_ASSET_ID,
            name: "Cooling Pump".to_string(),
            site_id: MAINTENANCE_SITE_ID,
            position: Position::origin(7, 100),
            state: AssetState::Degraded,
            last_service_tick: 0,
        })
        .map_err(MaintenanceDemoError::Domain)?;
    for actor in maintenance_actors() {
        runtime
            .domain_mut()
            .register_actor(actor)
            .map_err(MaintenanceDemoError::Domain)?;
    }

    let identity = AdapterIdentity {
        id: AdapterId(1),
        site_id: MAINTENANCE_SITE_ID,
        protocol: AdapterProtocol::Simulator,
        public_key_sha256: [7; 32],
        firmware_version: 1,
        session_epoch: 5,
        state: AdapterState::Online,
        last_seen_tick: 100,
        last_receive_sequence: 0,
    };
    runtime
        .adapters_mut()
        .register_adapter(identity.clone())
        .map_err(MaintenanceDemoError::Adapter)?;
    register_endpoints(runtime.adapters_mut())?;
    runtime
        .fleet_mut()
        .provision(FleetDevice {
            adapter_id: AdapterId(1),
            site_id: MAINTENANCE_SITE_ID,
            identity_sha256: identity.public_key_sha256,
            lifecycle: DeviceLifecycle::Provisioning,
            firmware_version: 1,
            minimum_allowed_firmware_version: 1,
            session_epoch: 5,
            last_seen_tick: 100,
            health: DeviceHealth {
                battery_permille: 900,
                link_quality_permille: 900,
                fault_code: 0,
            },
        })
        .map_err(MaintenanceDemoError::Fleet)?;
    runtime
        .fleet_mut()
        .activate(AdapterId(1), 5, 100)
        .map_err(MaintenanceDemoError::Fleet)?;
    runtime
        .safety_mut()
        .install_policy(SafetyPolicy {
            site_id: MAINTENANCE_SITE_ID,
            zone_id: 7,
            revision: 1,
            geofence: Geofence {
                minimum_x_mm: -2_000,
                maximum_x_mm: 2_000,
                minimum_y_mm: -2_000,
                maximum_y_mm: 2_000,
                minimum_z_mm: 0,
                maximum_z_mm: 2_000,
            },
            proximity_sensor_id: Some(9),
            minimum_clearance_mm: 500,
            maximum_sensor_age_ticks: 20,
            permit_ttl_ticks: 5,
            allow_motion_with_humans: false,
            require_human_approval_for_motion: false,
            require_human_approval_for_actuation: true,
            learned_warning_threshold_permille: 600,
            learned_block_threshold_permille: 800,
        })
        .map_err(|error| MaintenanceDemoError::Runtime(RuntimeError::Safety(error)))?;
    runtime
        .privacy_mut()
        .bind_site(TenantId(7), MAINTENANCE_SITE_ID)
        .map_err(MaintenanceDemoError::Privacy)?;
    runtime
        .privacy_mut()
        .install_retention_policy(RetentionPolicy {
            data_kind: DataKind::OperationalTelemetry,
            purpose: ProcessingPurpose::Maintenance,
            maximum_age_ticks: 1_000,
            retain_raw_content: false,
        })
        .map_err(MaintenanceDemoError::Privacy)?;
    let driver = SimulatedAdapter::new(identity).map_err(MaintenanceDemoError::Adapter)?;
    Ok((runtime, driver))
}

fn register_endpoints(adapters: &mut AdapterRegistry) -> Result<(), MaintenanceDemoError> {
    adapters
        .register_endpoint(Endpoint {
            id: EndpointId(2),
            adapter_id: AdapterId(1),
            kind: EndpointKind::Robot,
            zone_id: 7,
            controlled_actor_id: Some(ActorId(10)),
            capabilities: EndpointCapabilitySet::empty()
                .with(EndpointCapability::Sense)
                .with(EndpointCapability::Move)
                .with(EndpointCapability::EmergencyStop),
        })
        .map_err(MaintenanceDemoError::Adapter)?;
    adapters
        .register_endpoint(Endpoint {
            id: EndpointId(3),
            adapter_id: AdapterId(1),
            kind: EndpointKind::Sensor,
            zone_id: 7,
            controlled_actor_id: None,
            capabilities: EndpointCapabilitySet::empty().with(EndpointCapability::Sense),
        })
        .map_err(MaintenanceDemoError::Adapter)
}

fn maintenance_actors() -> [Actor; 3] {
    [
        Actor {
            id: ActorId(10),
            name: "Inspection Robot".to_string(),
            kind: ActorKind::Robot,
            status: ActorStatus::Available,
            site_id: MAINTENANCE_SITE_ID,
            position: Position::origin(7, 100),
            capabilities: CapabilitySet::empty()
                .with(Capability::Inspect)
                .with(Capability::Navigate),
            qualifications: QualificationSet::empty().with(Qualification::SiteInduction),
            available_from_tick: 0,
            last_seen_tick: 100,
            battery_permille: 900,
            load_permille: 0,
            max_payload_grams: 2_000,
        },
        Actor {
            id: ActorId(20),
            name: "Diagnostic Agent".to_string(),
            kind: ActorKind::Agent,
            status: ActorStatus::Available,
            site_id: MAINTENANCE_SITE_ID,
            position: Position::origin(7, 100),
            capabilities: CapabilitySet::empty()
                .with(Capability::Diagnose)
                .with(Capability::ExecuteDigital),
            qualifications: QualificationSet::empty().with(Qualification::SiteInduction),
            available_from_tick: 0,
            last_seen_tick: 100,
            battery_permille: 1_000,
            load_permille: 0,
            max_payload_grams: 0,
        },
        Actor {
            id: ActorId(30),
            name: "Maintenance Technician".to_string(),
            kind: ActorKind::Human,
            status: ActorStatus::Available,
            site_id: MAINTENANCE_SITE_ID,
            position: Position::origin(7, 100),
            capabilities: CapabilitySet::empty()
                .with(Capability::Approve)
                .with(Capability::Repair),
            qualifications: QualificationSet::empty()
                .with(Qualification::SiteInduction)
                .with(Qualification::Mechanical)
                .with(Qualification::SafetySupervisor),
            available_from_tick: 0,
            last_seen_tick: 100,
            battery_permille: 1_000,
            load_permille: 0,
            max_payload_grams: 20_000,
        },
    ]
}

fn maintenance_order() -> WorkOrder {
    let base = |id, dependencies, constraint, capability, qualification, approval| WorkTask {
        id: TaskId(id),
        dependencies,
        status: TaskStatus::Pending,
        actor_constraint: constraint,
        required_capabilities: CapabilitySet::empty().with(capability),
        required_qualifications: QualificationSet::empty().with(qualification),
        zone_id: 7,
        minimum_battery_permille: 200,
        payload_grams: 0,
        estimated_duration_ticks: 10,
        requires_human_approval: approval,
    };
    WorkOrder {
        id: MAINTENANCE_JOB_ID,
        asset_id: MAINTENANCE_ASSET_ID,
        site_id: MAINTENANCE_SITE_ID,
        priority: Priority::Urgent,
        deadline_tick: 1_000,
        state: JobState::Pending,
        revision: 0,
        tasks: vec![
            base(
                1,
                vec![],
                ActorConstraint::Robot,
                Capability::Inspect,
                Qualification::SiteInduction,
                false,
            ),
            base(
                2,
                vec![TaskId(1)],
                ActorConstraint::Agent,
                Capability::Diagnose,
                Qualification::SiteInduction,
                false,
            ),
            base(
                3,
                vec![TaskId(2)],
                ActorConstraint::Human,
                Capability::Approve,
                Qualification::SafetySupervisor,
                true,
            ),
            base(
                4,
                vec![TaskId(3)],
                ActorConstraint::Human,
                Capability::Repair,
                Qualification::Mechanical,
                false,
            ),
            base(
                5,
                vec![TaskId(4)],
                ActorConstraint::Robot,
                Capability::Inspect,
                Qualification::SiteInduction,
                false,
            ),
        ],
    }
}

fn proximity_frame(sequence: u64, clearance: i64, tick: u64) -> AdapterFrame {
    AdapterFrame {
        adapter_id: AdapterId(1),
        endpoint_id: EndpointId(2),
        session_epoch: 5,
        sequence,
        observed_at_tick: tick,
        metadata: ObservationMetadata::simulated(sequence, tick.saturating_add(10)),
        payload: AdapterPayload::SensorReading(SensorReading {
            sensor_id: 9,
            site_id: MAINTENANCE_SITE_ID,
            asset_id: Some(MAINTENANCE_ASSET_ID),
            kind: SensorKind::ProximityMillimeters,
            value: clearance,
            quality_permille: 1_000,
            observed_at_tick: tick,
        }),
    }
}

fn asset_frame(sequence: u64, state: AssetState, tick: u64) -> AdapterFrame {
    AdapterFrame {
        adapter_id: AdapterId(1),
        endpoint_id: EndpointId(3),
        session_epoch: 5,
        sequence,
        observed_at_tick: tick,
        metadata: ObservationMetadata::simulated(sequence, tick.saturating_add(10)),
        payload: AdapterPayload::AssetTelemetry(AssetTelemetry {
            asset_id: MAINTENANCE_ASSET_ID,
            state,
            position: Position::origin(7, tick),
        }),
    }
}

fn motion_command(
    command_id: u64,
    idempotency_key: u64,
    context: SafetyContext,
    issued_at_tick: u64,
) -> AdapterCommand {
    AdapterCommand {
        command_id,
        idempotency_key,
        adapter_id: AdapterId(1),
        endpoint_id: EndpointId(2),
        session_epoch: 5,
        kind: CommandKind::MoveTo,
        argument0: 100,
        argument1: 100,
        argument2: 0,
        deadline_tick: 200,
        metadata: CommandMetadata::kernel(
            issued_at_tick,
            context.expected_policy_revision,
            context.expected_twin_event_id,
            EndpointCapability::Move,
            ConfirmationProvenance::LocalHuman {
                confirmation_id: command_id,
            },
        ),
    }
}

fn current_context(runtime: &PhysicalRuntime) -> SafetyContext {
    SafetyContext {
        expected_policy_revision: 1,
        expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
        human_approved: true,
        requesting_actor_id: Some(ActorId(20)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maintenance_vertical_runs_across_robot_agent_and_human() {
        let report = run_maintenance_demo().unwrap();
        assert!(report.job_completed);
        assert_eq!(
            report.assigned_actors,
            vec![
                ActorId(10),
                ActorId(20),
                ActorId(30),
                ActorId(30),
                ActorId(10)
            ]
        );
        assert!(report.approval_was_enforced);
        assert!(report.unsafe_motion_blocked);
        assert!(report.safe_motion_delivered);
        assert_eq!(report.delivered_policy_revision, 1);
        assert_eq!(report.unsafe_shadow_risk_permille, 950);
        assert_eq!(report.safe_shadow_risk_permille, 0);
        assert_eq!(report.final_asset_state, AssetState::Operational);
        assert_eq!(report.privacy_representation, Representation::Aggregate);
        assert_eq!(report.reliability.task_attempts, 5);
        assert_eq!(report.reliability.task_successes, 5);
        assert_eq!(report.reliability.safety_interventions, 1);
        assert!(report.retained_twin_events >= 13);
    }

    #[test]
    fn simulator_caution_changes_only_the_combined_verdict_and_never_mints_a_rejected_permit() {
        let risky = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 900,
            uncertainty_permille: 20,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: false,
        };
        let safe = PhysicalPrediction {
            risk_permille: 0,
            ..risky
        };
        let report = run_simulation_caution_demo(risky, safe, [9; 32]).unwrap();
        assert!(report.rules_only_allowed);
        assert!(report.shadow_only_allowed);
        assert!(report.rules_plus_jepa_blocked);
        assert!(!report.rejected_command_received_permit);
        assert!(report.bounded_safe_command_delivered);
        assert!(report.evidence_records > 0);
        assert_ne!(report.evidence_checksum, 0);
    }
}
