use super::planner::Planner;
use alloc::string::String;
use alloc::vec::Vec;
use crate::memory::vector_store::VectorStore;
use crate::network;

pub struct Orchestrator {
    planner: Planner,
    memory: VectorStore,
    tick_count: u64,
    last_response: Option<String>,
}

impl Orchestrator {
    pub fn new() -> Self {
        Self {
            planner: Planner::new(),
            memory: VectorStore::new(),
            tick_count: 0,
            last_response: None,
        }
    }

    pub fn tick(&mut self) {
        self.tick_count += 1;

        // Only attempt LLM calls every 100 ticks to avoid flooding
        if self.tick_count % 100 != 0 {
            return;
        }

        // 1. Generate prompt based on current goal
        let prompt = self.planner.generate_prompt();

        // 2. Query the LLM via the network layer
        //    Targets a local Ollama instance on the QEMU host (10.0.2.2:11434)
        match network::query_ollama(&prompt) {
            Ok(response) => {
                if response.status_code == 200 {
                    self.last_response = Some(response.body);

                    // 3. TODO (Part 3): Parse the JSON response for tool calls
                    // let action = json::parse_tool_call(&response.body);

                    // 4. TODO (Part 3): Execute the action via syscall
                    // tool_mapper::execute(action);

                    // 5. Save the interaction to vector memory for context
                    // (embedding generation would require a separate model;
                    //  for now we store a placeholder embedding)
                    let embedding = alloc::vec![0.0f32; 8]; // placeholder
                    self.memory.add(
                        alloc::format!("tick-{}", self.tick_count),
                        prompt,
                        embedding,
                    );
                }
            }
            Err(_e) => {
                // Network not ready yet or LLM not available — silently continue.
                // The daemon will retry on the next tick cycle.
            }
        }
    }

    /// Returns the last LLM response, if any.
    pub fn last_response(&self) -> Option<&str> {
        self.last_response.as_deref()
    }
}
