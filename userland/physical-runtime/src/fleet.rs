//! Device lifecycle, signed-update orchestration, and recoverable command claims.
//!
//! This module records control-plane intent only. Cryptographic verification is
//! supplied by a platform verifier, while anti-rollback and transition rules
//! remain deterministic and testable in the `no_std` runtime.

use alloc::collections::VecDeque;
use alloc::vec::Vec;

use crate::adapter::{AdapterId, RoutedCommand};
use crate::domain::SiteId;

pub const MAX_FLEET_DEVICES: usize = 128;
pub const MAX_PENDING_UPDATES: usize = 128;
pub const MAX_COMMAND_JOURNAL: usize = 2_048;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceLifecycle {
    Provisioning,
    Active,
    Degraded,
    Offline,
    Updating,
    Quarantined,
    Retired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeviceHealth {
    pub battery_permille: u16,
    pub link_quality_permille: u16,
    pub fault_code: u32,
}

impl DeviceHealth {
    fn is_valid(self) -> bool {
        self.battery_permille <= 1_000 && self.link_quality_permille <= 1_000
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FleetDevice {
    pub adapter_id: AdapterId,
    pub site_id: SiteId,
    pub identity_sha256: [u8; 32],
    pub lifecycle: DeviceLifecycle,
    pub firmware_version: u32,
    pub minimum_allowed_firmware_version: u32,
    pub session_epoch: u64,
    pub last_seen_tick: u64,
    pub health: DeviceHealth,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UpdateManifest {
    pub update_id: u64,
    pub adapter_id: AdapterId,
    pub from_version: u32,
    pub to_version: u32,
    pub artifact_sha256: [u8; 32],
    pub signing_key_id: u64,
    pub signature: [u8; 64],
    pub expires_at_tick: u64,
}

pub trait UpdateVerifier {
    fn verify(&self, manifest: &UpdateManifest) -> bool;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpdateState {
    Staged,
    AppliedAwaitingHealth,
    Committed,
    RolledBack,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PendingUpdate {
    pub manifest: UpdateManifest,
    pub state: UpdateState,
    pub staged_at_tick: u64,
    pub previous_version: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandDeliveryState {
    Queued,
    Dispatched,
    Acknowledged,
    Failed,
    Expired,
    Uncertain,
    Reconciled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CommandClaim {
    pub routed: RoutedCommand,
    pub state: CommandDeliveryState,
    pub attempt_count: u16,
    pub last_transition_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FleetError {
    DuplicateDevice,
    UnknownDevice,
    CapacityExceeded,
    InvalidIdentity,
    InvalidHealth,
    InvalidTransition,
    SessionRollback,
    FirmwareRollback,
    DuplicateUpdate,
    InvalidUpdate,
    SignatureRejected,
    UpdateExpired,
    UpdateConflict,
    DuplicateCommand,
    UnknownCommand,
    CommandExpired,
    CommandConflict,
}

#[derive(Debug, Default)]
pub struct FleetManager {
    devices: Vec<FleetDevice>,
    updates: Vec<PendingUpdate>,
    command_journal: VecDeque<CommandClaim>,
}

impl FleetManager {
    pub const fn new() -> Self {
        Self {
            devices: Vec::new(),
            updates: Vec::new(),
            command_journal: VecDeque::new(),
        }
    }

    pub fn provision(&mut self, device: FleetDevice) -> Result<(), FleetError> {
        if device.identity_sha256.iter().all(|byte| *byte == 0)
            || device.session_epoch == 0
            || !device.health.is_valid()
            || device.firmware_version < device.minimum_allowed_firmware_version
            || device.lifecycle != DeviceLifecycle::Provisioning
        {
            return Err(FleetError::InvalidIdentity);
        }
        if self
            .devices
            .iter()
            .any(|existing| existing.adapter_id == device.adapter_id)
        {
            return Err(FleetError::DuplicateDevice);
        }
        if self.devices.len() >= MAX_FLEET_DEVICES {
            return Err(FleetError::CapacityExceeded);
        }
        self.devices.push(device);
        Ok(())
    }

    pub fn activate(
        &mut self,
        adapter_id: AdapterId,
        session_epoch: u64,
        tick: u64,
    ) -> Result<(), FleetError> {
        let device = self.device_mut(adapter_id)?;
        if device.lifecycle != DeviceLifecycle::Provisioning {
            return Err(FleetError::InvalidTransition);
        }
        if session_epoch < device.session_epoch {
            return Err(FleetError::SessionRollback);
        }
        device.session_epoch = session_epoch;
        device.last_seen_tick = tick;
        device.lifecycle = DeviceLifecycle::Active;
        Ok(())
    }

    pub fn heartbeat(
        &mut self,
        adapter_id: AdapterId,
        session_epoch: u64,
        health: DeviceHealth,
        tick: u64,
    ) -> Result<(), FleetError> {
        if !health.is_valid() {
            return Err(FleetError::InvalidHealth);
        }
        let device = self.device_mut(adapter_id)?;
        if matches!(
            device.lifecycle,
            DeviceLifecycle::Quarantined | DeviceLifecycle::Retired
        ) {
            return Err(FleetError::InvalidTransition);
        }
        if session_epoch < device.session_epoch {
            return Err(FleetError::SessionRollback);
        }
        device.session_epoch = session_epoch;
        device.health = health;
        device.last_seen_tick = tick;
        device.lifecycle = if health.fault_code != 0 || health.link_quality_permille < 250 {
            DeviceLifecycle::Degraded
        } else if device.lifecycle == DeviceLifecycle::Updating {
            DeviceLifecycle::Updating
        } else {
            DeviceLifecycle::Active
        };
        Ok(())
    }

    pub fn mark_stale_offline(&mut self, current_tick: u64, maximum_age_ticks: u64) -> usize {
        let mut changed = 0;
        for device in &mut self.devices {
            if matches!(
                device.lifecycle,
                DeviceLifecycle::Active | DeviceLifecycle::Degraded
            ) && current_tick.saturating_sub(device.last_seen_tick) > maximum_age_ticks
            {
                device.lifecycle = DeviceLifecycle::Offline;
                changed += 1;
            }
        }
        changed
    }

    pub fn quarantine(&mut self, adapter_id: AdapterId) -> Result<(), FleetError> {
        let device = self.device_mut(adapter_id)?;
        if device.lifecycle == DeviceLifecycle::Retired {
            return Err(FleetError::InvalidTransition);
        }
        device.lifecycle = DeviceLifecycle::Quarantined;
        Ok(())
    }

    pub fn retire(&mut self, adapter_id: AdapterId) -> Result<(), FleetError> {
        let device = self.device_mut(adapter_id)?;
        device.lifecycle = DeviceLifecycle::Retired;
        Ok(())
    }

    pub fn stage_update(
        &mut self,
        manifest: UpdateManifest,
        verifier: &impl UpdateVerifier,
        current_tick: u64,
    ) -> Result<(), FleetError> {
        if manifest.update_id == 0
            || manifest.artifact_sha256.iter().all(|byte| *byte == 0)
            || manifest.signing_key_id == 0
            || manifest.signature.iter().all(|byte| *byte == 0)
            || manifest.to_version <= manifest.from_version
        {
            return Err(FleetError::InvalidUpdate);
        }
        if current_tick > manifest.expires_at_tick {
            return Err(FleetError::UpdateExpired);
        }
        if !verifier.verify(&manifest) {
            return Err(FleetError::SignatureRejected);
        }
        if self
            .updates
            .iter()
            .any(|update| update.manifest.update_id == manifest.update_id)
        {
            return Err(FleetError::DuplicateUpdate);
        }
        let device = self
            .devices
            .iter()
            .find(|device| device.adapter_id == manifest.adapter_id)
            .ok_or(FleetError::UnknownDevice)?;
        if device.lifecycle != DeviceLifecycle::Active
            || device.firmware_version != manifest.from_version
            || manifest.to_version < device.minimum_allowed_firmware_version
        {
            return Err(FleetError::FirmwareRollback);
        }
        if self.updates.iter().any(|update| {
            update.manifest.adapter_id == manifest.adapter_id
                && matches!(
                    update.state,
                    UpdateState::Staged | UpdateState::AppliedAwaitingHealth
                )
        }) {
            return Err(FleetError::UpdateConflict);
        }
        if self.updates.len() >= MAX_PENDING_UPDATES {
            return Err(FleetError::CapacityExceeded);
        }
        self.updates.push(PendingUpdate {
            manifest,
            state: UpdateState::Staged,
            staged_at_tick: current_tick,
            previous_version: device.firmware_version,
        });
        Ok(())
    }

    pub fn mark_update_applied(
        &mut self,
        update_id: u64,
        observed_version: u32,
    ) -> Result<(), FleetError> {
        let index = self.update_index(update_id)?;
        let update = self.updates[index];
        if update.state != UpdateState::Staged || observed_version != update.manifest.to_version {
            return Err(FleetError::InvalidTransition);
        }
        let device = self.device_mut(update.manifest.adapter_id)?;
        device.firmware_version = observed_version;
        device.lifecycle = DeviceLifecycle::Updating;
        self.updates[index].state = UpdateState::AppliedAwaitingHealth;
        Ok(())
    }

    pub fn commit_update(&mut self, update_id: u64) -> Result<(), FleetError> {
        let index = self.update_index(update_id)?;
        let update = self.updates[index];
        if update.state != UpdateState::AppliedAwaitingHealth {
            return Err(FleetError::InvalidTransition);
        }
        let device = self.device_mut(update.manifest.adapter_id)?;
        if device.health.fault_code != 0 {
            return Err(FleetError::InvalidHealth);
        }
        device.minimum_allowed_firmware_version = update.manifest.to_version;
        device.lifecycle = DeviceLifecycle::Active;
        self.updates[index].state = UpdateState::Committed;
        Ok(())
    }

    pub fn roll_back_update(&mut self, update_id: u64) -> Result<(), FleetError> {
        let index = self.update_index(update_id)?;
        let update = self.updates[index];
        if update.state != UpdateState::AppliedAwaitingHealth {
            return Err(FleetError::InvalidTransition);
        }
        let device = self.device_mut(update.manifest.adapter_id)?;
        if update.previous_version < device.minimum_allowed_firmware_version {
            return Err(FleetError::FirmwareRollback);
        }
        device.firmware_version = update.previous_version;
        device.lifecycle = DeviceLifecycle::Degraded;
        self.updates[index].state = UpdateState::RolledBack;
        Ok(())
    }

    pub fn queue_command(
        &mut self,
        routed: RoutedCommand,
        current_tick: u64,
    ) -> Result<(), FleetError> {
        if current_tick > routed.command.deadline_tick {
            return Err(FleetError::CommandExpired);
        }
        if self.command_journal.iter().any(|claim| {
            claim.routed.command.command_id == routed.command.command_id
                || claim.routed.command.idempotency_key == routed.command.idempotency_key
        }) {
            return Err(FleetError::DuplicateCommand);
        }
        if self.command_journal.len() >= MAX_COMMAND_JOURNAL {
            return Err(FleetError::CapacityExceeded);
        }
        self.command_journal.push_back(CommandClaim {
            routed,
            state: CommandDeliveryState::Queued,
            attempt_count: 0,
            last_transition_tick: current_tick,
        });
        Ok(())
    }

    pub fn claim_next_ready(
        &mut self,
        adapter_id: AdapterId,
        current_tick: u64,
    ) -> Option<RoutedCommand> {
        for claim in &mut self.command_journal {
            if claim.routed.command.adapter_id == adapter_id
                && matches!(
                    claim.state,
                    CommandDeliveryState::Queued | CommandDeliveryState::Failed
                )
            {
                if current_tick > claim.routed.command.deadline_tick {
                    claim.state = CommandDeliveryState::Expired;
                    claim.last_transition_tick = current_tick;
                    continue;
                }
                claim.state = CommandDeliveryState::Dispatched;
                claim.attempt_count = claim.attempt_count.saturating_add(1);
                claim.last_transition_tick = current_tick;
                return Some(claim.routed);
            }
        }
        None
    }

    pub fn record_delivery(
        &mut self,
        command_id: u64,
        state: CommandDeliveryState,
        tick: u64,
    ) -> Result<(), FleetError> {
        let claim = self
            .command_journal
            .iter_mut()
            .find(|claim| claim.routed.command.command_id == command_id)
            .ok_or(FleetError::UnknownCommand)?;
        let valid = matches!(
            (claim.state, state),
            (
                CommandDeliveryState::Dispatched,
                CommandDeliveryState::Acknowledged
            ) | (
                CommandDeliveryState::Dispatched,
                CommandDeliveryState::Failed
            ) | (
                CommandDeliveryState::Dispatched,
                CommandDeliveryState::Uncertain
            ) | (
                CommandDeliveryState::Uncertain,
                CommandDeliveryState::Reconciled
            )
        );
        if !valid {
            return Err(FleetError::CommandConflict);
        }
        claim.state = state;
        claim.last_transition_tick = tick;
        Ok(())
    }

    pub fn recover_interrupted_dispatches(&mut self, tick: u64) -> usize {
        let mut recovered = 0;
        for claim in &mut self.command_journal {
            if claim.state == CommandDeliveryState::Dispatched {
                claim.state = CommandDeliveryState::Uncertain;
                claim.last_transition_tick = tick;
                recovered += 1;
            }
        }
        recovered
    }

    pub fn device(&self, adapter_id: AdapterId) -> Option<&FleetDevice> {
        self.devices
            .iter()
            .find(|device| device.adapter_id == adapter_id)
    }

    pub fn update(&self, update_id: u64) -> Option<&PendingUpdate> {
        self.updates
            .iter()
            .find(|update| update.manifest.update_id == update_id)
    }

    pub fn command_claim(&self, command_id: u64) -> Option<&CommandClaim> {
        self.command_journal
            .iter()
            .find(|claim| claim.routed.command.command_id == command_id)
    }

    pub fn devices(&self) -> &[FleetDevice] {
        &self.devices
    }

    fn device_mut(&mut self, adapter_id: AdapterId) -> Result<&mut FleetDevice, FleetError> {
        self.devices
            .iter_mut()
            .find(|device| device.adapter_id == adapter_id)
            .ok_or(FleetError::UnknownDevice)
    }

    fn update_index(&self, update_id: u64) -> Result<usize, FleetError> {
        self.updates
            .iter()
            .position(|update| update.manifest.update_id == update_id)
            .ok_or(FleetError::InvalidUpdate)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::adapter::{AdapterCommand, CommandKind, EndpointId};

    struct AcceptingVerifier;

    impl UpdateVerifier for AcceptingVerifier {
        fn verify(&self, manifest: &UpdateManifest) -> bool {
            manifest.signing_key_id == 7 && manifest.signature[0] == 9
        }
    }

    fn device() -> FleetDevice {
        FleetDevice {
            adapter_id: AdapterId(1),
            site_id: SiteId(2),
            identity_sha256: [3; 32],
            lifecycle: DeviceLifecycle::Provisioning,
            firmware_version: 10,
            minimum_allowed_firmware_version: 10,
            session_epoch: 1,
            last_seen_tick: 0,
            health: DeviceHealth {
                battery_permille: 900,
                link_quality_permille: 900,
                fault_code: 0,
            },
        }
    }

    fn manifest() -> UpdateManifest {
        let mut signature = [0; 64];
        signature[0] = 9;
        UpdateManifest {
            update_id: 77,
            adapter_id: AdapterId(1),
            from_version: 10,
            to_version: 11,
            artifact_sha256: [4; 32],
            signing_key_id: 7,
            signature,
            expires_at_tick: 500,
        }
    }

    fn command(id: u64, deadline_tick: u64) -> RoutedCommand {
        RoutedCommand {
            command: AdapterCommand {
                command_id: id,
                idempotency_key: id + 100,
                adapter_id: AdapterId(1),
                endpoint_id: EndpointId(2),
                session_epoch: 1,
                kind: CommandKind::MoveTo,
                argument0: 0,
                argument1: 0,
                argument2: 0,
                deadline_tick,
            },
            policy_revision: 7,
        }
    }

    #[test]
    fn lifecycle_fails_closed_on_stale_or_rolled_back_sessions() {
        let mut fleet = FleetManager::new();
        fleet.provision(device()).unwrap();
        fleet.activate(AdapterId(1), 2, 10).unwrap();
        assert_eq!(
            fleet.heartbeat(
                AdapterId(1),
                1,
                DeviceHealth {
                    battery_permille: 800,
                    link_quality_permille: 800,
                    fault_code: 0,
                },
                11
            ),
            Err(FleetError::SessionRollback)
        );
        assert_eq!(fleet.mark_stale_offline(100, 20), 1);
        assert_eq!(
            fleet.device(AdapterId(1)).unwrap().lifecycle,
            DeviceLifecycle::Offline
        );
    }

    #[test]
    fn signed_update_requires_verification_and_health_before_commit() {
        let mut fleet = FleetManager::new();
        fleet.provision(device()).unwrap();
        fleet.activate(AdapterId(1), 1, 10).unwrap();
        fleet
            .stage_update(manifest(), &AcceptingVerifier, 20)
            .unwrap();
        fleet.mark_update_applied(77, 11).unwrap();
        fleet.commit_update(77).unwrap();
        let updated = fleet.device(AdapterId(1)).unwrap();
        assert_eq!(updated.firmware_version, 11);
        assert_eq!(updated.minimum_allowed_firmware_version, 11);
        assert_eq!(fleet.update(77).unwrap().state, UpdateState::Committed);
    }

    #[test]
    fn rejected_signature_and_firmware_rollback_never_stage() {
        struct RejectingVerifier;
        impl UpdateVerifier for RejectingVerifier {
            fn verify(&self, _: &UpdateManifest) -> bool {
                false
            }
        }
        let mut fleet = FleetManager::new();
        fleet.provision(device()).unwrap();
        fleet.activate(AdapterId(1), 1, 10).unwrap();
        assert_eq!(
            fleet.stage_update(manifest(), &RejectingVerifier, 20),
            Err(FleetError::SignatureRejected)
        );
        let mut rollback = manifest();
        rollback.from_version = 9;
        rollback.to_version = 10;
        assert_eq!(
            fleet.stage_update(rollback, &AcceptingVerifier, 20),
            Err(FleetError::FirmwareRollback)
        );
    }

    #[test]
    fn interrupted_delivery_becomes_uncertain_and_requires_reconciliation() {
        let mut fleet = FleetManager::new();
        fleet.queue_command(command(1, 100), 10).unwrap();
        assert_eq!(
            fleet.claim_next_ready(AdapterId(1), 11),
            Some(command(1, 100))
        );
        assert_eq!(fleet.recover_interrupted_dispatches(12), 1);
        assert_eq!(
            fleet.command_claim(1).unwrap().state,
            CommandDeliveryState::Uncertain
        );
        assert_eq!(fleet.claim_next_ready(AdapterId(1), 13), None);
        fleet
            .record_delivery(1, CommandDeliveryState::Reconciled, 14)
            .unwrap();
    }

    #[test]
    fn expired_and_duplicate_commands_do_not_execute() {
        let mut fleet = FleetManager::new();
        assert_eq!(
            fleet.queue_command(command(1, 9), 10),
            Err(FleetError::CommandExpired)
        );
        fleet.queue_command(command(1, 20), 10).unwrap();
        assert_eq!(
            fleet.queue_command(command(1, 20), 10),
            Err(FleetError::DuplicateCommand)
        );
        assert_eq!(fleet.claim_next_ready(AdapterId(1), 21), None);
        assert_eq!(
            fleet.command_claim(1).unwrap().state,
            CommandDeliveryState::Expired
        );
    }
}
