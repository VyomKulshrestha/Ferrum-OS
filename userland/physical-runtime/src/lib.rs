#![cfg_attr(not(test), no_std)]

extern crate alloc;

pub mod adapter;
pub mod domain;
pub mod fleet;
pub mod model;
pub mod privacy;
pub mod reliability;
pub mod runtime;
pub mod safety;
pub mod scenario;
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
pub use fleet::{
    CommandClaim, CommandDeliveryState, DeviceHealth, DeviceLifecycle, FleetDevice, FleetError,
    FleetManager, PendingUpdate, UpdateManifest, UpdateState, UpdateVerifier,
};
pub use model::{
    PhysicalAction, PhysicalActionKind, PhysicalForecast, PhysicalModelError, PhysicalObservation,
    PhysicalState, PhysicalTransitionModel, PHYSICAL_ACTION_COUNT, PHYSICAL_ACTION_FEATURE_SIZE,
    PHYSICAL_STATE_SIZE,
};
pub use privacy::{
    ConsentGrant, DataAccessRequest, DataKind, DataKindSet, PrivacyAuditEvent, PrivacyDecision,
    PrivacyError, PrivacyGuard, PrivacyReason, ProcessingPurpose, PurposeSet, Representation,
    RetentionPolicy, TenantId,
};
pub use reliability::{
    ReliabilityError, ReliabilityEvent, ReliabilityEventKind, ReliabilityMonitor,
    ReliabilitySnapshot, ServiceLevelAssessment, ServiceLevelObjective,
};
pub use runtime::{PhysicalRuntime, RuntimeError};
pub use safety::{
    EffectKind, Geofence, PhysicalPrediction, PredictionSource, SafetyContext, SafetyDecision,
    SafetyError, SafetyPolicy, SafetyReason, SafetySupervisor, SafetyVerdict,
};
pub use scenario::{
    run_maintenance_demo, run_maintenance_demo_with_predictions, MaintenanceDemoError,
    MaintenanceDemoReport, MAINTENANCE_ASSET_ID, MAINTENANCE_JOB_ID, MAINTENANCE_SITE_ID,
};
pub use twin::{
    ActorTelemetry, AssetTelemetry, EventEnvelope, EventPayload, OperationalTwin, SensorKind,
    SensorReading, TwinError, TwinSnapshot, ZoneOccupancy,
};
pub use work::{
    ActorConstraint, DispatchError, DispatchReceipt, JobId, JobState, Priority, TaskId, TaskStatus,
    WorkGraph, WorkGraphError, WorkOrder, WorkTask,
};
