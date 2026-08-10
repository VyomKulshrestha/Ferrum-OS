//! Dependency-aware work orders and deterministic actor dispatch.

use alloc::vec::Vec;

use crate::domain::{
    ActorId, ActorKind, ActorStatus, AssetId, CapabilitySet, DomainRegistry, QualificationSet,
    SiteId,
};

pub const MAX_WORK_ORDERS: usize = 64;
pub const MAX_TASKS_PER_ORDER: usize = 64;
pub const MAX_DEPENDENCIES_PER_TASK: usize = 16;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct JobId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct TaskId(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Priority {
    Routine = 0,
    Normal = 1,
    Urgent = 2,
    Emergency = 3,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobState {
    Pending,
    Active,
    Completed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaskStatus {
    Pending,
    Assigned(ActorId),
    InProgress(ActorId),
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActorConstraint {
    Any,
    Human,
    Agent,
    Robot,
}

impl ActorConstraint {
    fn accepts(self, kind: ActorKind) -> bool {
        matches!(self, Self::Any)
            || matches!(
                (self, kind),
                (Self::Human, ActorKind::Human)
                    | (Self::Agent, ActorKind::Agent)
                    | (Self::Robot, ActorKind::Robot)
            )
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkTask {
    pub id: TaskId,
    pub dependencies: Vec<TaskId>,
    pub status: TaskStatus,
    pub actor_constraint: ActorConstraint,
    pub required_capabilities: CapabilitySet,
    pub required_qualifications: QualificationSet,
    pub zone_id: u32,
    pub minimum_battery_permille: u16,
    pub payload_grams: u32,
    pub estimated_duration_ticks: u64,
    pub requires_human_approval: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkOrder {
    pub id: JobId,
    pub asset_id: AssetId,
    pub site_id: SiteId,
    pub priority: Priority,
    pub deadline_tick: u64,
    pub state: JobState,
    pub revision: u64,
    pub tasks: Vec<WorkTask>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkGraphError {
    DuplicateJob,
    DuplicateTask,
    EmptyOrder,
    InvalidInitialState,
    UnknownDependency,
    DependencyCycle,
    SelfDependency,
    CapacityExceeded,
    InvalidBatteryRequirement,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchError {
    NoReadyTask,
    NoEligibleActor,
    RevisionConflict,
    UnknownJob,
    UnknownTask,
    TaskNotReady,
    ActorUnavailable,
    AssignmentMismatch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DispatchReceipt {
    pub job_id: JobId,
    pub task_id: TaskId,
    pub actor_id: ActorId,
    pub revision: u64,
}

#[derive(Debug, Default)]
pub struct WorkGraph {
    orders: Vec<WorkOrder>,
}

impl WorkGraph {
    pub const fn new() -> Self {
        Self { orders: Vec::new() }
    }

    pub fn add_order(&mut self, order: WorkOrder) -> Result<(), WorkGraphError> {
        if self.orders.iter().any(|existing| existing.id == order.id) {
            return Err(WorkGraphError::DuplicateJob);
        }
        if self.orders.len() >= MAX_WORK_ORDERS || order.tasks.len() > MAX_TASKS_PER_ORDER {
            return Err(WorkGraphError::CapacityExceeded);
        }
        if order.tasks.is_empty() {
            return Err(WorkGraphError::EmptyOrder);
        }
        if order.state != JobState::Pending
            || order.revision != 0
            || order
                .tasks
                .iter()
                .any(|task| task.status != TaskStatus::Pending)
        {
            return Err(WorkGraphError::InvalidInitialState);
        }
        validate_tasks(&order.tasks)?;
        self.orders.push(order);
        Ok(())
    }

    pub fn order(&self, id: JobId) -> Option<&WorkOrder> {
        self.orders.iter().find(|order| order.id == id)
    }

    pub fn order_mut(&mut self, id: JobId) -> Option<&mut WorkOrder> {
        self.orders.iter_mut().find(|order| order.id == id)
    }

    pub fn orders(&self) -> &[WorkOrder] {
        &self.orders
    }

    /// Select and commit the next assignment as one deterministic transaction.
    /// All validation happens before either actor or task state is mutated.
    pub fn dispatch_next(
        &mut self,
        registry: &mut DomainRegistry,
        tick: u64,
        max_actor_staleness_ticks: u64,
    ) -> Result<DispatchReceipt, DispatchError> {
        let (order_index, task_index) = self.best_ready_task().ok_or(DispatchError::NoReadyTask)?;

        let order = &self.orders[order_index];
        let task = &order.tasks[task_index];
        let actor_id = best_actor(
            registry,
            order.site_id,
            task,
            tick,
            max_actor_staleness_ticks,
        )
        .ok_or(DispatchError::NoEligibleActor)?;

        let actor = registry
            .actor_mut(actor_id)
            .ok_or(DispatchError::NoEligibleActor)?;
        if !actor.is_dispatchable_at(tick) {
            return Err(DispatchError::ActorUnavailable);
        }

        actor.status = ActorStatus::Busy;
        let order = &mut self.orders[order_index];
        order.state = JobState::Active;
        order.tasks[task_index].status = TaskStatus::Assigned(actor_id);
        order.revision = order.revision.saturating_add(1);

        Ok(DispatchReceipt {
            job_id: order.id,
            task_id: order.tasks[task_index].id,
            actor_id,
            revision: order.revision,
        })
    }

    /// Compare-and-set transition used by multiple controllers sharing a work graph.
    pub fn start_task(
        &mut self,
        job_id: JobId,
        task_id: TaskId,
        actor_id: ActorId,
        expected_revision: u64,
    ) -> Result<u64, DispatchError> {
        let order = self.order_mut(job_id).ok_or(DispatchError::UnknownJob)?;
        if order.revision != expected_revision {
            return Err(DispatchError::RevisionConflict);
        }
        let task = order
            .tasks
            .iter_mut()
            .find(|task| task.id == task_id)
            .ok_or(DispatchError::UnknownTask)?;
        if task.status != TaskStatus::Assigned(actor_id) {
            return Err(DispatchError::AssignmentMismatch);
        }
        task.status = TaskStatus::InProgress(actor_id);
        order.revision = order.revision.saturating_add(1);
        Ok(order.revision)
    }

    pub fn complete_task(
        &mut self,
        registry: &mut DomainRegistry,
        job_id: JobId,
        task_id: TaskId,
        actor_id: ActorId,
        expected_revision: u64,
    ) -> Result<u64, DispatchError> {
        let order_index = self
            .orders
            .iter()
            .position(|order| order.id == job_id)
            .ok_or(DispatchError::UnknownJob)?;
        if self.orders[order_index].revision != expected_revision {
            return Err(DispatchError::RevisionConflict);
        }
        let task_index = self.orders[order_index]
            .tasks
            .iter()
            .position(|task| task.id == task_id)
            .ok_or(DispatchError::UnknownTask)?;
        if self.orders[order_index].tasks[task_index].status != TaskStatus::InProgress(actor_id) {
            return Err(DispatchError::AssignmentMismatch);
        }
        let actor = registry
            .actor_mut(actor_id)
            .ok_or(DispatchError::ActorUnavailable)?;
        if actor.status != ActorStatus::Busy {
            return Err(DispatchError::ActorUnavailable);
        }

        actor.status = ActorStatus::Available;
        let order = &mut self.orders[order_index];
        order.tasks[task_index].status = TaskStatus::Completed;
        if order
            .tasks
            .iter()
            .all(|task| task.status == TaskStatus::Completed)
        {
            order.state = JobState::Completed;
        }
        order.revision = order.revision.saturating_add(1);
        Ok(order.revision)
    }

    fn best_ready_task(&self) -> Option<(usize, usize)> {
        let mut best: Option<(usize, usize)> = None;
        for (order_index, order) in self.orders.iter().enumerate() {
            if matches!(order.state, JobState::Completed | JobState::Cancelled) {
                continue;
            }
            for (task_index, task) in order.tasks.iter().enumerate() {
                if task.status != TaskStatus::Pending || !dependencies_complete(order, task) {
                    continue;
                }
                let replace = best.is_none_or(|(best_order, best_task)| {
                    let current_key = (
                        core::cmp::Reverse(order.priority),
                        order.deadline_tick,
                        order.id,
                        task.id,
                    );
                    let selected = &self.orders[best_order];
                    let selected_task = &selected.tasks[best_task];
                    let selected_key = (
                        core::cmp::Reverse(selected.priority),
                        selected.deadline_tick,
                        selected.id,
                        selected_task.id,
                    );
                    current_key < selected_key
                });
                if replace {
                    best = Some((order_index, task_index));
                }
            }
        }
        best
    }
}

fn dependencies_complete(order: &WorkOrder, task: &WorkTask) -> bool {
    task.dependencies.iter().all(|dependency| {
        order
            .tasks
            .iter()
            .find(|candidate| candidate.id == *dependency)
            .is_some_and(|candidate| candidate.status == TaskStatus::Completed)
    })
}

fn best_actor(
    registry: &DomainRegistry,
    site_id: SiteId,
    task: &WorkTask,
    tick: u64,
    max_staleness_ticks: u64,
) -> Option<ActorId> {
    registry
        .actors()
        .iter()
        .filter(|actor| {
            actor.site_id == site_id
                && actor.is_dispatchable_at(tick)
                && tick.saturating_sub(actor.last_seen_tick) <= max_staleness_ticks
                && actor.position.zone_id == task.zone_id
                && task.actor_constraint.accepts(actor.kind)
                && actor.capabilities.contains_all(task.required_capabilities)
                && actor
                    .qualifications
                    .contains_all(task.required_qualifications)
                && actor.battery_permille >= task.minimum_battery_permille
                && actor.max_payload_grams >= task.payload_grams
        })
        .min_by_key(|actor| {
            (
                actor.load_permille,
                core::cmp::Reverse(actor.battery_permille),
                actor.id,
            )
        })
        .map(|actor| actor.id)
}

fn validate_tasks(tasks: &[WorkTask]) -> Result<(), WorkGraphError> {
    for (index, task) in tasks.iter().enumerate() {
        if task.dependencies.len() > MAX_DEPENDENCIES_PER_TASK {
            return Err(WorkGraphError::CapacityExceeded);
        }
        if task.minimum_battery_permille > 1_000 {
            return Err(WorkGraphError::InvalidBatteryRequirement);
        }
        if tasks[..index].iter().any(|existing| existing.id == task.id) {
            return Err(WorkGraphError::DuplicateTask);
        }
        for dependency in &task.dependencies {
            if *dependency == task.id {
                return Err(WorkGraphError::SelfDependency);
            }
            if !tasks.iter().any(|candidate| candidate.id == *dependency) {
                return Err(WorkGraphError::UnknownDependency);
            }
        }
    }

    let mut completed = Vec::with_capacity(tasks.len());
    while completed.len() < tasks.len() {
        let before = completed.len();
        for task in tasks {
            if completed.contains(&task.id) {
                continue;
            }
            if task
                .dependencies
                .iter()
                .all(|dependency| completed.contains(dependency))
            {
                completed.push(task.id);
            }
        }
        if completed.len() == before {
            return Err(WorkGraphError::DependencyCycle);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::{Actor, Asset, AssetState, Capability, Position, Qualification, Site};
    use alloc::string::ToString;
    use alloc::vec;

    fn registry() -> DomainRegistry {
        let mut registry = DomainRegistry::new();
        registry
            .register_site(Site {
                id: SiteId(1),
                name: "Plant".to_string(),
                emergency_zone_id: 99,
            })
            .unwrap();
        registry
            .register_asset(Asset {
                id: AssetId(50),
                name: "Pump".to_string(),
                site_id: SiteId(1),
                position: Position::origin(7, 10),
                state: AssetState::Degraded,
                last_service_tick: 0,
            })
            .unwrap();
        registry
    }

    fn actor(id: u64, kind: ActorKind, load: u16, capabilities: CapabilitySet) -> Actor {
        Actor {
            id: ActorId(id),
            name: "worker".to_string(),
            kind,
            status: ActorStatus::Available,
            site_id: SiteId(1),
            position: Position::origin(7, 100),
            capabilities,
            qualifications: QualificationSet::empty().with(Qualification::SiteInduction),
            available_from_tick: 0,
            last_seen_tick: 100,
            battery_permille: 900,
            load_permille: load,
            max_payload_grams: 20_000,
        }
    }

    fn task(id: u64, dependencies: Vec<TaskId>, constraint: ActorConstraint) -> WorkTask {
        WorkTask {
            id: TaskId(id),
            dependencies,
            status: TaskStatus::Pending,
            actor_constraint: constraint,
            required_capabilities: CapabilitySet::empty().with(Capability::Inspect),
            required_qualifications: QualificationSet::empty().with(Qualification::SiteInduction),
            zone_id: 7,
            minimum_battery_permille: 200,
            payload_grams: 0,
            estimated_duration_ticks: 100,
            requires_human_approval: false,
        }
    }

    fn order(tasks: Vec<WorkTask>) -> WorkOrder {
        WorkOrder {
            id: JobId(1),
            asset_id: AssetId(50),
            site_id: SiteId(1),
            priority: Priority::Normal,
            deadline_tick: 1_000,
            state: JobState::Pending,
            revision: 0,
            tasks,
        }
    }

    #[test]
    fn graph_rejects_cycles_before_activation() {
        let mut graph = WorkGraph::new();
        let tasks = vec![
            task(1, vec![TaskId(2)], ActorConstraint::Any),
            task(2, vec![TaskId(1)], ActorConstraint::Any),
        ];
        assert_eq!(
            graph.add_order(order(tasks)),
            Err(WorkGraphError::DependencyCycle)
        );
    }

    #[test]
    fn graph_rejects_empty_or_pretransitioned_orders() {
        let mut graph = WorkGraph::new();
        assert_eq!(
            graph.add_order(order(vec![])),
            Err(WorkGraphError::EmptyOrder)
        );

        let mut already_running = order(vec![task(1, vec![], ActorConstraint::Any)]);
        already_running.tasks[0].status = TaskStatus::Assigned(ActorId(1));
        assert_eq!(
            graph.add_order(already_running),
            Err(WorkGraphError::InvalidInitialState)
        );
    }

    #[test]
    fn scheduler_honours_actor_kind_and_capabilities() {
        let mut registry = registry();
        registry
            .register_actor(actor(
                1,
                ActorKind::Agent,
                0,
                CapabilitySet::empty().with(Capability::ExecuteDigital),
            ))
            .unwrap();
        registry
            .register_actor(actor(
                2,
                ActorKind::Human,
                20,
                CapabilitySet::empty().with(Capability::Inspect),
            ))
            .unwrap();
        let mut graph = WorkGraph::new();
        graph
            .add_order(order(vec![task(1, vec![], ActorConstraint::Human)]))
            .unwrap();
        let receipt = graph.dispatch_next(&mut registry, 100, 10).unwrap();
        assert_eq!(receipt.actor_id, ActorId(2));
        assert_eq!(
            registry.actor(ActorId(2)).unwrap().status,
            ActorStatus::Busy
        );
    }

    #[test]
    fn deterministic_tie_break_prefers_lower_load_then_id() {
        let mut registry = registry();
        for (id, load) in [(9, 100), (4, 100), (2, 200)] {
            registry
                .register_actor(actor(
                    id,
                    ActorKind::Robot,
                    load,
                    CapabilitySet::empty().with(Capability::Inspect),
                ))
                .unwrap();
        }
        let mut graph = WorkGraph::new();
        graph
            .add_order(order(vec![task(1, vec![], ActorConstraint::Robot)]))
            .unwrap();
        let receipt = graph.dispatch_next(&mut registry, 100, 10).unwrap();
        assert_eq!(receipt.actor_id, ActorId(4));
    }

    #[test]
    fn revision_conflict_does_not_change_task_state() {
        let mut registry = registry();
        registry
            .register_actor(actor(
                1,
                ActorKind::Human,
                0,
                CapabilitySet::empty().with(Capability::Inspect),
            ))
            .unwrap();
        let mut graph = WorkGraph::new();
        graph
            .add_order(order(vec![task(1, vec![], ActorConstraint::Any)]))
            .unwrap();
        let receipt = graph.dispatch_next(&mut registry, 100, 10).unwrap();
        assert_eq!(
            graph.start_task(receipt.job_id, receipt.task_id, receipt.actor_id, 0),
            Err(DispatchError::RevisionConflict)
        );
        assert_eq!(
            graph.order(JobId(1)).unwrap().tasks[0].status,
            TaskStatus::Assigned(ActorId(1))
        );
    }

    #[test]
    fn completion_releases_actor_and_unlocks_dependency() {
        let mut registry = registry();
        registry
            .register_actor(actor(
                1,
                ActorKind::Human,
                0,
                CapabilitySet::empty().with(Capability::Inspect),
            ))
            .unwrap();
        let mut graph = WorkGraph::new();
        graph
            .add_order(order(vec![
                task(1, vec![], ActorConstraint::Any),
                task(2, vec![TaskId(1)], ActorConstraint::Any),
            ]))
            .unwrap();
        let first = graph.dispatch_next(&mut registry, 100, 10).unwrap();
        let revision = graph
            .start_task(first.job_id, first.task_id, first.actor_id, first.revision)
            .unwrap();
        graph
            .complete_task(
                &mut registry,
                first.job_id,
                first.task_id,
                first.actor_id,
                revision,
            )
            .unwrap();
        assert_eq!(
            registry.actor(ActorId(1)).unwrap().status,
            ActorStatus::Available
        );
        let second = graph.dispatch_next(&mut registry, 101, 10).unwrap();
        assert_eq!(second.task_id, TaskId(2));
    }

    #[test]
    fn stale_actor_telemetry_fails_closed() {
        let mut registry = registry();
        registry
            .register_actor(actor(
                1,
                ActorKind::Robot,
                0,
                CapabilitySet::empty().with(Capability::Inspect),
            ))
            .unwrap();
        let mut graph = WorkGraph::new();
        graph
            .add_order(order(vec![task(1, vec![], ActorConstraint::Robot)]))
            .unwrap();
        assert_eq!(
            graph.dispatch_next(&mut registry, 1_000, 50),
            Err(DispatchError::NoEligibleActor)
        );
    }
}
