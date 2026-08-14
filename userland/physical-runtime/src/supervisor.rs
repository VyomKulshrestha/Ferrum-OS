//! Bounded deterministic control-plane primitives.
//!
//! These types do not execute motion. They constrain proposal admission,
//! liveness, queue priority, and post-stop recovery before a permit can reach
//! a transport driver.

use alloc::collections::VecDeque;
use alloc::vec::Vec;

use crate::adapter::EndpointId;

pub const MAX_CONTROL_QUEUE: usize = 256;
pub const MAX_RATE_EVENTS: usize = 1_024;
pub const MAX_WATCHDOGS: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum AuthoritySeverity {
    Allow,
    RequireApproval,
    Block,
    EmergencyStop,
}

impl AuthoritySeverity {
    pub const fn stricter(self, other: Self) -> Self {
        if self as u8 >= other as u8 {
            self
        } else {
            other
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ControlTrafficClass {
    Goal,
    Health,
    Stop,
}

impl ControlTrafficClass {
    const fn priority(self) -> u8 {
        match self {
            Self::Goal => 0,
            Self::Health => 1,
            Self::Stop => 2,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QueuedControl {
    pub id: u64,
    pub endpoint_id: EndpointId,
    pub class: ControlTrafficClass,
    pub enqueued_at_tick: u64,
    pub deadline_tick: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SupervisorError {
    InvalidConfiguration,
    InvalidControl,
    DuplicateControl,
    QueueFull,
    RateLimited,
    TimeReversal,
    CapacityExceeded,
    UnknownWatchdog,
    RecoveryIncomplete,
    AuthorityUnavailable,
}

#[derive(Debug, Default)]
pub struct PriorityControlQueue {
    entries: VecDeque<QueuedControl>,
}

impl PriorityControlQueue {
    pub const fn new() -> Self {
        Self {
            entries: VecDeque::new(),
        }
    }

    pub fn push(&mut self, control: QueuedControl) -> Result<(), SupervisorError> {
        if control.id == 0
            || control.endpoint_id.0 == 0
            || control.deadline_tick < control.enqueued_at_tick
        {
            return Err(SupervisorError::InvalidControl);
        }
        if self.entries.iter().any(|entry| entry.id == control.id) {
            return Err(SupervisorError::DuplicateControl);
        }
        if self.entries.len() == MAX_CONTROL_QUEUE {
            if control.class == ControlTrafficClass::Goal {
                return Err(SupervisorError::QueueFull);
            }
            let replaceable = self
                .entries
                .iter()
                .enumerate()
                .filter(|(_, entry)| entry.class.priority() < control.class.priority())
                .min_by_key(|(_, entry)| entry.class.priority())
                .map(|(index, _)| index)
                .ok_or(SupervisorError::QueueFull)?;
            self.entries.remove(replaceable);
        }
        self.entries.push_back(control);
        Ok(())
    }

    pub fn pop_next(&mut self, current_tick: u64) -> Option<QueuedControl> {
        self.entries
            .retain(|entry| current_tick <= entry.deadline_tick);
        let position = self
            .entries
            .iter()
            .enumerate()
            .max_by_key(|(index, entry)| (entry.class.priority(), core::cmp::Reverse(*index)))
            .map(|(index, _)| index)?;
        self.entries.remove(position)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }
}

#[derive(Debug)]
pub struct CommandRateLimiter {
    window_ticks: u64,
    maximum_per_endpoint: usize,
    events: VecDeque<(EndpointId, u64)>,
    last_tick: u64,
}

impl CommandRateLimiter {
    pub fn new(window_ticks: u64, maximum_per_endpoint: usize) -> Result<Self, SupervisorError> {
        if window_ticks == 0 || maximum_per_endpoint == 0 || maximum_per_endpoint > MAX_RATE_EVENTS
        {
            return Err(SupervisorError::InvalidConfiguration);
        }
        Ok(Self {
            window_ticks,
            maximum_per_endpoint,
            events: VecDeque::new(),
            last_tick: 0,
        })
    }

    pub fn admit(&mut self, endpoint_id: EndpointId, tick: u64) -> Result<(), SupervisorError> {
        if endpoint_id.0 == 0 {
            return Err(SupervisorError::InvalidControl);
        }
        if tick < self.last_tick {
            return Err(SupervisorError::TimeReversal);
        }
        self.last_tick = tick;
        while self
            .events
            .front()
            .is_some_and(|(_, event_tick)| tick.saturating_sub(*event_tick) >= self.window_ticks)
        {
            self.events.pop_front();
        }
        if self
            .events
            .iter()
            .filter(|(endpoint, _)| *endpoint == endpoint_id)
            .count()
            >= self.maximum_per_endpoint
        {
            return Err(SupervisorError::RateLimited);
        }
        if self.events.len() >= MAX_RATE_EVENTS {
            return Err(SupervisorError::CapacityExceeded);
        }
        self.events.push_back((endpoint_id, tick));
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WatchdogRole {
    Heliox,
    LearnedModel,
    Adapter,
    Supervisor,
    Controller,
    Sensor,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WatchdogState {
    pub id: u64,
    pub role: WatchdogRole,
    pub timeout_ticks: u64,
    pub last_heartbeat_tick: u64,
    pub armed: bool,
}

impl WatchdogState {
    pub const fn expiry_severity(self) -> AuthoritySeverity {
        match self.role {
            WatchdogRole::Heliox | WatchdogRole::LearnedModel => AuthoritySeverity::Block,
            WatchdogRole::Adapter | WatchdogRole::Sensor => AuthoritySeverity::Block,
            WatchdogRole::Supervisor | WatchdogRole::Controller => AuthoritySeverity::EmergencyStop,
        }
    }
}

#[derive(Debug, Default)]
pub struct WatchdogBank {
    entries: Vec<WatchdogState>,
}

impl WatchdogBank {
    pub const fn new() -> Self {
        Self {
            entries: Vec::new(),
        }
    }

    pub fn register(&mut self, watchdog: WatchdogState) -> Result<(), SupervisorError> {
        if watchdog.id == 0
            || watchdog.timeout_ticks == 0
            || self.entries.iter().any(|entry| entry.id == watchdog.id)
        {
            return Err(SupervisorError::InvalidConfiguration);
        }
        if self.entries.len() >= MAX_WATCHDOGS {
            return Err(SupervisorError::CapacityExceeded);
        }
        self.entries.push(watchdog);
        Ok(())
    }

    pub fn heartbeat(&mut self, id: u64, tick: u64) -> Result<(), SupervisorError> {
        let watchdog = self
            .entries
            .iter_mut()
            .find(|entry| entry.id == id)
            .ok_or(SupervisorError::UnknownWatchdog)?;
        if tick < watchdog.last_heartbeat_tick {
            return Err(SupervisorError::TimeReversal);
        }
        watchdog.last_heartbeat_tick = tick;
        watchdog.armed = true;
        Ok(())
    }

    pub fn severity(&self, tick: u64) -> AuthoritySeverity {
        self.entries
            .iter()
            .filter(|entry| {
                entry.armed && tick.saturating_sub(entry.last_heartbeat_tick) > entry.timeout_ticks
            })
            .fold(AuthoritySeverity::Allow, |severity, entry| {
                severity.stricter(entry.expiry_severity())
            })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct OperationalLimits {
    pub minimum_battery_permille: u16,
    pub maximum_payload_grams: u32,
    pub maximum_speed_mm_per_second: u32,
    pub maximum_clock_uncertainty_ticks: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ResourceSnapshot {
    pub battery_permille: u16,
    pub payload_grams: u32,
    pub requested_speed_mm_per_second: u32,
    pub clock_uncertainty_ticks: u64,
    pub maintenance_ready: bool,
    pub qualified: bool,
}

impl OperationalLimits {
    pub fn evaluate(self, state: ResourceSnapshot) -> AuthoritySeverity {
        if self.minimum_battery_permille > 1_000
            || state.battery_permille > 1_000
            || self.maximum_payload_grams == 0
            || self.maximum_speed_mm_per_second == 0
        {
            return AuthoritySeverity::Block;
        }
        if state.battery_permille < self.minimum_battery_permille
            || state.payload_grams > self.maximum_payload_grams
            || state.requested_speed_mm_per_second > self.maximum_speed_mm_per_second
            || state.clock_uncertainty_ticks > self.maximum_clock_uncertainty_ticks
            || !state.maintenance_ready
            || !state.qualified
        {
            AuthoritySeverity::Block
        } else {
            AuthoritySeverity::Allow
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct RecoveryLatch {
    stop_observed: bool,
    controller_safe: bool,
    fresh_twin: bool,
    operator_acknowledged: bool,
}

impl RecoveryLatch {
    pub fn observe_stop(&mut self) {
        self.stop_observed = true;
    }
    pub fn observe_controller_safe(&mut self) {
        self.controller_safe = true;
    }
    pub fn observe_fresh_twin(&mut self) {
        self.fresh_twin = true;
    }
    pub fn acknowledge_operator(&mut self) {
        self.operator_acknowledged = true;
    }
    pub fn release(&mut self) -> Result<(), SupervisorError> {
        if !(self.stop_observed
            && self.controller_safe
            && self.fresh_twin
            && self.operator_acknowledged)
        {
            return Err(SupervisorError::RecoveryIncomplete);
        }
        *self = Self::default();
        Ok(())
    }

    pub const fn is_complete(self) -> bool {
        self.stop_observed && self.controller_safe && self.fresh_twin && self.operator_acknowledged
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn control(id: u64, class: ControlTrafficClass) -> QueuedControl {
        QueuedControl {
            id,
            endpoint_id: EndpointId(1),
            class,
            enqueued_at_tick: 1,
            deadline_tick: 100,
        }
    }

    #[test]
    fn severity_can_only_move_toward_more_caution() {
        for left in [
            AuthoritySeverity::Allow,
            AuthoritySeverity::RequireApproval,
            AuthoritySeverity::Block,
            AuthoritySeverity::EmergencyStop,
        ] {
            for right in [
                AuthoritySeverity::Allow,
                AuthoritySeverity::RequireApproval,
                AuthoritySeverity::Block,
                AuthoritySeverity::EmergencyStop,
            ] {
                assert!(left.stricter(right) >= left);
                assert!(left.stricter(right) >= right);
            }
        }
    }

    #[test]
    fn stop_and_health_preempt_goals_under_backpressure() {
        let mut queue = PriorityControlQueue::new();
        for id in 1..=MAX_CONTROL_QUEUE as u64 {
            queue.push(control(id, ControlTrafficClass::Goal)).unwrap();
        }
        assert_eq!(
            queue.push(control(300, ControlTrafficClass::Goal)),
            Err(SupervisorError::QueueFull)
        );
        queue
            .push(control(301, ControlTrafficClass::Health))
            .unwrap();
        queue.push(control(302, ControlTrafficClass::Stop)).unwrap();
        assert_eq!(queue.len(), MAX_CONTROL_QUEUE);
        assert_eq!(queue.pop_next(2).unwrap().class, ControlTrafficClass::Stop);
        assert_eq!(
            queue.pop_next(2).unwrap().class,
            ControlTrafficClass::Health
        );
    }

    #[test]
    fn command_rate_is_per_endpoint_bounded_and_monotonic() {
        let mut limiter = CommandRateLimiter::new(10, 2).unwrap();
        limiter.admit(EndpointId(1), 1).unwrap();
        limiter.admit(EndpointId(1), 2).unwrap();
        assert_eq!(
            limiter.admit(EndpointId(1), 3),
            Err(SupervisorError::RateLimited)
        );
        limiter.admit(EndpointId(2), 3).unwrap();
        limiter.admit(EndpointId(1), 11).unwrap();
        assert_eq!(
            limiter.admit(EndpointId(1), 10),
            Err(SupervisorError::TimeReversal)
        );
    }

    #[test]
    fn watchdog_consequences_are_fail_closed() {
        let mut bank = WatchdogBank::new();
        bank.register(WatchdogState {
            id: 1,
            role: WatchdogRole::LearnedModel,
            timeout_ticks: 5,
            last_heartbeat_tick: 10,
            armed: true,
        })
        .unwrap();
        bank.register(WatchdogState {
            id: 2,
            role: WatchdogRole::Controller,
            timeout_ticks: 5,
            last_heartbeat_tick: 10,
            armed: true,
        })
        .unwrap();
        assert_eq!(bank.severity(15), AuthoritySeverity::Allow);
        assert_eq!(bank.severity(16), AuthoritySeverity::EmergencyStop);
    }

    #[test]
    fn every_resource_limit_fails_closed_independently() {
        let limits = OperationalLimits {
            minimum_battery_permille: 200,
            maximum_payload_grams: 500,
            maximum_speed_mm_per_second: 100,
            maximum_clock_uncertainty_ticks: 2,
        };
        let safe = ResourceSnapshot {
            battery_permille: 900,
            payload_grams: 100,
            requested_speed_mm_per_second: 50,
            clock_uncertainty_ticks: 1,
            maintenance_ready: true,
            qualified: true,
        };
        assert_eq!(limits.evaluate(safe), AuthoritySeverity::Allow);
        for unsafe_state in [
            ResourceSnapshot {
                battery_permille: 199,
                ..safe
            },
            ResourceSnapshot {
                payload_grams: 501,
                ..safe
            },
            ResourceSnapshot {
                requested_speed_mm_per_second: 101,
                ..safe
            },
            ResourceSnapshot {
                clock_uncertainty_ticks: 3,
                ..safe
            },
            ResourceSnapshot {
                maintenance_ready: false,
                ..safe
            },
            ResourceSnapshot {
                qualified: false,
                ..safe
            },
        ] {
            assert_eq!(limits.evaluate(unsafe_state), AuthoritySeverity::Block);
        }
    }

    #[test]
    fn post_stop_recovery_requires_all_independent_evidence() {
        let mut latch = RecoveryLatch::default();
        latch.observe_stop();
        latch.observe_controller_safe();
        latch.observe_fresh_twin();
        assert_eq!(latch.release(), Err(SupervisorError::RecoveryIncomplete));
        latch.acknowledge_operator();
        assert_eq!(latch.release(), Ok(()));
        assert_eq!(latch.release(), Err(SupervisorError::RecoveryIncomplete));
    }
}
