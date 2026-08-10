//! Consent, tenant isolation, data minimisation, and retention decisions.
//!
//! Raw audio/video and biometric material are denied by default. The runtime
//! returns a decision describing the minimum permitted representation; storage
//! and transport implementations must enforce that decision at their boundary.

use alloc::collections::VecDeque;
use alloc::vec::Vec;

use crate::domain::{ActorId, SiteId};

pub const MAX_TENANT_SITES: usize = 128;
pub const MAX_CONSENT_GRANTS: usize = 512;
pub const MAX_RETENTION_POLICIES: usize = 64;
pub const MAX_PRIVACY_AUDIT_EVENTS: usize = 2_048;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TenantId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum DataKind {
    OperationalTelemetry = 0,
    Location = 1,
    Audio = 2,
    Video = 3,
    Biometric = 4,
    WorkRecord = 5,
    SafetyEvent = 6,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct DataKindSet(u64);

impl DataKindSet {
    pub const fn empty() -> Self {
        Self(0)
    }

    pub const fn with(self, kind: DataKind) -> Self {
        Self(self.0 | (1u64 << kind as u8))
    }

    pub const fn contains(self, kind: DataKind) -> bool {
        self.0 & (1u64 << kind as u8) != 0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum ProcessingPurpose {
    Dispatch = 0,
    Safety = 1,
    Maintenance = 2,
    Training = 3,
    IncidentReview = 4,
    ProductAnalytics = 5,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct PurposeSet(u64);

impl PurposeSet {
    pub const fn empty() -> Self {
        Self(0)
    }

    pub const fn with(self, purpose: ProcessingPurpose) -> Self {
        Self(self.0 | (1u64 << purpose as u8))
    }

    pub const fn contains(self, purpose: ProcessingPurpose) -> bool {
        self.0 & (1u64 << purpose as u8) != 0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConsentGrant {
    pub grant_id: u64,
    pub tenant_id: TenantId,
    pub site_id: SiteId,
    pub subject_actor_id: ActorId,
    pub data_kinds: DataKindSet,
    pub purposes: PurposeSet,
    pub allow_raw_media: bool,
    pub issued_at_tick: u64,
    pub expires_at_tick: u64,
    pub revoked_at_tick: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RetentionPolicy {
    pub data_kind: DataKind,
    pub purpose: ProcessingPurpose,
    pub maximum_age_ticks: u64,
    pub retain_raw_content: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DataAccessRequest {
    pub request_id: u64,
    pub tenant_id: TenantId,
    pub site_id: SiteId,
    pub subject_actor_id: Option<ActorId>,
    pub data_kind: DataKind,
    pub purpose: ProcessingPurpose,
    pub raw_content_requested: bool,
    pub observed_at_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Representation {
    Denied,
    Aggregate,
    Redacted,
    Raw,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PrivacyReason {
    AllowedByOperationalPolicy,
    AllowedByConsent,
    UnknownTenantSite,
    ConsentRequired,
    ConsentExpired,
    ConsentRevoked,
    PurposeNotGranted,
    DataKindNotGranted,
    RawMediaNotGranted,
    RetentionExpired,
    MissingRetentionPolicy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PrivacyDecision {
    pub representation: Representation,
    pub reason: PrivacyReason,
    pub delete_after_tick: u64,
    pub consent_grant_id: Option<u64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PrivacyAuditEvent {
    pub request_id: u64,
    pub tenant_id: TenantId,
    pub site_id: SiteId,
    pub data_kind: DataKind,
    pub purpose: ProcessingPurpose,
    pub decision: PrivacyDecision,
    pub decided_at_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PrivacyError {
    DuplicateTenantSite,
    DuplicateGrant,
    DuplicatePolicy,
    UnknownGrant,
    InvalidGrant,
    InvalidPolicy,
    CapacityExceeded,
}

#[derive(Debug, Default)]
pub struct PrivacyGuard {
    tenant_sites: Vec<(TenantId, SiteId)>,
    grants: Vec<ConsentGrant>,
    policies: Vec<RetentionPolicy>,
    audit: VecDeque<PrivacyAuditEvent>,
}

impl PrivacyGuard {
    pub const fn new() -> Self {
        Self {
            tenant_sites: Vec::new(),
            grants: Vec::new(),
            policies: Vec::new(),
            audit: VecDeque::new(),
        }
    }

    pub fn bind_site(&mut self, tenant_id: TenantId, site_id: SiteId) -> Result<(), PrivacyError> {
        if self
            .tenant_sites
            .iter()
            .any(|binding| binding.0 == tenant_id && binding.1 == site_id)
        {
            return Err(PrivacyError::DuplicateTenantSite);
        }
        if self.tenant_sites.len() >= MAX_TENANT_SITES {
            return Err(PrivacyError::CapacityExceeded);
        }
        self.tenant_sites.push((tenant_id, site_id));
        Ok(())
    }

    pub fn install_retention_policy(
        &mut self,
        policy: RetentionPolicy,
    ) -> Result<(), PrivacyError> {
        if policy.maximum_age_ticks == 0 {
            return Err(PrivacyError::InvalidPolicy);
        }
        if self.policies.iter().any(|existing| {
            existing.data_kind == policy.data_kind && existing.purpose == policy.purpose
        }) {
            return Err(PrivacyError::DuplicatePolicy);
        }
        if self.policies.len() >= MAX_RETENTION_POLICIES {
            return Err(PrivacyError::CapacityExceeded);
        }
        self.policies.push(policy);
        Ok(())
    }

    pub fn grant_consent(&mut self, grant: ConsentGrant) -> Result<(), PrivacyError> {
        if grant.grant_id == 0
            || grant.expires_at_tick <= grant.issued_at_tick
            || grant.revoked_at_tick.is_some()
            || !self
                .tenant_sites
                .iter()
                .any(|binding| binding.0 == grant.tenant_id && binding.1 == grant.site_id)
        {
            return Err(PrivacyError::InvalidGrant);
        }
        if self
            .grants
            .iter()
            .any(|existing| existing.grant_id == grant.grant_id)
        {
            return Err(PrivacyError::DuplicateGrant);
        }
        if self.grants.len() >= MAX_CONSENT_GRANTS {
            return Err(PrivacyError::CapacityExceeded);
        }
        self.grants.push(grant);
        Ok(())
    }

    pub fn revoke_consent(&mut self, grant_id: u64, tick: u64) -> Result<(), PrivacyError> {
        let grant = self
            .grants
            .iter_mut()
            .find(|grant| grant.grant_id == grant_id)
            .ok_or(PrivacyError::UnknownGrant)?;
        if tick < grant.issued_at_tick || grant.revoked_at_tick.is_some() {
            return Err(PrivacyError::InvalidGrant);
        }
        grant.revoked_at_tick = Some(tick);
        Ok(())
    }

    pub fn evaluate(&mut self, request: DataAccessRequest, current_tick: u64) -> PrivacyDecision {
        let decision = self.evaluate_inner(request, current_tick);
        if self.audit.len() >= MAX_PRIVACY_AUDIT_EVENTS {
            self.audit.pop_front();
        }
        self.audit.push_back(PrivacyAuditEvent {
            request_id: request.request_id,
            tenant_id: request.tenant_id,
            site_id: request.site_id,
            data_kind: request.data_kind,
            purpose: request.purpose,
            decision,
            decided_at_tick: current_tick,
        });
        decision
    }

    fn evaluate_inner(&self, request: DataAccessRequest, current_tick: u64) -> PrivacyDecision {
        if !self
            .tenant_sites
            .iter()
            .any(|binding| binding.0 == request.tenant_id && binding.1 == request.site_id)
        {
            return denied(PrivacyReason::UnknownTenantSite);
        }
        let policy = match self.policies.iter().find(|policy| {
            policy.data_kind == request.data_kind && policy.purpose == request.purpose
        }) {
            Some(policy) => policy,
            None => return denied(PrivacyReason::MissingRetentionPolicy),
        };
        if current_tick.saturating_sub(request.observed_at_tick) > policy.maximum_age_ticks {
            return denied(PrivacyReason::RetentionExpired);
        }

        let delete_after_tick = request
            .observed_at_tick
            .saturating_add(policy.maximum_age_ticks);
        if !requires_consent(request.data_kind) {
            return PrivacyDecision {
                representation: if request.raw_content_requested && policy.retain_raw_content {
                    Representation::Raw
                } else {
                    Representation::Aggregate
                },
                reason: PrivacyReason::AllowedByOperationalPolicy,
                delete_after_tick,
                consent_grant_id: None,
            };
        }

        let subject = match request.subject_actor_id {
            Some(subject) => subject,
            None => return denied(PrivacyReason::ConsentRequired),
        };
        let matching = self.grants.iter().find(|grant| {
            grant.tenant_id == request.tenant_id
                && grant.site_id == request.site_id
                && grant.subject_actor_id == subject
        });
        let grant = match matching {
            Some(grant) => grant,
            None => return denied(PrivacyReason::ConsentRequired),
        };
        if grant
            .revoked_at_tick
            .is_some_and(|tick| tick <= current_tick)
        {
            return denied(PrivacyReason::ConsentRevoked);
        }
        if current_tick > grant.expires_at_tick {
            return denied(PrivacyReason::ConsentExpired);
        }
        if !grant.data_kinds.contains(request.data_kind) {
            return denied(PrivacyReason::DataKindNotGranted);
        }
        if !grant.purposes.contains(request.purpose) {
            return denied(PrivacyReason::PurposeNotGranted);
        }
        if request.raw_content_requested && (!grant.allow_raw_media || !policy.retain_raw_content) {
            return PrivacyDecision {
                representation: Representation::Redacted,
                reason: PrivacyReason::RawMediaNotGranted,
                delete_after_tick,
                consent_grant_id: Some(grant.grant_id),
            };
        }
        PrivacyDecision {
            representation: if request.raw_content_requested {
                Representation::Raw
            } else {
                Representation::Redacted
            },
            reason: PrivacyReason::AllowedByConsent,
            delete_after_tick,
            consent_grant_id: Some(grant.grant_id),
        }
    }

    pub fn audit_events(&self) -> &VecDeque<PrivacyAuditEvent> {
        &self.audit
    }
}

const fn requires_consent(kind: DataKind) -> bool {
    matches!(
        kind,
        DataKind::Location | DataKind::Audio | DataKind::Video | DataKind::Biometric
    )
}

const fn denied(reason: PrivacyReason) -> PrivacyDecision {
    PrivacyDecision {
        representation: Representation::Denied,
        reason,
        delete_after_tick: 0,
        consent_grant_id: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn guard() -> PrivacyGuard {
        let mut guard = PrivacyGuard::new();
        guard.bind_site(TenantId(1), SiteId(2)).unwrap();
        guard
            .install_retention_policy(RetentionPolicy {
                data_kind: DataKind::Location,
                purpose: ProcessingPurpose::Safety,
                maximum_age_ticks: 100,
                retain_raw_content: false,
            })
            .unwrap();
        guard
            .install_retention_policy(RetentionPolicy {
                data_kind: DataKind::OperationalTelemetry,
                purpose: ProcessingPurpose::Maintenance,
                maximum_age_ticks: 1_000,
                retain_raw_content: true,
            })
            .unwrap();
        guard
    }

    fn location_request() -> DataAccessRequest {
        DataAccessRequest {
            request_id: 1,
            tenant_id: TenantId(1),
            site_id: SiteId(2),
            subject_actor_id: Some(ActorId(3)),
            data_kind: DataKind::Location,
            purpose: ProcessingPurpose::Safety,
            raw_content_requested: false,
            observed_at_tick: 100,
        }
    }

    fn consent() -> ConsentGrant {
        ConsentGrant {
            grant_id: 5,
            tenant_id: TenantId(1),
            site_id: SiteId(2),
            subject_actor_id: ActorId(3),
            data_kinds: DataKindSet::empty().with(DataKind::Location),
            purposes: PurposeSet::empty().with(ProcessingPurpose::Safety),
            allow_raw_media: false,
            issued_at_tick: 50,
            expires_at_tick: 500,
            revoked_at_tick: None,
        }
    }

    #[test]
    fn sensitive_data_is_denied_without_scoped_consent() {
        let mut guard = guard();
        let decision = guard.evaluate(location_request(), 110);
        assert_eq!(decision.representation, Representation::Denied);
        assert_eq!(decision.reason, PrivacyReason::ConsentRequired);
    }

    #[test]
    fn consent_is_bound_to_subject_kind_purpose_site_and_expiry() {
        let mut guard = guard();
        guard.grant_consent(consent()).unwrap();
        let allowed = guard.evaluate(location_request(), 110);
        assert_eq!(allowed.representation, Representation::Redacted);
        assert_eq!(allowed.consent_grant_id, Some(5));

        let mut analytics = location_request();
        analytics.purpose = ProcessingPurpose::ProductAnalytics;
        assert_eq!(
            guard.evaluate(analytics, 110).reason,
            PrivacyReason::MissingRetentionPolicy
        );
        assert_eq!(
            guard.evaluate(location_request(), 501).reason,
            PrivacyReason::RetentionExpired
        );
        let mut fresh_but_after_consent = location_request();
        fresh_but_after_consent.observed_at_tick = 480;
        assert_eq!(
            guard.evaluate(fresh_but_after_consent, 501).reason,
            PrivacyReason::ConsentExpired
        );
    }

    #[test]
    fn revocation_is_immediate_and_audited() {
        let mut guard = guard();
        guard.grant_consent(consent()).unwrap();
        guard.revoke_consent(5, 120).unwrap();
        let decision = guard.evaluate(location_request(), 120);
        assert_eq!(decision.reason, PrivacyReason::ConsentRevoked);
        assert_eq!(guard.audit_events().len(), 1);
        assert_eq!(guard.audit_events()[0].decision, decision);
    }

    #[test]
    fn tenant_site_isolation_precedes_consent_lookup() {
        let mut guard = guard();
        guard.grant_consent(consent()).unwrap();
        let mut cross_tenant = location_request();
        cross_tenant.tenant_id = TenantId(99);
        assert_eq!(
            guard.evaluate(cross_tenant, 110).reason,
            PrivacyReason::UnknownTenantSite
        );
    }

    #[test]
    fn operational_telemetry_is_minimised_without_subject_consent() {
        let mut guard = guard();
        let request = DataAccessRequest {
            request_id: 2,
            tenant_id: TenantId(1),
            site_id: SiteId(2),
            subject_actor_id: None,
            data_kind: DataKind::OperationalTelemetry,
            purpose: ProcessingPurpose::Maintenance,
            raw_content_requested: false,
            observed_at_tick: 100,
        };
        let decision = guard.evaluate(request, 120);
        assert_eq!(decision.representation, Representation::Aggregate);
        assert_eq!(decision.delete_after_tick, 1_100);
    }

    #[test]
    fn raw_media_requires_both_explicit_policy_and_subject_consent() {
        let mut guard = PrivacyGuard::new();
        guard.bind_site(TenantId(1), SiteId(2)).unwrap();
        guard
            .install_retention_policy(RetentionPolicy {
                data_kind: DataKind::Video,
                purpose: ProcessingPurpose::Safety,
                maximum_age_ticks: 10,
                retain_raw_content: true,
            })
            .unwrap();
        let mut grant = consent();
        grant.data_kinds = DataKindSet::empty().with(DataKind::Video);
        grant.allow_raw_media = true;
        guard.grant_consent(grant).unwrap();
        let decision = guard.evaluate(
            DataAccessRequest {
                request_id: 3,
                tenant_id: TenantId(1),
                site_id: SiteId(2),
                subject_actor_id: Some(ActorId(3)),
                data_kind: DataKind::Video,
                purpose: ProcessingPurpose::Safety,
                raw_content_requested: true,
                observed_at_tick: 100,
            },
            105,
        );
        assert_eq!(decision.representation, Representation::Raw);
        assert_eq!(decision.delete_after_tick, 110);
    }
}
