//! Single-owner orchestration boundary for physical operations.
//!
//! The runtime composes scheduling, the twin, safety, privacy, fleet delivery,
//! and reliability under one mutable owner. This prevents a preview/execute race
//! inside one operation and makes cross-service sequencing explicit.

use crate::adapter::{
    AdapterCommand, AdapterDriver, AdapterError, AdapterFrame, AdapterId, AdapterRegistry,
    AdapterState, DriverExecutionMode, RoutedCommand,
};
use crate::contract::ObservationPolicy;
use crate::domain::{DomainRegistry, SiteId};
use crate::experience::{ExperienceError, PhysicalExperienceBuffer, PhysicalOutcome};
use crate::fleet::{CommandDeliveryState, DeviceHealth, DeviceLifecycle, FleetError, FleetManager};
use crate::model::{PhysicalAction, PhysicalState};
use crate::privacy::{DataAccessRequest, PrivacyDecision, PrivacyGuard};
use crate::reliability::{
    ReliabilityError, ReliabilityEvent, ReliabilityEventKind, ReliabilityMonitor,
};
use crate::replay::{
    FaultController, FrameDisposition, ReplayAction, ReplayError, ReplayOutcome, ReplayStep,
};
use crate::safety::{
    PhysicalPrediction, PredictionUse, SafetyContext, SafetyDecision, SafetyError, SafetyReason,
    SafetySupervisor, SafetyVerdict,
};
use crate::session::{EvidenceKind, EvidenceLog, SessionDescriptor, SessionError, SessionMode};
use crate::supervisor::{
    AuthoritySeverity, CommandRateLimiter, RecoveryLatch, SupervisorError, WatchdogBank,
    WatchdogState,
};
use crate::twin::{EventPayload, OperationalTwin, TwinError};
use crate::work::{DispatchError, DispatchReceipt, JobId, WorkGraph, WorkGraphError, WorkOrder};

const RUNTIME_TWIN_SOURCE_ID: u64 = u64::MAX - 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeError {
    UnknownSite,
    UnknownAsset,
    AssetSiteMismatch,
    InvalidWorkOrder,
    WorkGraph(WorkGraphError),
    Dispatch(DispatchError),
    Twin(TwinError),
    Safety(SafetyError),
    Fleet(FleetError),
    Adapter(AdapterError),
    Reliability(ReliabilityError),
    Experience(ExperienceError),
    DeliveryUncertain(AdapterError),
    Session(SessionError),
    Replay(ReplayError),
    DriverModeMismatch,
    DeploymentUnqualified,
    Supervisor(SupervisorError),
    SimulationCautionUnavailable,
    SequenceExhausted,
}

/// An OS-owned, session-bound capability to let one exact JEPA checkpoint add
/// caution in simulation. It cannot be constructed from model bytes and it is
/// revalidated against the runtime session before every use.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SimulationCautionGrant {
    run_id: u64,
    model_sha256: [u8; 32],
    model_version: u64,
}

#[derive(Debug)]
pub struct PhysicalRuntime {
    domain: DomainRegistry,
    work: WorkGraph,
    twin: OperationalTwin,
    adapters: AdapterRegistry,
    safety: SafetySupervisor,
    fleet: FleetManager,
    privacy: PrivacyGuard,
    reliability: ReliabilityMonitor,
    experience: PhysicalExperienceBuffer,
    evidence: EvidenceLog,
    faults: FaultController,
    watchdogs: WatchdogBank,
    command_rate: CommandRateLimiter,
    recovery: RecoveryLatch,
    runtime_twin_sequence: u64,
    reliability_event_id: u64,
}

impl Default for PhysicalRuntime {
    fn default() -> Self {
        Self::new()
    }
}

impl PhysicalRuntime {
    pub fn new() -> Self {
        Self::new_with_session(SessionDescriptor::simulator(1, 1, 42))
            .expect("built-in simulator session descriptor is valid")
    }

    pub fn new_with_session(descriptor: SessionDescriptor) -> Result<Self, RuntimeError> {
        let mut twin = OperationalTwin::new();
        // The empty twin always has room. Reserving before any adapter traffic
        // prevents hostile source exhaustion from disabling work/safety records.
        let reserved = twin.reserve_source(RUNTIME_TWIN_SOURCE_ID);
        debug_assert!(reserved.is_ok());
        Ok(Self {
            domain: DomainRegistry::new(),
            work: WorkGraph::new(),
            twin,
            adapters: AdapterRegistry::new(),
            safety: SafetySupervisor::new(),
            fleet: FleetManager::new(),
            privacy: PrivacyGuard::new(),
            reliability: ReliabilityMonitor::new(),
            experience: PhysicalExperienceBuffer::new(),
            evidence: EvidenceLog::new(descriptor).map_err(RuntimeError::Session)?,
            faults: FaultController::new(),
            watchdogs: WatchdogBank::new(),
            command_rate: CommandRateLimiter::new(100, 16).map_err(RuntimeError::Supervisor)?,
            recovery: RecoveryLatch::default(),
            runtime_twin_sequence: 0,
            reliability_event_id: 0,
        })
    }

    pub fn domain(&self) -> &DomainRegistry {
        &self.domain
    }

    pub fn domain_mut(&mut self) -> &mut DomainRegistry {
        &mut self.domain
    }

    pub fn work(&self) -> &WorkGraph {
        &self.work
    }

    pub fn twin(&self) -> &OperationalTwin {
        &self.twin
    }

    pub fn adapters(&self) -> &AdapterRegistry {
        &self.adapters
    }

    pub fn adapters_mut(&mut self) -> &mut AdapterRegistry {
        &mut self.adapters
    }

    pub fn safety(&self) -> &SafetySupervisor {
        &self.safety
    }

    pub fn safety_mut(&mut self) -> &mut SafetySupervisor {
        &mut self.safety
    }

    pub fn fleet(&self) -> &FleetManager {
        &self.fleet
    }

    pub fn fleet_mut(&mut self) -> &mut FleetManager {
        &mut self.fleet
    }

    pub fn privacy(&self) -> &PrivacyGuard {
        &self.privacy
    }

    pub fn privacy_mut(&mut self) -> &mut PrivacyGuard {
        &mut self.privacy
    }

    pub fn reliability(&self) -> &ReliabilityMonitor {
        &self.reliability
    }

    pub fn experience(&self) -> &PhysicalExperienceBuffer {
        &self.experience
    }

    pub fn evidence(&self) -> &EvidenceLog {
        &self.evidence
    }

    pub fn simulation_caution_grant(
        &self,
        model_sha256: [u8; 32],
        model_version: u64,
    ) -> Result<SimulationCautionGrant, RuntimeError> {
        let descriptor = self.evidence.descriptor();
        if descriptor.mode != SessionMode::Simulation
            || model_version == 0
            || model_sha256.iter().all(|byte| *byte == 0)
            || descriptor.model_sha256 != model_sha256
        {
            return Err(RuntimeError::SimulationCautionUnavailable);
        }
        Ok(SimulationCautionGrant {
            run_id: descriptor.run_id,
            model_sha256,
            model_version,
        })
    }

    pub fn register_watchdog(&mut self, watchdog: WatchdogState) -> Result<(), RuntimeError> {
        self.watchdogs
            .register(watchdog)
            .map_err(RuntimeError::Supervisor)
    }

    pub fn heartbeat_watchdog(&mut self, id: u64, tick: u64) -> Result<(), RuntimeError> {
        // A heartbeat that arrives after an emergency-stop expiry restores
        // liveness only; the stop stays latched until recovery is released.
        if self.watchdogs.severity(tick) == AuthoritySeverity::EmergencyStop {
            self.latch_emergency_stop();
        }
        self.watchdogs
            .heartbeat(id, tick)
            .map_err(RuntimeError::Supervisor)
    }

    pub fn authority_severity(&self, tick: u64) -> AuthoritySeverity {
        self.watchdogs.severity(tick)
    }

    pub fn recovery_mut(&mut self) -> &mut RecoveryLatch {
        &mut self.recovery
    }

    pub fn faults(&self) -> &FaultController {
        &self.faults
    }

    pub fn record_resolved_intent(
        &mut self,
        tick: u64,
        intent_id: u64,
        source_kind: u64,
        action_kind: u64,
    ) -> Result<(), RuntimeError> {
        self.evidence
            .append(
                tick,
                EvidenceKind::IntentResolved,
                intent_id,
                source_kind,
                action_kind,
                0,
                0,
            )
            .map(|_| ())
            .map_err(RuntimeError::Session)
    }

    pub fn record_operator_action(
        &mut self,
        tick: u64,
        action_id: u64,
        action_kind: u64,
    ) -> Result<(), RuntimeError> {
        self.evidence
            .append(
                tick,
                EvidenceKind::OperatorAction,
                action_id,
                action_kind,
                0,
                0,
                0,
            )
            .map(|_| ())
            .map_err(RuntimeError::Session)
    }

    /// Records a telemetry-confirmed transition or an explicitly non-executed
    /// outcome. Callers cannot label predicted states as observed training data.
    pub fn record_model_experience(
        &mut self,
        observed_at_tick: u64,
        before: PhysicalState,
        action: PhysicalAction,
        after: Option<PhysicalState>,
        outcome: PhysicalOutcome,
        reward: f32,
    ) -> Result<u64, RuntimeError> {
        self.experience
            .record(observed_at_tick, before, action, after, outcome, reward)
            .map_err(RuntimeError::Experience)
    }

    pub fn submit_work_order(&mut self, order: WorkOrder) -> Result<(), RuntimeError> {
        let asset = self
            .domain
            .asset(order.asset_id)
            .ok_or(RuntimeError::UnknownAsset)?;
        if self.domain.site(order.site_id).is_none() {
            return Err(RuntimeError::UnknownSite);
        }
        if asset.site_id != order.site_id {
            return Err(RuntimeError::AssetSiteMismatch);
        }
        if order.revision != 0 || order.deadline_tick == 0 {
            return Err(RuntimeError::InvalidWorkOrder);
        }
        self.work.add_order(order).map_err(RuntimeError::WorkGraph)
    }

    pub fn ingest_adapter_frame(
        &mut self,
        frame: AdapterFrame,
        received_at_tick: u64,
        maximum_clock_skew_ticks: u64,
    ) -> Result<u64, RuntimeError> {
        self.ingest_adapter_frame_with_policy(
            frame,
            received_at_tick,
            ObservationPolicy::strict(maximum_clock_skew_ticks),
        )
    }

    pub fn ingest_adapter_frame_with_policy(
        &mut self,
        frame: AdapterFrame,
        received_at_tick: u64,
        observation_policy: ObservationPolicy,
    ) -> Result<u64, RuntimeError> {
        self.evidence
            .reserve_at(received_at_tick, 1)
            .map_err(RuntimeError::Session)?;
        let frame_id = frame.metadata.frame_id;
        let evidence_class = frame.metadata.evidence_class as u64;
        let adapter_id = frame.adapter_id.0;
        let endpoint_id = frame.endpoint_id.0;
        let event_id = self
            .adapters
            .ingest_frame_with_policy(
                &mut self.twin,
                &mut self.domain,
                frame,
                received_at_tick,
                observation_policy,
            )
            .map_err(RuntimeError::Adapter)?;
        self.evidence
            .append(
                received_at_tick,
                EvidenceKind::ObservationAccepted,
                adapter_id,
                event_id,
                endpoint_id,
                frame_id,
                evidence_class,
            )
            .map_err(RuntimeError::Session)?;
        Ok(event_id)
    }

    pub fn apply_replay_step(&mut self, step: ReplayStep) -> Result<ReplayOutcome, RuntimeError> {
        let descriptor = self.evidence.descriptor();
        if step.run_id != descriptor.run_id {
            return Err(RuntimeError::Replay(ReplayError::RunMismatch));
        }
        // Replay and fault injection are simulation tooling: a hand-built
        // step gets the same validation as a manifest step and never runs live.
        if descriptor.mode == SessionMode::Live {
            return Err(RuntimeError::Replay(ReplayError::InvalidDescriptor));
        }
        crate::replay::validate_action(descriptor.mode, step.at_tick, step.action)
            .map_err(RuntimeError::Replay)?;
        self.faults.expire_before(step.at_tick);
        match step.action {
            ReplayAction::IngestFrame {
                frame,
                received_at_tick,
                observation_policy,
            } => match self
                .faults
                .transform_frame(frame, received_at_tick, step.at_tick)
            {
                FrameDisposition::Deliver {
                    frame,
                    received_at_tick,
                } => self
                    .ingest_adapter_frame_with_policy(frame, received_at_tick, observation_policy)
                    .map(|event_id| ReplayOutcome::ObservationApplied { event_id }),
                FrameDisposition::Duplicate {
                    frame,
                    received_at_tick,
                } => {
                    let event_id = self.ingest_adapter_frame_with_policy(
                        frame,
                        received_at_tick,
                        observation_policy,
                    )?;
                    match self.ingest_adapter_frame_with_policy(
                        frame,
                        received_at_tick,
                        observation_policy,
                    ) {
                        Err(RuntimeError::Adapter(AdapterError::DuplicateOrOutOfOrder)) => {
                            Ok(ReplayOutcome::DuplicateRejected { event_id })
                        }
                        _ => Err(RuntimeError::Replay(ReplayError::InvalidAction)),
                    }
                }
                FrameDisposition::Drop => Ok(ReplayOutcome::FrameDropped),
                FrameDisposition::Hold => Ok(ReplayOutcome::FrameHeld),
            },
            ReplayAction::DeviceHealth {
                adapter_id,
                session_epoch,
                health,
            } => {
                self.update_device_health(adapter_id, session_epoch, health, step.at_tick)?;
                Ok(ReplayOutcome::DeviceHealthApplied)
            }
            ReplayAction::ActivateFault(fault) => {
                self.evidence
                    .reserve_at(step.at_tick, 1)
                    .map_err(RuntimeError::Session)?;
                self.faults.activate(fault).map_err(RuntimeError::Replay)?;
                self.evidence
                    .append(
                        step.at_tick,
                        EvidenceKind::FaultInjected,
                        fault.manifest_id,
                        fault.fault_code as u64,
                        fault.target_code(),
                        fault.kind_code(),
                        fault.kind_argument(),
                    )
                    .map_err(RuntimeError::Session)?;
                Ok(ReplayOutcome::FaultActivated {
                    manifest_id: fault.manifest_id,
                })
            }
            ReplayAction::Checkpoint { checkpoint_id } => {
                let twin_event_id = self.twin.snapshot().latest_event_id;
                let previous_checksum = self.evidence.final_checksum();
                self.evidence
                    .append(
                        step.at_tick,
                        EvidenceKind::Checkpoint,
                        checkpoint_id,
                        step.step_id,
                        twin_event_id,
                        previous_checksum,
                        0,
                    )
                    .map_err(RuntimeError::Session)?;
                Ok(ReplayOutcome::CheckpointRecorded { checkpoint_id })
            }
            ReplayAction::Pause => {
                let twin_event_id = self.twin.snapshot().latest_event_id;
                let previous_checksum = self.evidence.final_checksum();
                self.evidence
                    .append(
                        step.at_tick,
                        EvidenceKind::Checkpoint,
                        step.step_id,
                        1,
                        twin_event_id,
                        previous_checksum,
                        0,
                    )
                    .map_err(RuntimeError::Session)?;
                Ok(ReplayOutcome::Paused)
            }
        }
    }

    pub fn dispatch_next(
        &mut self,
        tick: u64,
        maximum_actor_staleness_ticks: u64,
    ) -> Result<DispatchReceipt, RuntimeError> {
        let receipt = self
            .work
            .dispatch_next(&mut self.domain, tick, maximum_actor_staleness_ticks)
            .map_err(RuntimeError::Dispatch)?;
        self.append_runtime_event(
            tick,
            EventPayload::WorkAssigned {
                job_id: receipt.job_id,
                task_id: receipt.task_id,
                actor_id: receipt.actor_id,
            },
        )?;
        Ok(receipt)
    }

    pub fn start_task(
        &mut self,
        receipt: DispatchReceipt,
        expected_revision: u64,
        human_approved: bool,
        tick: u64,
    ) -> Result<u64, RuntimeError> {
        let site_id = self.job_site(receipt.job_id)?;
        let revision = self
            .work
            .start_task(
                receipt.job_id,
                receipt.task_id,
                receipt.actor_id,
                expected_revision,
                human_approved,
            )
            .map_err(RuntimeError::Dispatch)?;
        self.record_reliability(
            site_id,
            tick,
            ReliabilityEventKind::TaskAttempted {
                job_id: receipt.job_id,
                task_id: receipt.task_id,
            },
        )?;
        Ok(revision)
    }

    pub fn complete_task(
        &mut self,
        receipt: DispatchReceipt,
        expected_revision: u64,
        duration_ticks: u64,
        tick: u64,
    ) -> Result<u64, RuntimeError> {
        if duration_ticks == 0 {
            return Err(RuntimeError::Reliability(ReliabilityError::InvalidDuration));
        }
        let site_id = self.job_site(receipt.job_id)?;
        let revision = self
            .work
            .complete_task(
                &mut self.domain,
                receipt.job_id,
                receipt.task_id,
                receipt.actor_id,
                expected_revision,
            )
            .map_err(RuntimeError::Dispatch)?;
        self.append_runtime_event(
            tick,
            EventPayload::WorkCompleted {
                job_id: receipt.job_id,
                task_id: receipt.task_id,
                actor_id: receipt.actor_id,
            },
        )?;
        self.record_reliability(
            site_id,
            tick,
            ReliabilityEventKind::TaskSucceeded {
                job_id: receipt.job_id,
                task_id: receipt.task_id,
                duration_ticks,
            },
        )?;
        Ok(revision)
    }

    pub fn preview_command(
        &mut self,
        command: &AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
    ) -> Result<SafetyDecision, RuntimeError> {
        self.preview_command_with_prediction_use(
            command,
            context,
            predictions,
            current_tick,
            PredictionUse::ShadowOnly,
        )
    }

    pub fn preview_command_with_simulation_caution(
        &mut self,
        command: &AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
        grant: SimulationCautionGrant,
    ) -> Result<SafetyDecision, RuntimeError> {
        let prediction_use = self.validate_simulation_caution_grant(grant)?;
        self.preview_command_with_prediction_use(
            command,
            context,
            predictions,
            current_tick,
            prediction_use,
        )
    }

    fn preview_command_with_prediction_use(
        &mut self,
        command: &AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
        prediction_use: PredictionUse,
    ) -> Result<SafetyDecision, RuntimeError> {
        self.evidence
            .reserve_at(current_tick, 2)
            .map_err(RuntimeError::Session)?;
        let decision = self
            .safety
            .evaluate_with_prediction_use(
                &self.adapters,
                &self.domain,
                &self.twin,
                command,
                context,
                predictions,
                current_tick,
                prediction_use,
            )
            .map_err(RuntimeError::Safety)?;
        self.record_prediction_summary(
            command.command_id,
            predictions,
            current_tick,
            prediction_use,
        )?;
        self.record_safety_decision(command.command_id, &decision, current_tick)?;
        Ok(decision)
    }

    pub fn authorize_and_queue_command(
        &mut self,
        command: AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
    ) -> Result<RoutedCommand, RuntimeError> {
        self.authorize_and_queue_command_with_prediction_use(
            command,
            context,
            predictions,
            current_tick,
            PredictionUse::ShadowOnly,
        )
    }

    pub fn authorize_and_queue_command_with_simulation_caution(
        &mut self,
        command: AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
        grant: SimulationCautionGrant,
    ) -> Result<RoutedCommand, RuntimeError> {
        let prediction_use = self.validate_simulation_caution_grant(grant)?;
        self.authorize_and_queue_command_with_prediction_use(
            command,
            context,
            predictions,
            current_tick,
            prediction_use,
        )
    }

    fn authorize_and_queue_command_with_prediction_use(
        &mut self,
        command: AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
        prediction_use: PredictionUse,
    ) -> Result<RoutedCommand, RuntimeError> {
        if command.kind != crate::adapter::CommandKind::Stop
            && !self.execution_authority_available(current_tick)
        {
            return Err(RuntimeError::Supervisor(
                SupervisorError::AuthorityUnavailable,
            ));
        }
        self.evidence
            .reserve_at(current_tick, 3)
            .map_err(RuntimeError::Session)?;
        let decision = self
            .safety
            .evaluate_with_prediction_use(
                &self.adapters,
                &self.domain,
                &self.twin,
                &command,
                context,
                predictions,
                current_tick,
                prediction_use,
            )
            .map_err(RuntimeError::Safety)?;
        self.record_prediction_summary(
            command.command_id,
            predictions,
            current_tick,
            prediction_use,
        )?;
        self.record_safety_decision(command.command_id, &decision, current_tick)?;
        if decision.verdict != SafetyVerdict::Allow {
            if decision.verdict == SafetyVerdict::Block {
                let site_id = self
                    .adapters
                    .adapter(command.adapter_id)
                    .map(|adapter| adapter.site_id)
                    .ok_or(RuntimeError::Adapter(AdapterError::UnknownAdapter))?;
                let zone_id = self
                    .adapters
                    .endpoint(command.endpoint_id)
                    .map(|endpoint| endpoint.zone_id)
                    .ok_or(RuntimeError::Adapter(AdapterError::UnknownEndpoint))?;
                let reason_code = decision
                    .reasons
                    .first()
                    .copied()
                    .map(safety_reason_code)
                    .unwrap_or(0);
                self.append_runtime_event(
                    current_tick,
                    EventPayload::SafetyInterlock {
                        site_id,
                        zone_id,
                        reason_code,
                    },
                )?;
                self.record_reliability(
                    site_id,
                    current_tick,
                    ReliabilityEventKind::SafetyIntervention { reason_code },
                )?;
                return Err(RuntimeError::Safety(SafetyError::Blocked));
            }
            return Err(RuntimeError::Safety(SafetyError::ApprovalRequired));
        }

        // Preflight journal capacity/idempotency before the adapter consumes its
        // single-use execution claim. The policy revision is checked again by
        // the supervisor immediately afterwards under the same mutable owner.
        self.fleet
            .can_queue_command(
                &RoutedCommand {
                    command,
                    policy_revision: decision.policy_revision,
                    twin_event_id: context.expected_twin_event_id,
                    confirmation: command.metadata.confirmation,
                    permit_expires_at_tick: command.deadline_tick,
                },
                current_tick,
            )
            .map_err(RuntimeError::Fleet)?;
        if command.kind != crate::adapter::CommandKind::Stop {
            self.command_rate
                .admit(command.endpoint_id, current_tick)
                .map_err(RuntimeError::Supervisor)?;
        }
        let routed = self
            .safety
            .authorize_and_route(
                &mut self.adapters,
                &self.domain,
                &self.twin,
                command,
                context,
                predictions,
                current_tick,
            )
            .map_err(RuntimeError::Safety)?;
        self.fleet
            .queue_command(routed, current_tick)
            .map_err(RuntimeError::Fleet)?;
        self.evidence
            .append(
                current_tick,
                EvidenceKind::PermitIssued,
                routed.command.command_id,
                routed.policy_revision,
                routed.twin_event_id,
                routed.command.deadline_tick,
                confirmation_code(routed.confirmation),
            )
            .map_err(RuntimeError::Session)?;
        Ok(routed)
    }

    fn validate_simulation_caution_grant(
        &self,
        grant: SimulationCautionGrant,
    ) -> Result<PredictionUse, RuntimeError> {
        let descriptor = self.evidence.descriptor();
        if descriptor.mode != SessionMode::Simulation
            || descriptor.run_id != grant.run_id
            || descriptor.model_sha256 != grant.model_sha256
        {
            return Err(RuntimeError::SimulationCautionUnavailable);
        }
        Ok(PredictionUse::SimulationCaution {
            model_version: grant.model_version,
        })
    }

    pub fn deliver_next(
        &mut self,
        adapter_id: AdapterId,
        driver: &mut impl AdapterDriver,
        tick: u64,
    ) -> Result<Option<RoutedCommand>, RuntimeError> {
        if driver.identity().id != adapter_id {
            return Err(RuntimeError::Adapter(AdapterError::EndpointMismatch));
        }
        let session_mode = self.evidence.descriptor().mode;
        if session_mode == SessionMode::Live {
            // No authenticated real-device qualification authority exists yet.
            // Keeping this path structurally closed prevents an enum match from
            // being mistaken for deployment approval.
            return Err(RuntimeError::DeploymentUnqualified);
        }
        let driver_allowed = matches!(
            (session_mode, driver.execution_mode()),
            (SessionMode::Simulation, DriverExecutionMode::Simulation)
                | (
                    SessionMode::HardwareInLoopActuatorDisabled,
                    DriverExecutionMode::ActuatorDisabled
                )
        );
        if !driver_allowed {
            return Err(RuntimeError::DriverModeMismatch);
        }
        self.evidence
            .reserve_at(tick, 1)
            .map_err(RuntimeError::Session)?;
        // Re-check authority at time of use: a watchdog may have expired
        // after the permit was issued. Only a queued stop may still leave.
        let routed = if self.execution_authority_available(tick) {
            match self.fleet.claim_next_ready(adapter_id, tick) {
                Some(routed) => routed,
                None => return Ok(None),
            }
        } else {
            self.fleet
                .claim_next_stop(adapter_id, tick)
                .ok_or(RuntimeError::Supervisor(
                    SupervisorError::AuthorityUnavailable,
                ))?
        };
        // Time-of-use re-check of the deterministic interlocks (actor e-stop,
        // geofence under the current policy, proximity, occupancy, device in
        // service). A permit issued against an earlier twin state does not
        // outlive a change that would have blocked it.
        if !self.safety.permits_delivery(
            &self.adapters,
            &self.domain,
            &self.twin,
            &routed.command,
            routed.policy_revision,
            tick,
        ) || (routed.command.kind != crate::adapter::CommandKind::Stop
            && self
                .fleet
                .device(adapter_id)
                .is_some_and(|device| device.lifecycle != DeviceLifecycle::Active))
        {
            self.fleet
                .revoke_dispatched(routed.command.command_id, tick)
                .map_err(RuntimeError::Fleet)?;
            return Err(RuntimeError::Safety(SafetyError::Blocked));
        }
        match driver.submit(routed) {
            Ok(()) => {
                self.fleet
                    .record_delivery(
                        routed.command.command_id,
                        CommandDeliveryState::Acknowledged,
                        tick,
                    )
                    .map_err(RuntimeError::Fleet)?;
                let evidence_kind =
                    if driver.execution_mode() == DriverExecutionMode::ActuatorDisabled {
                        EvidenceKind::ActuatorDisabledAcknowledged
                    } else {
                        EvidenceKind::DeliveryAcknowledged
                    };
                self.evidence
                    .append(
                        tick,
                        evidence_kind,
                        routed.command.command_id,
                        adapter_id.0,
                        routed.command.endpoint_id.0,
                        routed.policy_revision,
                        routed.twin_event_id,
                    )
                    .map_err(RuntimeError::Session)?;
                Ok(Some(routed))
            }
            Err(error) => {
                // A transport error does not prove the physical endpoint did
                // nothing. Mark uncertain and require reconciliation.
                self.fleet
                    .record_delivery(
                        routed.command.command_id,
                        CommandDeliveryState::Uncertain,
                        tick,
                    )
                    .map_err(RuntimeError::Fleet)?;
                if let Some(site_id) = self
                    .adapters
                    .adapter(adapter_id)
                    .map(|adapter| adapter.site_id)
                {
                    self.record_reliability(
                        site_id,
                        tick,
                        ReliabilityEventKind::DeviceCommandUncertain,
                    )?;
                }
                self.evidence
                    .append(
                        tick,
                        EvidenceKind::DeliveryUncertain,
                        routed.command.command_id,
                        adapter_id.0,
                        routed.command.endpoint_id.0,
                        routed.policy_revision,
                        routed.twin_event_id,
                    )
                    .map_err(RuntimeError::Session)?;
                Err(RuntimeError::DeliveryUncertain(error))
            }
        }
    }

    pub fn update_device_health(
        &mut self,
        adapter_id: AdapterId,
        session_epoch: u64,
        health: DeviceHealth,
        tick: u64,
    ) -> Result<(), RuntimeError> {
        self.evidence
            .reserve_at(tick, 1)
            .map_err(RuntimeError::Session)?;
        if self.adapters.adapter(adapter_id).is_none() {
            return Err(RuntimeError::Adapter(AdapterError::UnknownAdapter));
        }
        self.fleet
            .heartbeat(adapter_id, session_epoch, health, tick)
            .map_err(RuntimeError::Fleet)?;
        let state = match self
            .fleet
            .device(adapter_id)
            .map(|device| device.lifecycle)
            .ok_or(RuntimeError::Fleet(FleetError::UnknownDevice))?
        {
            DeviceLifecycle::Active => AdapterState::Online,
            DeviceLifecycle::Degraded | DeviceLifecycle::Updating => AdapterState::Degraded,
            DeviceLifecycle::Offline => AdapterState::Offline,
            DeviceLifecycle::Quarantined | DeviceLifecycle::Retired => AdapterState::Quarantined,
            DeviceLifecycle::Provisioning => AdapterState::Provisioning,
        };
        self.adapters
            .set_state(adapter_id, state, tick)
            .map_err(RuntimeError::Adapter)?;
        self.evidence
            .append(
                tick,
                EvidenceKind::ObservationAccepted,
                adapter_id.0,
                session_epoch,
                health.battery_permille as u64,
                health.link_quality_permille as u64,
                health.fault_code as u64,
            )
            .map_err(RuntimeError::Session)?;
        Ok(())
    }

    pub fn evaluate_data_access(
        &mut self,
        request: DataAccessRequest,
        current_tick: u64,
    ) -> PrivacyDecision {
        self.privacy.evaluate(request, current_tick)
    }

    fn latch_emergency_stop(&mut self) {
        if !self.recovery.stop_pending() {
            self.recovery = RecoveryLatch::default();
            self.recovery.observe_stop();
        }
    }

    /// Non-stop authority needs every watchdog below `Block` and no
    /// unreleased emergency stop. Observing an emergency stop latches it.
    fn execution_authority_available(&mut self, tick: u64) -> bool {
        let severity = self.watchdogs.severity(tick);
        if severity == AuthoritySeverity::EmergencyStop {
            self.latch_emergency_stop();
        }
        severity < AuthoritySeverity::Block && !self.recovery.stop_pending()
    }

    fn append_runtime_event(
        &mut self,
        tick: u64,
        payload: EventPayload,
    ) -> Result<u64, RuntimeError> {
        let next_sequence = self
            .runtime_twin_sequence
            .checked_add(1)
            .ok_or(RuntimeError::SequenceExhausted)?;
        let event_id = self
            .twin
            .append_internal(
                &mut self.domain,
                RUNTIME_TWIN_SOURCE_ID,
                next_sequence,
                tick,
                tick,
                payload,
            )
            .map_err(RuntimeError::Twin)?;
        self.runtime_twin_sequence = next_sequence;
        Ok(event_id)
    }

    fn record_reliability(
        &mut self,
        site_id: SiteId,
        tick: u64,
        kind: ReliabilityEventKind,
    ) -> Result<(), RuntimeError> {
        let next_id = self
            .reliability_event_id
            .checked_add(1)
            .ok_or(RuntimeError::SequenceExhausted)?;
        self.reliability
            .record(ReliabilityEvent {
                event_id: next_id,
                site_id,
                observed_at_tick: tick,
                kind,
            })
            .map_err(RuntimeError::Reliability)?;
        self.reliability_event_id = next_id;
        Ok(())
    }

    fn job_site(&self, job_id: JobId) -> Result<SiteId, RuntimeError> {
        self.work
            .order(job_id)
            .map(|order| order.site_id)
            .ok_or(RuntimeError::Dispatch(DispatchError::UnknownJob))
    }

    fn record_prediction_summary(
        &mut self,
        command_id: u64,
        predictions: &[PhysicalPrediction],
        tick: u64,
        prediction_use: PredictionUse,
    ) -> Result<(), RuntimeError> {
        let maximum_risk = predictions
            .iter()
            .map(|prediction| prediction.risk_permille)
            .max()
            .unwrap_or(0);
        let maximum_uncertainty = predictions
            .iter()
            .map(|prediction| prediction.uncertainty_permille)
            .max()
            .unwrap_or(0);
        let caution_count = match prediction_use {
            PredictionUse::ShadowOnly => 0,
            PredictionUse::SimulationCaution { model_version } => predictions
                .iter()
                .filter(|prediction| {
                    prediction.source == crate::safety::PredictionSource::PhysicalJepa
                        && prediction.model_version == model_version
                        && !prediction.validated_for_gating
                })
                .count(),
        };
        self.evidence
            .append(
                tick,
                EvidenceKind::PredictionObserved,
                command_id,
                predictions.len() as u64,
                maximum_risk as u64,
                maximum_uncertainty as u64,
                caution_count as u64,
            )
            .map(|_| ())
            .map_err(RuntimeError::Session)
    }

    fn record_safety_decision(
        &mut self,
        command_id: u64,
        decision: &SafetyDecision,
        tick: u64,
    ) -> Result<(), RuntimeError> {
        let packed_risk = (decision.maximum_validated_risk_permille as u64) << 16
            | decision.maximum_shadow_risk_permille as u64;
        self.evidence
            .append(
                tick,
                EvidenceKind::SafetyDecision,
                command_id,
                verdict_code(decision.verdict),
                decision.policy_revision,
                self.twin.snapshot().latest_event_id,
                packed_risk,
            )
            .map(|_| ())
            .map_err(RuntimeError::Session)
    }
}

const fn verdict_code(verdict: SafetyVerdict) -> u64 {
    match verdict {
        SafetyVerdict::Allow => 0,
        SafetyVerdict::RequireApproval => 1,
        SafetyVerdict::Block => 2,
    }
}

const fn confirmation_code(confirmation: crate::contract::ConfirmationProvenance) -> u64 {
    match confirmation {
        crate::contract::ConfirmationProvenance::NotRequired => 0,
        crate::contract::ConfirmationProvenance::LocalHuman { confirmation_id } => confirmation_id,
        crate::contract::ConfirmationProvenance::ExternalSupervisor { confirmation_id } => {
            confirmation_id | (1u64 << 63)
        }
    }
}

fn safety_reason_code(reason: SafetyReason) -> u32 {
    match reason {
        SafetyReason::NoPolicy => 1,
        SafetyReason::PolicyRevisionMismatch => 2,
        SafetyReason::TwinRevisionMismatch => 3,
        SafetyReason::InvalidPolicy => 4,
        SafetyReason::InvalidPrediction => 5,
        SafetyReason::GeofenceViolation => 6,
        SafetyReason::MissingProximitySensor => 7,
        SafetyReason::StaleProximitySensor => 8,
        SafetyReason::UnsafeProximity => 9,
        SafetyReason::HumanOccupiedZone => 10,
        SafetyReason::HumanApprovalRequired => 11,
        SafetyReason::ConfirmationProvenanceMismatch => 12,
        SafetyReason::EmergencyStoppedActor => 13,
        SafetyReason::PredictiveWarning => 14,
        SafetyReason::PredictiveBlock => 15,
        SafetyReason::PredictiveShadowOnly => 16,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{
        AdapterIdentity, AdapterPayload, AdapterProtocol, Endpoint, EndpointCapability,
        EndpointCapabilitySet, EndpointId, EndpointKind, SimulatedAdapter,
    };
    use crate::contract::{CommandMetadata, ConfirmationProvenance, ObservationMetadata};
    use crate::domain::{
        Actor, ActorId, ActorKind, ActorStatus, Asset, AssetId, AssetState, Capability,
        CapabilitySet, Position, Qualification, QualificationSet, Site,
    };
    use crate::fleet::{DeviceLifecycle, FleetDevice};
    use crate::replay::{FaultKind, FaultSpec, FaultTarget, ReplayManifest};
    use crate::safety::{EffectKind, Geofence, PredictionSource, SafetyPolicy};
    use crate::twin::{SensorKind, SensorReading};
    use crate::work::{ActorConstraint, JobState, Priority, TaskId, TaskStatus, WorkTask};
    use alloc::string::ToString;
    use alloc::vec;

    fn configured_runtime() -> PhysicalRuntime {
        configured_runtime_with(
            SessionDescriptor::simulator(1, 1, 42),
            AdapterProtocol::Simulator,
        )
    }

    fn configured_runtime_with(
        descriptor: SessionDescriptor,
        protocol: AdapterProtocol,
    ) -> PhysicalRuntime {
        let mut runtime = PhysicalRuntime::new_with_session(descriptor).unwrap();
        runtime
            .domain_mut()
            .register_site(Site {
                id: SiteId(1),
                name: "Plant".to_string(),
                emergency_zone_id: 99,
            })
            .unwrap();
        runtime
            .domain_mut()
            .register_asset(Asset {
                id: AssetId(50),
                name: "Pump".to_string(),
                site_id: SiteId(1),
                position: Position::origin(7, 100),
                state: AssetState::Degraded,
                last_service_tick: 0,
            })
            .unwrap();
        runtime
            .domain_mut()
            .register_actor(Actor {
                id: ActorId(8),
                name: "Robot".to_string(),
                kind: ActorKind::Robot,
                status: ActorStatus::Available,
                site_id: SiteId(1),
                position: Position::origin(7, 100),
                capabilities: CapabilitySet::empty()
                    .with(Capability::Inspect)
                    .with(Capability::Navigate),
                qualifications: QualificationSet::empty().with(Qualification::SiteInduction),
                available_from_tick: 0,
                last_seen_tick: 100,
                battery_permille: 900,
                load_permille: 0,
                max_payload_grams: 1_000,
            })
            .unwrap();
        let identity = AdapterIdentity {
            id: AdapterId(1),
            site_id: SiteId(1),
            protocol,
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
            .unwrap();
        runtime
            .adapters_mut()
            .register_endpoint(Endpoint {
                id: EndpointId(2),
                adapter_id: AdapterId(1),
                kind: EndpointKind::Robot,
                zone_id: 7,
                controlled_actor_id: Some(ActorId(8)),
                capabilities: EndpointCapabilitySet::empty()
                    .with(EndpointCapability::Sense)
                    .with(EndpointCapability::Move)
                    .with(EndpointCapability::EmergencyStop),
            })
            .unwrap();
        runtime
            .fleet_mut()
            .provision(FleetDevice {
                adapter_id: AdapterId(1),
                site_id: SiteId(1),
                identity_sha256: [7; 32],
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
            .unwrap();
        runtime.fleet_mut().activate(AdapterId(1), 5, 100).unwrap();
        runtime
            .safety_mut()
            .install_policy(SafetyPolicy {
                site_id: SiteId(1),
                zone_id: 7,
                revision: 1,
                geofence: Geofence {
                    minimum_x_mm: -1_000,
                    maximum_x_mm: 1_000,
                    minimum_y_mm: -1_000,
                    maximum_y_mm: 1_000,
                    minimum_z_mm: 0,
                    maximum_z_mm: 1_000,
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
            .unwrap();
        runtime
    }

    fn order() -> WorkOrder {
        WorkOrder {
            id: JobId(1),
            asset_id: AssetId(50),
            site_id: SiteId(1),
            priority: Priority::Urgent,
            deadline_tick: 1_000,
            state: JobState::Pending,
            revision: 0,
            tasks: vec![WorkTask {
                id: TaskId(1),
                dependencies: vec![],
                status: TaskStatus::Pending,
                actor_constraint: ActorConstraint::Robot,
                required_capabilities: CapabilitySet::empty().with(Capability::Inspect),
                required_qualifications: QualificationSet::empty()
                    .with(Qualification::SiteInduction),
                zone_id: 7,
                minimum_battery_permille: 200,
                payload_grams: 0,
                estimated_duration_ticks: 10,
                requires_human_approval: false,
            }],
        }
    }

    fn frame(sequence: u64, clearance: i64, tick: u64) -> AdapterFrame {
        AdapterFrame {
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 5,
            sequence,
            observed_at_tick: tick,
            metadata: ObservationMetadata::simulated(sequence, tick.saturating_add(10)),
            payload: AdapterPayload::SensorReading(SensorReading {
                sensor_id: 9,
                site_id: SiteId(1),
                asset_id: Some(AssetId(50)),
                kind: SensorKind::ProximityMillimeters,
                value: clearance,
                quality_permille: 1_000,
                observed_at_tick: tick,
            }),
        }
    }

    fn command(command_id: u64) -> AdapterCommand {
        AdapterCommand {
            command_id,
            idempotency_key: command_id + 100,
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 5,
            kind: crate::adapter::CommandKind::MoveTo,
            argument0: 100,
            argument1: 100,
            argument2: 0,
            deadline_tick: 200,
            metadata: CommandMetadata::kernel(
                100,
                1,
                1,
                EndpointCapability::Move,
                ConfirmationProvenance::LocalHuman {
                    confirmation_id: command_id,
                },
            ),
        }
    }

    #[test]
    fn work_lifecycle_updates_twin_and_reliability_as_one_owner() {
        let mut runtime = configured_runtime();
        runtime.submit_work_order(order()).unwrap();
        let receipt = runtime.dispatch_next(100, 10).unwrap();
        let running_revision = runtime
            .start_task(receipt, receipt.revision, false, 101)
            .unwrap();
        runtime
            .complete_task(receipt, running_revision, 9, 110)
            .unwrap();
        assert_eq!(
            runtime.work().order(JobId(1)).unwrap().state,
            JobState::Completed
        );
        assert_eq!(runtime.twin().snapshot().retained_events, 2);
        let metrics = runtime.reliability().snapshot(SiteId(1)).unwrap();
        assert_eq!(metrics.task_attempts, 1);
        assert_eq!(metrics.task_successes, 1);
    }

    #[test]
    fn exhausted_runtime_sequences_fail_before_mutation() {
        let mut runtime = configured_runtime();
        runtime.runtime_twin_sequence = u64::MAX;
        assert_eq!(
            runtime.append_runtime_event(
                100,
                EventPayload::SafetyInterlock {
                    site_id: SiteId(1),
                    zone_id: 7,
                    reason_code: 7,
                },
            ),
            Err(RuntimeError::SequenceExhausted)
        );
        assert_eq!(runtime.twin().snapshot().retained_events, 0);

        runtime.reliability_event_id = u64::MAX;
        assert_eq!(
            runtime.record_reliability(SiteId(1), 100, ReliabilityEventKind::DeviceCommandRetried,),
            Err(RuntimeError::SequenceExhausted)
        );
        assert_eq!(
            runtime.reliability().snapshot(SiteId(1)),
            Err(ReliabilityError::UnknownSite)
        );
    }

    #[test]
    fn stale_preview_cannot_be_reused_after_twin_changes() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let stale = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        assert_eq!(
            runtime
                .preview_command(&command(1), stale, &[], 100)
                .unwrap()
                .verdict,
            SafetyVerdict::Allow
        );
        runtime
            .ingest_adapter_frame(frame(2, 100, 101), 101, 0)
            .unwrap();
        assert_eq!(
            runtime.authorize_and_queue_command(command(1), stale, &[], 101),
            Err(RuntimeError::Safety(SafetyError::Blocked))
        );
        assert!(runtime.fleet().command_claim(1).is_none());
        assert_eq!(
            runtime
                .reliability()
                .snapshot(SiteId(1))
                .unwrap()
                .safety_interventions,
            1
        );
    }

    #[test]
    fn exact_model_digest_can_add_caution_only_inside_its_simulation_session() {
        let mut descriptor = SessionDescriptor::simulator(7, 3, 42);
        descriptor.model_sha256 = [9; 32];
        let mut runtime = configured_runtime_with(descriptor, AdapterProtocol::Simulator);
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        let prediction = PhysicalPrediction {
            effect: EffectKind::Move,
            risk_permille: 900,
            uncertainty_permille: 20,
            source: PredictionSource::PhysicalJepa,
            model_version: 1,
            validated_for_gating: false,
        };
        assert_eq!(
            runtime
                .preview_command(&command(70), context, &[prediction], 100)
                .unwrap()
                .verdict,
            SafetyVerdict::Allow
        );
        assert_eq!(
            runtime.simulation_caution_grant([8; 32], 1),
            Err(RuntimeError::SimulationCautionUnavailable)
        );
        let grant = runtime.simulation_caution_grant([9; 32], 1).unwrap();
        let decision = runtime
            .preview_command_with_simulation_caution(
                &command(71),
                context,
                &[prediction],
                100,
                grant,
            )
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Block);
        assert!(decision.reasons.contains(&SafetyReason::PredictiveBlock));
        assert_eq!(
            runtime.authorize_and_queue_command_with_simulation_caution(
                command(72),
                context,
                &[prediction],
                100,
                grant,
            ),
            Err(RuntimeError::Safety(SafetyError::Blocked))
        );
        assert!(runtime.fleet().command_claim(72).is_none());
        assert!(!runtime
            .evidence()
            .records()
            .iter()
            .any(|record| record.kind == EvidenceKind::PermitIssued));
    }

    #[test]
    fn live_and_actuator_disabled_sessions_cannot_obtain_simulation_caution() {
        for mode in [
            SessionMode::HardwareInLoopActuatorDisabled,
            SessionMode::Live,
        ] {
            let mut descriptor = SessionDescriptor::simulator(9, 3, 42);
            descriptor.mode = mode;
            descriptor.model_sha256 = [9; 32];
            let runtime = PhysicalRuntime::new_with_session(descriptor).unwrap();
            assert_eq!(
                runtime.simulation_caution_grant([9; 32], 1),
                Err(RuntimeError::SimulationCautionUnavailable)
            );
        }
    }

    #[test]
    fn safe_command_keeps_policy_provenance_through_delivery() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        let routed = runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        assert_eq!(routed.policy_revision, 1);
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        assert_eq!(
            runtime
                .deliver_next(AdapterId(1), &mut driver, 100)
                .unwrap(),
            Some(routed)
        );
        assert_eq!(driver.commands()[0].policy_revision, 1);
        assert_eq!(
            runtime.fleet().command_claim(1).unwrap().state,
            CommandDeliveryState::Acknowledged
        );
        let kinds: alloc::vec::Vec<_> = runtime
            .evidence()
            .records()
            .iter()
            .map(|record| record.kind)
            .collect();
        assert_eq!(
            kinds,
            alloc::vec![
                EvidenceKind::ObservationAccepted,
                EvidenceKind::PredictionObserved,
                EvidenceKind::SafetyDecision,
                EvidenceKind::PermitIssued,
                EvidenceKind::DeliveryAcknowledged,
            ]
        );
        assert_eq!(runtime.evidence().verify(), Ok(()));
    }

    #[test]
    fn session_mode_cannot_be_crossed_by_a_driver() {
        struct PhysicalDriver {
            identity: AdapterIdentity,
        }

        impl AdapterDriver for PhysicalDriver {
            fn identity(&self) -> &AdapterIdentity {
                &self.identity
            }

            fn execution_mode(&self) -> DriverExecutionMode {
                DriverExecutionMode::Physical
            }

            fn poll_frame(&mut self) -> Option<AdapterFrame> {
                None
            }

            fn submit(&mut self, _: RoutedCommand) -> Result<(), AdapterError> {
                panic!("mode mismatch must be rejected before delivery")
            }
        }

        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let mut driver = PhysicalDriver {
            identity: runtime.adapters().adapter(AdapterId(1)).unwrap().clone(),
        };
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 100),
            Err(RuntimeError::DriverModeMismatch)
        );
        assert_eq!(
            runtime.fleet().command_claim(1).unwrap().state,
            CommandDeliveryState::Queued
        );
    }

    #[test]
    fn actuator_disabled_hil_runs_full_permit_path_without_physical_driver() {
        let descriptor = SessionDescriptor {
            run_id: 9,
            parent_run_id: 0,
            fork_sequence: 0,
            simulator_epoch: 4,
            seed: 42,
            started_at_tick: 0,
            mode: SessionMode::HardwareInLoopActuatorDisabled,
            topology_sha256: [1; 32],
            policy_sha256: [2; 32],
            model_sha256: [3; 32],
        };
        let mut runtime = configured_runtime_with(descriptor, AdapterProtocol::Mqtt);
        let mut input = frame(1, 900, 100);
        input.metadata.evidence_class = crate::contract::EvidenceClass::HardwareInLoop;
        input.metadata.integrity =
            crate::contract::IntegrityEvidence::TransportAuthenticated([4; 32]);
        runtime.ingest_adapter_frame(input, 100, 0).unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        let routed = runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut disabled = crate::adapter::ActuatorDisabledAdapter::new(identity).unwrap();
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut disabled, 100),
            Ok(Some(routed))
        );
        assert_eq!(disabled.recorded_commands(), &[routed]);
        assert_eq!(
            disabled.execution_mode(),
            DriverExecutionMode::ActuatorDisabled
        );
        assert_eq!(
            runtime.evidence().records().back().unwrap().kind,
            EvidenceKind::ActuatorDisabledAcknowledged
        );
    }

    #[test]
    fn live_session_cannot_reach_a_physical_driver_without_qualification_authority() {
        struct PhysicalDriver {
            identity: AdapterIdentity,
        }

        impl AdapterDriver for PhysicalDriver {
            fn identity(&self) -> &AdapterIdentity {
                &self.identity
            }

            fn execution_mode(&self) -> DriverExecutionMode {
                DriverExecutionMode::Physical
            }

            fn poll_frame(&mut self) -> Option<AdapterFrame> {
                None
            }

            fn submit(&mut self, _: RoutedCommand) -> Result<(), AdapterError> {
                panic!("unqualified live delivery must fail before driver submission")
            }
        }

        let mut descriptor = SessionDescriptor::simulator(10, 5, 43);
        descriptor.mode = SessionMode::Live;
        descriptor.topology_sha256 = [1; 32];
        descriptor.policy_sha256 = [2; 32];
        descriptor.model_sha256 = [3; 32];
        let mut runtime = configured_runtime_with(descriptor, AdapterProtocol::Mqtt);
        let mut input = frame(1, 900, 100);
        input.metadata.evidence_class = crate::contract::EvidenceClass::Live;
        input.metadata.integrity =
            crate::contract::IntegrityEvidence::TransportAuthenticated([4; 32]);
        runtime.ingest_adapter_frame(input, 100, 0).unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let mut driver = PhysicalDriver {
            identity: runtime.adapters().adapter(AdapterId(1)).unwrap().clone(),
        };
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 100),
            Err(RuntimeError::DeploymentUnqualified)
        );
        assert_eq!(
            runtime.fleet().command_claim(1).unwrap().state,
            CommandDeliveryState::Queued
        );
    }

    #[test]
    fn expired_controller_watchdog_blocks_motion_before_evidence_or_permit() {
        let mut runtime = configured_runtime();
        runtime
            .register_watchdog(WatchdogState {
                id: 1,
                role: crate::supervisor::WatchdogRole::Controller,
                timeout_ticks: 5,
                last_heartbeat_tick: 90,
                armed: true,
            })
            .unwrap();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        assert_eq!(
            runtime.authority_severity(100),
            AuthoritySeverity::EmergencyStop
        );
        assert_eq!(
            runtime.authorize_and_queue_command(command(1), context, &[], 100),
            Err(RuntimeError::Supervisor(
                SupervisorError::AuthorityUnavailable
            ))
        );
        assert!(runtime.fleet().command_claim(1).is_none());
    }

    fn safe_context(runtime: &PhysicalRuntime) -> SafetyContext {
        SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        }
    }

    fn stop_command(command_id: u64, tick: u64) -> AdapterCommand {
        AdapterCommand {
            command_id,
            idempotency_key: command_id + 100,
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 5,
            kind: crate::adapter::CommandKind::Stop,
            argument0: 0,
            argument1: 0,
            argument2: 0,
            deadline_tick: tick + 10,
            metadata: CommandMetadata::kernel(
                tick,
                0,
                0,
                EndpointCapability::EmergencyStop,
                ConfirmationProvenance::NotRequired,
            ),
        }
    }

    fn stop_context() -> SafetyContext {
        SafetyContext {
            expected_policy_revision: 0,
            expected_twin_event_id: 0,
            human_approved: false,
            requesting_actor_id: None,
        }
    }

    #[test]
    fn queued_permit_cannot_be_delivered_after_its_ttl() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = safe_context(&runtime);
        runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        // Policy permit_ttl_ticks is 5: tick 106 is after the permit but
        // well before the command's own deadline of 200.
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 106),
            Ok(None)
        );
        assert!(driver.commands().is_empty());
        assert_eq!(
            runtime.fleet().command_claim(1).unwrap().state,
            CommandDeliveryState::Expired
        );
    }

    /// Queues a MoveTo at tick 100, applies `change` at tick 101, and tries
    /// to deliver at tick 102 (inside the 5-tick permit). Returns the
    /// delivery result, how many commands reached the driver, and the claim.
    fn deliver_after_change(
        change: impl FnOnce(&mut PhysicalRuntime),
    ) -> (
        Result<Option<RoutedCommand>, RuntimeError>,
        usize,
        CommandDeliveryState,
    ) {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = safe_context(&runtime);
        runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        change(&mut runtime);
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        let result = runtime.deliver_next(AdapterId(1), &mut driver, 102);
        let state = runtime.fleet().command_claim(1).unwrap().state;
        (result, driver.commands().len(), state)
    }

    fn assert_revoked_at_delivery(
        outcome: (
            Result<Option<RoutedCommand>, RuntimeError>,
            usize,
            CommandDeliveryState,
        ),
    ) {
        let (result, delivered, state) = outcome;
        assert_eq!(
            delivered, 0,
            "a command invalid at delivery reached the driver"
        );
        assert_eq!(result, Err(RuntimeError::Safety(SafetyError::Blocked)));
        assert_eq!(state, CommandDeliveryState::Expired);
    }

    #[test]
    fn baseline_queued_motion_is_delivered_when_nothing_changes() {
        let (result, delivered, state) = deliver_after_change(|_| {});
        assert!(matches!(result, Ok(Some(_))));
        assert_eq!(delivered, 1);
        assert_eq!(state, CommandDeliveryState::Acknowledged);
    }

    #[test]
    fn benign_fresh_telemetry_after_queueing_does_not_revoke_motion() {
        let (result, delivered, _) = deliver_after_change(|runtime| {
            runtime
                .ingest_adapter_frame(frame(2, 950, 101), 101, 0)
                .unwrap();
        });
        assert!(matches!(result, Ok(Some(_))));
        assert_eq!(delivered, 1);
    }

    #[test]
    fn actor_emergency_stop_after_queueing_revokes_motion_delivery() {
        assert_revoked_at_delivery(deliver_after_change(|runtime| {
            let mut stop = frame(2, 900, 101);
            stop.payload = AdapterPayload::EmergencyStop {
                actor_id: ActorId(8),
                reason_code: 1,
            };
            runtime.ingest_adapter_frame(stop, 101, 0).unwrap();
        }));
    }

    #[test]
    fn unsafe_proximity_after_queueing_revokes_motion_delivery() {
        assert_revoked_at_delivery(deliver_after_change(|runtime| {
            runtime
                .ingest_adapter_frame(frame(2, 100, 101), 101, 0)
                .unwrap();
        }));
    }

    #[test]
    fn human_entering_zone_after_queueing_revokes_motion_delivery() {
        assert_revoked_at_delivery(deliver_after_change(|runtime| {
            let mut occupied = frame(2, 900, 101);
            occupied.payload = AdapterPayload::ZoneOccupancy(crate::twin::ZoneOccupancy {
                site_id: SiteId(1),
                zone_id: 7,
                humans: 1,
                robots: 0,
                observed_at_tick: 101,
            });
            runtime.ingest_adapter_frame(occupied, 101, 0).unwrap();
        }));
    }

    #[test]
    fn policy_tightened_after_queueing_revokes_motion_delivery() {
        assert_revoked_at_delivery(deliver_after_change(|runtime| {
            runtime
                .safety_mut()
                .install_policy(SafetyPolicy {
                    site_id: SiteId(1),
                    zone_id: 7,
                    revision: 2,
                    geofence: Geofence {
                        minimum_x_mm: -50,
                        maximum_x_mm: 50,
                        minimum_y_mm: -50,
                        maximum_y_mm: 50,
                        minimum_z_mm: 0,
                        maximum_z_mm: 50,
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
                .unwrap();
        }));
    }

    #[test]
    fn device_quarantined_after_queueing_revokes_motion_delivery() {
        assert_revoked_at_delivery(deliver_after_change(|runtime| {
            runtime.fleet_mut().quarantine(AdapterId(1)).unwrap();
        }));
    }

    #[test]
    fn device_degraded_after_queueing_revokes_motion_delivery() {
        assert_revoked_at_delivery(deliver_after_change(|runtime| {
            runtime
                .update_device_health(
                    AdapterId(1),
                    5,
                    DeviceHealth {
                        battery_permille: 900,
                        link_quality_permille: 900,
                        fault_code: 7,
                    },
                    101,
                )
                .unwrap();
            assert_ne!(
                runtime.adapters().adapter(AdapterId(1)).unwrap().state,
                crate::adapter::AdapterState::Online
            );
        }));
    }

    #[test]
    fn older_sensor_observation_cannot_overwrite_a_newer_one() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        // Newest truth: a person is 100 mm away.
        runtime
            .ingest_adapter_frame(frame(2, 100, 105), 105, 0)
            .unwrap();
        // A later frame carrying an older (still "fresh") safe reading.
        // Delivery-tolerant policy: observations up to 20 ticks old are
        // accepted, matching the zone's maximum_sensor_age_ticks.
        let tolerant = ObservationPolicy {
            maximum_clock_skew_ticks: 0,
            maximum_clock_uncertainty_ticks: 0,
            maximum_observation_age_ticks: 20,
        };
        let _ = runtime.ingest_adapter_frame_with_policy(frame(3, 900, 101), 106, tolerant);
        assert_eq!(runtime.twin().sensor(9).unwrap().value, 100);
        let context = safe_context(&runtime);
        assert_eq!(
            runtime.authorize_and_queue_command(command(1), context, &[], 106),
            Err(RuntimeError::Safety(SafetyError::Blocked))
        );
    }

    #[test]
    fn older_occupancy_observation_cannot_overwrite_a_newer_one() {
        let mut runtime = configured_runtime();
        let occupancy = |sequence: u64, humans: u16, tick: u64| {
            let mut occupied = frame(sequence, 900, tick);
            occupied.payload = AdapterPayload::ZoneOccupancy(crate::twin::ZoneOccupancy {
                site_id: SiteId(1),
                zone_id: 7,
                humans,
                robots: 0,
                observed_at_tick: tick,
            });
            occupied
        };
        runtime
            .ingest_adapter_frame(frame(1, 900, 105), 105, 0)
            .unwrap();
        runtime
            .ingest_adapter_frame(occupancy(2, 1, 105), 105, 0)
            .unwrap();
        let tolerant = ObservationPolicy {
            maximum_clock_skew_ticks: 0,
            maximum_clock_uncertainty_ticks: 0,
            maximum_observation_age_ticks: 20,
        };
        let _ = runtime.ingest_adapter_frame_with_policy(occupancy(3, 0, 101), 106, tolerant);
        assert_eq!(runtime.twin().occupancy(SiteId(1), 7).unwrap().humans, 1);
    }

    fn actor_telemetry_frame(sequence: u64, actor: u64, tick: u64) -> AdapterFrame {
        let mut telemetry = frame(sequence, 900, tick);
        telemetry.payload = AdapterPayload::ActorTelemetry(crate::twin::ActorTelemetry {
            actor_id: ActorId(actor),
            position: Position::origin(7, 100),
            battery_permille: 900,
            load_permille: 0,
            status: ActorStatus::Available,
        });
        telemetry
    }

    #[test]
    fn actor_telemetry_cannot_clear_an_emergency_stop() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let mut stop = frame(2, 900, 101);
        stop.payload = AdapterPayload::EmergencyStop {
            actor_id: ActorId(8),
            reason_code: 1,
        };
        runtime.ingest_adapter_frame(stop, 101, 0).unwrap();
        let _ = runtime.ingest_adapter_frame(actor_telemetry_frame(3, 8, 102), 102, 0);
        assert_eq!(
            runtime.domain().actor(ActorId(8)).unwrap().status,
            ActorStatus::EmergencyStop
        );
        let context = safe_context(&runtime);
        assert_eq!(
            runtime.authorize_and_queue_command(command(1), context, &[], 102),
            Err(RuntimeError::Safety(SafetyError::Blocked))
        );
        // Only the operator-side registry can release the stop.
        runtime
            .domain_mut()
            .release_emergency_stop(ActorId(8))
            .unwrap();
        assert_eq!(
            runtime.domain().actor(ActorId(8)).unwrap().status,
            ActorStatus::Available
        );
    }

    #[test]
    fn adapter_cannot_publish_telemetry_for_an_actor_it_does_not_control() {
        let mut runtime = configured_runtime();
        let mut other = runtime.domain().actor(ActorId(8)).unwrap().clone();
        other.id = ActorId(9);
        other.status = ActorStatus::Offline;
        runtime.domain_mut().register_actor(other).unwrap();
        assert!(runtime
            .ingest_adapter_frame(actor_telemetry_frame(1, 9, 100), 100, 0)
            .is_err());
        assert_eq!(
            runtime.domain().actor(ActorId(9)).unwrap().status,
            ActorStatus::Offline
        );
    }

    // ---- Open items O1 and O5 (policy decision pending; NOT fixed) --------
    // These tests document current behaviour so a policy change shows up as
    // a deliberate test edit. Flip the assertions when the author decides.

    #[test]
    fn documents_o1_missing_or_stale_occupancy_counts_as_zero_humans() {
        // No occupancy record at all: the human interlock is silent and only
        // the proximity sensor protects (allow_motion_with_humans=false).
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        assert!(runtime.twin().occupancy(SiteId(1), 7).is_none());
        let context = safe_context(&runtime);
        assert!(runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .is_ok());

        // A zero-human record observed at tick 10 still counts at tick 500:
        // occupancy freshness is never checked.
        let mut runtime = configured_runtime();
        let tolerant = ObservationPolicy {
            maximum_clock_skew_ticks: 0,
            maximum_clock_uncertainty_ticks: 0,
            maximum_observation_age_ticks: 1_000,
        };
        let mut empty = frame(1, 900, 10);
        empty.metadata = ObservationMetadata::simulated(1, 1_000);
        empty.payload = AdapterPayload::ZoneOccupancy(crate::twin::ZoneOccupancy {
            site_id: SiteId(1),
            zone_id: 7,
            humans: 0,
            robots: 0,
            observed_at_tick: 10,
        });
        runtime
            .ingest_adapter_frame_with_policy(empty, 10, tolerant)
            .unwrap();
        let mut fresh = frame(2, 900, 500);
        fresh.metadata = ObservationMetadata::simulated(2, 1_000);
        runtime.ingest_adapter_frame(fresh, 500, 0).unwrap();
        let context = safe_context(&runtime);
        let mut late = command(2);
        late.deadline_tick = 600;
        late.metadata = CommandMetadata::kernel(
            500,
            1,
            context.expected_twin_event_id,
            EndpointCapability::Move,
            ConfirmationProvenance::LocalHuman { confirmation_id: 2 },
        );
        assert!(runtime
            .authorize_and_queue_command(late, context, &[], 500)
            .is_ok());
    }

    #[test]
    fn documents_o5_motion_has_no_step_speed_or_payload_bound() {
        // The actor stands at the zone origin; one MoveTo to the far corner
        // of the geofence (1 m, 1 m, 1 m: a 1.73 m step) is authorized. The
        // command has no speed field, and the actor's payload is not
        // compared with OperationalLimits on this path.
        let mut runtime = configured_runtime();
        runtime
            .domain_mut()
            .actor_mut(ActorId(8))
            .unwrap()
            .load_permille = 1_000;
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = safe_context(&runtime);
        let mut far = command(1);
        far.argument0 = 1_000;
        far.argument1 = 1_000;
        far.argument2 = 1_000;
        assert!(runtime
            .authorize_and_queue_command(far, context, &[], 100)
            .is_ok());
    }

    #[test]
    fn stop_still_leaves_after_actor_emergency_stop() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let mut stop_frame = frame(2, 900, 101);
        stop_frame.payload = AdapterPayload::EmergencyStop {
            actor_id: ActorId(8),
            reason_code: 1,
        };
        runtime.ingest_adapter_frame(stop_frame, 101, 0).unwrap();
        let stop = runtime
            .authorize_and_queue_command(stop_command(2, 101), stop_context(), &[], 101)
            .unwrap();
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 102),
            Ok(Some(stop))
        );
    }

    #[test]
    fn permit_is_deliverable_up_to_and_including_its_expiry_tick() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = safe_context(&runtime);
        let routed = runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 105),
            Ok(Some(routed))
        );
    }

    #[test]
    fn watchdog_expiry_after_queueing_blocks_motion_delivery_but_not_stop() {
        let mut runtime = configured_runtime();
        runtime
            .register_watchdog(WatchdogState {
                id: 1,
                role: crate::supervisor::WatchdogRole::Controller,
                timeout_ticks: 3,
                last_heartbeat_tick: 100,
                armed: true,
            })
            .unwrap();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = safe_context(&runtime);
        runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        assert_eq!(
            runtime.authority_severity(104),
            AuthoritySeverity::EmergencyStop
        );
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 104),
            Err(RuntimeError::Supervisor(
                SupervisorError::AuthorityUnavailable
            ))
        );
        assert!(driver.commands().is_empty());
        assert_eq!(
            runtime.fleet().command_claim(1).unwrap().state,
            CommandDeliveryState::Queued
        );
        let stop = runtime
            .authorize_and_queue_command(stop_command(2, 104), stop_context(), &[], 104)
            .unwrap();
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 104),
            Ok(Some(stop))
        );
        assert_eq!(driver.commands().len(), 1);
    }

    #[test]
    fn controller_watchdog_stop_is_latched_until_recovery_is_complete() {
        let mut runtime = configured_runtime();
        runtime
            .register_watchdog(WatchdogState {
                id: 1,
                role: crate::supervisor::WatchdogRole::Controller,
                timeout_ticks: 5,
                last_heartbeat_tick: 100,
                armed: true,
            })
            .unwrap();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        assert_eq!(
            runtime.authority_severity(107),
            AuthoritySeverity::EmergencyStop
        );
        // A late heartbeat restores liveness but must not erase the stop.
        runtime.heartbeat_watchdog(1, 107).unwrap();
        assert_eq!(runtime.authority_severity(107), AuthoritySeverity::Allow);
        let context = safe_context(&runtime);
        assert_eq!(
            runtime.authorize_and_queue_command(command(1), context, &[], 107),
            Err(RuntimeError::Supervisor(
                SupervisorError::AuthorityUnavailable
            ))
        );
        assert!(runtime.fleet().command_claim(1).is_none());
        runtime.recovery_mut().observe_controller_safe();
        runtime.recovery_mut().observe_fresh_twin();
        runtime.recovery_mut().acknowledge_operator();
        runtime.recovery_mut().release().unwrap();
        assert!(runtime
            .authorize_and_queue_command(command(2), context, &[], 108)
            .is_ok());
    }

    #[test]
    fn only_simulation_and_actuator_disabled_pairings_ever_reach_a_driver() {
        struct ModeDriver {
            identity: AdapterIdentity,
            mode: DriverExecutionMode,
            submitted: usize,
        }

        impl AdapterDriver for ModeDriver {
            fn identity(&self) -> &AdapterIdentity {
                &self.identity
            }

            fn execution_mode(&self) -> DriverExecutionMode {
                self.mode
            }

            fn poll_frame(&mut self) -> Option<AdapterFrame> {
                None
            }

            fn submit(&mut self, _: RoutedCommand) -> Result<(), AdapterError> {
                self.submitted += 1;
                Ok(())
            }
        }

        for session_mode in [
            SessionMode::Simulation,
            SessionMode::RecordedPlayback,
            SessionMode::HardwareInLoopActuatorDisabled,
            SessionMode::Live,
        ] {
            for driver_mode in [
                DriverExecutionMode::Simulation,
                DriverExecutionMode::ActuatorDisabled,
                DriverExecutionMode::Physical,
            ] {
                let mut descriptor = SessionDescriptor::simulator(3, 1, 42);
                descriptor.mode = session_mode;
                let mut runtime = configured_runtime_with(descriptor, AdapterProtocol::Mqtt);
                let stop = runtime
                    .authorize_and_queue_command(stop_command(1, 100), stop_context(), &[], 100)
                    .unwrap();
                let mut driver = ModeDriver {
                    identity: runtime.adapters().adapter(AdapterId(1)).unwrap().clone(),
                    mode: driver_mode,
                    submitted: 0,
                };
                let outcome = runtime.deliver_next(AdapterId(1), &mut driver, 100);
                let expected = match (session_mode, driver_mode) {
                    (SessionMode::Live, _) => Err(RuntimeError::DeploymentUnqualified),
                    (SessionMode::Simulation, DriverExecutionMode::Simulation)
                    | (
                        SessionMode::HardwareInLoopActuatorDisabled,
                        DriverExecutionMode::ActuatorDisabled,
                    ) => Ok(Some(stop)),
                    _ => Err(RuntimeError::DriverModeMismatch),
                };
                assert_eq!(outcome, expected, "{session_mode:?}/{driver_mode:?}");
                assert_eq!(driver.submitted, usize::from(expected.is_ok()));
            }
        }
    }

    #[test]
    fn repeated_commands_are_rate_limited_and_keys_cannot_be_reused() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = safe_context(&runtime);
        for id in 1..=16 {
            runtime
                .authorize_and_queue_command(command(id), context, &[], 100)
                .unwrap();
        }
        assert_eq!(
            runtime.authorize_and_queue_command(command(17), context, &[], 100),
            Err(RuntimeError::Supervisor(SupervisorError::RateLimited))
        );
        assert_eq!(
            runtime.authorize_and_queue_command(command(1), context, &[], 100),
            Err(RuntimeError::Fleet(FleetError::DuplicateCommand))
        );
        let mut same_key = command(40);
        same_key.idempotency_key = command(2).idempotency_key;
        assert_eq!(
            runtime.authorize_and_queue_command(same_key, context, &[], 100),
            Err(RuntimeError::Fleet(FleetError::DuplicateCommand))
        );
        let identity = runtime.adapters().adapter(AdapterId(1)).unwrap().clone();
        let mut driver = SimulatedAdapter::new(identity).unwrap();
        for _ in 0..16 {
            assert!(runtime
                .deliver_next(AdapterId(1), &mut driver, 101)
                .unwrap()
                .is_some());
        }
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 101),
            Ok(None)
        );
        assert_eq!(driver.commands().len(), 16);
    }

    #[test]
    fn replay_steps_are_validated_and_refused_in_live_sessions() {
        let mut runtime = configured_runtime();
        assert_eq!(
            runtime.apply_replay_step(ReplayStep {
                run_id: 1,
                step_id: 1,
                at_tick: 100,
                action: ReplayAction::Checkpoint { checkpoint_id: 0 },
            }),
            Err(RuntimeError::Replay(ReplayError::InvalidAction))
        );
        assert!(runtime.evidence().records().is_empty());

        let mut descriptor = SessionDescriptor::simulator(10, 5, 43);
        descriptor.mode = SessionMode::Live;
        let mut live = configured_runtime_with(descriptor, AdapterProtocol::Mqtt);
        assert_eq!(
            live.apply_replay_step(ReplayStep {
                run_id: 10,
                step_id: 1,
                at_tick: 100,
                action: ReplayAction::ActivateFault(FaultSpec {
                    manifest_id: 9,
                    fault_code: 4,
                    target: FaultTarget::Sensor(9),
                    kind: FaultKind::DropFrame,
                    starts_at_tick: 100,
                    ends_at_tick: 200,
                }),
            }),
            Err(RuntimeError::Replay(ReplayError::InvalidDescriptor))
        );
        assert!(live.faults().active_faults().is_empty());
        assert!(live.evidence().records().is_empty());
    }

    #[test]
    fn transport_failure_becomes_uncertain_and_is_not_retried() {
        struct AmbiguousDriver {
            identity: AdapterIdentity,
        }

        impl AdapterDriver for AmbiguousDriver {
            fn identity(&self) -> &AdapterIdentity {
                &self.identity
            }

            fn execution_mode(&self) -> DriverExecutionMode {
                DriverExecutionMode::Simulation
            }

            fn poll_frame(&mut self) -> Option<AdapterFrame> {
                None
            }

            fn submit(&mut self, _: RoutedCommand) -> Result<(), AdapterError> {
                Err(AdapterError::AdapterUnavailable)
            }
        }

        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: runtime.twin().snapshot().latest_event_id,
            human_approved: true,
            requesting_actor_id: None,
        };
        runtime
            .authorize_and_queue_command(command(1), context, &[], 100)
            .unwrap();
        let mut driver = AmbiguousDriver {
            identity: runtime.adapters().adapter(AdapterId(1)).unwrap().clone(),
        };
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 100),
            Err(RuntimeError::DeliveryUncertain(
                AdapterError::AdapterUnavailable
            ))
        );
        assert_eq!(
            runtime.fleet().command_claim(1).unwrap().state,
            CommandDeliveryState::Uncertain
        );
        assert_eq!(
            runtime.deliver_next(AdapterId(1), &mut driver, 101),
            Ok(None)
        );
        assert_eq!(
            runtime
                .reliability()
                .snapshot(SiteId(1))
                .unwrap()
                .uncertain_commands,
            1
        );
        assert_eq!(
            runtime.evidence().records().back().unwrap().kind,
            EvidenceKind::DeliveryUncertain
        );
        assert_eq!(runtime.evidence().verify(), Ok(()));
    }

    #[test]
    fn evidence_time_reversal_rejects_input_before_twin_mutation() {
        let mut runtime = configured_runtime();
        runtime
            .ingest_adapter_frame(frame(1, 900, 100), 100, 0)
            .unwrap();
        assert_eq!(
            runtime.ingest_adapter_frame(frame(2, 800, 99), 99, 0),
            Err(RuntimeError::Session(SessionError::TimeReversal))
        );
        assert_eq!(runtime.twin().snapshot().latest_event_id, 1);
        assert_eq!(
            runtime
                .adapters()
                .adapter(AdapterId(1))
                .unwrap()
                .last_receive_sequence,
            1
        );
        assert_eq!(runtime.evidence().records().len(), 1);
    }

    #[test]
    fn resolved_intent_and_operator_action_have_bounded_public_recorders() {
        let mut runtime = configured_runtime();
        runtime.record_resolved_intent(10, 7, 2, 4).unwrap();
        runtime.record_operator_action(11, 8, 3).unwrap();
        assert_eq!(runtime.evidence().records().len(), 2);
        assert_eq!(
            runtime.evidence().records()[0].kind,
            EvidenceKind::IntentResolved
        );
        assert_eq!(
            runtime.evidence().records()[1].kind,
            EvidenceKind::OperatorAction
        );
        assert_eq!(runtime.evidence().verify(), Ok(()));
    }

    #[test]
    fn replay_faults_are_deterministic_and_preserve_twin_state() {
        let mut runtime = configured_runtime();
        let mut manifest = ReplayManifest::new(SessionDescriptor::simulator(1, 1, 42)).unwrap();
        manifest
            .push(
                100,
                ReplayAction::ActivateFault(FaultSpec {
                    manifest_id: 9,
                    fault_code: 4,
                    target: FaultTarget::Adapter(AdapterId(1)),
                    kind: FaultKind::DropFrame,
                    starts_at_tick: 100,
                    ends_at_tick: 102,
                }),
            )
            .unwrap();
        manifest
            .push(
                101,
                ReplayAction::IngestFrame {
                    frame: frame(1, 900, 101),
                    received_at_tick: 101,
                    observation_policy: ObservationPolicy::strict(0),
                },
            )
            .unwrap();
        manifest
            .push(
                103,
                ReplayAction::IngestFrame {
                    frame: frame(1, 800, 103),
                    received_at_tick: 103,
                    observation_policy: ObservationPolicy::strict(0),
                },
            )
            .unwrap();

        let mut cursor = manifest.cursor();
        assert_eq!(
            runtime.apply_replay_step(cursor.next_step().unwrap()),
            Ok(ReplayOutcome::FaultActivated { manifest_id: 9 })
        );
        assert_eq!(
            runtime.apply_replay_step(cursor.next_step().unwrap()),
            Ok(ReplayOutcome::FrameDropped)
        );
        assert_eq!(runtime.twin().snapshot().latest_event_id, 0);
        assert_eq!(
            runtime.apply_replay_step(cursor.next_step().unwrap()),
            Ok(ReplayOutcome::ObservationApplied { event_id: 1 })
        );
        assert_eq!(runtime.twin().snapshot().latest_event_id, 1);
        assert_eq!(runtime.evidence().verify(), Ok(()));
    }

    #[test]
    fn duplicate_fault_is_rejected_by_the_normal_adapter_replay_guard() {
        let mut runtime = configured_runtime();
        let fault = ReplayStep {
            run_id: 1,
            step_id: 1,
            at_tick: 100,
            action: ReplayAction::ActivateFault(FaultSpec {
                manifest_id: 10,
                fault_code: 5,
                target: FaultTarget::Endpoint(EndpointId(2)),
                kind: FaultKind::DuplicateFrame,
                starts_at_tick: 100,
                ends_at_tick: 100,
            }),
        };
        let duplicate = ReplayStep {
            run_id: 1,
            step_id: 2,
            at_tick: 100,
            action: ReplayAction::IngestFrame {
                frame: frame(1, 900, 100),
                received_at_tick: 100,
                observation_policy: ObservationPolicy::strict(0),
            },
        };
        runtime.apply_replay_step(fault).unwrap();
        assert_eq!(
            runtime.apply_replay_step(duplicate),
            Ok(ReplayOutcome::DuplicateRejected { event_id: 1 })
        );
        assert_eq!(runtime.twin().snapshot().retained_events, 1);
        assert_eq!(runtime.evidence().verify(), Ok(()));
    }

    #[test]
    fn replay_run_identity_is_bound_to_the_runtime_session() {
        let mut runtime = configured_runtime();
        assert_eq!(
            runtime.apply_replay_step(ReplayStep {
                run_id: 99,
                step_id: 1,
                at_tick: 1,
                action: ReplayAction::Pause,
            }),
            Err(RuntimeError::Replay(ReplayError::RunMismatch))
        );
        assert!(runtime.evidence().records().is_empty());
    }
}
