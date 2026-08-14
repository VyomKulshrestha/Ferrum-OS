//! Event-sourced operational digital twin.
//!
//! The twin accepts observations from adapters only after validating identity,
//! sequence, time, and telemetry ranges. It retains a bounded history and keeps
//! raw observation time distinct from receipt time so stale data cannot be
//! mistaken for a current physical state.

use alloc::collections::VecDeque;
use alloc::vec::Vec;

use crate::contract::{ContractError, ObservationMetadata};
use crate::domain::{ActorId, ActorStatus, AssetId, AssetState, DomainRegistry, Position, SiteId};
use crate::work::{JobId, TaskId};

pub const MAX_TWIN_EVENTS: usize = 4_096;
pub const MAX_EVENT_SOURCES: usize = 256;
pub const MAX_SENSOR_READINGS: usize = 512;
pub const MAX_ZONE_OCCUPANCIES: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SensorKind {
    TemperatureMilliCelsius,
    VibrationMicrometersPerSecond,
    PressurePascal,
    ProximityMillimeters,
    CurrentMilliamp,
    BatteryPermille,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ActorTelemetry {
    pub actor_id: ActorId,
    pub position: Position,
    pub battery_permille: u16,
    pub load_permille: u16,
    pub status: ActorStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AssetTelemetry {
    pub asset_id: AssetId,
    pub state: AssetState,
    pub position: Position,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SensorReading {
    pub sensor_id: u64,
    pub site_id: SiteId,
    pub asset_id: Option<AssetId>,
    pub kind: SensorKind,
    pub value: i64,
    pub quality_permille: u16,
    pub observed_at_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ZoneOccupancy {
    pub site_id: SiteId,
    pub zone_id: u32,
    pub humans: u16,
    pub robots: u16,
    pub observed_at_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventPayload {
    ActorTelemetry(ActorTelemetry),
    AssetTelemetry(AssetTelemetry),
    SensorReading(SensorReading),
    ZoneOccupancy(ZoneOccupancy),
    WorkAssigned {
        job_id: JobId,
        task_id: TaskId,
        actor_id: ActorId,
    },
    WorkCompleted {
        job_id: JobId,
        task_id: TaskId,
        actor_id: ActorId,
    },
    SafetyInterlock {
        site_id: SiteId,
        zone_id: u32,
        reason_code: u32,
    },
    EmergencyStop {
        actor_id: ActorId,
        reason_code: u32,
    },
    AdapterOffline {
        adapter_id: u64,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventEnvelope {
    pub event_id: u64,
    pub source_id: u64,
    pub source_sequence: u64,
    pub observed_at_tick: u64,
    pub received_at_tick: u64,
    pub metadata: ObservationMetadata,
    pub payload: EventPayload,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TwinError {
    DuplicateOrOutOfOrder,
    FutureObservation,
    InvalidTelemetry,
    UnknownActor,
    UnknownAsset,
    UnknownSite,
    SourceCapacityExceeded,
    SensorCapacityExceeded,
    ZoneCapacityExceeded,
    ClockIdentityChanged,
    Contract(ContractError),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TwinSnapshot {
    pub latest_event_id: u64,
    pub retained_events: usize,
    pub source_count: usize,
    pub sensor_count: usize,
    pub occupied_zone_count: usize,
}

#[derive(Debug, Default)]
pub struct OperationalTwin {
    events: VecDeque<EventEnvelope>,
    source_sequences: Vec<(u64, u64)>,
    source_clocks: Vec<(u64, u64)>,
    sensor_readings: Vec<SensorReading>,
    zone_occupancies: Vec<ZoneOccupancy>,
    latest_event_id: u64,
}

impl OperationalTwin {
    pub const fn new() -> Self {
        Self {
            events: VecDeque::new(),
            source_sequences: Vec::new(),
            source_clocks: Vec::new(),
            sensor_readings: Vec::new(),
            zone_occupancies: Vec::new(),
            latest_event_id: 0,
        }
    }

    pub fn apply(
        &mut self,
        registry: &mut DomainRegistry,
        envelope: EventEnvelope,
        maximum_clock_skew_ticks: u64,
    ) -> Result<(), TwinError> {
        self.validate_envelope(registry, &envelope, maximum_clock_skew_ticks)?;

        match envelope.payload {
            EventPayload::ActorTelemetry(telemetry) => {
                let actor = registry
                    .actor_mut(telemetry.actor_id)
                    .ok_or(TwinError::UnknownActor)?;
                actor.position = telemetry.position;
                actor.battery_permille = telemetry.battery_permille;
                actor.load_permille = telemetry.load_permille;
                actor.status = telemetry.status;
                actor.last_seen_tick = envelope.observed_at_tick;
            }
            EventPayload::AssetTelemetry(telemetry) => {
                let asset = registry
                    .asset_mut(telemetry.asset_id)
                    .ok_or(TwinError::UnknownAsset)?;
                asset.state = telemetry.state;
                asset.position = telemetry.position;
            }
            EventPayload::SensorReading(reading) => {
                if let Some(existing) = self
                    .sensor_readings
                    .iter_mut()
                    .find(|existing| existing.sensor_id == reading.sensor_id)
                {
                    *existing = reading;
                } else {
                    self.sensor_readings.push(reading);
                }
            }
            EventPayload::ZoneOccupancy(occupancy) => {
                if let Some(existing) = self.zone_occupancies.iter_mut().find(|existing| {
                    existing.site_id == occupancy.site_id && existing.zone_id == occupancy.zone_id
                }) {
                    *existing = occupancy;
                } else {
                    self.zone_occupancies.push(occupancy);
                }
            }
            EventPayload::EmergencyStop { actor_id, .. } => {
                registry
                    .actor_mut(actor_id)
                    .ok_or(TwinError::UnknownActor)?
                    .status = ActorStatus::EmergencyStop;
            }
            EventPayload::WorkAssigned { .. }
            | EventPayload::WorkCompleted { .. }
            | EventPayload::SafetyInterlock { .. }
            | EventPayload::AdapterOffline { .. } => {}
        }

        self.commit_sequence(envelope.source_id, envelope.source_sequence);
        if !self
            .source_clocks
            .iter()
            .any(|(source_id, _)| *source_id == envelope.source_id)
        {
            self.source_clocks
                .push((envelope.source_id, envelope.metadata.source_clock_id));
        }
        self.latest_event_id = envelope.event_id;
        if self.events.len() == MAX_TWIN_EVENTS {
            self.events.pop_front();
        }
        self.events.push_back(envelope);
        Ok(())
    }

    pub fn sensor(&self, sensor_id: u64) -> Option<&SensorReading> {
        self.sensor_readings
            .iter()
            .find(|reading| reading.sensor_id == sensor_id)
    }

    pub fn sensor_is_fresh(
        &self,
        sensor_id: u64,
        current_tick: u64,
        maximum_age_ticks: u64,
    ) -> bool {
        self.sensor(sensor_id).is_some_and(|reading| {
            current_tick >= reading.observed_at_tick
                && current_tick - reading.observed_at_tick <= maximum_age_ticks
        })
    }

    pub fn occupancy(&self, site_id: SiteId, zone_id: u32) -> Option<&ZoneOccupancy> {
        self.zone_occupancies
            .iter()
            .find(|entry| entry.site_id == site_id && entry.zone_id == zone_id)
    }

    pub fn events(&self) -> &VecDeque<EventEnvelope> {
        &self.events
    }

    /// Allocate from the twin's single event-id domain. Producers must not
    /// maintain independent counters because internal and adapter events share
    /// this log.
    pub const fn next_event_id(&self) -> u64 {
        self.latest_event_id.saturating_add(1)
    }

    pub fn append_internal(
        &mut self,
        registry: &mut DomainRegistry,
        source_id: u64,
        source_sequence: u64,
        observed_at_tick: u64,
        received_at_tick: u64,
        payload: EventPayload,
    ) -> Result<u64, TwinError> {
        let event_id = self.next_event_id();
        self.apply(
            registry,
            EventEnvelope {
                event_id,
                source_id,
                source_sequence,
                observed_at_tick,
                received_at_tick,
                metadata: ObservationMetadata::internal(event_id, received_at_tick),
                payload,
            },
            0,
        )?;
        Ok(event_id)
    }

    pub fn reserve_source(&mut self, source_id: u64) -> Result<(), TwinError> {
        if self
            .source_sequences
            .iter()
            .any(|(existing, _)| *existing == source_id)
        {
            return Ok(());
        }
        if self.source_sequences.len() >= MAX_EVENT_SOURCES {
            return Err(TwinError::SourceCapacityExceeded);
        }
        self.source_sequences.push((source_id, 0));
        Ok(())
    }

    pub fn snapshot(&self) -> TwinSnapshot {
        TwinSnapshot {
            latest_event_id: self.latest_event_id,
            retained_events: self.events.len(),
            source_count: self.source_sequences.len(),
            sensor_count: self.sensor_readings.len(),
            occupied_zone_count: self
                .zone_occupancies
                .iter()
                .filter(|entry| entry.humans > 0 || entry.robots > 0)
                .count(),
        }
    }

    fn validate_envelope(
        &self,
        registry: &DomainRegistry,
        envelope: &EventEnvelope,
        maximum_clock_skew_ticks: u64,
    ) -> Result<(), TwinError> {
        if envelope.event_id <= self.latest_event_id {
            return Err(TwinError::DuplicateOrOutOfOrder);
        }
        if self
            .source_sequences
            .iter()
            .find(|(source_id, _)| *source_id == envelope.source_id)
            .is_some_and(|(_, sequence)| envelope.source_sequence <= *sequence)
        {
            return Err(TwinError::DuplicateOrOutOfOrder);
        }
        if envelope.observed_at_tick
            > envelope
                .received_at_tick
                .saturating_add(maximum_clock_skew_ticks)
        {
            return Err(TwinError::FutureObservation);
        }
        envelope
            .metadata
            .validate_event(
                envelope.observed_at_tick,
                envelope.received_at_tick,
                maximum_clock_skew_ticks,
            )
            .map_err(TwinError::Contract)?;
        if self
            .source_clocks
            .iter()
            .find(|(source_id, _)| *source_id == envelope.source_id)
            .is_some_and(|(_, clock_id)| *clock_id != envelope.metadata.source_clock_id)
        {
            return Err(TwinError::ClockIdentityChanged);
        }
        if !self
            .source_sequences
            .iter()
            .any(|(source_id, _)| *source_id == envelope.source_id)
            && self.source_sequences.len() >= MAX_EVENT_SOURCES
        {
            return Err(TwinError::SourceCapacityExceeded);
        }

        match envelope.payload {
            EventPayload::ActorTelemetry(telemetry) => {
                if registry.actor(telemetry.actor_id).is_none() {
                    return Err(TwinError::UnknownActor);
                }
                if telemetry.battery_permille > 1_000 || telemetry.load_permille > 1_000 {
                    return Err(TwinError::InvalidTelemetry);
                }
            }
            EventPayload::AssetTelemetry(telemetry) => {
                if registry.asset(telemetry.asset_id).is_none() {
                    return Err(TwinError::UnknownAsset);
                }
            }
            EventPayload::SensorReading(reading) => {
                if reading.quality_permille > 1_000
                    || reading.observed_at_tick != envelope.observed_at_tick
                {
                    return Err(TwinError::InvalidTelemetry);
                }
                if registry.site(reading.site_id).is_none() {
                    return Err(TwinError::UnknownSite);
                }
                if reading
                    .asset_id
                    .is_some_and(|asset_id| registry.asset(asset_id).is_none())
                {
                    return Err(TwinError::UnknownAsset);
                }
                if self.sensor(reading.sensor_id).is_none()
                    && self.sensor_readings.len() >= MAX_SENSOR_READINGS
                {
                    return Err(TwinError::SensorCapacityExceeded);
                }
            }
            EventPayload::ZoneOccupancy(occupancy) => {
                if occupancy.observed_at_tick != envelope.observed_at_tick {
                    return Err(TwinError::InvalidTelemetry);
                }
                if registry.site(occupancy.site_id).is_none() {
                    return Err(TwinError::UnknownSite);
                }
                if self
                    .occupancy(occupancy.site_id, occupancy.zone_id)
                    .is_none()
                    && self.zone_occupancies.len() >= MAX_ZONE_OCCUPANCIES
                {
                    return Err(TwinError::ZoneCapacityExceeded);
                }
            }
            EventPayload::EmergencyStop { actor_id, .. }
            | EventPayload::WorkAssigned { actor_id, .. }
            | EventPayload::WorkCompleted { actor_id, .. } => {
                if registry.actor(actor_id).is_none() {
                    return Err(TwinError::UnknownActor);
                }
            }
            EventPayload::SafetyInterlock { site_id, .. } => {
                if registry.site(site_id).is_none() {
                    return Err(TwinError::UnknownSite);
                }
            }
            EventPayload::AdapterOffline { .. } => {}
        }
        Ok(())
    }

    fn commit_sequence(&mut self, source_id: u64, sequence: u64) {
        if let Some((_, current)) = self
            .source_sequences
            .iter_mut()
            .find(|(existing, _)| *existing == source_id)
        {
            *current = sequence;
        } else {
            self.source_sequences.push((source_id, sequence));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{Actor, ActorKind, Asset, CapabilitySet, QualificationSet, Site};
    use alloc::string::ToString;

    fn registry() -> DomainRegistry {
        let mut registry = DomainRegistry::new();
        registry
            .register_site(Site {
                id: SiteId(1),
                name: "Plant".to_string(),
                emergency_zone_id: 99,
            })
            .unwrap();
        registry
            .register_actor(Actor {
                id: ActorId(1),
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
        registry
            .register_asset(Asset {
                id: AssetId(2),
                name: "Pump".to_string(),
                site_id: SiteId(1),
                position: Position::origin(7, 0),
                state: AssetState::Operational,
                last_service_tick: 0,
            })
            .unwrap();
        registry
    }

    fn actor_event(event_id: u64, sequence: u64, battery: u16) -> EventEnvelope {
        EventEnvelope {
            event_id,
            source_id: 10,
            source_sequence: sequence,
            observed_at_tick: 100,
            received_at_tick: 101,
            metadata: ObservationMetadata::simulated(event_id, 110),
            payload: EventPayload::ActorTelemetry(ActorTelemetry {
                actor_id: ActorId(1),
                position: Position::origin(7, 100),
                battery_permille: battery,
                load_permille: 10,
                status: ActorStatus::Available,
            }),
        }
    }

    #[test]
    fn valid_actor_telemetry_updates_registry_and_history() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        twin.apply(&mut registry, actor_event(1, 1, 800), 2)
            .unwrap();
        assert_eq!(registry.actor(ActorId(1)).unwrap().battery_permille, 800);
        assert_eq!(twin.snapshot().retained_events, 1);
    }

    #[test]
    fn source_clock_identity_cannot_change_mid_session() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        twin.apply(&mut registry, actor_event(1, 1, 900), 2)
            .unwrap();
        let mut changed_clock = actor_event(2, 2, 800);
        changed_clock.metadata.source_clock_id = 2;
        assert_eq!(
            twin.apply(&mut registry, changed_clock, 2),
            Err(TwinError::ClockIdentityChanged)
        );
        assert_eq!(twin.snapshot().latest_event_id, 1);
        assert_eq!(registry.actor(ActorId(1)).unwrap().battery_permille, 900);
    }

    #[test]
    fn replay_is_rejected_without_mutating_state() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        twin.apply(&mut registry, actor_event(1, 1, 800), 2)
            .unwrap();
        assert_eq!(
            twin.apply(&mut registry, actor_event(2, 1, 200), 2),
            Err(TwinError::DuplicateOrOutOfOrder)
        );
        assert_eq!(registry.actor(ActorId(1)).unwrap().battery_permille, 800);
    }

    #[test]
    fn impossible_telemetry_is_rejected_transactionally() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        assert_eq!(
            twin.apply(&mut registry, actor_event(1, 1, 1_001), 2),
            Err(TwinError::InvalidTelemetry)
        );
        assert_eq!(registry.actor(ActorId(1)).unwrap().battery_permille, 1_000);
        assert_eq!(twin.snapshot().retained_events, 0);
    }

    #[test]
    fn future_observations_fail_closed() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        let mut event = actor_event(1, 1, 800);
        event.observed_at_tick = 200;
        assert_eq!(
            twin.apply(&mut registry, event, 2),
            Err(TwinError::FutureObservation)
        );
    }

    #[test]
    fn sensor_freshness_uses_observation_time() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        twin.apply(
            &mut registry,
            EventEnvelope {
                event_id: 1,
                source_id: 20,
                source_sequence: 1,
                observed_at_tick: 100,
                received_at_tick: 101,
                metadata: ObservationMetadata::simulated(1, 110),
                payload: EventPayload::SensorReading(SensorReading {
                    sensor_id: 7,
                    site_id: SiteId(1),
                    asset_id: Some(AssetId(2)),
                    kind: SensorKind::VibrationMicrometersPerSecond,
                    value: 4_000,
                    quality_permille: 990,
                    observed_at_tick: 100,
                }),
            },
            2,
        )
        .unwrap();
        assert!(twin.sensor_is_fresh(7, 110, 10));
        assert!(!twin.sensor_is_fresh(7, 111, 10));
    }

    #[test]
    fn emergency_stop_cannot_be_overridden_by_dispatchability() {
        let mut registry = registry();
        let mut twin = OperationalTwin::new();
        twin.apply(
            &mut registry,
            EventEnvelope {
                event_id: 1,
                source_id: 30,
                source_sequence: 1,
                observed_at_tick: 100,
                received_at_tick: 100,
                metadata: ObservationMetadata::simulated(1, 110),
                payload: EventPayload::EmergencyStop {
                    actor_id: ActorId(1),
                    reason_code: 55,
                },
            },
            0,
        )
        .unwrap();
        assert_eq!(
            registry.actor(ActorId(1)).unwrap().status,
            ActorStatus::EmergencyStop
        );
        assert!(!registry.actor(ActorId(1)).unwrap().is_dispatchable_at(100));
    }
}
