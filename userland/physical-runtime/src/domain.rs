//! Typed physical-world identities and capability metadata.
//!
//! These types deliberately contain no device I/O or model inference. They are
//! deterministic values that can be validated before an operation reaches an
//! adapter, the predictive safety layer, or a kernel syscall.

use alloc::string::String;
use alloc::vec::Vec;

pub const MAX_ACTORS: usize = 128;
pub const MAX_ASSETS: usize = 256;
pub const MAX_SITES: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ActorId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct AssetId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SiteId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActorKind {
    Human,
    Agent,
    Robot,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActorStatus {
    Available,
    Busy,
    Offline,
    EmergencyStop,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssetState {
    Operational,
    Degraded,
    Offline,
    LockedOut,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Capability {
    Inspect = 0,
    Diagnose = 1,
    Repair = 2,
    Navigate = 3,
    Lift = 4,
    Communicate = 5,
    Approve = 6,
    ExecuteDigital = 7,
    EmergencyResponse = 8,
    OperateMachine = 9,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CapabilitySet(u64);

impl CapabilitySet {
    pub const fn empty() -> Self {
        Self(0)
    }

    pub const fn from_bits(bits: u64) -> Self {
        Self(bits)
    }

    pub const fn bits(self) -> u64 {
        self.0
    }

    pub const fn with(self, capability: Capability) -> Self {
        Self(self.0 | (1u64 << capability as u8))
    }

    pub const fn contains(self, capability: Capability) -> bool {
        self.0 & (1u64 << capability as u8) != 0
    }

    pub const fn contains_all(self, required: Self) -> bool {
        self.0 & required.0 == required.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Qualification {
    SiteInduction = 0,
    Electrical = 1,
    Mechanical = 2,
    WorkingAtHeight = 3,
    HeavyEquipment = 4,
    SafetySupervisor = 5,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct QualificationSet(u64);

impl QualificationSet {
    pub const fn empty() -> Self {
        Self(0)
    }

    pub const fn with(self, qualification: Qualification) -> Self {
        Self(self.0 | (1u64 << qualification as u8))
    }

    pub const fn contains_all(self, required: Self) -> bool {
        self.0 & required.0 == required.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Position {
    pub x_mm: i32,
    pub y_mm: i32,
    pub z_mm: i32,
    pub zone_id: u32,
    pub observed_at_tick: u64,
}

impl Position {
    pub const fn origin(zone_id: u32, observed_at_tick: u64) -> Self {
        Self {
            x_mm: 0,
            y_mm: 0,
            z_mm: 0,
            zone_id,
            observed_at_tick,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Actor {
    pub id: ActorId,
    pub name: String,
    pub kind: ActorKind,
    pub status: ActorStatus,
    pub site_id: SiteId,
    pub position: Position,
    pub capabilities: CapabilitySet,
    pub qualifications: QualificationSet,
    pub available_from_tick: u64,
    pub last_seen_tick: u64,
    pub battery_permille: u16,
    pub load_permille: u16,
    pub max_payload_grams: u32,
}

impl Actor {
    pub fn is_dispatchable_at(&self, tick: u64) -> bool {
        self.status == ActorStatus::Available
            && self.available_from_tick <= tick
            && self.battery_permille > 0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Asset {
    pub id: AssetId,
    pub name: String,
    pub site_id: SiteId,
    pub position: Position,
    pub state: AssetState,
    pub last_service_tick: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Site {
    pub id: SiteId,
    pub name: String,
    pub emergency_zone_id: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DomainError {
    DuplicateId,
    CapacityExceeded,
    UnknownSite,
    InvalidTelemetry,
}

#[derive(Debug, Default)]
pub struct DomainRegistry {
    actors: Vec<Actor>,
    assets: Vec<Asset>,
    sites: Vec<Site>,
}

impl DomainRegistry {
    pub const fn new() -> Self {
        Self {
            actors: Vec::new(),
            assets: Vec::new(),
            sites: Vec::new(),
        }
    }

    pub fn register_site(&mut self, site: Site) -> Result<(), DomainError> {
        if self.sites.iter().any(|existing| existing.id == site.id) {
            return Err(DomainError::DuplicateId);
        }
        if self.sites.len() >= MAX_SITES {
            return Err(DomainError::CapacityExceeded);
        }
        self.sites.push(site);
        Ok(())
    }

    pub fn register_actor(&mut self, actor: Actor) -> Result<(), DomainError> {
        if actor.battery_permille > 1_000 || actor.load_permille > 1_000 {
            return Err(DomainError::InvalidTelemetry);
        }
        if !self.sites.iter().any(|site| site.id == actor.site_id) {
            return Err(DomainError::UnknownSite);
        }
        if self.actors.iter().any(|existing| existing.id == actor.id) {
            return Err(DomainError::DuplicateId);
        }
        if self.actors.len() >= MAX_ACTORS {
            return Err(DomainError::CapacityExceeded);
        }
        self.actors.push(actor);
        Ok(())
    }

    pub fn register_asset(&mut self, asset: Asset) -> Result<(), DomainError> {
        if !self.sites.iter().any(|site| site.id == asset.site_id) {
            return Err(DomainError::UnknownSite);
        }
        if self.assets.iter().any(|existing| existing.id == asset.id) {
            return Err(DomainError::DuplicateId);
        }
        if self.assets.len() >= MAX_ASSETS {
            return Err(DomainError::CapacityExceeded);
        }
        self.assets.push(asset);
        Ok(())
    }

    pub fn actor(&self, id: ActorId) -> Option<&Actor> {
        self.actors.iter().find(|actor| actor.id == id)
    }

    pub fn actor_mut(&mut self, id: ActorId) -> Option<&mut Actor> {
        self.actors.iter_mut().find(|actor| actor.id == id)
    }

    pub fn asset(&self, id: AssetId) -> Option<&Asset> {
        self.assets.iter().find(|asset| asset.id == id)
    }

    pub fn site(&self, id: SiteId) -> Option<&Site> {
        self.sites.iter().find(|site| site.id == id)
    }

    pub fn actors(&self) -> &[Actor] {
        &self.actors
    }

    pub fn assets(&self) -> &[Asset] {
        &self.assets
    }

    pub fn sites(&self) -> &[Site] {
        &self.sites
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::string::ToString;

    fn site() -> Site {
        Site {
            id: SiteId(1),
            name: "Plant A".to_string(),
            emergency_zone_id: 999,
        }
    }

    fn technician() -> Actor {
        Actor {
            id: ActorId(10),
            name: "Technician".to_string(),
            kind: ActorKind::Human,
            status: ActorStatus::Available,
            site_id: SiteId(1),
            position: Position::origin(7, 100),
            capabilities: CapabilitySet::empty()
                .with(Capability::Inspect)
                .with(Capability::Repair),
            qualifications: QualificationSet::empty()
                .with(Qualification::SiteInduction)
                .with(Qualification::Mechanical),
            available_from_tick: 100,
            last_seen_tick: 100,
            battery_permille: 1_000,
            load_permille: 0,
            max_payload_grams: 15_000,
        }
    }

    #[test]
    fn capability_sets_require_every_requested_bit() {
        let held = CapabilitySet::empty()
            .with(Capability::Inspect)
            .with(Capability::Repair);
        assert!(held.contains(Capability::Inspect));
        assert!(held.contains_all(CapabilitySet::empty().with(Capability::Repair)));
        assert!(!held.contains_all(CapabilitySet::empty().with(Capability::Lift)));
    }

    #[test]
    fn actor_dispatchability_is_fail_closed() {
        let mut actor = technician();
        assert!(actor.is_dispatchable_at(100));
        actor.status = ActorStatus::EmergencyStop;
        assert!(!actor.is_dispatchable_at(100));
        actor.status = ActorStatus::Available;
        actor.battery_permille = 0;
        assert!(!actor.is_dispatchable_at(100));
    }

    #[test]
    fn registry_requires_known_sites_and_unique_ids() {
        let mut registry = DomainRegistry::new();
        assert_eq!(
            registry.register_actor(technician()),
            Err(DomainError::UnknownSite)
        );
        registry.register_site(site()).unwrap();
        registry.register_actor(technician()).unwrap();
        assert_eq!(
            registry.register_actor(technician()),
            Err(DomainError::DuplicateId)
        );
        assert_eq!(registry.actor(ActorId(10)).unwrap().kind, ActorKind::Human);
    }

    #[test]
    fn registry_rejects_impossible_telemetry() {
        let mut registry = DomainRegistry::new();
        registry.register_site(site()).unwrap();
        let mut actor = technician();
        actor.battery_permille = 1_001;
        assert_eq!(
            registry.register_actor(actor),
            Err(DomainError::InvalidTelemetry)
        );
    }
}
