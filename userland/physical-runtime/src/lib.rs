#![cfg_attr(not(test), no_std)]

extern crate alloc;

pub mod domain;
pub mod work;

pub use domain::{
    Actor, ActorId, ActorKind, ActorStatus, Asset, AssetId, AssetState, Capability, CapabilitySet,
    DomainError, DomainRegistry, Position, Qualification, QualificationSet, Site, SiteId,
};
pub use work::{
    ActorConstraint, DispatchError, DispatchReceipt, JobId, JobState, Priority, TaskId, TaskStatus,
    WorkGraph, WorkGraphError, WorkOrder, WorkTask,
};
