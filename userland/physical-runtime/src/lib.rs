#![cfg_attr(not(test), no_std)]

extern crate alloc;

pub mod adapter;
pub mod domain;
pub mod safety;
pub mod twin;
pub mod work;

pub use adapter::{
    AdapterCommand, AdapterDriver, AdapterError, AdapterFrame, AdapterId, AdapterIdentity,
    AdapterPayload, AdapterProtocol, AdapterRegistry, AdapterState, CommandKind, Endpoint,
    EndpointCapability, EndpointCapabilitySet, EndpointId, EndpointKind, RoutedCommand,
    SimulatedAdapter,
};
pub use domain::{
    Actor, ActorId, ActorKind, ActorStatus, Asset, AssetId, AssetState, Capability, CapabilitySet,
    DomainError, DomainRegistry, Position, Qualification, QualificationSet, Site, SiteId,
};
pub use safety::{
    EffectKind, Geofence, PhysicalPrediction, PredictionSource, SafetyContext, SafetyDecision,
    SafetyError, SafetyPolicy, SafetyReason, SafetySupervisor, SafetyVerdict,
};
pub use twin::{
    ActorTelemetry, AssetTelemetry, EventEnvelope, EventPayload, OperationalTwin, SensorKind,
    SensorReading, TwinError, TwinSnapshot, ZoneOccupancy,
};
pub use work::{
    ActorConstraint, DispatchError, DispatchReceipt, JobId, JobState, Priority, TaskId, TaskStatus,
    WorkGraph, WorkGraphError, WorkOrder, WorkTask,
};
