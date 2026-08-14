//! Logical virtual-device contracts for QEMU and external simulators.
//!
//! These contracts can be carried by VirtIO, vsock, serial, sockets, or a
//! network bridge. They intentionally do not claim that simulator and physical
//! devices share a low-level driver.

use alloc::vec::Vec;

use crate::adapter::{
    AdapterId, AdapterRegistry, EndpointCapability, EndpointCapabilitySet, EndpointId,
};
use crate::contract::CYBER_PHYSICAL_SCHEMA_VERSION;

pub const MAX_VIRTUAL_DEVICES: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct VirtualDeviceId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VirtualDeviceClass {
    Camera,
    DepthCamera,
    Imu,
    Proximity,
    Environment,
    MotorActuator,
    Robot,
    EegStream,
    EmergencyStopSignal,
    WatchdogSignal,
}

impl VirtualDeviceClass {
    const fn can_actuate(self) -> bool {
        matches!(self, Self::MotorActuator | Self::Robot)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VirtualTransport {
    Virtio,
    Vsock,
    Serial,
    SocketBackend,
    NetworkBridge,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VirtualDeviceState {
    Discovered,
    Ready,
    Degraded,
    Resetting,
    Offline,
    Removed,
    Quarantined,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VirtualDeviceDescriptor {
    pub schema_version: u16,
    pub id: VirtualDeviceId,
    pub adapter_id: AdapterId,
    pub endpoint_id: EndpointId,
    pub class: VirtualDeviceClass,
    pub transport: VirtualTransport,
    pub capabilities: EndpointCapabilitySet,
    pub identity_sha256: [u8; 32],
    pub session_epoch: u64,
    pub generation: u64,
    pub state: VirtualDeviceState,
    pub last_heartbeat_tick: u64,
    pub heartbeat_deadline_ticks: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VirtualDeviceAuthorization {
    device_id: VirtualDeviceId,
    adapter_id: AdapterId,
    endpoint_id: EndpointId,
    session_epoch: u64,
    identity_sha256: [u8; 32],
    authority_tag: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VirtualDeviceAuthority {
    root_tag: u64,
}

impl VirtualDeviceAuthority {
    pub fn new(root_tag: u64) -> Result<Self, VirtualDeviceError> {
        if root_tag == 0 {
            return Err(VirtualDeviceError::InvalidAuthority);
        }
        Ok(Self { root_tag })
    }

    pub fn authorize_actuator(
        self,
        descriptor: &VirtualDeviceDescriptor,
    ) -> Result<VirtualDeviceAuthorization, VirtualDeviceError> {
        validate_descriptor(*descriptor)?;
        if !descriptor.class.can_actuate()
            || !(descriptor
                .capabilities
                .contains(EndpointCapability::Actuate)
                || descriptor.capabilities.contains(EndpointCapability::Move))
        {
            return Err(VirtualDeviceError::AuthorizationNotApplicable);
        }
        Ok(VirtualDeviceAuthorization {
            device_id: descriptor.id,
            adapter_id: descriptor.adapter_id,
            endpoint_id: descriptor.endpoint_id,
            session_epoch: descriptor.session_epoch,
            identity_sha256: descriptor.identity_sha256,
            authority_tag: self.root_tag,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VirtualDeviceLease {
    pub device_id: VirtualDeviceId,
    pub session_epoch: u64,
    pub generation: u64,
    pub expires_at_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VirtualDeviceError {
    InvalidDescriptor,
    InvalidAuthority,
    AuthorizationNotApplicable,
    ActuatorAuthorizationRequired,
    AuthorizationMismatch,
    DuplicateDevice,
    CapacityExceeded,
    UnknownDevice,
    InvalidTransition,
    SessionMismatch,
    GenerationMismatch,
    DeviceUnavailable,
    LeaseExpired,
    StaleHeartbeat,
    AdapterBindingMismatch,
    EndpointBindingMismatch,
    CapabilityMismatch,
}

#[derive(Debug, Default)]
pub struct VirtualDeviceBus {
    devices: Vec<VirtualDeviceDescriptor>,
    authority_tag: Option<u64>,
}

impl VirtualDeviceBus {
    pub const fn new() -> Self {
        Self {
            devices: Vec::new(),
            authority_tag: None,
        }
    }

    pub fn install_authority(
        &mut self,
        authority: VirtualDeviceAuthority,
    ) -> Result<(), VirtualDeviceError> {
        if self.authority_tag.is_some() {
            return Err(VirtualDeviceError::InvalidTransition);
        }
        self.authority_tag = Some(authority.root_tag);
        Ok(())
    }

    pub fn register(
        &mut self,
        descriptor: VirtualDeviceDescriptor,
        authorization: Option<VirtualDeviceAuthorization>,
    ) -> Result<(), VirtualDeviceError> {
        validate_descriptor(descriptor)?;
        if self.devices.iter().any(|device| device.id == descriptor.id) {
            return Err(VirtualDeviceError::DuplicateDevice);
        }
        if self.devices.len() >= MAX_VIRTUAL_DEVICES {
            return Err(VirtualDeviceError::CapacityExceeded);
        }
        if descriptor.class.can_actuate() {
            let authorization =
                authorization.ok_or(VirtualDeviceError::ActuatorAuthorizationRequired)?;
            if authorization.device_id != descriptor.id
                || authorization.adapter_id != descriptor.adapter_id
                || authorization.endpoint_id != descriptor.endpoint_id
                || authorization.session_epoch != descriptor.session_epoch
                || authorization.identity_sha256 != descriptor.identity_sha256
                || self.authority_tag != Some(authorization.authority_tag)
            {
                return Err(VirtualDeviceError::AuthorizationMismatch);
            }
        } else if authorization.is_some() {
            return Err(VirtualDeviceError::AuthorizationNotApplicable);
        }
        self.devices.push(descriptor);
        Ok(())
    }

    pub fn validate_binding(
        &self,
        registry: &AdapterRegistry,
        id: VirtualDeviceId,
    ) -> Result<(), VirtualDeviceError> {
        let device = self.device(id).ok_or(VirtualDeviceError::UnknownDevice)?;
        if registry.adapter(device.adapter_id).is_none() {
            return Err(VirtualDeviceError::AdapterBindingMismatch);
        }
        let endpoint = registry
            .endpoint(device.endpoint_id)
            .ok_or(VirtualDeviceError::EndpointBindingMismatch)?;
        if endpoint.adapter_id != device.adapter_id {
            return Err(VirtualDeviceError::EndpointBindingMismatch);
        }
        for capability in [
            EndpointCapability::Sense,
            EndpointCapability::Actuate,
            EndpointCapability::Move,
            EndpointCapability::EmergencyStop,
            EndpointCapability::DisplayInstruction,
            EndpointCapability::Acknowledge,
        ] {
            if device.capabilities.contains(capability)
                && !endpoint.capabilities.contains(capability)
            {
                return Err(VirtualDeviceError::CapabilityMismatch);
            }
        }
        Ok(())
    }

    pub fn mark_ready(
        &mut self,
        id: VirtualDeviceId,
        session_epoch: u64,
        generation: u64,
        tick: u64,
    ) -> Result<(), VirtualDeviceError> {
        let device = self.device_mut(id)?;
        validate_identity(device, session_epoch, generation)?;
        if !matches!(
            device.state,
            VirtualDeviceState::Discovered
                | VirtualDeviceState::Resetting
                | VirtualDeviceState::Degraded
        ) {
            return Err(VirtualDeviceError::InvalidTransition);
        }
        device.state = VirtualDeviceState::Ready;
        device.last_heartbeat_tick = tick;
        Ok(())
    }

    pub fn heartbeat(
        &mut self,
        id: VirtualDeviceId,
        session_epoch: u64,
        generation: u64,
        tick: u64,
    ) -> Result<(), VirtualDeviceError> {
        let device = self.device_mut(id)?;
        validate_identity(device, session_epoch, generation)?;
        if !matches!(
            device.state,
            VirtualDeviceState::Ready | VirtualDeviceState::Degraded
        ) {
            return Err(VirtualDeviceError::DeviceUnavailable);
        }
        if tick < device.last_heartbeat_tick {
            return Err(VirtualDeviceError::StaleHeartbeat);
        }
        device.last_heartbeat_tick = tick;
        Ok(())
    }

    pub fn evaluate_liveness(&mut self, tick: u64) {
        for device in &mut self.devices {
            if matches!(
                device.state,
                VirtualDeviceState::Ready | VirtualDeviceState::Degraded
            ) && tick.saturating_sub(device.last_heartbeat_tick)
                > device.heartbeat_deadline_ticks
            {
                device.state = VirtualDeviceState::Offline;
            }
        }
    }

    pub fn begin_reset(
        &mut self,
        id: VirtualDeviceId,
        session_epoch: u64,
        generation: u64,
    ) -> Result<(), VirtualDeviceError> {
        let device = self.device_mut(id)?;
        validate_identity(device, session_epoch, generation)?;
        if matches!(
            device.state,
            VirtualDeviceState::Removed | VirtualDeviceState::Quarantined
        ) {
            return Err(VirtualDeviceError::InvalidTransition);
        }
        device.state = VirtualDeviceState::Resetting;
        Ok(())
    }

    pub fn complete_reset(
        &mut self,
        id: VirtualDeviceId,
        session_epoch: u64,
        prior_generation: u64,
        tick: u64,
    ) -> Result<u64, VirtualDeviceError> {
        let device = self.device_mut(id)?;
        validate_identity(device, session_epoch, prior_generation)?;
        if device.state != VirtualDeviceState::Resetting {
            return Err(VirtualDeviceError::InvalidTransition);
        }
        device.generation = device.generation.saturating_add(1);
        device.state = VirtualDeviceState::Discovered;
        device.last_heartbeat_tick = tick;
        Ok(device.generation)
    }

    pub fn hot_unplug(
        &mut self,
        id: VirtualDeviceId,
        session_epoch: u64,
        generation: u64,
    ) -> Result<(), VirtualDeviceError> {
        let device = self.device_mut(id)?;
        validate_identity(device, session_epoch, generation)?;
        if device.state == VirtualDeviceState::Removed {
            return Err(VirtualDeviceError::InvalidTransition);
        }
        device.state = VirtualDeviceState::Removed;
        device.generation = device.generation.saturating_add(1);
        Ok(())
    }

    pub fn issue_lease(
        &self,
        id: VirtualDeviceId,
        tick: u64,
        ttl_ticks: u64,
    ) -> Result<VirtualDeviceLease, VirtualDeviceError> {
        let device = self.device(id).ok_or(VirtualDeviceError::UnknownDevice)?;
        if device.state != VirtualDeviceState::Ready || ttl_ticks == 0 {
            return Err(VirtualDeviceError::DeviceUnavailable);
        }
        Ok(VirtualDeviceLease {
            device_id: id,
            session_epoch: device.session_epoch,
            generation: device.generation,
            expires_at_tick: tick.saturating_add(ttl_ticks),
        })
    }

    pub fn validate_lease(
        &self,
        lease: VirtualDeviceLease,
        tick: u64,
    ) -> Result<(), VirtualDeviceError> {
        if tick > lease.expires_at_tick {
            return Err(VirtualDeviceError::LeaseExpired);
        }
        let device = self
            .device(lease.device_id)
            .ok_or(VirtualDeviceError::UnknownDevice)?;
        validate_identity(device, lease.session_epoch, lease.generation)?;
        if device.state != VirtualDeviceState::Ready {
            return Err(VirtualDeviceError::DeviceUnavailable);
        }
        Ok(())
    }

    pub fn device(&self, id: VirtualDeviceId) -> Option<&VirtualDeviceDescriptor> {
        self.devices.iter().find(|device| device.id == id)
    }

    fn device_mut(
        &mut self,
        id: VirtualDeviceId,
    ) -> Result<&mut VirtualDeviceDescriptor, VirtualDeviceError> {
        self.devices
            .iter_mut()
            .find(|device| device.id == id)
            .ok_or(VirtualDeviceError::UnknownDevice)
    }
}

fn validate_descriptor(descriptor: VirtualDeviceDescriptor) -> Result<(), VirtualDeviceError> {
    if descriptor.schema_version != CYBER_PHYSICAL_SCHEMA_VERSION
        || descriptor.id.0 == 0
        || descriptor.adapter_id.0 == 0
        || descriptor.endpoint_id.0 == 0
        || descriptor.session_epoch == 0
        || descriptor.generation == 0
        || descriptor.heartbeat_deadline_ticks == 0
        || descriptor.identity_sha256.iter().all(|byte| *byte == 0)
        || !matches!(descriptor.state, VirtualDeviceState::Discovered)
    {
        return Err(VirtualDeviceError::InvalidDescriptor);
    }

    let valid_capabilities = match descriptor.class {
        VirtualDeviceClass::MotorActuator | VirtualDeviceClass::Robot => {
            descriptor
                .capabilities
                .contains(EndpointCapability::Actuate)
                || descriptor.capabilities.contains(EndpointCapability::Move)
        }
        VirtualDeviceClass::EmergencyStopSignal => descriptor
            .capabilities
            .contains(EndpointCapability::EmergencyStop),
        VirtualDeviceClass::WatchdogSignal
        | VirtualDeviceClass::Camera
        | VirtualDeviceClass::DepthCamera
        | VirtualDeviceClass::Imu
        | VirtualDeviceClass::Proximity
        | VirtualDeviceClass::Environment
        | VirtualDeviceClass::EegStream => {
            descriptor.capabilities.contains(EndpointCapability::Sense)
        }
    };
    if !valid_capabilities {
        return Err(VirtualDeviceError::CapabilityMismatch);
    }
    Ok(())
}

fn validate_identity(
    descriptor: &VirtualDeviceDescriptor,
    session_epoch: u64,
    generation: u64,
) -> Result<(), VirtualDeviceError> {
    if descriptor.session_epoch != session_epoch {
        return Err(VirtualDeviceError::SessionMismatch);
    }
    if descriptor.generation != generation {
        return Err(VirtualDeviceError::GenerationMismatch);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{AdapterIdentity, AdapterProtocol, AdapterState, Endpoint, EndpointKind};
    use crate::domain::SiteId;

    fn sensor() -> VirtualDeviceDescriptor {
        VirtualDeviceDescriptor {
            schema_version: CYBER_PHYSICAL_SCHEMA_VERSION,
            id: VirtualDeviceId(1),
            adapter_id: AdapterId(2),
            endpoint_id: EndpointId(3),
            class: VirtualDeviceClass::Proximity,
            transport: VirtualTransport::Vsock,
            capabilities: EndpointCapabilitySet::empty().with(EndpointCapability::Sense),
            identity_sha256: [7; 32],
            session_epoch: 4,
            generation: 1,
            state: VirtualDeviceState::Discovered,
            last_heartbeat_tick: 0,
            heartbeat_deadline_ticks: 10,
        }
    }

    #[test]
    fn sensors_register_without_actuator_authority() {
        let mut bus = VirtualDeviceBus::new();
        bus.register(sensor(), None).unwrap();
        bus.mark_ready(VirtualDeviceId(1), 4, 1, 10).unwrap();
        let lease = bus.issue_lease(VirtualDeviceId(1), 10, 5).unwrap();
        assert_eq!(bus.validate_lease(lease, 15), Ok(()));
        assert_eq!(
            bus.validate_lease(lease, 16),
            Err(VirtualDeviceError::LeaseExpired)
        );
    }

    #[test]
    fn actuator_registration_requires_matching_installed_authority() {
        let mut actuator = sensor();
        actuator.class = VirtualDeviceClass::MotorActuator;
        actuator.capabilities = EndpointCapabilitySet::empty().with(EndpointCapability::Move);
        let authority = VirtualDeviceAuthority::new(99).unwrap();
        let authorization = authority.authorize_actuator(&actuator).unwrap();
        let mut bus = VirtualDeviceBus::new();
        assert_eq!(
            bus.register(actuator, Some(authorization)),
            Err(VirtualDeviceError::AuthorizationMismatch)
        );
        bus.install_authority(authority).unwrap();
        bus.register(actuator, Some(authorization)).unwrap();
    }

    #[test]
    fn reset_and_hot_unplug_invalidate_stale_leases() {
        let mut bus = VirtualDeviceBus::new();
        bus.register(sensor(), None).unwrap();
        bus.mark_ready(VirtualDeviceId(1), 4, 1, 10).unwrap();
        let lease = bus.issue_lease(VirtualDeviceId(1), 10, 20).unwrap();
        bus.begin_reset(VirtualDeviceId(1), 4, 1).unwrap();
        assert_eq!(
            bus.validate_lease(lease, 11),
            Err(VirtualDeviceError::DeviceUnavailable)
        );
        assert_eq!(bus.complete_reset(VirtualDeviceId(1), 4, 1, 12), Ok(2));
        assert_eq!(
            bus.validate_lease(lease, 12),
            Err(VirtualDeviceError::GenerationMismatch)
        );
        bus.mark_ready(VirtualDeviceId(1), 4, 2, 12).unwrap();
        bus.hot_unplug(VirtualDeviceId(1), 4, 2).unwrap();
        assert_eq!(
            bus.issue_lease(VirtualDeviceId(1), 13, 1),
            Err(VirtualDeviceError::DeviceUnavailable)
        );
    }

    #[test]
    fn heartbeat_timeout_fails_closed() {
        let mut bus = VirtualDeviceBus::new();
        bus.register(sensor(), None).unwrap();
        bus.mark_ready(VirtualDeviceId(1), 4, 1, 10).unwrap();
        bus.evaluate_liveness(21);
        assert_eq!(
            bus.device(VirtualDeviceId(1)).unwrap().state,
            VirtualDeviceState::Offline
        );
    }

    #[test]
    fn logical_device_must_match_registered_adapter_endpoint_capabilities() {
        let mut registry = AdapterRegistry::new();
        registry
            .register_adapter(AdapterIdentity {
                id: AdapterId(2),
                site_id: SiteId(1),
                protocol: AdapterProtocol::Simulator,
                public_key_sha256: [5; 32],
                firmware_version: 1,
                session_epoch: 4,
                state: AdapterState::Online,
                last_seen_tick: 0,
                last_receive_sequence: 0,
            })
            .unwrap();
        registry
            .register_endpoint(Endpoint {
                id: EndpointId(3),
                adapter_id: AdapterId(2),
                kind: EndpointKind::Sensor,
                zone_id: 1,
                controlled_actor_id: None,
                capabilities: EndpointCapabilitySet::empty().with(EndpointCapability::Sense),
            })
            .unwrap();
        let mut bus = VirtualDeviceBus::new();
        bus.register(sensor(), None).unwrap();
        assert_eq!(bus.validate_binding(&registry, VirtualDeviceId(1)), Ok(()));
        registry
            .register_endpoint(Endpoint {
                id: EndpointId(4),
                adapter_id: AdapterId(2),
                kind: EndpointKind::Sensor,
                zone_id: 1,
                controlled_actor_id: None,
                capabilities: EndpointCapabilitySet::empty(),
            })
            .unwrap();
        let mut mismatched = sensor();
        mismatched.id = VirtualDeviceId(2);
        mismatched.endpoint_id = EndpointId(4);
        bus.register(mismatched, None).unwrap();
        assert_eq!(
            bus.validate_binding(&registry, VirtualDeviceId(2)),
            Err(VirtualDeviceError::CapabilityMismatch)
        );
    }
}
