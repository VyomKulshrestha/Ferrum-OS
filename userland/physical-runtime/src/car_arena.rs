//! The Probots car on a marked floor rectangle under an overhead camera (roadmap milestone M1,
//! docs/research/vision_physical_agent_roadmap_v1.md). Branch work, not main.
//!
//! `CarArena` turns measured numbers into the arena's `SafetyPolicy`. `CarGate` runs one
//! hardware-in-loop, actuator-disabled runtime session: each tracked camera scene becomes two
//! adapter frames (the car's position, and the edge-to-edge clearance to the obstacle as a
//! proximity reading), and each proposed move is judged by the unchanged safety supervisor.
//! Everything here is measurement and fixed geometry; nothing predicts. Nothing reaches an
//! actuator either: the session mode keeps delivery to a physical driver closed.
//!
//! The policy turns the gate's two point checks into checks on the whole move. The step bound
//! limits a permit to `max_step_mm` from the last tracked position, so the clearance during the
//! move can shrink by at most that much; the clearance floor therefore adds the step and the
//! margin to the required clearance. The geofence is the marked rectangle inset by the car's
//! radius and the margin, and a rectangle is convex, so a straight move between two points in it
//! stays in it.

use alloc::string::ToString;

use crate::adapter::{
    AdapterCommand, AdapterFrame, AdapterId, AdapterIdentity, AdapterPayload, AdapterProtocol,
    AdapterState, CommandKind, Endpoint, EndpointCapability, EndpointCapabilitySet, EndpointId,
    EndpointKind,
};
use crate::contract::{
    CommandMetadata, ConfirmationProvenance, EvidenceClass, FaultProvenance, IntegrityEvidence,
    ObservationMetadata, ObservationPolicy, CYBER_PHYSICAL_SCHEMA_VERSION,
};
use crate::domain::{
    Actor, ActorId, ActorKind, ActorStatus, Capability, CapabilitySet, Position, QualificationSet,
    Site, SiteId,
};
use crate::fleet::{DeviceHealth, DeviceLifecycle, FleetDevice};
use crate::runtime::{PhysicalRuntime, RuntimeError};
use crate::safety::{Geofence, SafetyContext, SafetyDecision, SafetyPolicy};
use crate::session::{SessionDescriptor, SessionMode};
use crate::twin::{ActorTelemetry, SensorKind, SensorReading};

pub const CAR_ADAPTER_ID: AdapterId = AdapterId(1);
pub const CAR_ENDPOINT_ID: EndpointId = EndpointId(1);
pub const CAR_ACTOR_ID: ActorId = ActorId(1);
const SESSION_EPOCH: u64 = 1;
const SOURCE_CLOCK_ID: u64 = 1;

/// The arena and the car, in arena millimetres and milliseconds. The last five numbers are
/// measured on the real car before any test (roadmap M1, "Margin").
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CarArena {
    pub site_id: SiteId,
    pub zone_id: u32,
    pub policy_revision: u64,
    pub proximity_sensor_id: u64,
    pub arena_min_x_mm: i64,
    pub arena_max_x_mm: i64,
    pub arena_min_y_mm: i64,
    pub arena_max_y_mm: i64,
    /// Radius of a circle around the tracked centre that covers the car's body.
    pub car_radius_mm: i64,
    pub obstacle_radius_mm: i64,
    /// Edge-to-edge distance the car must keep from the obstacle.
    pub required_clearance_mm: i64,
    pub require_approval_for_motion: bool,
    pub ticks_per_second: u64,
    /// 99th-percentile tracker position error against tape-measured points.
    pub tracker_error_p99_mm: i64,
    /// The firmware's speed cap.
    pub max_speed_mm_per_s: i64,
    /// Camera capture to gate verdict.
    pub latency_ms: i64,
    /// Stop command to standstill.
    pub stop_ms: i64,
    pub max_step_mm: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CarArenaError {
    InvalidMeasurement,
    EmptyGeofence,
    Runtime(RuntimeError),
}

impl From<RuntimeError> for CarArenaError {
    fn from(error: RuntimeError) -> Self {
        Self::Runtime(error)
    }
}

const fn ceil_div(numerator: i64, denominator: i64) -> i64 {
    (numerator + denominator - 1) / denominator
}

impl CarArena {
    pub fn validate(&self) -> Result<(), CarArenaError> {
        let valid = self.arena_min_x_mm < self.arena_max_x_mm
            && self.arena_min_y_mm < self.arena_max_y_mm
            && self.car_radius_mm > 0
            && self.obstacle_radius_mm >= 0
            && self.required_clearance_mm >= 0
            && self.ticks_per_second > 0
            && self.tracker_error_p99_mm >= 0
            && self.max_speed_mm_per_s > 0
            && self.latency_ms >= 0
            && self.stop_ms >= 0
            && self.max_step_mm > 0
            && self.policy_revision > 0
            && self.proximity_sensor_id > 0;
        if valid {
            Ok(())
        } else {
            Err(CarArenaError::InvalidMeasurement)
        }
    }

    /// How far the car can be from where the gate believes it is when a move ends: tracker
    /// error plus top speed over the capture-to-verdict latency and the stopping time.
    pub const fn margin_mm(&self) -> i64 {
        self.tracker_error_p99_mm
            + ceil_div(
                self.max_speed_mm_per_s * (self.latency_ms + self.stop_ms),
                1_000,
            )
    }

    /// A reading older than the measured latency counts as missing.
    pub fn maximum_reading_age_ticks(&self) -> u64 {
        let ticks = ceil_div(self.latency_ms * self.ticks_per_second as i64, 1_000);
        if ticks < 1 {
            1
        } else {
            ticks as u64
        }
    }

    pub fn safety_policy(&self) -> Result<SafetyPolicy, CarArenaError> {
        self.validate()?;
        let inset = self.car_radius_mm + self.margin_mm();
        let geofence = Geofence {
            minimum_x_mm: self.arena_min_x_mm + inset,
            maximum_x_mm: self.arena_max_x_mm - inset,
            minimum_y_mm: self.arena_min_y_mm + inset,
            maximum_y_mm: self.arena_max_y_mm - inset,
            minimum_z_mm: 0,
            maximum_z_mm: 0,
        };
        if geofence.minimum_x_mm > geofence.maximum_x_mm
            || geofence.minimum_y_mm > geofence.maximum_y_mm
        {
            return Err(CarArenaError::EmptyGeofence);
        }
        let age = self.maximum_reading_age_ticks();
        Ok(SafetyPolicy {
            site_id: self.site_id,
            zone_id: self.zone_id,
            revision: self.policy_revision,
            geofence,
            proximity_sensor_id: Some(self.proximity_sensor_id),
            minimum_clearance_mm: self.required_clearance_mm + self.margin_mm() + self.max_step_mm,
            maximum_step_mm: Some(self.max_step_mm),
            maximum_sensor_age_ticks: age,
            permit_ttl_ticks: age,
            allow_motion_with_humans: false,
            require_human_approval_for_motion: self.require_approval_for_motion,
            require_human_approval_for_actuation: true,
            // Learned predictions are shadow-only outside simulation sessions.
            learned_warning_threshold_permille: 600,
            learned_block_threshold_permille: 800,
        })
    }

    /// Edge-to-edge clearance between the car's covering circle and the obstacle, rounded down.
    pub fn clearance_mm(&self, scene: &TrackedScene) -> i64 {
        let dx = f64::from(scene.robot_x_mm) - f64::from(scene.obstacle_x_mm);
        let dy = f64::from(scene.robot_y_mm) - f64::from(scene.obstacle_y_mm);
        let centre = libm::floor(libm::sqrt(dx * dx + dy * dy)) as i64;
        centre - self.car_radius_mm - self.obstacle_radius_mm
    }
}

/// One overhead-camera scene in which both the car and the obstacle were seen. The tracker never
/// reports a scene it did not see; missing scenes let the readings age out, which blocks motion.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TrackedScene {
    pub captured_at_tick: u64,
    pub robot_x_mm: i32,
    pub robot_y_mm: i32,
    pub obstacle_x_mm: i32,
    pub obstacle_y_mm: i32,
    pub quality_permille: u16,
}

/// Session identity. The digests name the configuration this session judged under; the
/// transport digest stands for the tracker link's authentication, which the M1 harness does not
/// yet provide cryptographically (roadmap M2: kernel-owned evidence service).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CarSessionIdentity {
    pub run_id: u64,
    pub started_at_tick: u64,
    pub topology_sha256: [u8; 32],
    pub policy_sha256: [u8; 32],
    pub transport_digest: [u8; 32],
}

pub struct CarGate {
    runtime: PhysicalRuntime,
    arena: CarArena,
    policy: SafetyPolicy,
    transport_digest: [u8; 32],
    frame_sequence: u64,
}

impl CarGate {
    pub fn new(arena: CarArena, identity: CarSessionIdentity) -> Result<Self, CarArenaError> {
        let policy = arena.safety_policy()?;
        let mut runtime = PhysicalRuntime::new_with_session(SessionDescriptor {
            run_id: identity.run_id,
            parent_run_id: 0,
            fork_sequence: 0,
            simulator_epoch: 1,
            seed: 0,
            started_at_tick: identity.started_at_tick,
            mode: SessionMode::HardwareInLoopActuatorDisabled,
            topology_sha256: identity.topology_sha256,
            policy_sha256: identity.policy_sha256,
            model_sha256: [0xFF; 32], // no learned model takes part in the decision
        })?;
        runtime
            .domain_mut()
            .register_site(Site {
                id: arena.site_id,
                name: "car arena".to_string(),
                emergency_zone_id: arena.zone_id,
            })
            .map_err(|_| CarArenaError::InvalidMeasurement)?;
        runtime
            .domain_mut()
            .register_actor(Actor {
                id: CAR_ACTOR_ID,
                name: "Probots 2WD car".to_string(),
                kind: ActorKind::Robot,
                status: ActorStatus::Available,
                site_id: arena.site_id,
                // registered, never observed: the step bound treats this as no position
                position: Position::origin(arena.zone_id, 0),
                capabilities: CapabilitySet::empty().with(Capability::Navigate),
                qualifications: QualificationSet::empty(),
                available_from_tick: 0,
                last_seen_tick: 0,
                battery_permille: 1_000,
                load_permille: 0,
                max_payload_grams: 1,
            })
            .map_err(|_| CarArenaError::InvalidMeasurement)?;
        let identity_record = AdapterIdentity {
            id: CAR_ADAPTER_ID,
            site_id: arena.site_id,
            protocol: AdapterProtocol::VendorRpc,
            public_key_sha256: identity.transport_digest,
            firmware_version: 1,
            session_epoch: SESSION_EPOCH,
            state: AdapterState::Online,
            last_seen_tick: identity.started_at_tick,
            last_receive_sequence: 0,
        };
        runtime
            .adapters_mut()
            .register_adapter(identity_record)
            .map_err(|error| CarArenaError::Runtime(RuntimeError::Adapter(error)))?;
        runtime
            .adapters_mut()
            .register_endpoint(Endpoint {
                id: CAR_ENDPOINT_ID,
                adapter_id: CAR_ADAPTER_ID,
                kind: EndpointKind::Robot,
                zone_id: arena.zone_id,
                controlled_actor_id: Some(CAR_ACTOR_ID),
                capabilities: EndpointCapabilitySet::empty()
                    .with(EndpointCapability::Sense)
                    .with(EndpointCapability::Move)
                    .with(EndpointCapability::EmergencyStop),
            })
            .map_err(|error| CarArenaError::Runtime(RuntimeError::Adapter(error)))?;
        runtime
            .fleet_mut()
            .provision(FleetDevice {
                adapter_id: CAR_ADAPTER_ID,
                site_id: arena.site_id,
                identity_sha256: identity.transport_digest,
                lifecycle: DeviceLifecycle::Provisioning,
                firmware_version: 1,
                minimum_allowed_firmware_version: 1,
                session_epoch: SESSION_EPOCH,
                last_seen_tick: identity.started_at_tick,
                health: DeviceHealth {
                    battery_permille: 1_000,
                    link_quality_permille: 1_000,
                    fault_code: 0,
                },
            })
            .map_err(|error| CarArenaError::Runtime(RuntimeError::Fleet(error)))?;
        runtime
            .fleet_mut()
            .activate(CAR_ADAPTER_ID, SESSION_EPOCH, identity.started_at_tick)
            .map_err(|error| CarArenaError::Runtime(RuntimeError::Fleet(error)))?;
        runtime
            .safety_mut()
            .install_policy(policy)
            .map_err(|error| CarArenaError::Runtime(RuntimeError::Safety(error)))?;
        Ok(Self {
            runtime,
            arena,
            policy,
            transport_digest: identity.transport_digest,
            frame_sequence: 0,
        })
    }

    pub fn policy(&self) -> &SafetyPolicy {
        &self.policy
    }

    pub fn runtime(&self) -> &PhysicalRuntime {
        &self.runtime
    }

    fn metadata(&mut self, captured_at_tick: u64) -> ObservationMetadata {
        self.frame_sequence += 1;
        ObservationMetadata {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            source_clock_id: SOURCE_CLOCK_ID,
            clock_uncertainty_ticks: 0,
            frame_id: self.frame_sequence,
            expires_at_tick: captured_at_tick + self.policy.maximum_sensor_age_ticks,
            evidence_class: EvidenceClass::HardwareInLoop,
            fault_provenance: FaultProvenance::None,
            integrity: IntegrityEvidence::TransportAuthenticated(self.transport_digest),
        }
    }

    /// Ingest one tracked scene as the car's position and the obstacle clearance. Returns the
    /// twin's latest event id.
    pub fn ingest(
        &mut self,
        scene: &TrackedScene,
        received_at_tick: u64,
    ) -> Result<u64, CarArenaError> {
        let observation_policy = ObservationPolicy {
            maximum_clock_skew_ticks: 0,
            maximum_clock_uncertainty_ticks: 0,
            maximum_observation_age_ticks: self.policy.maximum_sensor_age_ticks,
        };
        let tick = scene.captured_at_tick;
        let position = AdapterFrame {
            adapter_id: CAR_ADAPTER_ID,
            endpoint_id: CAR_ENDPOINT_ID,
            session_epoch: SESSION_EPOCH,
            sequence: self.frame_sequence + 1,
            observed_at_tick: tick,
            metadata: self.metadata(tick),
            payload: AdapterPayload::ActorTelemetry(ActorTelemetry {
                actor_id: CAR_ACTOR_ID,
                position: Position {
                    x_mm: scene.robot_x_mm,
                    y_mm: scene.robot_y_mm,
                    z_mm: 0,
                    zone_id: self.arena.zone_id,
                    observed_at_tick: tick,
                },
                battery_permille: 1_000,
                load_permille: 0,
                status: ActorStatus::Available,
            }),
        };
        self.runtime.ingest_adapter_frame_with_policy(
            position,
            received_at_tick,
            observation_policy,
        )?;
        let clearance = AdapterFrame {
            adapter_id: CAR_ADAPTER_ID,
            endpoint_id: CAR_ENDPOINT_ID,
            session_epoch: SESSION_EPOCH,
            sequence: self.frame_sequence + 1,
            observed_at_tick: tick,
            metadata: self.metadata(tick),
            payload: AdapterPayload::SensorReading(SensorReading {
                sensor_id: self.arena.proximity_sensor_id,
                site_id: self.arena.site_id,
                asset_id: None,
                kind: SensorKind::ProximityMillimeters,
                value: self.arena.clearance_mm(scene),
                quality_permille: scene.quality_permille,
                observed_at_tick: tick,
            }),
        };
        self.runtime.ingest_adapter_frame_with_policy(
            clearance,
            received_at_tick,
            observation_policy,
        )?;
        Ok(self.runtime.twin().snapshot().latest_event_id)
    }

    /// Judge a move of the car's centre to (x, y) at `tick`, against the facts in the twin.
    pub fn propose(
        &mut self,
        command_id: u64,
        target_x_mm: i64,
        target_y_mm: i64,
        tick: u64,
        human_approved: bool,
    ) -> Result<SafetyDecision, CarArenaError> {
        let event_id = self.runtime.twin().snapshot().latest_event_id;
        let confirmation = if human_approved {
            ConfirmationProvenance::LocalHuman {
                confirmation_id: command_id,
            }
        } else {
            ConfirmationProvenance::NotRequired
        };
        let command = AdapterCommand {
            command_id,
            idempotency_key: command_id,
            adapter_id: CAR_ADAPTER_ID,
            endpoint_id: CAR_ENDPOINT_ID,
            session_epoch: SESSION_EPOCH,
            kind: CommandKind::MoveTo,
            argument0: target_x_mm,
            argument1: target_y_mm,
            argument2: 0,
            deadline_tick: tick + self.policy.permit_ttl_ticks,
            metadata: CommandMetadata::kernel(
                tick,
                self.policy.revision,
                event_id,
                EndpointCapability::Move,
                confirmation,
            ),
        };
        let context = SafetyContext {
            expected_policy_revision: self.policy.revision,
            expected_twin_event_id: event_id,
            human_approved,
            requesting_actor_id: None,
        };
        Ok(self.runtime.preview_command(&command, context, &[], tick)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::safety::{SafetyReason, SafetyVerdict};

    /// Placeholder measurements of the order expected on the kit: 1.0 x 0.75 m arena, 9 cm
    /// covering radius, a 4 cm cup, 5 cm required clearance, 100 ticks per second.
    fn arena() -> CarArena {
        CarArena {
            site_id: SiteId(1),
            zone_id: 1,
            policy_revision: 1,
            proximity_sensor_id: 1,
            arena_min_x_mm: 0,
            arena_max_x_mm: 1_000,
            arena_min_y_mm: 0,
            arena_max_y_mm: 750,
            car_radius_mm: 90,
            obstacle_radius_mm: 40,
            required_clearance_mm: 50,
            require_approval_for_motion: false,
            ticks_per_second: 100,
            tracker_error_p99_mm: 15,
            max_speed_mm_per_s: 200,
            latency_ms: 150,
            stop_ms: 100,
            max_step_mm: 100,
        }
    }

    fn gate() -> CarGate {
        CarGate::new(
            arena(),
            CarSessionIdentity {
                run_id: 1,
                started_at_tick: 1_000,
                topology_sha256: [1; 32],
                policy_sha256: [2; 32],
                transport_digest: [4; 32],
            },
        )
        .unwrap()
    }

    fn scene(tick: u64, robot: (i32, i32)) -> TrackedScene {
        TrackedScene {
            captured_at_tick: tick,
            robot_x_mm: robot.0,
            robot_y_mm: robot.1,
            obstacle_x_mm: 700,
            obstacle_y_mm: 400,
            quality_permille: 900,
        }
    }

    #[test]
    fn policy_comes_from_the_measurements() {
        let arena = arena();
        assert_eq!(arena.margin_mm(), 15 + 50); // 200 mm/s over 250 ms
        assert_eq!(arena.maximum_reading_age_ticks(), 15);
        let policy = arena.safety_policy().unwrap();
        assert_eq!(policy.geofence.minimum_x_mm, 155);
        assert_eq!(policy.geofence.maximum_x_mm, 845);
        assert_eq!(policy.geofence.maximum_y_mm, 595);
        assert_eq!(policy.minimum_clearance_mm, 50 + 65 + 100);
        assert_eq!(policy.maximum_step_mm, Some(100));
    }

    #[test]
    fn impossible_measurements_and_too_small_arenas_are_rejected() {
        let mut bad = arena();
        bad.max_step_mm = 0;
        assert_eq!(bad.safety_policy(), Err(CarArenaError::InvalidMeasurement));
        let mut small = arena();
        small.arena_max_y_mm = 300;
        assert_eq!(small.safety_policy(), Err(CarArenaError::EmptyGeofence));
    }

    #[test]
    fn clearance_is_edge_to_edge_and_rounded_down() {
        // centre distance 500 mm minus 90 + 40
        assert_eq!(arena().clearance_mm(&scene(0, (200, 400))), 370);
        // 3-4-5 triangle scaled: 250 mm
        assert_eq!(arena().clearance_mm(&scene(0, (550, 200))), 120);
    }

    #[test]
    fn short_move_with_fresh_facts_is_allowed() {
        let mut gate = gate();
        gate.ingest(&scene(1_010, (300, 300)), 1_012).unwrap();
        let decision = gate.propose(1, 360, 340, 1_012, false).unwrap();
        assert_eq!(
            decision.verdict,
            SafetyVerdict::Allow,
            "{:?}",
            decision.reasons
        );
    }

    #[test]
    fn long_move_far_target_and_near_obstacle_are_blocked_for_their_own_reasons() {
        let mut gate = gate();
        gate.ingest(&scene(1_010, (300, 300)), 1_012).unwrap();
        let long = gate.propose(1, 500, 300, 1_012, false).unwrap();
        assert_eq!(long.reasons, alloc::vec![SafetyReason::MoveStepTooLong]);
        let outside = gate.propose(2, 300, 640, 1_012, false).unwrap();
        assert!(outside.reasons.contains(&SafetyReason::GeofenceViolation));

        // 260 mm from the obstacle's centre: clearance 130 < 215
        gate.ingest(&scene(1_020, (440, 400)), 1_021).unwrap();
        let near = gate.propose(3, 400, 400, 1_021, false).unwrap();
        assert_eq!(near.verdict, SafetyVerdict::Block);
        assert!(near.reasons.contains(&SafetyReason::UnsafeProximity));
    }

    #[test]
    fn no_scene_or_an_old_scene_blocks_motion() {
        let mut gate = gate();
        let unseen = gate.propose(1, 300, 300, 1_005, false).unwrap();
        assert!(unseen.reasons.contains(&SafetyReason::StaleProximitySensor));
        assert!(unseen.reasons.contains(&SafetyReason::StaleActorPosition));

        gate.ingest(&scene(1_010, (300, 300)), 1_012).unwrap();
        // tracking lost: nothing new for longer than the measured latency
        let lost = gate.propose(2, 320, 300, 1_026, false).unwrap();
        assert!(lost.reasons.contains(&SafetyReason::StaleProximitySensor));
        assert!(lost.reasons.contains(&SafetyReason::StaleActorPosition));
    }

    #[test]
    fn a_scene_older_than_the_latency_is_refused_at_ingest() {
        let mut gate = gate();
        assert!(gate.ingest(&scene(1_000, (300, 300)), 1_020).is_err());
    }

    #[test]
    fn stop_is_never_blocked_by_missing_facts() {
        let mut gate = gate();
        let event_id = gate.runtime.twin().snapshot().latest_event_id;
        let stop = AdapterCommand {
            command_id: 9,
            idempotency_key: 9,
            adapter_id: CAR_ADAPTER_ID,
            endpoint_id: CAR_ENDPOINT_ID,
            session_epoch: SESSION_EPOCH,
            kind: CommandKind::Stop,
            argument0: 0,
            argument1: 0,
            argument2: 0,
            deadline_tick: 1_100,
            metadata: CommandMetadata::kernel(
                1_050,
                1,
                event_id,
                EndpointCapability::EmergencyStop,
                ConfirmationProvenance::NotRequired,
            ),
        };
        let context = SafetyContext {
            expected_policy_revision: 1,
            expected_twin_event_id: event_id,
            human_approved: false,
            requesting_actor_id: None,
        };
        let decision = gate
            .runtime
            .preview_command(&stop, context, &[], 1_050)
            .unwrap();
        assert_eq!(decision.verdict, SafetyVerdict::Allow);
    }
}
