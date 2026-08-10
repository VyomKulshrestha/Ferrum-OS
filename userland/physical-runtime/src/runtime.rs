//! Single-owner orchestration boundary for physical operations.
//!
//! The runtime composes scheduling, the twin, safety, privacy, fleet delivery,
//! and reliability under one mutable owner. This prevents a preview/execute race
//! inside one operation and makes cross-service sequencing explicit.

use crate::adapter::{
    AdapterCommand, AdapterDriver, AdapterError, AdapterFrame, AdapterId, AdapterRegistry,
    AdapterState, RoutedCommand,
};
use crate::domain::{DomainRegistry, SiteId};
use crate::fleet::{CommandDeliveryState, DeviceHealth, DeviceLifecycle, FleetError, FleetManager};
use crate::privacy::{DataAccessRequest, PrivacyDecision, PrivacyGuard};
use crate::reliability::{
    ReliabilityError, ReliabilityEvent, ReliabilityEventKind, ReliabilityMonitor,
};
use crate::safety::{
    PhysicalPrediction, SafetyContext, SafetyDecision, SafetyError, SafetyReason, SafetySupervisor,
    SafetyVerdict,
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
    DeliveryUncertain(AdapterError),
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
        let mut twin = OperationalTwin::new();
        // The empty twin always has room. Reserving before any adapter traffic
        // prevents hostile source exhaustion from disabling work/safety records.
        let reserved = twin.reserve_source(RUNTIME_TWIN_SOURCE_ID);
        debug_assert!(reserved.is_ok());
        Self {
            domain: DomainRegistry::new(),
            work: WorkGraph::new(),
            twin,
            adapters: AdapterRegistry::new(),
            safety: SafetySupervisor::new(),
            fleet: FleetManager::new(),
            privacy: PrivacyGuard::new(),
            reliability: ReliabilityMonitor::new(),
            runtime_twin_sequence: 0,
            reliability_event_id: 0,
        }
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
        self.adapters
            .ingest_frame(
                &mut self.twin,
                &mut self.domain,
                frame,
                received_at_tick,
                maximum_clock_skew_ticks,
            )
            .map_err(RuntimeError::Adapter)
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
        &self,
        command: &AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
    ) -> Result<SafetyDecision, RuntimeError> {
        self.safety
            .evaluate(
                &self.adapters,
                &self.domain,
                &self.twin,
                command,
                context,
                predictions,
                current_tick,
            )
            .map_err(RuntimeError::Safety)
    }

    pub fn authorize_and_queue_command(
        &mut self,
        command: AdapterCommand,
        context: SafetyContext,
        predictions: &[PhysicalPrediction],
        current_tick: u64,
    ) -> Result<RoutedCommand, RuntimeError> {
        let decision = self.preview_command(&command, context, predictions, current_tick)?;
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
                },
                current_tick,
            )
            .map_err(RuntimeError::Fleet)?;
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
        Ok(routed)
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
        let routed = match self.fleet.claim_next_ready(adapter_id, tick) {
            Some(routed) => routed,
            None => return Ok(None),
        };
        match driver.submit(routed) {
            Ok(()) => {
                self.fleet
                    .record_delivery(
                        routed.command.command_id,
                        CommandDeliveryState::Acknowledged,
                        tick,
                    )
                    .map_err(RuntimeError::Fleet)?;
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
            .map_err(RuntimeError::Adapter)
    }

    pub fn evaluate_data_access(
        &mut self,
        request: DataAccessRequest,
        current_tick: u64,
    ) -> PrivacyDecision {
        self.privacy.evaluate(request, current_tick)
    }

    fn append_runtime_event(
        &mut self,
        tick: u64,
        payload: EventPayload,
    ) -> Result<u64, RuntimeError> {
        let next_sequence = self.runtime_twin_sequence.saturating_add(1);
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
        let next_id = self.reliability_event_id.saturating_add(1);
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
        SafetyReason::EmergencyStoppedActor => 12,
        SafetyReason::PredictiveWarning => 13,
        SafetyReason::PredictiveBlock => 14,
        SafetyReason::PredictiveShadowOnly => 15,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{
        AdapterIdentity, AdapterPayload, AdapterProtocol, Endpoint, EndpointCapability,
        EndpointCapabilitySet, EndpointId, EndpointKind, SimulatedAdapter,
    };
    use crate::domain::{
        Actor, ActorId, ActorKind, ActorStatus, Asset, AssetId, AssetState, Capability,
        CapabilitySet, Position, Qualification, QualificationSet, Site,
    };
    use crate::fleet::{DeviceLifecycle, FleetDevice};
    use crate::safety::{Geofence, SafetyPolicy};
    use crate::twin::{SensorKind, SensorReading};
    use crate::work::{ActorConstraint, JobState, Priority, TaskId, TaskStatus, WorkTask};
    use alloc::string::ToString;
    use alloc::vec;

    fn configured_runtime() -> PhysicalRuntime {
        let mut runtime = PhysicalRuntime::new();
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
        }
    }

    #[test]
    fn work_lifecycle_updates_twin_and_reliability_as_one_owner() {
        let mut runtime = configured_runtime();
        runtime.submit_work_order(order()).unwrap();
        let receipt = runtime.dispatch_next(100, 10).unwrap();
        let running_revision = runtime.start_task(receipt, receipt.revision, 101).unwrap();
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
    }
}
