//! Transport conformance without transport authority.
//!
//! ROS 2, MQTT, and CAN gateways translate transport behavior into the same
//! bounded observation/goal states. A gateway can never construct an
//! `ExecutionPermit`; only the deterministic runtime owns that type.

use alloc::vec::Vec;

use crate::adapter::{AdapterId, AdapterProtocol, EndpointId};

pub const MAX_TRANSPORT_PAYLOAD_BYTES: usize = 16_384;
pub const MAX_TRANSPORT_SOURCES: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageClass {
    Telemetry,
    Health,
    Goal,
    Acknowledgement,
    Audit,
    EmergencyStopObservation,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransportError {
    InvalidPolicy,
    UnsupportedProtocol,
    AuthenticationRequired,
    RetainedControlForbidden,
    Expired,
    Replay,
    PayloadTooLarge,
    QosMismatch,
    CanIdForbidden,
    CanCounterMismatch,
    CanCrcMismatch,
    BusUnavailable,
    CapacityExceeded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RosReliability {
    BestEffort,
    Reliable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RosDurability {
    Volatile,
    TransientLocal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Ros2Qos {
    pub reliability: RosReliability,
    pub durability: RosDurability,
    pub history_depth: u16,
    pub lifespan_ticks: u64,
    pub deadline_ticks: u64,
}

impl Ros2Qos {
    pub fn validate(self, class: MessageClass) -> Result<(), TransportError> {
        if self.history_depth == 0
            || self.history_depth > 64
            || self.lifespan_ticks == 0
            || self.deadline_ticks == 0
        {
            return Err(TransportError::InvalidPolicy);
        }
        if matches!(
            class,
            MessageClass::Goal
                | MessageClass::Acknowledgement
                | MessageClass::EmergencyStopObservation
        ) && (self.reliability != RosReliability::Reliable
            || self.durability != RosDurability::Volatile)
        {
            return Err(TransportError::QosMismatch);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MqttPolicy {
    pub mutual_tls: bool,
    pub device_acl_bound: bool,
    pub maximum_payload_bytes: u32,
    pub maximum_expiry_ticks: u64,
}

impl MqttPolicy {
    pub fn validate(self) -> Result<(), TransportError> {
        if !self.mutual_tls || !self.device_acl_bound {
            return Err(TransportError::AuthenticationRequired);
        }
        if self.maximum_payload_bytes == 0
            || self.maximum_payload_bytes as usize > MAX_TRANSPORT_PAYLOAD_BYTES
            || self.maximum_expiry_ticks == 0
        {
            return Err(TransportError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanBusState {
    Active,
    ErrorPassive,
    BusOff,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CanFramePolicy {
    pub arbitration_id: u32,
    pub message_class: MessageClass,
    pub payload_length: u8,
    pub counter_offset: u8,
    pub crc_offset: u8,
    pub maximum_rate_hz: u16,
}

impl CanFramePolicy {
    pub fn validate(self) -> Result<(), TransportError> {
        if self.arbitration_id > 0x1fff_ffff
            || self.payload_length == 0
            || self.payload_length > 64
            || self.counter_offset >= self.payload_length
            || self.crc_offset >= self.payload_length
            || self.counter_offset == self.crc_offset
            || self.maximum_rate_hz == 0
        {
            return Err(TransportError::InvalidPolicy);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TransportEnvelope {
    pub protocol: AdapterProtocol,
    pub class: MessageClass,
    pub adapter_id: AdapterId,
    pub endpoint_id: EndpointId,
    pub session_epoch: u64,
    pub sequence: u64,
    pub observed_at_tick: u64,
    pub expires_at_tick: u64,
    pub payload_bytes: u32,
    pub authenticated: bool,
    pub retained: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct SourceSequence {
    adapter_id: AdapterId,
    endpoint_id: EndpointId,
    session_epoch: u64,
    sequence: u64,
}

#[derive(Debug, Default)]
pub struct TransportConformance {
    sources: Vec<SourceSequence>,
}

impl TransportConformance {
    pub const fn new() -> Self {
        Self {
            sources: Vec::new(),
        }
    }

    pub fn admit(
        &mut self,
        envelope: TransportEnvelope,
        current_tick: u64,
        ros_qos: Option<Ros2Qos>,
        mqtt_policy: Option<MqttPolicy>,
    ) -> Result<(), TransportError> {
        if envelope.adapter_id.0 == 0
            || envelope.endpoint_id.0 == 0
            || envelope.session_epoch == 0
            || envelope.sequence == 0
        {
            return Err(TransportError::InvalidPolicy);
        }
        if envelope.payload_bytes as usize > MAX_TRANSPORT_PAYLOAD_BYTES {
            return Err(TransportError::PayloadTooLarge);
        }
        if current_tick > envelope.expires_at_tick || envelope.observed_at_tick > current_tick {
            return Err(TransportError::Expired);
        }
        match envelope.protocol {
            AdapterProtocol::Ros2Dds => ros_qos
                .ok_or(TransportError::InvalidPolicy)?
                .validate(envelope.class)?,
            AdapterProtocol::Mqtt => {
                let policy = mqtt_policy.ok_or(TransportError::InvalidPolicy)?;
                policy.validate()?;
                if envelope.payload_bytes > policy.maximum_payload_bytes
                    || envelope.expires_at_tick.saturating_sub(current_tick)
                        > policy.maximum_expiry_ticks
                {
                    return Err(TransportError::InvalidPolicy);
                }
                if !envelope.authenticated {
                    return Err(TransportError::AuthenticationRequired);
                }
                if envelope.retained
                    && matches!(
                        envelope.class,
                        MessageClass::Goal
                            | MessageClass::Acknowledgement
                            | MessageClass::EmergencyStopObservation
                    )
                {
                    return Err(TransportError::RetainedControlForbidden);
                }
            }
            AdapterProtocol::CanOpen => {
                if !envelope.authenticated {
                    return Err(TransportError::AuthenticationRequired);
                }
            }
            AdapterProtocol::Simulator
            | AdapterProtocol::ModbusTcp
            | AdapterProtocol::OpcUa
            | AdapterProtocol::BleGatt
            | AdapterProtocol::VendorRpc => return Err(TransportError::UnsupportedProtocol),
        }
        if let Some(source) = self.sources.iter_mut().find(|source| {
            source.adapter_id == envelope.adapter_id && source.endpoint_id == envelope.endpoint_id
        }) {
            if source.session_epoch != envelope.session_epoch
                || envelope.sequence <= source.sequence
            {
                return Err(TransportError::Replay);
            }
            source.sequence = envelope.sequence;
        } else {
            if self.sources.len() >= MAX_TRANSPORT_SOURCES {
                return Err(TransportError::CapacityExceeded);
            }
            self.sources.push(SourceSequence {
                adapter_id: envelope.adapter_id,
                endpoint_id: envelope.endpoint_id,
                session_epoch: envelope.session_epoch,
                sequence: envelope.sequence,
            });
        }
        Ok(())
    }
}

#[derive(Debug)]
pub struct CanConformance {
    policies: Vec<CanFramePolicy>,
    last_counters: Vec<(u32, u8)>,
    state: CanBusState,
}

impl CanConformance {
    pub fn new(policies: &[CanFramePolicy]) -> Result<Self, TransportError> {
        if policies.is_empty() || policies.len() > 128 {
            return Err(TransportError::InvalidPolicy);
        }
        for (index, policy) in policies.iter().enumerate() {
            policy.validate()?;
            if policies[..index]
                .iter()
                .any(|existing| existing.arbitration_id == policy.arbitration_id)
            {
                return Err(TransportError::InvalidPolicy);
            }
        }
        Ok(Self {
            policies: policies.to_vec(),
            last_counters: Vec::new(),
            state: CanBusState::Active,
        })
    }

    pub fn set_bus_state(&mut self, state: CanBusState) {
        self.state = state;
    }

    pub fn admit(
        &mut self,
        arbitration_id: u32,
        payload: &[u8],
    ) -> Result<MessageClass, TransportError> {
        if self.state != CanBusState::Active {
            return Err(TransportError::BusUnavailable);
        }
        let policy = *self
            .policies
            .iter()
            .find(|policy| policy.arbitration_id == arbitration_id)
            .ok_or(TransportError::CanIdForbidden)?;
        if payload.len() != policy.payload_length as usize {
            return Err(TransportError::PayloadTooLarge);
        }
        let expected_crc = crc8_with_zeroed_byte(payload, policy.crc_offset as usize);
        if payload[policy.crc_offset as usize] != expected_crc {
            return Err(TransportError::CanCrcMismatch);
        }
        let counter = payload[policy.counter_offset as usize];
        if let Some((_, previous)) = self
            .last_counters
            .iter_mut()
            .find(|(id, _)| *id == arbitration_id)
        {
            if counter != previous.wrapping_add(1) {
                return Err(TransportError::CanCounterMismatch);
            }
            *previous = counter;
        } else {
            self.last_counters.push((arbitration_id, counter));
        }
        Ok(policy.message_class)
    }
}

pub fn crc8_with_zeroed_byte(payload: &[u8], zero_index: usize) -> u8 {
    let mut crc = 0xffu8;
    for (index, byte) in payload.iter().enumerate() {
        crc ^= if index == zero_index { 0 } else { *byte };
        for _ in 0..8 {
            crc = if crc & 0x80 != 0 {
                (crc << 1) ^ 0x1d
            } else {
                crc << 1
            };
        }
    }
    crc
}

#[cfg(test)]
mod tests {
    use super::*;

    fn envelope(
        protocol: AdapterProtocol,
        class: MessageClass,
        sequence: u64,
    ) -> TransportEnvelope {
        TransportEnvelope {
            protocol,
            class,
            adapter_id: AdapterId(1),
            endpoint_id: EndpointId(2),
            session_epoch: 3,
            sequence,
            observed_at_tick: 10,
            expires_at_tick: 20,
            payload_bytes: 100,
            authenticated: true,
            retained: false,
        }
    }

    #[test]
    fn ros_control_requires_reliable_volatile_bounded_qos() {
        let mut conformance = TransportConformance::new();
        let unsafe_qos = Ros2Qos {
            reliability: RosReliability::BestEffort,
            durability: RosDurability::TransientLocal,
            history_depth: 10,
            lifespan_ticks: 5,
            deadline_ticks: 5,
        };
        assert_eq!(
            conformance.admit(
                envelope(AdapterProtocol::Ros2Dds, MessageClass::Goal, 1),
                10,
                Some(unsafe_qos),
                None
            ),
            Err(TransportError::QosMismatch)
        );
        let safe_qos = Ros2Qos {
            reliability: RosReliability::Reliable,
            durability: RosDurability::Volatile,
            ..unsafe_qos
        };
        assert_eq!(
            conformance.admit(
                envelope(AdapterProtocol::Ros2Dds, MessageClass::Goal, 1),
                10,
                Some(safe_qos),
                None
            ),
            Ok(())
        );
    }

    #[test]
    fn mqtt_requires_mtls_acl_expiry_and_nonretained_control() {
        let mut conformance = TransportConformance::new();
        let policy = MqttPolicy {
            mutual_tls: true,
            device_acl_bound: true,
            maximum_payload_bytes: 512,
            maximum_expiry_ticks: 20,
        };
        let mut retained = envelope(AdapterProtocol::Mqtt, MessageClass::Goal, 1);
        retained.retained = true;
        assert_eq!(
            conformance.admit(retained, 10, None, Some(policy)),
            Err(TransportError::RetainedControlForbidden)
        );
        let mut unauthenticated = envelope(AdapterProtocol::Mqtt, MessageClass::Telemetry, 1);
        unauthenticated.authenticated = false;
        assert_eq!(
            conformance.admit(unauthenticated, 10, None, Some(policy)),
            Err(TransportError::AuthenticationRequired)
        );
        assert_eq!(
            conformance.admit(
                envelope(AdapterProtocol::Mqtt, MessageClass::Telemetry, 1),
                10,
                None,
                Some(policy)
            ),
            Ok(())
        );
        assert_eq!(
            conformance.admit(
                envelope(AdapterProtocol::Mqtt, MessageClass::Telemetry, 1),
                10,
                None,
                Some(policy)
            ),
            Err(TransportError::Replay)
        );
    }

    #[test]
    fn can_is_allowlisted_counted_crc_checked_and_bus_off_safe() {
        let policy = CanFramePolicy {
            arbitration_id: 0x120,
            message_class: MessageClass::Health,
            payload_length: 4,
            counter_offset: 1,
            crc_offset: 3,
            maximum_rate_hz: 20,
        };
        let mut conformance = CanConformance::new(&[policy]).unwrap();
        let mut first = [5, 7, 9, 0];
        first[3] = crc8_with_zeroed_byte(&first, 3);
        assert_eq!(conformance.admit(0x120, &first), Ok(MessageClass::Health));
        assert_eq!(
            conformance.admit(0x121, &first),
            Err(TransportError::CanIdForbidden)
        );
        let mut skipped = [5, 9, 9, 0];
        skipped[3] = crc8_with_zeroed_byte(&skipped, 3);
        assert_eq!(
            conformance.admit(0x120, &skipped),
            Err(TransportError::CanCounterMismatch)
        );
        conformance.set_bus_state(CanBusState::BusOff);
        assert_eq!(
            conformance.admit(0x120, &first),
            Err(TransportError::BusUnavailable)
        );
    }

    #[test]
    fn all_transports_share_session_sequence_and_expiry_guards() {
        for protocol in [
            AdapterProtocol::Ros2Dds,
            AdapterProtocol::Mqtt,
            AdapterProtocol::CanOpen,
        ] {
            let qos = Ros2Qos {
                reliability: RosReliability::Reliable,
                durability: RosDurability::Volatile,
                history_depth: 1,
                lifespan_ticks: 5,
                deadline_ticks: 5,
            };
            let mqtt = MqttPolicy {
                mutual_tls: true,
                device_acl_bound: true,
                maximum_payload_bytes: 512,
                maximum_expiry_ticks: 20,
            };
            let mut conformance = TransportConformance::new();
            assert_eq!(
                conformance.admit(
                    envelope(protocol, MessageClass::Telemetry, 1),
                    10,
                    Some(qos),
                    Some(mqtt)
                ),
                Ok(())
            );
            assert_eq!(
                conformance.admit(
                    envelope(protocol, MessageClass::Telemetry, 1),
                    10,
                    Some(qos),
                    Some(mqtt)
                ),
                Err(TransportError::Replay)
            );
            let mut expired = envelope(protocol, MessageClass::Telemetry, 2);
            expired.expires_at_tick = 9;
            assert_eq!(
                conformance.admit(expired, 10, Some(qos), Some(mqtt)),
                Err(TransportError::Expired)
            );
        }
    }
}
