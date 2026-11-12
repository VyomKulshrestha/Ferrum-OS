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
use crate::twin::{OperationalTwin, SensorKind};

pub const MAX_SAFETY_POLICIES: usize = 128;
pub const MAX_PHYSICAL_PREDICTIONS: usize = 32;

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
    /// Longest move a single permit may cover, measured from the controlled actor's last
    /// tracked position. With it, a clearance reading taken before the move bounds the
    /// clearance during the move (it can shrink by at most this much), and a target inside a
    /// convex geofence keeps the straight path inside. `None` keeps the target-only checks.
    /// (Same field as on the `vision-world-model` branch, commit 090e8a2.)
    pub maximum_step_mm: Option<i64>,
    pub maximum_sensor_age_ticks: u64,
    /// Oldest zone-occupancy record that still counts when humans are not allowed. With
    /// `allow_motion_with_humans == false`, a zone with no occupancy record, or with one
    /// observed more than this many ticks ago, blocks motion (fi2 O1: a feed that is absent
    /// or has silently stopped no longer reads as "no humans").
    pub maximum_occupancy_age_ticks: u64,
    /// Battery and payload limits for the actor a MoveTo moves (fi2 O5). `None` checks
    /// nothing. With limits, the controlled actor's last telemetry must be fresh
    /// (`maximum_sensor_age_ticks`) and within them, or the move is blocked.
    pub operational_limits: Option<crate::supervisor::OperationalLimits>,
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

/// Runtime-owned disposition for learned physical predictions.
///
/// Model bytes are always decoded as shadow evidence. Only a simulation
/// session that has separately bound the exact model digest may request
/// `SimulationCaution`, and even then predictions can only raise severity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PredictionUse {
    ShadowOnly,
    SimulationCaution { model_version: u64 },
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
    MoveStepTooLong,
    StaleActorPosition,
    /// Humans not allowed and the zone has no occupancy record (fi2 O1).
    MissingOccupancy,
    /// Humans not allowed and the zone's occupancy record is older than
    /// `maximum_occupancy_age_ticks` (fi2 O1).
    StaleOccupancy,
    /// The moving actor's battery or payload is outside `operational_limits` (fi2 O5).
    OperationalLimitExceeded,
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
        self.evaluate_with_prediction_use(
            adapters,
            domain,
            twin,
            command,
            context,
            predictions,
            current_tick,
            PredictionUse::ShadowOnly,
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) fn evaluate_with_prediction_use(
        &self,
        adapters: &AdapterRegistry,
        domain: &DomainRegistry,
        twin: &OperationalTwin,
        command: &AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
        prediction_use: PredictionUse,
    ) -> Result<SafetyDecision, SafetyError> {
        if predictions.len() > MAX_PHYSICAL_PREDICTIONS {
            return Ok(blocked_decision(
                context.expected_policy_revision,
                SafetyReason::InvalidPrediction,
            ));
        }
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
        apply_deterministic_interlocks(
            policy,
            endpoint,
            domain,
            twin,
            command,
            current_tick,
            &mut decision,
        );
        if command.kind == CommandKind::MoveTo
            && policy.require_human_approval_for_motion
            && !context.human_approved
        {
            add_reason(
                &mut decision,
                SafetyVerdict::RequireApproval,
                SafetyReason::HumanApprovalRequired,
            );
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
            let simulation_caution = matches!(
                prediction_use,
                PredictionUse::SimulationCaution { model_version }
                    if prediction.source == PredictionSource::PhysicalJepa
                        && prediction.model_version == model_version
                        && !prediction.validated_for_gating
            );
            if simulation_caution {
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
                // A prediction may not self-promote through a serialized or
                // caller-supplied flag. Promotion belongs to the OS session.
                if prediction.validated_for_gating {
                    add_reason(
                        &mut decision,
                        SafetyVerdict::Block,
                        SafetyReason::InvalidPrediction,
                    );
                }
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

    /// Time-of-use re-check for a queued non-stop command. The permit was
    /// issued against an earlier twin state; between issue and delivery the
    /// actor may have been emergency-stopped, a human may have entered the
    /// zone, proximity may have closed, the zone policy may have changed, or
    /// the device may have left service. Any of these revokes the permit.
    /// Predictions are not re-run: they may only add caution and already did
    /// so at issue time.
    pub(crate) fn permits_delivery(
        &self,
        adapters: &AdapterRegistry,
        domain: &DomainRegistry,
        twin: &OperationalTwin,
        command: &AdapterCommand,
        permit_policy_revision: u64,
        current_tick: u64,
    ) -> bool {
        if command.kind == CommandKind::Stop {
            return true;
        }
        let Some(adapter) = adapters.adapter(command.adapter_id) else {
            return false;
        };
        let Some(endpoint) = adapters.endpoint(command.endpoint_id) else {
            return false;
        };
        if adapter.state != crate::adapter::AdapterState::Online
            || adapter.session_epoch != command.session_epoch
            || endpoint.adapter_id != command.adapter_id
        {
            return false;
        }
        let Some(policy) = self
            .policies
            .iter()
            .find(|policy| policy.site_id == adapter.site_id && policy.zone_id == endpoint.zone_id)
        else {
            return false;
        };
        if policy.revision != permit_policy_revision {
            return false;
        }
        let mut decision = SafetyDecision {
            verdict: SafetyVerdict::Allow,
            policy_revision: policy.revision,
            reasons: Vec::new(),
            maximum_validated_risk_permille: 0,
            maximum_shadow_risk_permille: 0,
        };
        apply_deterministic_interlocks(
            policy,
            endpoint,
            domain,
            twin,
            command,
            current_tick,
            &mut decision,
        );
        decision.verdict == SafetyVerdict::Allow
    }
}

/// Interlocks that depend only on current state (never on a model, the
/// caller's approval flag or predictions). Shared by issue-time evaluation and
/// the delivery-time re-check so the two cannot drift apart.
fn apply_deterministic_interlocks(
    policy: &SafetyPolicy,
    endpoint: &crate::adapter::Endpoint,
    domain: &DomainRegistry,
    twin: &OperationalTwin,
    command: &AdapterCommand,
    current_tick: u64,
    decision: &mut SafetyDecision,
) {
    if endpoint
        .controlled_actor_id
        .and_then(|actor_id| domain.actor(actor_id))
        .is_some_and(|actor| actor.status == ActorStatus::EmergencyStop)
    {
        add_reason(
            decision,
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
                decision,
                SafetyVerdict::Block,
                SafetyReason::GeofenceViolation,
            );
        }

        // The controlled actor, if its last telemetry is fresh. A registered but never
        // observed or stale actor gives `None`, and every check that needs it fails closed.
        let fresh_actor = endpoint
            .controlled_actor_id
            .and_then(|actor_id| domain.actor(actor_id))
            .filter(|actor| {
                current_tick >= actor.last_seen_tick
                    && current_tick - actor.last_seen_tick <= policy.maximum_sensor_age_ticks
            });

        if let Some(maximum_step_mm) = policy.maximum_step_mm {
            // The step is measured from a fresh tracked position or not at all.
            match fresh_actor {
                Some(actor) => {
                    let dx = i128::from(command.argument0) - i128::from(actor.position.x_mm);
                    let dy = i128::from(command.argument1) - i128::from(actor.position.y_mm);
                    let dz = i128::from(command.argument2) - i128::from(actor.position.z_mm);
                    if dx * dx + dy * dy + dz * dz
                        > i128::from(maximum_step_mm) * i128::from(maximum_step_mm)
                    {
                        add_reason(decision, SafetyVerdict::Block, SafetyReason::MoveStepTooLong);
                    }
                }
                None => add_reason(
                    decision,
                    SafetyVerdict::Block,
                    SafetyReason::StaleActorPosition,
                ),
            }
        }

        if let Some(limits) = policy.operational_limits {
            match fresh_actor {
                Some(actor) => {
                    let payload_grams = (u64::from(actor.load_permille)
                        * u64::from(actor.max_payload_grams)
                        / 1_000)
                        .min(u64::from(u32::MAX)) as u32;
                    // Speed has no field on AdapterCommand yet (reported open), and
                    // maintenance and qualification are checked at dispatch; only the
                    // battery and payload limits are decided here.
                    let state = crate::supervisor::ResourceSnapshot {
                        battery_permille: actor.battery_permille,
                        payload_grams,
                        requested_speed_mm_per_second: 0,
                        clock_uncertainty_ticks: 0,
                        maintenance_ready: true,
                        qualified: true,
                    };
                    if limits.evaluate(state) != crate::supervisor::AuthoritySeverity::Allow {
                        add_reason(
                            decision,
                            SafetyVerdict::Block,
                            SafetyReason::OperationalLimitExceeded,
                        );
                    }
                }
                None => add_reason(
                    decision,
                    SafetyVerdict::Block,
                    SafetyReason::StaleActorPosition,
                ),
            }
        }

        match policy.proximity_sensor_id {
            Some(sensor_id) => {
                if twin.sensor(sensor_id).is_some_and(|reading| {
                    reading.kind != SensorKind::ProximityMillimeters
                        || reading.site_id != policy.site_id
                }) {
                    add_reason(
                        decision,
                        SafetyVerdict::Block,
                        SafetyReason::MissingProximitySensor,
                    );
                } else if !twin.sensor_is_fresh(
                    sensor_id,
                    current_tick,
                    policy.maximum_sensor_age_ticks,
                ) {
                    add_reason(
                        decision,
                        SafetyVerdict::Block,
                        SafetyReason::StaleProximitySensor,
                    );
                } else if twin
                    .sensor(sensor_id)
                    .is_some_and(|reading| reading.value < policy.minimum_clearance_mm)
                {
                    add_reason(
                        decision,
                        SafetyVerdict::Block,
                        SafetyReason::UnsafeProximity,
                    );
                }
            }
            None => add_reason(
                decision,
                SafetyVerdict::Block,
                SafetyReason::MissingProximitySensor,
            ),
        }

        if !policy.allow_motion_with_humans {
            // fi2 O1: when humans are not allowed, "no record" and "old record" are not
            // evidence of an empty zone.
            match twin.occupancy(policy.site_id, policy.zone_id) {
                None => add_reason(
                    decision,
                    SafetyVerdict::Block,
                    SafetyReason::MissingOccupancy,
                ),
                Some(occupancy)
                    if current_tick < occupancy.observed_at_tick
                        || current_tick - occupancy.observed_at_tick
                            > policy.maximum_occupancy_age_ticks =>
                {
                    add_reason(
                        decision,
                        SafetyVerdict::Block,
                        SafetyReason::StaleOccupancy,
                    );
                    if occupancy.humans > 0 {
                        add_reason(
                            decision,
                            SafetyVerdict::Block,
                            SafetyReason::HumanOccupiedZone,
                        );
                    }
                }
                Some(occupancy) if occupancy.humans > 0 => add_reason(
                    decision,
                    SafetyVerdict::Block,
                    SafetyReason::HumanOccupiedZone,
                ),
                Some(_) => {}
            }
        }
    }
}

impl SafetySupervisor {
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
        // The TTL must come from the policy that was evaluated for this
        // command's site and zone, not from any policy sharing its revision.
        let policy_ttl = adapters
            .adapter(command.adapter_id)
            .zip(adapters.endpoint(command.endpoint_id))
            .and_then(|(adapter, endpoint)| {
                self.policies.iter().find(|policy| {
                    policy.site_id == adapter.site_id
                        && policy.zone_id == endpoint.zone_id
                        && policy.revision == decision.policy_revision
                })
            })
            .map_or(1, |policy| policy.permit_ttl_ticks);
        let expires_at_tick = current_tick
            .checked_add(policy_ttl)
            .ok_or(SafetyError::InvalidPolicy)?
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
        || policy.maximum_step_mm.is_some_and(|step| step <= 0)
        || policy.operational_limits.is_some_and(|limits| {
            limits.minimum_battery_permille > 1_000
                || limits.maximum_payload_grams == 0
                || limits.maximum_speed_mm_per_second == 0
        })
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
            maximum_step_mm: None,
            maximum_occupancy_age_ticks: 20,
            operational_limits: None,
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
    fn simulation_prediction_can_only_add_caution_when_os_authorizes_its_model_version() {
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
            validated_for_gating: false,
        };
        let decision = supervisor
            .evaluate_with_prediction_use(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &[prediction],
                100,
                PredictionUse::SimulationCaution { model_version: 1 },
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::PredictiveBlock));
    }

    #[test]
    fn caller_supplied_gating_flag_fails_closed() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let prediction = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 0,
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
    fn permit_ttl_comes_from_the_commands_own_zone_policy() {
        let (mut domain, mut adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        let mut other_zone = policy();
        other_zone.zone_id = 8;
        other_zone.permit_ttl_ticks = 1_000;
        supervisor.install_policy(other_zone).unwrap();
        supervisor.install_policy(policy()).unwrap();
        let routed = supervisor
            .authorize_and_route(
                &mut adapters,
                &domain,
                &twin,
                motion(1, &twin),
                context(&twin),
                &[],
                100,
            )
            .unwrap();
        assert_eq!(routed.permit_expires_at_tick, 105);
    }

    #[test]
    fn permit_expiry_overflow_fails_closed_and_deadline_caps_ttl() {
        let (mut domain, mut adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        let mut long_ttl = policy();
        long_ttl.permit_ttl_ticks = u64::MAX;
        long_ttl.maximum_sensor_age_ticks = u64::MAX;
        supervisor.install_policy(long_ttl).unwrap();
        let mut command = motion(1, &twin);
        command.deadline_tick = u64::MAX;
        assert_eq!(
            supervisor.authorize_and_route(
                &mut adapters,
                &domain,
                &twin,
                command,
                context(&twin),
                &[],
                100,
            ),
            Err(SafetyError::InvalidPolicy)
        );
        let mut short = motion(2, &twin);
        short.deadline_tick = 101;
        let mut normal = policy();
        normal.revision = 2;
        supervisor.install_policy(normal).unwrap();
        short.metadata.expected_policy_revision = 2;
        let mut ctx = context(&twin);
        ctx.expected_policy_revision = 2;
        let routed = supervisor
            .authorize_and_route(&mut adapters, &domain, &twin, short, ctx, &[], 100)
            .unwrap();
        assert_eq!(routed.permit_expires_at_tick, 101);
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
    fn o5_step_bound_and_operational_limits_must_be_valid() {
        let limits = crate::supervisor::OperationalLimits {
            minimum_battery_permille: 200,
            maximum_payload_grams: 500,
            maximum_speed_mm_per_second: 1_000,
            maximum_clock_uncertainty_ticks: 0,
        };
        let mut supervisor = SafetySupervisor::new();
        for bad in [
            SafetyPolicy { maximum_step_mm: Some(0), ..policy() },
            SafetyPolicy { maximum_step_mm: Some(-5), ..policy() },
            SafetyPolicy {
                operational_limits: Some(crate::supervisor::OperationalLimits {
                    minimum_battery_permille: 1_001,
                    ..limits
                }),
                ..policy()
            },
            SafetyPolicy {
                operational_limits: Some(crate::supervisor::OperationalLimits {
                    maximum_payload_grams: 0,
                    ..limits
                }),
                ..policy()
            },
        ] {
            assert_eq!(supervisor.install_policy(bad), Err(SafetyError::InvalidPolicy));
        }
        assert_eq!(
            supervisor.install_policy(SafetyPolicy {
                maximum_step_mm: Some(1),
                operational_limits: Some(limits),
                ..policy()
            }),
            Ok(())
        );
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

    fn sensor_event(event_id: u64, sequence: u64, reading: SensorReading) -> EventEnvelope {
        EventEnvelope {
            event_id,
            source_id: 9,
            source_sequence: sequence,
            observed_at_tick: reading.observed_at_tick,
            received_at_tick: reading.observed_at_tick,
            metadata: ObservationMetadata::simulated(event_id, reading.observed_at_tick + 10),
            payload: EventPayload::SensorReading(reading),
        }
    }

    fn proximity_reading(value: i64, observed_at_tick: u64) -> SensorReading {
        SensorReading {
            sensor_id: 9,
            site_id: SiteId(1),
            asset_id: None,
            kind: SensorKind::ProximityMillimeters,
            value,
            quality_permille: 1_000,
            observed_at_tick,
        }
    }

    #[test]
    fn non_proximity_or_foreign_site_reading_cannot_satisfy_clearance() {
        let mut wrong_kind = proximity_reading(25_000, 100);
        wrong_kind.kind = SensorKind::TemperatureMilliCelsius;
        let mut foreign_site = proximity_reading(900, 100);
        foreign_site.site_id = SiteId(2);
        for reading in [wrong_kind, foreign_site] {
            let (mut domain, adapters, mut twin) = setup();
            domain
                .register_site(Site {
                    id: SiteId(2),
                    name: "Other".to_string(),
                    emergency_zone_id: 98,
                })
                .unwrap();
            twin.apply(&mut domain, sensor_event(1, 1, reading), 0)
                .unwrap();
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
                .contains(&SafetyReason::MissingProximitySensor));
        }
    }

    #[test]
    fn prediction_input_is_bounded_before_iteration() {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let prediction = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 0,
            uncertainty_permille: 0,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: false,
        };
        let predictions = alloc::vec![prediction; MAX_PHYSICAL_PREDICTIONS + 1];
        let decision = supervisor
            .evaluate(
                &adapters,
                &domain,
                &twin,
                &motion(1, &twin),
                context(&twin),
                &predictions,
                100,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert_eq!(
            decision.reasons,
            alloc::vec![SafetyReason::InvalidPrediction]
        );
    }

    fn primed_supervisor() -> (
        DomainRegistry,
        AdapterRegistry,
        OperationalTwin,
        SafetySupervisor,
    ) {
        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        (domain, adapters, twin, supervisor)
    }

    fn decide(
        parts: &(
            DomainRegistry,
            AdapterRegistry,
            OperationalTwin,
            SafetySupervisor,
        ),
        command: &AdapterCommand,
        predictions: &[PhysicalPrediction],
        tick: u64,
        prediction_use: PredictionUse,
    ) -> SafetyDecision {
        let (domain, adapters, twin, supervisor) = parts;
        supervisor
            .evaluate_with_prediction_use(
                adapters,
                domain,
                twin,
                command,
                context(twin),
                predictions,
                tick,
                prediction_use,
            )
            .unwrap()
    }

    #[test]
    fn geofence_bounds_are_inclusive_and_extreme_targets_block() {
        let parts = primed_supervisor();
        let fence = policy().geofence;
        let inside = [
            (fence.minimum_x_mm, fence.minimum_y_mm, fence.minimum_z_mm),
            (fence.maximum_x_mm, fence.maximum_y_mm, fence.maximum_z_mm),
            (0, 0, 0),
        ];
        for (x, y, z) in inside {
            let mut command = motion(1, &parts.2);
            (command.argument0, command.argument1, command.argument2) = (x, y, z);
            let decision = decide(&parts, &command, &[], 100, PredictionUse::ShadowOnly);
            assert_eq!(decision.verdict, SafetyVerdict::Allow, "{x},{y},{z}");
        }
        let outside = [
            (fence.minimum_x_mm - 1, 0, 0),
            (fence.maximum_x_mm + 1, 0, 0),
            (0, fence.minimum_y_mm - 1, 0),
            (0, fence.maximum_y_mm + 1, 0),
            (0, 0, fence.minimum_z_mm - 1),
            (0, 0, fence.maximum_z_mm + 1),
            (i64::MIN, 0, 0),
            (i64::MAX, 0, 0),
            (0, i64::MIN, 0),
            (0, i64::MAX, 0),
            (0, 0, i64::MIN),
            (0, 0, i64::MAX),
        ];
        for (x, y, z) in outside {
            let mut command = motion(1, &parts.2);
            (command.argument0, command.argument1, command.argument2) = (x, y, z);
            let decision = decide(&parts, &command, &[], 100, PredictionUse::ShadowOnly);
            assert_eq!(decision.verdict, SafetyVerdict::Block, "{x},{y},{z}");
            assert!(decision.reasons.contains(&SafetyReason::GeofenceViolation));
        }
    }

    #[test]
    fn clearance_at_the_minimum_is_allowed_and_anything_below_blocks() {
        for (value, expected) in [
            (500, SafetyVerdict::Allow),
            (i64::MAX, SafetyVerdict::Allow),
            (499, SafetyVerdict::Block),
            (0, SafetyVerdict::Block),
            (-1, SafetyVerdict::Block),
            (i64::MIN, SafetyVerdict::Block),
        ] {
            let (mut domain, adapters, mut twin) = setup();
            twin.apply(
                &mut domain,
                sensor_event(1, 1, proximity_reading(value, 100)),
                0,
            )
            .unwrap();
            let mut supervisor = SafetySupervisor::new();
            supervisor.install_policy(policy()).unwrap();
            let parts = (domain, adapters, twin, supervisor);
            let decision = decide(
                &parts,
                &motion(1, &parts.2),
                &[],
                100,
                PredictionUse::ShadowOnly,
            );
            assert_eq!(decision.verdict, expected, "clearance {value}");
            assert_eq!(
                decision.reasons.contains(&SafetyReason::UnsafeProximity),
                expected == SafetyVerdict::Block
            );
        }
    }

    #[test]
    fn sensor_age_is_inclusive_at_the_bound_and_clock_rollback_is_stale() {
        let parts = primed_supervisor();
        // prime_twin observes at tick 100; the policy allows age 10.
        for (tick, fresh) in [
            (100, true),
            (110, true),
            (111, false),
            (99, false),
            (u64::MAX, false),
        ] {
            let decision = decide(
                &parts,
                &motion(1, &parts.2),
                &[],
                tick,
                PredictionUse::ShadowOnly,
            );
            assert_eq!(
                decision.verdict == SafetyVerdict::Allow,
                fresh,
                "tick {tick}"
            );
            assert_eq!(
                decision
                    .reasons
                    .contains(&SafetyReason::StaleProximitySensor),
                !fresh,
                "tick {tick}"
            );
        }
    }

    #[test]
    fn missing_sensor_and_unconfigured_sensor_block_motion() {
        let (domain, adapters, twin) = setup();
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(policy()).unwrap();
        let parts = (domain, adapters, twin, supervisor);
        let decision = decide(
            &parts,
            &motion(1, &parts.2),
            &[],
            100,
            PredictionUse::ShadowOnly,
        );
        assert_eq!(decision.verdict, SafetyVerdict::Block);

        let (mut domain, adapters, mut twin) = setup();
        prime_twin(&mut domain, &mut twin);
        let mut no_sensor = policy();
        no_sensor.proximity_sensor_id = None;
        let mut supervisor = SafetySupervisor::new();
        supervisor.install_policy(no_sensor).unwrap();
        let parts = (domain, adapters, twin, supervisor);
        let decision = decide(
            &parts,
            &motion(1, &parts.2),
            &[],
            100,
            PredictionUse::ShadowOnly,
        );
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision
            .reasons
            .contains(&SafetyReason::MissingProximitySensor));
    }

    fn jepa(risk_permille: u16, uncertainty_permille: u16) -> PhysicalPrediction {
        PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille,
            uncertainty_permille,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: false,
        }
    }

    #[test]
    fn caution_thresholds_are_inclusive_and_only_ever_add_severity() {
        let parts = primed_supervisor();
        let caution = PredictionUse::SimulationCaution { model_version: 1 };
        // policy(): warning 600, block 800.
        for (risk, expected) in [
            (0, SafetyVerdict::Allow),
            (599, SafetyVerdict::Allow),
            (600, SafetyVerdict::RequireApproval),
            (799, SafetyVerdict::RequireApproval),
            (800, SafetyVerdict::Block),
            (1_000, SafetyVerdict::Block),
        ] {
            let decision = decide(&parts, &motion(1, &parts.2), &[jepa(risk, 0)], 100, caution);
            assert_eq!(decision.verdict, expected, "risk {risk}");
        }
        for (risk, uncertainty) in [(1_001, 0), (0, 1_001), (u16::MAX, u16::MAX)] {
            let decision = decide(
                &parts,
                &motion(1, &parts.2),
                &[jepa(risk, uncertainty)],
                100,
                caution,
            );
            assert_eq!(decision.verdict, SafetyVerdict::Block);
            assert!(decision.reasons.contains(&SafetyReason::InvalidPrediction));
        }
        // A zero-risk caution prediction cannot lift a deterministic block.
        let mut outside = motion(1, &parts.2);
        outside.argument0 = 5_000;
        let decision = decide(&parts, &outside, &[jepa(0, 0)], 100, caution);
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        // A low-risk caution prediction cannot lift an approval requirement.
        let mut actuation = motion(1, &parts.2);
        actuation.kind = CommandKind::SetOutput;
        let (domain, adapters, twin, supervisor) = &parts;
        let mut unapproved = context(twin);
        unapproved.human_approved = false;
        actuation.metadata.confirmation = ConfirmationProvenance::NotRequired;
        let decision = supervisor
            .evaluate_with_prediction_use(
                adapters,
                domain,
                twin,
                &actuation,
                unapproved,
                &[jepa(0, 0)],
                100,
                caution,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::RequireApproval);
        assert!(decision
            .reasons
            .contains(&SafetyReason::HumanApprovalRequired));
    }

    #[test]
    fn caution_from_a_different_model_or_source_stays_shadow_only() {
        let parts = primed_supervisor();
        let caution = PredictionUse::SimulationCaution { model_version: 1 };
        let mut other_version = jepa(1_000, 0);
        other_version.model_version = 2;
        let mut other_source = jepa(1_000, 0);
        other_source.source = PredictionSource::Simulator;
        for prediction in [other_version, other_source] {
            let decision = decide(&parts, &motion(1, &parts.2), &[prediction], 100, caution);
            assert_eq!(decision.verdict, SafetyVerdict::Allow);
            assert!(decision
                .reasons
                .contains(&SafetyReason::PredictiveShadowOnly));
            assert_eq!(decision.maximum_validated_risk_permille, 0);
        }
        let predictions = alloc::vec![jepa(0, 0); MAX_PHYSICAL_PREDICTIONS];
        let decision = decide(&parts, &motion(1, &parts.2), &predictions, 100, caution);
        assert_eq!(decision.verdict, SafetyVerdict::Allow);
    }

    #[test]
    fn policy_validation_rejects_each_malformed_bound() {
        let mut supervisor = SafetySupervisor::new();
        let mutations: [fn(&mut SafetyPolicy); 8] = [
            |p| p.revision = 0,
            |p| p.permit_ttl_ticks = 0,
            |p| p.minimum_clearance_mm = -1,
            |p| p.learned_warning_threshold_permille = 801,
            |p| p.learned_block_threshold_permille = 1_001,
            |p| p.geofence.minimum_x_mm = p.geofence.maximum_x_mm + 1,
            |p| p.geofence.minimum_y_mm = p.geofence.maximum_y_mm + 1,
            |p| p.geofence.minimum_z_mm = p.geofence.maximum_z_mm + 1,
        ];
        for mutate in mutations {
            let mut invalid = policy();
            mutate(&mut invalid);
            assert_eq!(
                supervisor.install_policy(invalid),
                Err(SafetyError::InvalidPolicy)
            );
        }
        let mut edge = policy();
        edge.learned_warning_threshold_permille = 1_000;
        edge.learned_block_threshold_permille = 1_000;
        edge.geofence.minimum_x_mm = edge.geofence.maximum_x_mm;
        edge.minimum_clearance_mm = 0;
        assert_eq!(supervisor.install_policy(edge), Ok(()));
        let mut newer = policy();
        newer.revision = u64::MAX;
        assert_eq!(supervisor.install_policy(newer), Ok(()));
        assert_eq!(
            supervisor.install_policy(policy()),
            Err(SafetyError::PolicyRollback)
        );
    }

    #[test]
    fn unknown_adapter_or_endpoint_is_an_error_not_an_allow() {
        let parts = primed_supervisor();
        let (domain, adapters, twin, supervisor) = &parts;
        let mut command = motion(1, twin);
        command.adapter_id = AdapterId(99);
        assert_eq!(
            supervisor.evaluate(adapters, domain, twin, &command, context(twin), &[], 100),
            Err(SafetyError::UnknownAdapter)
        );
        let mut command = motion(1, twin);
        command.endpoint_id = EndpointId(99);
        assert_eq!(
            supervisor.evaluate(adapters, domain, twin, &command, context(twin), &[], 100),
            Err(SafetyError::UnknownEndpoint)
        );
    }
}
