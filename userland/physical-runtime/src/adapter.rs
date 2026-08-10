//! Protocol-neutral physical adapter boundary.
//!
//! Vendor transports terminate outside the scheduler. Adapters translate ROS,
//! MQTT, CAN, industrial, wearable, or simulator traffic into the same typed
//! event and command envelopes. Commands cannot be routed without an
//! [`ExecutionPermit`], whose constructor is crate-private and issued only by
//! the independent safety supervisor.

use alloc::collections::VecDeque;
use alloc::vec::Vec;

use crate::domain::{ActorId, DomainRegistry, SiteId};
use crate::twin::{
    ActorTelemetry, AssetTelemetry, EventEnvelope, EventPayload, OperationalTwin, SensorReading,
    TwinError, ZoneOccupancy,
};

pub const MAX_ADAPTERS: usize = 128;
pub const MAX_ENDPOINTS: usize = 512;
pub const MAX_COMMAND_CLAIMS: usize = 1_024;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct AdapterId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct EndpointId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdapterProtocol {
    Ros2Dds,
    Mqtt,
    CanOpen,
    ModbusTcp,
    OpcUa,
    BleGatt,
    VendorRpc,
    Simulator,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdapterState {
    Provisioning,
    Online,
    Degraded,
    Offline,
    Quarantined,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EndpointKind {
    Sensor,
    Actuator,
    Robot,
    Wearable,
    Gateway,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum EndpointCapability {
    Sense = 0,
    Actuate = 1,
    Move = 2,
    EmergencyStop = 3,
    DisplayInstruction = 4,
    Acknowledge = 5,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct EndpointCapabilitySet(u64);

impl EndpointCapabilitySet {
    pub const fn empty() -> Self {
        Self(0)
    }

    pub const fn with(self, capability: EndpointCapability) -> Self {
        Self(self.0 | (1u64 << capability as u8))
    }

    pub const fn contains(self, capability: EndpointCapability) -> bool {
        self.0 & (1u64 << capability as u8) != 0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdapterIdentity {
    pub id: AdapterId,
    pub site_id: SiteId,
    pub protocol: AdapterProtocol,
    pub public_key_sha256: [u8; 32],
    pub firmware_version: u32,
    pub session_epoch: u64,
    pub state: AdapterState,
    pub last_seen_tick: u64,
    pub last_receive_sequence: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Endpoint {
    pub id: EndpointId,
    pub adapter_id: AdapterId,
    pub kind: EndpointKind,
    pub zone_id: u32,
    pub controlled_actor_id: Option<ActorId>,
    pub capabilities: EndpointCapabilitySet,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdapterPayload {
    ActorTelemetry(ActorTelemetry),
    AssetTelemetry(AssetTelemetry),
    SensorReading(SensorReading),
    ZoneOccupancy(ZoneOccupancy),
    EmergencyStop { actor_id: ActorId, reason_code: u32 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AdapterFrame {
    pub adapter_id: AdapterId,
    pub endpoint_id: EndpointId,
    pub session_epoch: u64,
    pub sequence: u64,
    pub observed_at_tick: u64,
    pub payload: AdapterPayload,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandKind {
    ReadSensor,
    SetOutput,
    MoveTo,
    Stop,
    DisplayInstruction,
    Acknowledge,
}

impl CommandKind {
    fn required_capability(self) -> EndpointCapability {
        match self {
            Self::ReadSensor => EndpointCapability::Sense,
            Self::SetOutput => EndpointCapability::Actuate,
            Self::MoveTo => EndpointCapability::Move,
            Self::Stop => EndpointCapability::EmergencyStop,
            Self::DisplayInstruction => EndpointCapability::DisplayInstruction,
            Self::Acknowledge => EndpointCapability::Acknowledge,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AdapterCommand {
    pub command_id: u64,
    pub idempotency_key: u64,
    pub adapter_id: AdapterId,
    pub endpoint_id: EndpointId,
    pub session_epoch: u64,
    pub kind: CommandKind,
    pub argument0: i64,
    pub argument1: i64,
    pub argument2: i64,
    pub deadline_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RoutedCommand {
    pub command: AdapterCommand,
    pub policy_revision: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ExecutionPermit {
    command_id: u64,
    expires_at_tick: u64,
    policy_revision: u64,
}

impl ExecutionPermit {
    pub(crate) const fn new(command_id: u64, expires_at_tick: u64, policy_revision: u64) -> Self {
        Self {
            command_id,
            expires_at_tick,
            policy_revision,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdapterError {
    DuplicateAdapter,
    DuplicateEndpoint,
    UnknownAdapter,
    UnknownEndpoint,
    InvalidIdentity,
    CapacityExceeded,
    AdapterUnavailable,
    SessionMismatch,
    DuplicateOrOutOfOrder,
    EndpointMismatch,
    UnsupportedCommand,
    PermitMismatch,
    PermitExpired,
    CommandExpired,
    DuplicateCommand,
    TwinRejected(TwinError),
}

#[derive(Debug, Default)]
pub struct AdapterRegistry {
    adapters: Vec<AdapterIdentity>,
    endpoints: Vec<Endpoint>,
    command_claims: Vec<u64>,
    next_event_id: u64,
}

impl AdapterRegistry {
    pub const fn new() -> Self {
        Self {
            adapters: Vec::new(),
            endpoints: Vec::new(),
            command_claims: Vec::new(),
            next_event_id: 1,
        }
    }

    pub fn register_adapter(&mut self, identity: AdapterIdentity) -> Result<(), AdapterError> {
        if identity.public_key_sha256.iter().all(|byte| *byte == 0) || identity.session_epoch == 0 {
            return Err(AdapterError::InvalidIdentity);
        }
        if self.adapters.iter().any(|entry| entry.id == identity.id) {
            return Err(AdapterError::DuplicateAdapter);
        }
        if self.adapters.len() >= MAX_ADAPTERS {
            return Err(AdapterError::CapacityExceeded);
        }
        self.adapters.push(identity);
        Ok(())
    }

    pub fn register_endpoint(&mut self, endpoint: Endpoint) -> Result<(), AdapterError> {
        if !self
            .adapters
            .iter()
            .any(|adapter| adapter.id == endpoint.adapter_id)
        {
            return Err(AdapterError::UnknownAdapter);
        }
        if self.endpoints.iter().any(|entry| entry.id == endpoint.id) {
            return Err(AdapterError::DuplicateEndpoint);
        }
        if self.endpoints.len() >= MAX_ENDPOINTS {
            return Err(AdapterError::CapacityExceeded);
        }
        self.endpoints.push(endpoint);
        Ok(())
    }

    pub fn set_state(
        &mut self,
        adapter_id: AdapterId,
        state: AdapterState,
        tick: u64,
    ) -> Result<(), AdapterError> {
        let adapter = self
            .adapters
            .iter_mut()
            .find(|entry| entry.id == adapter_id)
            .ok_or(AdapterError::UnknownAdapter)?;
        adapter.state = state;
        adapter.last_seen_tick = tick;
        Ok(())
    }

    pub fn adapter(&self, id: AdapterId) -> Option<&AdapterIdentity> {
        self.adapters.iter().find(|adapter| adapter.id == id)
    }

    pub fn endpoint(&self, id: EndpointId) -> Option<&Endpoint> {
        self.endpoints.iter().find(|endpoint| endpoint.id == id)
    }

    pub fn ingest_frame(
        &mut self,
        twin: &mut OperationalTwin,
        domain: &mut DomainRegistry,
        frame: AdapterFrame,
        received_at_tick: u64,
        maximum_clock_skew_ticks: u64,
    ) -> Result<u64, AdapterError> {
        let adapter_index = self
            .adapters
            .iter()
            .position(|adapter| adapter.id == frame.adapter_id)
            .ok_or(AdapterError::UnknownAdapter)?;
        let adapter = &self.adapters[adapter_index];
        if !matches!(adapter.state, AdapterState::Online | AdapterState::Degraded) {
            return Err(AdapterError::AdapterUnavailable);
        }
        if frame.session_epoch != adapter.session_epoch {
            return Err(AdapterError::SessionMismatch);
        }
        if frame.sequence <= adapter.last_receive_sequence {
            return Err(AdapterError::DuplicateOrOutOfOrder);
        }
        let endpoint = self
            .endpoint(frame.endpoint_id)
            .ok_or(AdapterError::UnknownEndpoint)?;
        if endpoint.adapter_id != frame.adapter_id {
            return Err(AdapterError::EndpointMismatch);
        }
        if !endpoint_accepts_payload(endpoint, frame.payload) {
            return Err(AdapterError::EndpointMismatch);
        }

        let event_id = self.next_event_id;
        twin.apply(
            domain,
            EventEnvelope {
                event_id,
                source_id: frame.adapter_id.0,
                source_sequence: frame.sequence,
                observed_at_tick: frame.observed_at_tick,
                received_at_tick,
                payload: frame.payload.into(),
            },
            maximum_clock_skew_ticks,
        )
        .map_err(AdapterError::TwinRejected)?;

        let adapter = &mut self.adapters[adapter_index];
        adapter.last_receive_sequence = frame.sequence;
        adapter.last_seen_tick = received_at_tick;
        self.next_event_id = self.next_event_id.saturating_add(1);
        Ok(event_id)
    }

    pub(crate) fn route_authorized(
        &mut self,
        command: AdapterCommand,
        permit: ExecutionPermit,
        current_tick: u64,
    ) -> Result<RoutedCommand, AdapterError> {
        if permit.command_id != command.command_id {
            return Err(AdapterError::PermitMismatch);
        }
        if current_tick > permit.expires_at_tick {
            return Err(AdapterError::PermitExpired);
        }
        if current_tick > command.deadline_tick {
            return Err(AdapterError::CommandExpired);
        }
        let adapter = self
            .adapter(command.adapter_id)
            .ok_or(AdapterError::UnknownAdapter)?;
        if adapter.state != AdapterState::Online {
            return Err(AdapterError::AdapterUnavailable);
        }
        if adapter.session_epoch != command.session_epoch {
            return Err(AdapterError::SessionMismatch);
        }
        let endpoint = self
            .endpoint(command.endpoint_id)
            .ok_or(AdapterError::UnknownEndpoint)?;
        if endpoint.adapter_id != command.adapter_id {
            return Err(AdapterError::EndpointMismatch);
        }
        if !endpoint
            .capabilities
            .contains(command.kind.required_capability())
        {
            return Err(AdapterError::UnsupportedCommand);
        }
        if self.command_claims.contains(&command.idempotency_key) {
            return Err(AdapterError::DuplicateCommand);
        }
        if self.command_claims.len() >= MAX_COMMAND_CLAIMS {
            return Err(AdapterError::CapacityExceeded);
        }
        self.command_claims.push(command.idempotency_key);
        Ok(RoutedCommand {
            command,
            policy_revision: permit.policy_revision,
        })
    }
}

impl From<AdapterPayload> for EventPayload {
    fn from(payload: AdapterPayload) -> Self {
        match payload {
            AdapterPayload::ActorTelemetry(value) => Self::ActorTelemetry(value),
            AdapterPayload::AssetTelemetry(value) => Self::AssetTelemetry(value),
            AdapterPayload::SensorReading(value) => Self::SensorReading(value),
            AdapterPayload::ZoneOccupancy(value) => Self::ZoneOccupancy(value),
            AdapterPayload::EmergencyStop {
                actor_id,
                reason_code,
            } => Self::EmergencyStop {
                actor_id,
                reason_code,
            },
        }
    }
}

fn endpoint_accepts_payload(endpoint: &Endpoint, payload: AdapterPayload) -> bool {
    match payload {
        AdapterPayload::SensorReading(_) | AdapterPayload::ZoneOccupancy(_) => {
            endpoint.capabilities.contains(EndpointCapability::Sense)
        }
        AdapterPayload::ActorTelemetry(_) => matches!(
            endpoint.kind,
            EndpointKind::Robot | EndpointKind::Wearable | EndpointKind::Gateway
        ),
        AdapterPayload::AssetTelemetry(_) => {
            matches!(endpoint.kind, EndpointKind::Sensor | EndpointKind::Gateway)
        }
        AdapterPayload::EmergencyStop { .. } => endpoint
            .capabilities
            .contains(EndpointCapability::EmergencyStop),
    }
}

pub trait AdapterDriver {
    fn identity(&self) -> &AdapterIdentity;
    fn poll_frame(&mut self) -> Option<AdapterFrame>;
    fn submit(&mut self, command: RoutedCommand) -> Result<(), AdapterError>;
}

#[derive(Debug)]
pub struct SimulatedAdapter {
    identity: AdapterIdentity,
    frames: VecDeque<AdapterFrame>,
    commands: Vec<RoutedCommand>,
}

impl SimulatedAdapter {
    pub fn new(identity: AdapterIdentity) -> Result<Self, AdapterError> {
        if identity.protocol != AdapterProtocol::Simulator {
            return Err(AdapterError::InvalidIdentity);
        }
        Ok(Self {
            identity,
            frames: VecDeque::new(),
            commands: Vec::new(),
        })
    }

    pub fn queue_frame(&mut self, frame: AdapterFrame) -> Result<(), AdapterError> {
        if frame.adapter_id != self.identity.id {
            return Err(AdapterError::EndpointMismatch);
        }
        self.frames.push_back(frame);
        Ok(())
    }

    pub fn commands(&self) -> &[RoutedCommand] {
        &self.commands
    }
}

impl AdapterDriver for SimulatedAdapter {
    fn identity(&self) -> &AdapterIdentity {
        &self.identity
    }

    fn poll_frame(&mut self) -> Option<AdapterFrame> {
        self.frames.pop_front()
    }

    fn submit(&mut self, command: RoutedCommand) -> Result<(), AdapterError> {
        if command.command.adapter_id != self.identity.id {
            return Err(AdapterError::EndpointMismatch);
        }
        self.commands.push(command);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{
        Actor, ActorKind, ActorStatus, CapabilitySet, Position, QualificationSet, Site,
    };
    use crate::twin::{SensorKind, SensorReading};
    use alloc::string::ToString;

    fn identity(state: AdapterState) -> AdapterIdentity {
        AdapterIdentity {
            id: AdapterId(1),
            site_id: SiteId(1),
            protocol: AdapterProtocol::Simulator,
            public_key_sha256: [7; 32],
            firmware_version: 1,
            session_epoch: 5,
            state,
            last_seen_tick: 0,
            last_receive_sequence: 0,
        }
    }

    fn registry(state: AdapterState) -> AdapterRegistry {
        let mut registry = AdapterRegistry::new();
        registry.register_adapter(identity(state)).unwrap();
        registry
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
        registry
    }

    fn domain() -> DomainRegistry {
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
        domain
    }

    fn sensor_frame(sequence: u64) -> AdapterFrame {
        AdapterFrame {
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 5,
            sequence,
            observed_at_tick: 10,
            payload: AdapterPayload::SensorReading(SensorReading {
                sensor_id: 4,
                site_id: SiteId(1),
                asset_id: None,
                kind: SensorKind::ProximityMillimeters,
                value: 500,
                quality_permille: 1_000,
                observed_at_tick: 10,
            }),
        }
    }

    fn command(key: u64) -> AdapterCommand {
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
            deadline_tick: 100,
        }
    }

    #[test]
    fn adapter_identity_must_be_attested() {
        let mut invalid = identity(AdapterState::Online);
        invalid.public_key_sha256 = [0; 32];
        assert_eq!(
            AdapterRegistry::new().register_adapter(invalid),
            Err(AdapterError::InvalidIdentity)
        );
    }

    #[test]
    fn frame_ingestion_is_transactional_and_replay_protected() {
        let mut adapters = registry(AdapterState::Online);
        let mut domain = domain();
        let mut twin = OperationalTwin::new();
        assert_eq!(
            adapters
                .ingest_frame(&mut twin, &mut domain, sensor_frame(1), 11, 1)
                .unwrap(),
            1
        );
        assert_eq!(
            adapters.ingest_frame(&mut twin, &mut domain, sensor_frame(1), 12, 2),
            Err(AdapterError::DuplicateOrOutOfOrder)
        );
        assert_eq!(twin.snapshot().retained_events, 1);
    }

    #[test]
    fn offline_adapter_cannot_ingest_or_route() {
        let mut adapters = registry(AdapterState::Offline);
        let mut domain = domain();
        let mut twin = OperationalTwin::new();
        assert_eq!(
            adapters.ingest_frame(&mut twin, &mut domain, sensor_frame(1), 11, 1),
            Err(AdapterError::AdapterUnavailable)
        );
        assert_eq!(
            adapters.route_authorized(command(1), ExecutionPermit::new(10, 100, 1), 10),
            Err(AdapterError::AdapterUnavailable)
        );
    }

    #[test]
    fn command_requires_matching_unexpired_permit() {
        let mut adapters = registry(AdapterState::Online);
        assert_eq!(
            adapters.route_authorized(command(1), ExecutionPermit::new(11, 100, 1), 10),
            Err(AdapterError::PermitMismatch)
        );
        assert_eq!(
            adapters.route_authorized(command(1), ExecutionPermit::new(10, 5, 1), 10),
            Err(AdapterError::PermitExpired)
        );
    }

    #[test]
    fn idempotency_key_prevents_duplicate_physical_effects() {
        let mut adapters = registry(AdapterState::Online);
        adapters
            .route_authorized(command(77), ExecutionPermit::new(10, 100, 1), 10)
            .unwrap();
        assert_eq!(
            adapters.route_authorized(command(77), ExecutionPermit::new(10, 100, 1), 10),
            Err(AdapterError::DuplicateCommand)
        );
    }

    #[test]
    fn simulator_queues_real_typed_frames_and_routed_commands() {
        let mut driver = SimulatedAdapter::new(identity(AdapterState::Online)).unwrap();
        driver.queue_frame(sensor_frame(1)).unwrap();
        assert_eq!(driver.poll_frame().unwrap().sequence, 1);
        driver
            .submit(RoutedCommand {
                command: command(9),
                policy_revision: 3,
            })
            .unwrap();
        assert_eq!(driver.commands().len(), 1);
    }
}
