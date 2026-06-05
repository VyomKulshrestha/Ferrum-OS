use alloc::string::String;
use alloc::vec::Vec;

pub struct Planner {
    system_prompt: String,
    goal: String,
}

impl Planner {
    pub fn new() -> Self {
        Self {
            system_prompt: String::from("You are Heliox-OS, an autonomous agentic operating system."),
            goal: String::from("Explore the system and ensure everything is functioning."),
        }
    }

    pub fn set_goal(&mut self, goal: &str) {
        self.goal = String::from(goal);
    }

    pub fn generate_prompt(&self) -> String {
        let mut prompt = String::new();
        prompt.push_str(&self.system_prompt);
        prompt.push_str("\n\nCurrent Goal: ");
        prompt.push_str(&self.goal);
        prompt.push_str("\n\nPlease respond with a JSON-RPC method call to execute your next step.");
        prompt
    }
}
