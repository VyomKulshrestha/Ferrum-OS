// ============================================================================
// Heliox-Daemon - Planner
// ============================================================================
// Hierarchical task decomposition engine. Given a high-level goal, the
// planner breaks it into a dependency-ordered tree of sub-tasks. Each
// sub-task is a concrete action the orchestrator can execute.
//
// Architecture:
//   Goal → [SubTask₁, SubTask₂, ...] → each SubTask has tool + args
//   Dependencies are expressed as "this task must complete before that one"
//   The planner also supports plan simulation (dry-run analysis)
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use alloc::format;
use super::tool_mapper;

/// The state of a sub-task in the plan.
#[derive(Debug, Clone, PartialEq)]
pub enum TaskState {
    Pending,
    InProgress,
    Completed,
    Failed(String),
    Skipped,
}

/// A single sub-task in the plan tree.
#[derive(Debug, Clone)]
pub struct SubTask {
    /// Unique ID within the plan.
    pub id: u32,
    /// Human-readable description of what this task does.
    pub description: String,
    /// The tool to invoke (matches tool_mapper names).
    pub tool_name: Option<String>,
    /// Arguments for the tool call (serialized as key=value pairs).
    pub tool_args: String,
    /// IDs of tasks that must complete before this one can run.
    pub depends_on: Vec<u32>,
    /// Current state.
    pub state: TaskState,
    /// Expected keywords in the output (for verification).
    pub expected_keywords: Vec<String>,
}

/// The execution plan for a goal.
#[derive(Debug)]
pub struct Plan {
    pub goal: String,
    pub tasks: Vec<SubTask>,
    next_id: u32,
}

impl Plan {
    pub fn new(goal: &str) -> Self {
        Self {
            goal: String::from(goal),
            tasks: Vec::new(),
            next_id: 1,
        }
    }

    /// Add a sub-task to the plan.
    pub fn add_task(
        &mut self,
        description: &str,
        tool_name: Option<&str>,
        tool_args: &str,
        depends_on: Vec<u32>,
        expected_keywords: Vec<&str>,
    ) -> u32 {
        let id = self.next_id;
        self.next_id += 1;
        self.tasks.push(SubTask {
            id,
            description: String::from(description),
            tool_name: tool_name.map(String::from),
            tool_args: String::from(tool_args),
            depends_on,
            state: TaskState::Pending,
            expected_keywords: expected_keywords.iter().map(|s| String::from(*s)).collect(),
        });
        id
    }

    /// Get the next runnable task (all dependencies completed, state is Pending).
    pub fn next_runnable(&self) -> Option<&SubTask> {
        for task in &self.tasks {
            if task.state != TaskState::Pending {
                continue;
            }
            let deps_met = task.depends_on.iter().all(|dep_id| {
                self.tasks.iter().any(|t| {
                    t.id == *dep_id && t.state == TaskState::Completed
                })
            });
            if deps_met {
                return Some(task);
            }
        }
        None
    }

    /// Mark a task as completed.
    pub fn complete_task(&mut self, id: u32) {
        if let Some(task) = self.tasks.iter_mut().find(|t| t.id == id) {
            task.state = TaskState::Completed;
        }
    }

    /// Mark a task as failed.
    pub fn fail_task(&mut self, id: u32, reason: &str) {
        if let Some(task) = self.tasks.iter_mut().find(|t| t.id == id) {
            task.state = TaskState::Failed(String::from(reason));
        }
        // Also skip any tasks that depend on the failed one
        let dependents: Vec<u32> = self.tasks.iter()
            .filter(|t| t.depends_on.contains(&id))
            .map(|t| t.id)
            .collect();
        for dep_id in dependents {
            if let Some(task) = self.tasks.iter_mut().find(|t| t.id == dep_id) {
                if task.state == TaskState::Pending {
                    task.state = TaskState::Skipped;
                }
            }
        }
    }

    /// Mark a task as in-progress.
    pub fn start_task(&mut self, id: u32) {
        if let Some(task) = self.tasks.iter_mut().find(|t| t.id == id) {
            task.state = TaskState::InProgress;
        }
    }

    /// Check if all tasks are done (completed, failed, or skipped).
    pub fn is_complete(&self) -> bool {
        self.tasks.iter().all(|t| {
            matches!(t.state, TaskState::Completed | TaskState::Failed(_) | TaskState::Skipped)
        })
    }

    /// Dry-run analysis: check if the plan is well-formed.
    /// Returns a list of warnings/issues found.
    pub fn simulate(&self) -> Vec<String> {
        let mut warnings = Vec::new();

        // Check for missing dependencies
        for task in &self.tasks {
            for dep_id in &task.depends_on {
                if !self.tasks.iter().any(|t| t.id == *dep_id) {
                    warnings.push(format!(
                        "Task {} depends on non-existent task {}",
                        task.id, dep_id
                    ));
                }
            }
        }

        // Check for circular dependencies (simple DFS)
        for task in &self.tasks {
            let mut visited = Vec::new();
            if self.has_cycle(task.id, &mut visited) {
                warnings.push(format!(
                    "Circular dependency detected involving task {}",
                    task.id
                ));
            }
        }

        // Check for tasks with no tool (pure planning nodes)
        let no_tool_count = self.tasks.iter()
            .filter(|t| t.tool_name.is_none())
            .count();
        if no_tool_count > 0 {
            warnings.push(format!(
                "{} tasks have no tool assigned (will be skipped during execution)",
                no_tool_count
            ));
        }

        if warnings.is_empty() {
            warnings.push(String::from("Plan simulation: no issues found"));
        }

        warnings
    }

    fn has_cycle(&self, task_id: u32, visited: &mut Vec<u32>) -> bool {
        if visited.contains(&task_id) {
            return true;
        }
        visited.push(task_id);
        if let Some(task) = self.tasks.iter().find(|t| t.id == task_id) {
            for dep_id in &task.depends_on {
                if self.has_cycle(*dep_id, visited) {
                    return true;
                }
            }
        }
        visited.pop();
        false
    }

    /// Get a summary of the plan's progress.
    pub fn progress_summary(&self) -> String {
        let total = self.tasks.len();
        let completed = self.tasks.iter().filter(|t| t.state == TaskState::Completed).count();
        let failed = self.tasks.iter().filter(|t| matches!(t.state, TaskState::Failed(_))).count();
        let pending = self.tasks.iter().filter(|t| t.state == TaskState::Pending).count();
        format!(
            "Plan '{}': {}/{} done, {} failed, {} pending",
            self.goal, completed, total, failed, pending
        )
    }
}

/// The Planner manages the current plan and generates prompts.
pub struct Planner {
    system_prompt: String,
    current_plan: Option<Plan>,
    /// Observation context from the previous tick (tool results, errors, etc.)
    observation: String,
    /// Memory context injected from RAG search results.
    memory_context: String,
    /// Lessons learned from the reflector.
    lessons_context: String,
}

impl Planner {
    pub fn new() -> Self {
        Self {
            system_prompt: String::from(
                "You are Heliox-OS, an autonomous agentic operating system running on FerrumOS. \
                 You can observe the system, make decisions, and execute actions through tool calls. \
                 You follow a ReAct pattern: Observe the current state, Think about what to do, \
                 then Act by calling a tool. After each action, you Observe the result and decide \
                 the next step."
            ),
            current_plan: None,
            observation: String::new(),
            memory_context: String::new(),
            lessons_context: String::new(),
        }
    }

    /// Set the current goal and create a default plan.
    pub fn set_goal(&mut self, goal: &str) {
        let mut plan = Plan::new(goal);
        // Default exploration plan
        plan.add_task(
            "Observe current system state",
            Some("audit_write"),
            "message=Observing system state",
            Vec::new(),
            vec![],
        );
        self.current_plan = Some(plan);
    }

    /// Get a mutable reference to the current plan.
    pub fn plan_mut(&mut self) -> Option<&mut Plan> {
        self.current_plan.as_mut()
    }

    /// Get a reference to the current plan.
    pub fn plan(&self) -> Option<&Plan> {
        self.current_plan.as_ref()
    }

    /// Set the observation context (result of last action).
    pub fn set_observation(&mut self, obs: &str) {
        self.observation = String::from(obs);
    }

    /// Set memory context from RAG results.
    pub fn set_memory_context(&mut self, ctx: &str) {
        self.memory_context = String::from(ctx);
    }

    /// Set lessons learned context from the reflector.
    pub fn set_lessons_context(&mut self, ctx: &str) {
        self.lessons_context = String::from(ctx);
    }

    /// Generate a prompt for the LLM that includes:
    /// - System prompt
    /// - Tool definitions
    /// - Current goal and plan progress
    /// - Observation from last action
    /// - Relevant memories (RAG)
    /// - Lessons learned
    pub fn generate_prompt(&self) -> String {
        let mut prompt = String::new();

        // System prompt
        prompt.push_str(&self.system_prompt);
        prompt.push_str("\n\n");

        // Tool definitions
        prompt.push_str(tool_mapper::TOOL_DEFINITIONS);
        prompt.push_str("\n\n");

        // Current goal
        if let Some(plan) = &self.current_plan {
            prompt.push_str("Current Goal: ");
            prompt.push_str(&plan.goal);
            prompt.push_str("\n\n");

            // Plan progress
            prompt.push_str("Plan Progress:\n");
            prompt.push_str(&plan.progress_summary());
            prompt.push_str("\n");

            // Next runnable task hint
            if let Some(next) = plan.next_runnable() {
                prompt.push_str(&format!(
                    "\nNext planned task: {} ({})\n",
                    next.description,
                    next.tool_name.as_deref().unwrap_or("no tool")
                ));
            }
        } else {
            prompt.push_str("Current Goal: Explore the system and ensure everything is functioning.\n");
        }

        // Observation from last action
        if !self.observation.is_empty() {
            prompt.push_str("\nObservation (last action result):\n");
            prompt.push_str(&self.observation);
            prompt.push_str("\n");
        }

        // Memory context (RAG results)
        if !self.memory_context.is_empty() {
            prompt.push_str("\nRelevant Memories:\n");
            prompt.push_str(&self.memory_context);
            prompt.push_str("\n");
        }

        // Lessons learned
        if !self.lessons_context.is_empty() {
            prompt.push_str(&self.lessons_context);
        }

        prompt.push_str("\nRespond with a JSON tool call or plain text.");
        prompt
    }
}
