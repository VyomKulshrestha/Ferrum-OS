// ============================================================================
// Heliox-Daemon - Planner
// ============================================================================
// Generates prompts for the LLM with the system prompt, tool definitions,
// and the current goal.
// ============================================================================

use alloc::string::String;
use super::tool_mapper;

pub struct Planner {
    system_prompt: String,
    goal: String,
}

impl Planner {
    pub fn new() -> Self {
        Self {
            system_prompt: String::from(
                "You are Heliox-OS, an autonomous agentic operating system running on FerrumOS. \
                 You can observe the system, make decisions, and execute actions through tool calls."
            ),
            goal: String::from("Explore the system and ensure everything is functioning."),
        }
    }

    pub fn set_goal(&mut self, goal: &str) {
        self.goal = String::from(goal);
    }

    pub fn generate_prompt(&self) -> String {
        let mut prompt = String::new();
        prompt.push_str(&self.system_prompt);
        prompt.push_str("\n\n");
        prompt.push_str(tool_mapper::TOOL_DEFINITIONS);
        prompt.push_str("\n\nCurrent Goal: ");
        prompt.push_str(&self.goal);
        prompt.push_str("\n\nRespond with a JSON tool call or plain text.");
        prompt
    }
}
