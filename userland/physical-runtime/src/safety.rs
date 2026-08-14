//! Independent physical safety supervisor.
//!
//! Deterministic interlocks are authoritative. Predictive evidence may add a
//! block or approval requirement only when its artifact has been validated for
//! gating; it can never remove an interlock or create execution authority.

use alloc::vec::Vec;

use crate::adapter::{
    AdapterCommand, AdapterError, AdapterRegistry, CommandKind, ExecutionPermit, RoutedCommand,
};
use crate::domain::{ActorId, ActorStatus, DomainRegistry, SiteId};
use crate::twin::OperationalTwin;

pub const MAX_SAFETY_POLICIES: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Geofence {
    pub minimum_x_mm: i64,
    pub maximum_x_mm: i64,
    pub minimum_y_mm: i64,
    pub maximum_y_mm: i64,
    pub minimum_z_mm: i64,
    pub maximum_z_mm: i64,
}

impl Geofence {
    fn contains(self, x_mm: i64, y_mm: i64, z_mm: i64) -> bool {
        x_mm >= self.minimum_x_mm
            && x_mm <= self.maximum_x_mm
            && y_mm >= self.minimum_y_mm
            && y_mm <= self.maximum_y_mm
            && z_mm >= self.minimum_z_mm
            && z_mm <= self.maximum_z_mm
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SafetyPolicy {
    pub site_id: SiteId,
    pub zone_id: u32,
    pub revision: u64,
    pub geofence: Geofence,
    pub proximity_sensor_id: Option<u64>,
    pub minimum_clearance_mm: i64,
    pub maximum_sensor_age_ticks: u64,
    pub permit_ttl_ticks: u64,
    pub allow_motion_with_humans: bool,
    pub require_human_approval_for_motion: bool,
    pub require_human_approval_for_actuation: bool,
    pub learned_warning_threshold_permille: u16,
    pub learned_block_threshold_permille: u16,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectKind {
    Observe,
    Actuate,
    Move,
    Stop,
    Inform,
    Acknowledge,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PredictionSource {
    StructuredRules,
    PhysicalJepa,
    HistoricalFailure,
    Simulator,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PhysicalPrediction {
    pub effect: EffectKind,
    pub risk_permille: u16,
    pub uncertainty_permille: u16,
    pub source: PredictionSource,
    pub model_version: u64,
    pub validated_for_gating: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SafetyContext {
    pub expected_policy_revision: u64,
    pub expected_twin_event_id: u64,
    pub human_approved: bool,
    pub requesting_actor_id: Option<ActorId>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum SafetyVerdict {
    Allow,
    RequireApproval,
    Block,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SafetyReason {
    NoPolicy,
    PolicyRevisionMismatch,
    TwinRevisionMismatch,
    InvalidPolicy,
    InvalidPrediction,
    GeofenceViolation,
    MissingProximitySensor,
    StaleProximitySensor,
    UnsafeProximity,
    HumanOccupiedZone,
    HumanApprovalRequired,
    ConfirmationProvenanceMismatch,
    EmergencyStoppedActor,
    PredictiveWarning,
    PredictiveBlock,
    PredictiveShadowOnly,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SafetyDecision {
    pub verdict: SafetyVerdict,
    pub policy_revision: u64,
    pub reasons: Vec<SafetyReason>,
    pub maximum_validated_risk_permille: u16,
    pub maximum_shadow_risk_permille: u16,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SafetyError {
    InvalidPolicy,
    PolicyRollback,
    CapacityExceeded,
    UnknownAdapter,
    UnknownEndpoint,
    Blocked,
    ApprovalRequired,
    Adapter(AdapterError),
}

#[derive(Debug, Default)]
pub struct SafetySupervisor {
    policies: Vec<SafetyPolicy>,
}

impl SafetySupervisor {
    pub const fn new() -> Self {
        Self {
            policies: Vec::new(),
        }
    }

    pub fn install_policy(&mut self, policy: SafetyPolicy) -> Result<(), SafetyError> {
        validate_policy(policy)?;
        if let Some(existing) = self.policies.iter_mut().find(|existing| {
            existing.site_id == policy.site_id && existing.zone_id == policy.zone_id
        }) {
            if policy.revision <= existing.revision {
                return Err(SafetyError::PolicyRollback);
            }
            *existing = policy;
            return Ok(());
        }
        if self.policies.len() >= MAX_SAFETY_POLICIES {
            return Err(SafetyError::CapacityExceeded);
        }
        self.policies.push(policy);
        Ok(())
    }

    pub fn evaluate(
        &self,
        adapters: &AdapterRegistry,
        domain: &DomainRegistry,
        twin: &OperationalTwin,
        command: &AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
    ) -> Result<SafetyDecision, SafetyError> {
        let adapter = adapters
            .adapter(command.adapter_id)
            .ok_or(SafetyError::UnknownAdapter)?;
        let endpoint = adapters
            .endpoint(command.endpoint_id)
            .ok_or(SafetyError::UnknownEndpoint)?;

        let metadata = command.metadata;
        let confirmation_matches =
            context.human_approved == metadata.confirmation.is_human_verified();
        if metadata.expected_policy_revision != context.expected_policy_revision {
            return Ok(blocked_decision(
                context.expected_policy_revision,
                SafetyReason::PolicyRevisionMismatch,
            ));
        }
        if metadata.expected_twin_event_id != context.expected_twin_event_id {
            return Ok(blocked_decision(
                context.expected_policy_revision,
                SafetyReason::TwinRevisionMismatch,
            ));
        }
        if !confirmation_matches {
            return Ok(blocked_decision(
                context.expected_policy_revision,
                SafetyReason::ConfirmationProvenanceMismatch,
            ));
        }

        // Emergency stop must not depend on a model, fresh telemetry, or an
        // installed zone policy. Transport/session checks still occur when the
        // resulting permit reaches the adapter registry.
        if command.kind == CommandKind::Stop {
            return Ok(SafetyDecision {
                verdict: SafetyVerdict::Allow,
                policy_revision: context.expected_policy_revision,
                reasons: Vec::new(),
                maximum_validated_risk_permille: 0,
                maximum_shadow_risk_permille: 0,
            });
        }

        let policy =
            match self.policies.iter().find(|policy| {
                policy.site_id == adapter.site_id && policy.zone_id == endpoint.zone_id
            }) {
                Some(policy) => policy,
                None => {
                    return Ok(blocked_decision(0, SafetyReason::NoPolicy));
                }
            };

        let mut decision = SafetyDecision {
            verdict: SafetyVerdict::Allow,
            policy_revision: policy.revision,
            reasons: Vec::new(),
            maximum_validated_risk_permille: 0,
            maximum_shadow_risk_permille: 0,
        };

        if context.expected_policy_revision != policy.revision {
            add_reason(
                &mut decision,
                SafetyVerdict::Block,
                SafetyReason::PolicyRevisionMismatch,
            );
        }
        if context.expected_twin_event_id != twin.snapshot().latest_event_id {
            add_reason(
                &mut decision,
                SafetyVerdict::Block,
                SafetyReason::TwinRevisionMismatch,
            );
        }
        if endpoint
            .controlled_actor_id
            .and_then(|actor_id| domain.actor(actor_id))
            .is_some_and(|actor| actor.status == ActorStatus::EmergencyStop)
        {
            add_reason(
                &mut decision,
                SafetyVerdict::Block,
                SafetyReason::EmergencyStoppedActor,
            );
        }

        if command.kind == CommandKind::MoveTo {
            if !policy
                .geofence
                .contains(command.argument0, command.argument1, command.argument2)
            {
                add_reason(
                    &mut decision,
                    SafetyVerdict::Block,
                    SafetyReason::GeofenceViolation,
                );
            }

            match policy.proximity_sensor_id {
                Some(sensor_id) => {
                    if !twin.sensor_is_fresh(
                        sensor_id,
                        current_tick,
                        policy.maximum_sensor_age_ticks,
                    ) {
                        add_reason(
                            &mut decision,
                            SafetyVerdict::Block,
                            SafetyReason::StaleProximitySensor,
                        );
                    } else if twin
                        .sensor(sensor_id)
                        .is_some_and(|reading| reading.value < policy.minimum_clearance_mm)
                    {
                        add_reason(
                            &mut decision,
                            SafetyVerdict::Block,
                            SafetyReason::UnsafeProximity,
                        );
                    }
                }
                None => add_reason(
                    &mut decision,
                    SafetyVerdict::Block,
                    SafetyReason::MissingProximitySensor,
                ),
            }

            if twin
                .occupancy(policy.site_id, policy.zone_id)
                .is_some_and(|occupancy| occupancy.humans > 0)
                && !policy.allow_motion_with_humans
            {
                add_reason(
                    &mut decision,
                    SafetyVerdict::Block,
                    SafetyReason::HumanOccupiedZone,
                );
            }
            if policy.require_human_approval_for_motion && !context.human_approved {
                add_reason(
                    &mut decision,
                    SafetyVerdict::RequireApproval,
                    SafetyReason::HumanApprovalRequired,
                );
            }
        }

        if command.kind == CommandKind::SetOutput
            && policy.require_human_approval_for_actuation
            && !context.human_approved
        {
            add_reason(
                &mut decision,
                SafetyVerdict::RequireApproval,
                SafetyReason::HumanApprovalRequired,
            );
        }

        for prediction in predictions {
            if prediction.risk_permille > 1_000 || prediction.uncertainty_permille > 1_000 {
                add_reason(
                    &mut decision,
                    SafetyVerdict::Block,
                    SafetyReason::InvalidPrediction,
                );
                continue;
            }
            if prediction.validated_for_gating {
                decision.maximum_validated_risk_permille = decision
                    .maximum_validated_risk_permille
                    .max(prediction.risk_permille);
                if prediction.risk_permille >= policy.learned_block_threshold_permille {
                    add_reason(
                        &mut decision,
                        SafetyVerdict::Block,
                        SafetyReason::PredictiveBlock,
                    );
                } else if prediction.risk_permille >= policy.learned_warning_threshold_permille {
                    add_reason(
                        &mut decision,
                        SafetyVerdict::RequireApproval,
                        SafetyReason::PredictiveWarning,
                    );
                }
            } else {
                decision.maximum_shadow_risk_permille = decision
                    .maximum_shadow_risk_permille
                    .max(prediction.risk_permille);
                if prediction.risk_permille >= policy.learned_warning_threshold_permille {
                    decision.reasons.push(SafetyReason::PredictiveShadowOnly);
                }
            }
        }

        Ok(decision)
    }

    pub fn authorize_and_route(
        &self,
        adapters: &mut AdapterRegistry,
        domain: &DomainRegistry,
        twin: &OperationalTwin,
        command: AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
    ) -> Result<RoutedCommand, SafetyError> {
        let decision = self.evaluate(
            adapters,
            domain,
            twin,
            &command,
            context,
            predictions,
            current_tick,
        )?;
        match decision.verdict {
            SafetyVerdict::Block => return Err(SafetyError::Blocked),
            SafetyVerdict::RequireApproval => return Err(SafetyError::ApprovalRequired),
            SafetyVerdict::Allow => {}
        }
        let policy_ttl = self
            .policies
            .iter()
            .find(|policy| policy.revision == decision.policy_revision)
            .map_or(1, |policy| policy.permit_ttl_ticks);
        let expires_at_tick = current_tick
            .saturating_add(policy_ttl)
            .min(command.deadline_tick);
        adapters
            .route_authorized(
                command,
                ExecutionPermit::new(
                    command.command_id,
                    expires_at_tick,
                    decision.policy_revision,
                    context.expected_twin_event_id,
                    command.metadata.confirmation,
                ),
                current_tick,
            )
            .map_err(SafetyError::Adapter)
    }
}

fn validate_policy(policy: SafetyPolicy) -> Result<(), SafetyError> {
    let valid_bounds = policy.geofence.minimum_x_mm <= policy.geofence.maximum_x_mm
        && policy.geofence.minimum_y_mm <= policy.geofence.maximum_y_mm
        && policy.geofence.minimum_z_mm <= policy.geofence.maximum_z_mm;
    if policy.revision == 0
        || policy.permit_ttl_ticks == 0
        || policy.minimum_clearance_mm < 0
        || policy.learned_warning_threshold_permille > policy.learned_block_threshold_permille
        || policy.learned_block_threshold_permille > 1_000
        || !valid_bounds
    {
        return Err(SafetyError::InvalidPolicy);
    }
    Ok(())
}

fn blocked_decision(policy_revision: u64, reason: SafetyReason) -> SafetyDecision {
    SafetyDecision {
        verdict: SafetyVerdict::Block,
        policy_revision,
        reasons: alloc::vec![reason],
        maximum_validated_risk_permille: 0,
        maximum_shadow_risk_permille: 0,
    }
}

fn add_reason(decision: &mut SafetyDecision, verdict: SafetyVerdict, reason: SafetyReason) {
    decision.verdict = decision.verdict.max(verdict);
    if !decision.reasons.contains(&reason) {
        decision.reasons.push(reason);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{
        AdapterId, AdapterIdentity, AdapterProtocol, AdapterState, Endpoint, EndpointCapability,
        EndpointCapabilitySet, EndpointId, EndpointKind,
    };
    use crate::contract::{CommandMetadata, ConfirmationProvenance, ObservationMetadata};
    use crate::domain::{
        Actor, ActorKind, CapabilitySet, DomainRegistry, Position, QualificationSet, Site,
    };
    use crate::twin::{EventEnvelope, EventPayload, SensorKind, SensorReading, ZoneOccupancy};
    use alloc::string::ToString;

    fn setup() -> (DomainRegistry, AdapterRegistry, OperationalTwin) {
        let mut domain = DomainRegistry::new();
        domain
            .register_site(Site {
                id: SiteId(1),
                name: "Plant".to_string(),
                emergency_zone_id: 99,
            })
            .unwrap();
        domain
            .register_actor(Actor {
                id: ActorId(8),
                name: "Robot".to_string(),
                kind: ActorKind::Robot,
                status: ActorStatus::Available,
                site_id: SiteId(1),
                position: Position::origin(7, 0),
                capabilities: CapabilitySet::empty(),
                qualifications: QualificationSet::empty(),
                available_from_tick: 0,
                last_seen_tick: 0,
                battery_permille: 1_000,
                load_permille: 0,
                max_payload_grams: 1_000,
            })
            .unwrap();
        let mut adapters = AdapterRegistry::new();
        adapters
            .register_adapter(AdapterIdentity {
                id: AdapterId(1),
                site_id: SiteId(1),
                protocol: AdapterProtocol::Simulator,
                public_key_sha256: [7; 32],
                firmware_version: 1,
                session_epoch: 5,
                state: AdapterState::Online,
                last_seen_tick: 0,
                last_receive_sequence: 0,
            })
            .unwrap();
        adapters
            .register_endpoint(Endpoint {
                id: EndpointId(2),
                adapter_id: AdapterId(1),
                kind: EndpointKind::Robot,
                zone_id: 7,
                controlled_actor_id: Some(ActorId(8)),
                capabilities: EndpointCapabilitySet::empty()
                    .with(EndpointCapability::Move)
                    .with(EndpointCapability::EmergencyStop),
            })
            .unwrap();
        (domain, adapters, OperationalTwin::new())
    }

    fn policy() -> SafetyPolicy {
        SafetyPolicy {
            site_id: SiteId(1),
            zone_id: 7,
            revision: 1,
            geofence: Geofence {
                minimum_x_mm: -1_000,
                maximum_x_mm: 1_000,
                minimum_y_mm: -1_000,
                maximum_y_mm: 1_000,
                minimum_z_mm: 0,
                maximum_z_mm: 2_000,
            },
            proximity_sensor_id: Some(9),
            minimum_clearance_mm: 500,
            maximum_sensor_age_ticks: 10,
            permit_ttl_ticks: 5,
            allow_motion_with_humans: true,
            require_human_approval_for_motion: false,
            require_human_approval_for_actuation: true,
            learned_warning_threshold_permille: 600,
            learned_block_threshold_permille: 800,
        }
    }

    fn motion(key: u64, twin: &OperationalTwin) -> AdapterCommand {
        AdapterCommand {
            command_id: 10,
            idempotency_key: key,
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 5,
            kind: CommandKind::MoveTo,
            argument0: 100,
            argument1: 200,
            argument2: 0,
            deadline_tick: 200,
            metadata: CommandMetadata::kernel(
                100,
                1,
                twin.snapshot().latest_event_id,
                EndpointCapability::Move,
                ConfirmationProvenance::LocalHuman {
                    confirmation_id: key,
                },
            ),
        }
    }

    fn prime_twin(domain: &mut DomainRegistry, twin: &mut OperationalTwin) {
        twin.apply(
            domain,
            EventEnvelope {
                event_id: 1,
                source_id: 9,
                source_sequence: 1,
                observed_at_tick: 100,
                received_at_tick: 100,
                metadata: ObservationMetadata::simulated(1, 110),
                payload: EventPayload::SensorReading(SensorReading {
                    sensor_id: 9,
                    site_id: SiteId(1),
                    asset_id: None,
                    kind: SensorKind::ProximityMillimeters,
                    value: 900,
                    quality_permille: 1_000,
                    observed_at_tick: 100,
                }),
            },
            0,
        )
        .unwrap();
    }

    fn context(twin: &OperationalTwin) -> SafetyContext {
        SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: twin.snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        }
    }

    #[test]
    fn motion_without_policy_fails_closed() {
        let (_domain, adapters, twin) = setup();
        let decision = SafetySupervisor::new()
            .evaluate(
                &adapters,
                &_domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[],
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::NoPolicy));
    }

    #[test]
    fn geofence_and_stale_sensor_are_independent_blocks() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let mut command = motion(1, &twin);
        command.argument0 = 5_000;
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &command,
                context(&twin),
                &[],
                111,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::GeofenceViolation));
        assert!(decision
            .reasons
            .contains(&SafetyReason::StaleProximitySensor));
    }

    #[test]
    fn shadow_prediction_cannot_block_a_safe_command() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let prediction = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 999,
            uncertainty_permille: 100,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: false,
        };
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[prediction],
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Allow);
        assert_eq!(decision.maximum_shadow_risk_permille, 999);
        assert!(decision
            .reasons
            .contains(&SafetyReason::PredictiveShadowOnly));
    }

    #[test]
    fn validated_prediction_can_only_add_caution() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let prediction = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 900,
            uncertainty_permille: 100,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: true,
        };
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[prediction],
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::PredictiveBlock));
    }

    #[test]
    fn twin_revision_prevents_time_of_check_time_of_use() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let mut stale_context = context(&twin);
        stale_context.expected_twin_event_id = 0;
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                stale_context,
                &[],
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision
            .reasons
            .contains(&SafetyReason::TwinRevisionMismatch));
    }

    #[test]
    fn unproven_confirmation_cannot_set_human_approved() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let mut command = motion(1, &twin);
        command.metadata.confirmation = ConfirmationProvenance::NotRequired;
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &command,
                context(&twin),
                &[],
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision
            .reasons
            .contains(&SafetyReason::ConfirmationProvenanceMismatch));
    }

    #[test]
    fn approved_command_receives_single_use_route() {
        let (mut domain, mut adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let routed = supervisor
            .authorize_and_route(
                &mut adapters,
                &domain,
                &twin,
                motion(77, &twin),
                context(&twin),
                &[],
                100,
            )
            .unwrap();
        assert_eq!(routed.policy_revision, 1);
        assert_eq!(
            supervisor.authorize_and_route(
                &mut adapters,
                &domain,
                &twin,
                motion(77, &twin),
                context(&twin),
                &[],
                100,
            ),
            Err(SafetyError::Adapter(AdapterError::DuplicateCommand))
        );
    }

    #[test]
    fn stop_does_not_depend_on_sensor_or_model_availability() {
        let (_domain, mut adapters, twin) = setup();
        let supervisor = SafetySupervisor::new();
        let mut command = motion(5, &twin);
        command.kind = CommandKind::Stop;
        command.metadata = CommandMetadata::kernel(
            100,
            0,
            0,
            EndpointCapability::EmergencyStop,
            ConfirmationProvenance::NotRequired,
        );
        let routed = supervisor
            .authorize_and_route(
                &mut adapters,
                &_domain,
                &twin,
                command,
                SafetyContext {
                    expected_policy_revision: 0,
                    expected_twin_event_id: 0,
                    human_approved: false,
                    requesting_actor_id: None,
                },
                &[],
                100,
            )
            .unwrap();
        assert_eq!(routed.command.kind, CommandKind::Stop);
    }

    #[test]
    fn human_occupancy_can_block_motion() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        twin.apply(
            &mut domain,
            EventEnvelope {
                event_id: 2,
                source_id: 10,
                source_sequence: 1,
                observed_at_tick: 100,
                received_at_tick: 100,
                metadata: ObservationMetadata::simulated(2, 110),
                payload: EventPayload::ZoneOccupancy(ZoneOccupancy {
                    site_id: SiteId(1),
                    zone_id: 7,
                    humans: 1,
                    robots: 1,
                    observed_at_tick: 100,
                }),
            },
            0,
        )
        .unwrap();
        let mut supervisor = SafetySupervisor::new();
        let mut strict = policy();
        strict.allow_motion_with_humans = false;
        supervisor.install_policy(strict).unwrap();
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[],
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::HumanOccupiedZone));
    }

    #[test]
    fn policy_revisions_cannot_roll_back() {
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        assert_eq!(
            supervisor.install_policy(policy()),
            Err(SafetyError::PolicyRollback)
        );
    }

    #[test]
    fn emergency_stopped_actor_cannot_receive_non_stop_commands() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        domain.actor_mut(ActorId(8)).unwrap().status = ActorStatus::EmergencyStop;
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();

        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[],
                100,
            )
            .unwrap();

        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision
            .reasons
            .contains(&SafetyReason::EmergencyStoppedActor));
    }

    #[test]
    fn malformed_prediction_fails_closed_without_becoming_policy_error() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let prediction = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 1_001,
            uncertainty_permille: 0,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: true,
        };

        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[prediction],
                100,
            )
            .unwrap();

        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::InvalidPrediction));
        assert!(!decision.reasons.contains(&SafetyReason::InvalidPolicy));
    }
}
