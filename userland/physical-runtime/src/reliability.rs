//! Reliability, intervention, and incident accounting for physical work.
//!
//! Metrics use integer counters and permille rates so they remain deterministic
//! in kernel-adjacent builds. The bounded event ring supports diagnosis without
//! turning telemetry into an unbounded memory sink.

use alloc::collections::VecDeque;
use alloc::vec::Vec;

use crate::domain::SiteId;
use crate::work::{JobId, TaskId};

pub const MAX_RELIABILITY_SITES: usize = 32;
pub const MAX_RELIABILITY_EVENTS: usize = 4_096;
pub const MAX_OPEN_INCIDENTS: usize = 128;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReliabilityEventKind {
    TaskAttempted {
        job_id: JobId,
        task_id: TaskId,
    },
    TaskSucceeded {
        job_id: JobId,
        task_id: TaskId,
        duration_ticks: u64,
    },
    TaskFailed {
        job_id: JobId,
        task_id: TaskId,
    },
    SafetyIntervention {
        reason_code: u32,
    },
    NearMiss {
        severity_permille: u16,
    },
    HumanOverride {
        reason_code: u32,
    },
    DeviceCommandRetried,
    DeviceCommandUncertain,
    DowntimeStarted {
        incident_id: u64,
    },
    DowntimeEnded {
        incident_id: u64,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReliabilityEvent {
    pub event_id: u64,
    pub site_id: SiteId,
    pub observed_at_tick: u64,
    pub kind: ReliabilityEventKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct OpenIncident {
    incident_id: u64,
    site_id: SiteId,
    started_at_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct SiteCounters {
    site_id: SiteId,
    task_attempts: u64,
    task_successes: u64,
    task_failures: u64,
    total_task_duration_ticks: u64,
    maximum_task_duration_ticks: u64,
    safety_interventions: u64,
    near_misses: u64,
    maximum_near_miss_severity_permille: u16,
    human_overrides: u64,
    command_retries: u64,
    uncertain_commands: u64,
    resolved_incidents: u64,
    total_downtime_ticks: u64,
    maximum_recovery_ticks: u64,
}

impl SiteCounters {
    const fn new(site_id: SiteId) -> Self {
        Self {
            site_id,
            task_attempts: 0,
            task_successes: 0,
            task_failures: 0,
            total_task_duration_ticks: 0,
            maximum_task_duration_ticks: 0,
            safety_interventions: 0,
            near_misses: 0,
            maximum_near_miss_severity_permille: 0,
            human_overrides: 0,
            command_retries: 0,
            uncertain_commands: 0,
            resolved_incidents: 0,
            total_downtime_ticks: 0,
            maximum_recovery_ticks: 0,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReliabilitySnapshot {
    pub site_id: SiteId,
    pub task_attempts: u64,
    pub task_successes: u64,
    pub task_failures: u64,
    pub task_success_rate_permille: u16,
    pub average_task_duration_ticks: u64,
    pub maximum_task_duration_ticks: u64,
    pub safety_interventions: u64,
    pub near_misses: u64,
    pub maximum_near_miss_severity_permille: u16,
    pub human_overrides: u64,
    pub command_retries: u64,
    pub uncertain_commands: u64,
    pub resolved_incidents: u64,
    pub total_downtime_ticks: u64,
    pub mean_recovery_ticks: u64,
    pub maximum_recovery_ticks: u64,
    pub open_incidents: u16,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ServiceLevelObjective {
    pub minimum_task_success_rate_permille: u16,
    pub maximum_average_task_duration_ticks: u64,
    pub maximum_mean_recovery_ticks: u64,
    pub maximum_uncertain_commands: u64,
    pub maximum_open_incidents: u16,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ServiceLevelAssessment {
    pub success_rate_met: bool,
    pub task_latency_met: bool,
    pub recovery_time_met: bool,
    pub command_certainty_met: bool,
    pub incident_budget_met: bool,
}

impl ServiceLevelAssessment {
    pub const fn all_met(self) -> bool {
        self.success_rate_met
            && self.task_latency_met
            && self.recovery_time_met
            && self.command_certainty_met
            && self.incident_budget_met
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReliabilityError {
    DuplicateOrOutOfOrderEvent,
    InvalidSeverity,
    InvalidDuration,
    CapacityExceeded,
    DuplicateIncident,
    UnknownIncident,
    IncidentSiteMismatch,
    TimeRegression,
    UnknownSite,
    InvalidObjective,
}

#[derive(Debug, Default)]
pub struct ReliabilityMonitor {
    sites: Vec<SiteCounters>,
    events: VecDeque<ReliabilityEvent>,
    open_incidents: Vec<OpenIncident>,
    latest_event_id: u64,
}

impl ReliabilityMonitor {
    pub const fn new() -> Self {
        Self {
            sites: Vec::new(),
            events: VecDeque::new(),
            open_incidents: Vec::new(),
            latest_event_id: 0,
        }
    }

    pub fn record(&mut self, event: ReliabilityEvent) -> Result<(), ReliabilityError> {
        if event.event_id <= self.latest_event_id {
            return Err(ReliabilityError::DuplicateOrOutOfOrderEvent);
        }
        validate_event(event.kind)?;

        // Validate incident transitions before changing counters or history.
        match event.kind {
            ReliabilityEventKind::DowntimeStarted { incident_id } => {
                if self
                    .open_incidents
                    .iter()
                    .any(|incident| incident.incident_id == incident_id)
                {
                    return Err(ReliabilityError::DuplicateIncident);
                }
                if self.open_incidents.len() >= MAX_OPEN_INCIDENTS {
                    return Err(ReliabilityError::CapacityExceeded);
                }
            }
            ReliabilityEventKind::DowntimeEnded { incident_id } => {
                let incident = self
                    .open_incidents
                    .iter()
                    .find(|incident| incident.incident_id == incident_id)
                    .ok_or(ReliabilityError::UnknownIncident)?;
                if incident.site_id != event.site_id {
                    return Err(ReliabilityError::IncidentSiteMismatch);
                }
                if event.observed_at_tick < incident.started_at_tick {
                    return Err(ReliabilityError::TimeRegression);
                }
            }
            _ => {}
        }

        let site_index = match self
            .sites
            .iter()
            .position(|site| site.site_id == event.site_id)
        {
            Some(index) => index,
            None => {
                if self.sites.len() >= MAX_RELIABILITY_SITES {
                    return Err(ReliabilityError::CapacityExceeded);
                }
                self.sites.push(SiteCounters::new(event.site_id));
                self.sites.len() - 1
            }
        };

        let counters = &mut self.sites[site_index];
        match event.kind {
            ReliabilityEventKind::TaskAttempted { .. } => {
                counters.task_attempts = counters.task_attempts.saturating_add(1);
            }
            ReliabilityEventKind::TaskSucceeded { duration_ticks, .. } => {
                counters.task_successes = counters.task_successes.saturating_add(1);
                counters.total_task_duration_ticks = counters
                    .total_task_duration_ticks
                    .saturating_add(duration_ticks);
                counters.maximum_task_duration_ticks =
                    counters.maximum_task_duration_ticks.max(duration_ticks);
            }
            ReliabilityEventKind::TaskFailed { .. } => {
                counters.task_failures = counters.task_failures.saturating_add(1);
            }
            ReliabilityEventKind::SafetyIntervention { .. } => {
                counters.safety_interventions = counters.safety_interventions.saturating_add(1);
            }
            ReliabilityEventKind::NearMiss { severity_permille } => {
                counters.near_misses = counters.near_misses.saturating_add(1);
                counters.maximum_near_miss_severity_permille = counters
                    .maximum_near_miss_severity_permille
                    .max(severity_permille);
            }
            ReliabilityEventKind::HumanOverride { .. } => {
                counters.human_overrides = counters.human_overrides.saturating_add(1);
            }
            ReliabilityEventKind::DeviceCommandRetried => {
                counters.command_retries = counters.command_retries.saturating_add(1);
            }
            ReliabilityEventKind::DeviceCommandUncertain => {
                counters.uncertain_commands = counters.uncertain_commands.saturating_add(1);
            }
            ReliabilityEventKind::DowntimeStarted { incident_id } => {
                self.open_incidents.push(OpenIncident {
                    incident_id,
                    site_id: event.site_id,
                    started_at_tick: event.observed_at_tick,
                });
            }
            ReliabilityEventKind::DowntimeEnded { incident_id } => {
                let index = self
                    .open_incidents
                    .iter()
                    .position(|incident| incident.incident_id == incident_id)
                    .expect("incident transition validated above");
                let incident = self.open_incidents.remove(index);
                let duration = event
                    .observed_at_tick
                    .saturating_sub(incident.started_at_tick);
                counters.resolved_incidents = counters.resolved_incidents.saturating_add(1);
                counters.total_downtime_ticks =
                    counters.total_downtime_ticks.saturating_add(duration);
                counters.maximum_recovery_ticks = counters.maximum_recovery_ticks.max(duration);
            }
        }

        if self.events.len() >= MAX_RELIABILITY_EVENTS {
            self.events.pop_front();
        }
        self.events.push_back(event);
        self.latest_event_id = event.event_id;
        Ok(())
    }

    pub fn snapshot(&self, site_id: SiteId) -> Result<ReliabilitySnapshot, ReliabilityError> {
        let counters = self
            .sites
            .iter()
            .find(|site| site.site_id == site_id)
            .ok_or(ReliabilityError::UnknownSite)?;
        let completed = counters
            .task_successes
            .saturating_add(counters.task_failures);
        Ok(ReliabilitySnapshot {
            site_id,
            task_attempts: counters.task_attempts,
            task_successes: counters.task_successes,
            task_failures: counters.task_failures,
            task_success_rate_permille: ratio_permille(counters.task_successes, completed),
            average_task_duration_ticks: if counters.task_successes == 0 {
                0
            } else {
                counters.total_task_duration_ticks / counters.task_successes
            },
            maximum_task_duration_ticks: counters.maximum_task_duration_ticks,
            safety_interventions: counters.safety_interventions,
            near_misses: counters.near_misses,
            maximum_near_miss_severity_permille: counters.maximum_near_miss_severity_permille,
            human_overrides: counters.human_overrides,
            command_retries: counters.command_retries,
            uncertain_commands: counters.uncertain_commands,
            resolved_incidents: counters.resolved_incidents,
            total_downtime_ticks: counters.total_downtime_ticks,
            mean_recovery_ticks: if counters.resolved_incidents == 0 {
                0
            } else {
                counters.total_downtime_ticks / counters.resolved_incidents
            },
            maximum_recovery_ticks: counters.maximum_recovery_ticks,
            open_incidents: self
                .open_incidents
                .iter()
                .filter(|incident| incident.site_id == site_id)
                .count()
                .min(u16::MAX as usize) as u16,
        })
    }

    pub fn assess(
        &self,
        site_id: SiteId,
        objective: ServiceLevelObjective,
    ) -> Result<ServiceLevelAssessment, ReliabilityError> {
        if objective.minimum_task_success_rate_permille > 1_000 {
            return Err(ReliabilityError::InvalidObjective);
        }
        let snapshot = self.snapshot(site_id)?;
        Ok(ServiceLevelAssessment {
            success_rate_met: snapshot.task_success_rate_permille
                >= objective.minimum_task_success_rate_permille,
            task_latency_met: snapshot.average_task_duration_ticks
                <= objective.maximum_average_task_duration_ticks,
            recovery_time_met: snapshot.mean_recovery_ticks
                <= objective.maximum_mean_recovery_ticks,
            command_certainty_met: snapshot.uncertain_commands
                <= objective.maximum_uncertain_commands,
            incident_budget_met: snapshot.open_incidents <= objective.maximum_open_incidents,
        })
    }

    pub fn events(&self) -> &VecDeque<ReliabilityEvent> {
        &self.events
    }
}

fn validate_event(kind: ReliabilityEventKind) -> Result<(), ReliabilityError> {
    match kind {
        ReliabilityEventKind::NearMiss { severity_permille } if severity_permille > 1_000 => {
            Err(ReliabilityError::InvalidSeverity)
        }
        ReliabilityEventKind::TaskSucceeded {
            duration_ticks: 0, ..
        } => Err(ReliabilityError::InvalidDuration),
        ReliabilityEventKind::DowntimeStarted { incident_id: 0 }
        | ReliabilityEventKind::DowntimeEnded { incident_id: 0 } => {
            Err(ReliabilityError::DuplicateIncident)
        }
        _ => Ok(()),
    }
}

fn ratio_permille(numerator: u64, denominator: u64) -> u16 {
    if denominator == 0 {
        return 0;
    }
    numerator
        .saturating_mul(1_000)
        .checked_div(denominator)
        .unwrap_or(0)
        .min(1_000) as u16
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(event_id: u64, tick: u64, kind: ReliabilityEventKind) -> ReliabilityEvent {
        ReliabilityEvent {
            event_id,
            site_id: SiteId(1),
            observed_at_tick: tick,
            kind,
        }
    }

    #[test]
    fn task_and_safety_metrics_are_integer_deterministic() {
        let mut monitor = ReliabilityMonitor::new();
        monitor
            .record(event(
                1,
                10,
                ReliabilityEventKind::TaskAttempted {
                    job_id: JobId(1),
                    task_id: TaskId(1),
                },
            ))
            .unwrap();
        monitor
            .record(event(
                2,
                20,
                ReliabilityEventKind::TaskSucceeded {
                    job_id: JobId(1),
                    task_id: TaskId(1),
                    duration_ticks: 10,
                },
            ))
            .unwrap();
        monitor
            .record(event(
                3,
                21,
                ReliabilityEventKind::SafetyIntervention { reason_code: 9 },
            ))
            .unwrap();
        let snapshot = monitor.snapshot(SiteId(1)).unwrap();
        assert_eq!(snapshot.task_success_rate_permille, 1_000);
        assert_eq!(snapshot.average_task_duration_ticks, 10);
        assert_eq!(snapshot.safety_interventions, 1);
    }

    #[test]
    fn incidents_measure_recovery_and_reject_invalid_closure() {
        let mut monitor = ReliabilityMonitor::new();
        monitor
            .record(event(
                1,
                100,
                ReliabilityEventKind::DowntimeStarted { incident_id: 5 },
            ))
            .unwrap();
        assert_eq!(
            monitor.record(ReliabilityEvent {
                event_id: 2,
                site_id: SiteId(2),
                observed_at_tick: 105,
                kind: ReliabilityEventKind::DowntimeEnded { incident_id: 5 },
            }),
            Err(ReliabilityError::IncidentSiteMismatch)
        );
        monitor
            .record(event(
                2,
                130,
                ReliabilityEventKind::DowntimeEnded { incident_id: 5 },
            ))
            .unwrap();
        let snapshot = monitor.snapshot(SiteId(1)).unwrap();
        assert_eq!(snapshot.total_downtime_ticks, 30);
        assert_eq!(snapshot.mean_recovery_ticks, 30);
        assert_eq!(snapshot.open_incidents, 0);
    }

    #[test]
    fn failed_event_is_transactional_and_id_can_be_reused() {
        let mut monitor = ReliabilityMonitor::new();
        assert_eq!(
            monitor.record(event(
                1,
                10,
                ReliabilityEventKind::NearMiss {
                    severity_permille: 1_001,
                },
            )),
            Err(ReliabilityError::InvalidSeverity)
        );
        monitor
            .record(event(
                1,
                10,
                ReliabilityEventKind::NearMiss {
                    severity_permille: 900,
                },
            ))
            .unwrap();
        assert_eq!(monitor.snapshot(SiteId(1)).unwrap().near_misses, 1);
    }

    #[test]
    fn objective_reports_each_failed_dimension_without_hiding_it() {
        let mut monitor = ReliabilityMonitor::new();
        monitor
            .record(event(
                1,
                10,
                ReliabilityEventKind::TaskAttempted {
                    job_id: JobId(1),
                    task_id: TaskId(1),
                },
            ))
            .unwrap();
        monitor
            .record(event(
                2,
                20,
                ReliabilityEventKind::TaskFailed {
                    job_id: JobId(1),
                    task_id: TaskId(1),
                },
            ))
            .unwrap();
        monitor
            .record(event(3, 21, ReliabilityEventKind::DeviceCommandUncertain))
            .unwrap();
        let assessment = monitor
            .assess(
                SiteId(1),
                ServiceLevelObjective {
                    minimum_task_success_rate_permille: 990,
                    maximum_average_task_duration_ticks: 10,
                    maximum_mean_recovery_ticks: 10,
                    maximum_uncertain_commands: 0,
                    maximum_open_incidents: 0,
                },
            )
            .unwrap();
        assert!(!assessment.success_rate_met);
        assert!(!assessment.command_certainty_met);
        assert!(!assessment.all_met());
    }
}
