//! Development-host-managed cell contract.
//!
//! This models the security boundary Ferrum expects from QEMU/Firecracker-style
//! research VMs. It is not a native Ferrum hypervisor and confers no physical
//! authority. Permit issuance and deterministic control are intentionally not
//! representable as cell capabilities.

use alloc::vec::Vec;

pub const MAX_HOST_CELLS: usize = 32;
pub const MAX_CELL_MESSAGE_BYTES: u32 = 65_536;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostCellKind {
    Provider,
    Perception,
    NeuralDecoder,
    UntrustedPlugin,
    DigitalTwin,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum CellCapability {
    ProposeGoal = 0,
    PublishObservation = 1,
    ReadMinimizedContext = 2,
    EmitShadowPrediction = 3,
    RequestAuditAppend = 4,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CellCapabilitySet(u32);

impl CellCapabilitySet {
    pub const fn empty() -> Self {
        Self(0)
    }
    pub const fn with(self, capability: CellCapability) -> Self {
        Self(self.0 | (1 << capability as u8))
    }
    pub const fn contains(self, capability: CellCapability) -> bool {
        self.0 & (1 << capability as u8) != 0
    }
    pub const fn is_valid(self) -> bool {
        self.0 & !0x1f == 0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CellQuota {
    pub memory_bytes: u64,
    pub virtual_cpu_millis_per_second: u16,
    pub maximum_message_bytes: u32,
    pub maximum_messages_per_window: u16,
    pub heartbeat_timeout_ticks: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HostCellManifest {
    pub cell_id: u64,
    pub kind: HostCellKind,
    pub image_sha256: [u8; 32],
    pub configuration_sha256: [u8; 32],
    pub capabilities: CellCapabilitySet,
    pub quota: CellQuota,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CellState {
    Registered,
    Running,
    Paused,
    Terminated,
    Quarantined,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CellIpcEnvelope {
    pub cell_id: u64,
    pub generation: u64,
    pub sequence: u64,
    pub capability: CellCapability,
    pub payload_bytes: u32,
    pub created_at_tick: u64,
    pub expires_at_tick: u64,
    pub attestation_sha256: [u8; 32],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IsolationError {
    InvalidManifest,
    DuplicateCell,
    CapacityExceeded,
    UnknownCell,
    InvalidTransition,
    CapabilityDenied,
    AttestationMismatch,
    GenerationMismatch,
    Replay,
    Expired,
    QuotaExceeded,
    HeartbeatExpired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct HostCell {
    manifest: HostCellManifest,
    state: CellState,
    generation: u64,
    last_sequence: u64,
    last_heartbeat_tick: u64,
    window_started_at_tick: u64,
    messages_in_window: u16,
}

#[derive(Debug, Default)]
pub struct HostCellManager {
    cells: Vec<HostCell>,
}

impl HostCellManager {
    pub const fn new() -> Self {
        Self { cells: Vec::new() }
    }

    pub fn register(&mut self, manifest: HostCellManifest) -> Result<(), IsolationError> {
        if !valid_manifest(manifest) {
            return Err(IsolationError::InvalidManifest);
        }
        if self
            .cells
            .iter()
            .any(|cell| cell.manifest.cell_id == manifest.cell_id)
        {
            return Err(IsolationError::DuplicateCell);
        }
        if self.cells.len() >= MAX_HOST_CELLS {
            return Err(IsolationError::CapacityExceeded);
        }
        self.cells.push(HostCell {
            manifest,
            state: CellState::Registered,
            generation: 0,
            last_sequence: 0,
            last_heartbeat_tick: 0,
            window_started_at_tick: 0,
            messages_in_window: 0,
        });
        Ok(())
    }

    pub fn launch(&mut self, cell_id: u64, tick: u64) -> Result<u64, IsolationError> {
        let cell = self.cell_mut(cell_id)?;
        if !matches!(cell.state, CellState::Registered | CellState::Terminated) {
            return Err(IsolationError::InvalidTransition);
        }
        cell.generation = cell
            .generation
            .checked_add(1)
            .ok_or(IsolationError::InvalidTransition)?;
        cell.state = CellState::Running;
        cell.last_sequence = 0;
        cell.last_heartbeat_tick = tick;
        cell.window_started_at_tick = tick;
        cell.messages_in_window = 0;
        Ok(cell.generation)
    }

    pub fn heartbeat(
        &mut self,
        cell_id: u64,
        generation: u64,
        tick: u64,
    ) -> Result<(), IsolationError> {
        let cell = self.cell_mut(cell_id)?;
        if cell.state != CellState::Running || cell.generation != generation {
            return Err(IsolationError::GenerationMismatch);
        }
        if tick < cell.last_heartbeat_tick {
            return Err(IsolationError::Replay);
        }
        cell.last_heartbeat_tick = tick;
        Ok(())
    }

    pub fn admit(&mut self, envelope: CellIpcEnvelope, tick: u64) -> Result<(), IsolationError> {
        let cell = self.cell_mut(envelope.cell_id)?;
        if cell.state != CellState::Running {
            return Err(IsolationError::InvalidTransition);
        }
        if tick.saturating_sub(cell.last_heartbeat_tick)
            > cell.manifest.quota.heartbeat_timeout_ticks
        {
            cell.state = CellState::Quarantined;
            return Err(IsolationError::HeartbeatExpired);
        }
        if envelope.generation != cell.generation {
            return Err(IsolationError::GenerationMismatch);
        }
        if envelope.sequence == 0 || envelope.sequence <= cell.last_sequence {
            return Err(IsolationError::Replay);
        }
        if tick > envelope.expires_at_tick || envelope.created_at_tick > tick {
            return Err(IsolationError::Expired);
        }
        if envelope.attestation_sha256 != cell.manifest.image_sha256 {
            return Err(IsolationError::AttestationMismatch);
        }
        if !cell.manifest.capabilities.contains(envelope.capability) {
            return Err(IsolationError::CapabilityDenied);
        }
        if envelope.payload_bytes > cell.manifest.quota.maximum_message_bytes {
            return Err(IsolationError::QuotaExceeded);
        }
        if tick.saturating_sub(cell.window_started_at_tick) >= 1_000 {
            cell.window_started_at_tick = tick;
            cell.messages_in_window = 0;
        }
        if cell.messages_in_window >= cell.manifest.quota.maximum_messages_per_window {
            return Err(IsolationError::QuotaExceeded);
        }
        cell.messages_in_window += 1;
        cell.last_sequence = envelope.sequence;
        Ok(())
    }

    pub fn terminate(&mut self, cell_id: u64) -> Result<(), IsolationError> {
        let cell = self.cell_mut(cell_id)?;
        if !matches!(
            cell.state,
            CellState::Running | CellState::Paused | CellState::Quarantined
        ) {
            return Err(IsolationError::InvalidTransition);
        }
        cell.state = CellState::Terminated;
        cell.last_sequence = 0;
        Ok(())
    }

    pub fn state(&self, cell_id: u64) -> Option<CellState> {
        self.cells
            .iter()
            .find(|cell| cell.manifest.cell_id == cell_id)
            .map(|cell| cell.state)
    }

    fn cell_mut(&mut self, cell_id: u64) -> Result<&mut HostCell, IsolationError> {
        self.cells
            .iter_mut()
            .find(|cell| cell.manifest.cell_id == cell_id)
            .ok_or(IsolationError::UnknownCell)
    }
}

fn valid_manifest(manifest: HostCellManifest) -> bool {
    manifest.cell_id != 0
        && manifest.image_sha256.iter().any(|byte| *byte != 0)
        && manifest.configuration_sha256.iter().any(|byte| *byte != 0)
        && manifest.capabilities.is_valid()
        && manifest.quota.memory_bytes >= 16 * 1024 * 1024
        && manifest.quota.virtual_cpu_millis_per_second > 0
        && manifest.quota.virtual_cpu_millis_per_second <= 1_000
        && manifest.quota.maximum_message_bytes > 0
        && manifest.quota.maximum_message_bytes <= MAX_CELL_MESSAGE_BYTES
        && manifest.quota.maximum_messages_per_window > 0
        && manifest.quota.heartbeat_timeout_ticks > 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn manifest() -> HostCellManifest {
        HostCellManifest {
            cell_id: 1,
            kind: HostCellKind::Provider,
            image_sha256: [1; 32],
            configuration_sha256: [2; 32],
            capabilities: CellCapabilitySet::empty().with(CellCapability::ProposeGoal),
            quota: CellQuota {
                memory_bytes: 64 * 1024 * 1024,
                virtual_cpu_millis_per_second: 100,
                maximum_message_bytes: 1024,
                maximum_messages_per_window: 2,
                heartbeat_timeout_ticks: 10,
            },
        }
    }

    fn envelope(generation: u64, sequence: u64) -> CellIpcEnvelope {
        CellIpcEnvelope {
            cell_id: 1,
            generation,
            sequence,
            capability: CellCapability::ProposeGoal,
            payload_bytes: 100,
            created_at_tick: 1,
            expires_at_tick: 10,
            attestation_sha256: [1; 32],
        }
    }

    #[test]
    fn cell_capabilities_expose_proposals_not_execution_authority() {
        let all = [
            CellCapability::ProposeGoal,
            CellCapability::PublishObservation,
            CellCapability::ReadMinimizedContext,
            CellCapability::EmitShadowPrediction,
            CellCapability::RequestAuditAppend,
        ];
        assert_eq!(all.len(), 5);
        // Execution permits, policy mutation, controller ownership, and stop
        // reset are intentionally absent from the representable enum.
        assert!(all.iter().all(|capability| (*capability as u8) <= 4));
    }

    #[test]
    fn restart_invalidates_stale_generation_and_sequence() {
        let mut manager = HostCellManager::new();
        manager.register(manifest()).unwrap();
        let first = manager.launch(1, 0).unwrap();
        manager.admit(envelope(first, 1), 1).unwrap();
        manager.terminate(1).unwrap();
        let second = manager.launch(1, 2).unwrap();
        assert_ne!(first, second);
        assert_eq!(
            manager.admit(envelope(first, 2), 2),
            Err(IsolationError::GenerationMismatch)
        );
    }

    #[test]
    fn forged_attestation_capability_replay_and_exhaustion_fail_closed() {
        let mut manager = HostCellManager::new();
        manager.register(manifest()).unwrap();
        let generation = manager.launch(1, 0).unwrap();
        let mut forged = envelope(generation, 1);
        forged.attestation_sha256 = [9; 32];
        assert_eq!(
            manager.admit(forged, 1),
            Err(IsolationError::AttestationMismatch)
        );
        let mut denied = envelope(generation, 1);
        denied.capability = CellCapability::EmitShadowPrediction;
        assert_eq!(
            manager.admit(denied, 1),
            Err(IsolationError::CapabilityDenied)
        );
        manager.admit(envelope(generation, 1), 1).unwrap();
        assert_eq!(
            manager.admit(envelope(generation, 1), 1),
            Err(IsolationError::Replay)
        );
        manager.admit(envelope(generation, 2), 1).unwrap();
        assert_eq!(
            manager.admit(envelope(generation, 3), 1),
            Err(IsolationError::QuotaExceeded)
        );
    }

    #[test]
    fn heartbeat_loss_quarantines_without_affecting_external_authority() {
        let mut manager = HostCellManager::new();
        manager.register(manifest()).unwrap();
        let generation = manager.launch(1, 0).unwrap();
        assert_eq!(
            manager.admit(envelope(generation, 1), 11),
            Err(IsolationError::HeartbeatExpired)
        );
        assert_eq!(manager.state(1), Some(CellState::Quarantined));
        manager.terminate(1).unwrap();
        assert_eq!(manager.state(1), Some(CellState::Terminated));
    }
}
