#![cfg_attr(not(test), no_std)]

extern crate alloc;

pub mod domain;

pub use domain::{
    Actor, ActorId, ActorKind, ActorStatus, Asset, AssetId, AssetState, Capability, CapabilitySet,
    DomainError, DomainRegistry, Position, Qualification, QualificationSet, Site, SiteId,
};
