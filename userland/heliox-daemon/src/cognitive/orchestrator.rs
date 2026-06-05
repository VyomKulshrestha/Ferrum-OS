// ============================================================================
// Heliox-Daemon - Orchestrator
// ============================================================================
// The main agent loop. Each tick: generate prompt → query LLM → parse
// JSON response → execute tool calls → store results in vector memory.
// ============================================================================

use super::planner::Planner;
use super::json;
use super::tool_mapper;
use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;
use crate::memory::vector_store::VectorStore;
use crate::network;

pub struct Orchestrator {
    planner: Planner,
    memory: VectorStore,
    tick_count: u64,
    last_response: Option<String>,
    last_action: Option<String>,
}

impl Orchestrator {
    pub fn new() -> Self {
        Self {
            planner: Planner::new(),
            memory: VectorStore::new(),
            tick_count: 0,
            last_response: None,
            last_action: None,
        }
    }

    pub fn tick(&mut self) {
        self.tick_count += 1;

        // Only attempt LLM calls every 100 ticks to avoid flooding
        if self.tick_count % 100 != 0 {
            return;
        }

        // 1. Generate prompt based on current goal (includes tool definitions)
        let prompt = self.planner.generate_prompt();

        // 2. Query the LLM via the network layer
        //    Targets a local Ollama instance on the QEMU host (10.0.2.2:11434)
        match network::query_ollama(&prompt) {
            Ok(response) => {
                if response.status_code == 200 {
                    // 3. Parse the JSON response
                    match json::parse(&response.body) {
                        Ok(parsed) => {
                            // Store raw response
                            self.last_response = json::extract_content(&parsed)
                                .or_else(|| Some(response.body.clone()));

                            // 4. Extract and execute tool calls
                            let tool_calls = json::extract_tool_calls(&parsed);

                            if !tool_calls.is_empty() {
                                for tc in &tool_calls {
                                    let result = tool_mapper::execute(tc);
                                    self.last_action = Some(format!(
                                        "{}:{} -> {}",
                                        result.tool_name,
                                        if result.success { "ok" } else { "fail" },
                                        result.output
                                    ));

                                    // 5. Store the tool execution in vector memory
                                    let embedding = alloc::vec![0.0f32; 8]; // placeholder
                                    self.memory.add(
                                        format!("action-{}", self.tick_count),
                                        format!("tool={} result={}", tc.name, result.output),
                                        embedding,
                                    );
                                }
                            } else {
                                // No tool calls — store the text response as context
                                let content = self.last_response.clone().unwrap_or_default();
                                let embedding = alloc::vec![0.0f32; 8];
                                self.memory.add(
                                    format!("response-{}", self.tick_count),
                                    content,
                                    embedding,
                                );
                            }
                        }
                        Err(_) => {
                            // Response wasn't valid JSON — store raw text
                            self.last_response = Some(response.body);
                        }
                    }
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

    /// Returns the last tool action executed, if any.
    pub fn last_action(&self) -> Option<&str> {
        self.last_action.as_deref()
    }
}
