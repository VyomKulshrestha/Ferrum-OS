#!/usr/bin/env node
// Generate provider responses ahead of QEMU collection. The local/provider LLM
// proposes canonical actions and arguments; FerrumOS remains the sole source of
// before/after state and therefore of transition training truth.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TOOL_NAMES } from "./audit_world_model_dataset.mjs";

const ARGUMENT_GUIDE = {
  ipc_send: { target_pid: "number", message: "string" },
  audit_write: { message: "string" },
  yield_cpu: {}, camera_capture: {}, gesture_status: {},
  report_status: { status: "string" }, capability_check: { capability_id: "number" },
  read_file: { path: "string" }, read_dir: { path: "string" },
  query_memory: { query: "string", top_k: "number" }, get_config: { key: "string" },
  system_info: {}, list_processes: {},
  net_connect: { host: "string", port: "number" },
  net_send: { fd: "number", data: "string" }, net_recv: { fd: "number" },
  http_get: { host: "string", port: "number", path: "string" },
  write_file: { path: "string", content: "string" }, create_directory: { path: "string" },
  save_memory: {}, load_memory: {}, set_goal: { goal: "string" }, sleep: { ms: "number" },
  service_start: { service_id: "number" }, service_stop: { service_id: "number" },
  exec_process: { path: "string" }, delete_file: { path: "string" },
  local_inference: { prompt: "string" }, trigger_kernel_upgrade: {},
  hud_update: { flags: "number", point_x: "number", point_y: "number", suggestion: "string" },
  hit_test: { x: "number", y: "number" }, read_screen: {},
  add_subtask: { description: "string", depends_on: "string" },
  record_audio: { duration_ms: "number" }, play_audio: {}, set_volume: { level: "number" },
  keyboard_type: { text: "string" }, mouse_click: { button: "number" },
  mouse_move: { dx: "number", dy: "number" }, browse_url: { url: "string" }, poll_input: {},
};

function stripCodeFence(text) {
  const trimmed = String(text || "").trim();
  const match = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  return match ? match[1] : trimmed;
}

export function parseProviderResponse(provider, payload) {
  const content = provider === "ollama"
    ? payload?.message?.content ?? payload?.response
    : payload?.choices?.[0]?.message?.content;
  if (typeof content !== "string") throw new Error("provider response has no text content");
  const parsed = JSON.parse(stripCodeFence(content));
  const responses = Array.isArray(parsed) ? parsed : parsed.responses;
  if (!Array.isArray(responses)) throw new Error("model output must contain a responses array");
  return responses;
}

export function validateBatch(tasks, responses, allowToolMismatch = false) {
  const byKey = new Map();
  for (const response of responses) {
    const key = `${String(response?.id || "")}#${Number(response?.step)}`;
    if (byKey.has(key)) throw new Error(`duplicate response ${key}`);
    byKey.set(key, response);
  }
  return tasks.map((task) => {
    const key = `${task.id}#${task.step}`;
    const response = byKey.get(key);
    if (!response) throw new Error(`missing response ${key}`);
    if (!TOOL_NAMES.includes(response.tool)) throw new Error(`${key} returned unknown tool ${response.tool}`);
    if (!allowToolMismatch && task.expected_tool && response.tool !== task.expected_tool) {
      throw new Error(`${key} returned ${response.tool}; expected ${task.expected_tool}`);
    }
    if (!response.args || typeof response.args !== "object" || Array.isArray(response.args)) {
      throw new Error(`${key} args must be an object`);
    }
    return { tool: response.tool, args: response.args };
  });
}

function promptFor(tasks) {
  const relevantGuide = Object.fromEntries(
    [...new Set(tasks.map((task) => task.expected_tool).filter(Boolean))]
      .map((tool) => [tool, ARGUMENT_GUIDE[tool] || {}]),
  );
  return [
    "Produce one canonical Heliox tool call for every task.",
    "The expected_tool is a controlled coverage target; use it exactly and infer varied, valid arguments from the goal.",
    "Return JSON only: {\"responses\":[{\"id\":\"...\",\"step\":0,\"tool\":\"...\",\"args\":{}}]}.",
    "Do not omit, duplicate, reorder, explain, or wrap entries in markdown.",
    `Argument schemas: ${JSON.stringify(relevantGuide)}`,
    `Tasks: ${JSON.stringify(tasks)}`,
  ].join("\n");
}

export async function requestBatch(tasks, options) {
  const messages = [
    { role: "system", content: "You generate strict JSON tool calls for offline OS world-model data collection." },
    { role: "user", content: promptFor(tasks) },
  ];
  const body = options.provider === "ollama"
    ? {
        model: options.model,
        messages,
        stream: false,
        think: false,
        format: "json",
        options: { temperature: options.temperature, seed: options.seed },
      }
    : {
        model: options.model,
        messages,
        temperature: options.temperature,
        response_format: { type: "json_object" },
      };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs);
  let response;
  try {
    response = await fetch(options.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(options.apiKey ? { Authorization: `Bearer ${options.apiKey}` } : {}),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  const text = await response.text();
  if (!response.ok) throw new Error(`provider HTTP ${response.status}: ${text.slice(0, 500)}`);
  let payload;
  try { payload = JSON.parse(text); }
  catch { throw new Error(`provider returned non-JSON transport: ${text.slice(0, 500)}`); }
  return {
    calls: validateBatch(tasks, parseProviderResponse(options.provider, payload), options.allowToolMismatch),
    raw: payload,
  };
}

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  if (process.argv.includes("--help")) {
    console.log("usage: node scripts/prefetch_world_model_responses.mjs [--input PATH] [--out PATH] [--provider ollama|openai] [--url URL] [--model MODEL] [--batch-size N] [--max-scenarios N] [--resume] [--replace-existing]");
    return;
  }
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const input = path.resolve(arg("--input", path.join(repo, "target", "world_model_hybrid_corpus.jsonl")));
  const output = path.resolve(arg("--out", path.join(repo, "target", "world_model_hybrid_prefetched.jsonl")));
  const trace = path.resolve(arg("--trace", path.join(repo, "target", "world_model_response_prefetch_trace.jsonl")));
  if (input === output) throw new Error("--input and --out must differ so interrupted runs cannot destroy the source corpus");
  const provider = arg("--provider", "ollama");
  if (!["ollama", "openai"].includes(provider)) throw new Error("--provider must be ollama or openai");
  const options = {
    provider,
    url: arg("--url", provider === "ollama" ? "http://127.0.0.1:11434/api/chat" : ""),
    model: arg("--model", provider === "ollama" ? "qwen3.5:4b" : ""),
    apiKey: process.env.WM_PROVIDER_KEY || "",
    temperature: Number(arg("--temperature", "0.7")),
    seed: Number(arg("--seed", "42")),
    timeoutMs: Number(arg("--timeout-ms", "180000")),
    allowToolMismatch: process.argv.includes("--allow-tool-mismatch"),
  };
  if (!options.url || !options.model) throw new Error("provider URL and model are required");
  const batchSize = Math.max(1, Number(arg("--batch-size", "12")));
  const retries = Math.max(0, Number(arg("--retries", "2")));
  const maxScenarios = Math.max(0, Number(arg("--max-scenarios", "0")));
  const resume = process.argv.includes("--resume");
  const replace = process.argv.includes("--replace-existing");
  let scenarios = fs.readFileSync(input, "utf8").split(/\r?\n/).filter((line) => line.trim()).map(JSON.parse);
  if (maxScenarios > 0) scenarios = scenarios.slice(0, maxScenarios);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.mkdirSync(path.dirname(trace), { recursive: true });
  if (!resume) {
    fs.rmSync(output, { force: true });
    fs.rmSync(trace, { force: true });
  }
  const completed = new Set();
  if (resume && fs.existsSync(output)) {
    for (const line of fs.readFileSync(output, "utf8").split(/\r?\n/)) {
      if (line.trim()) completed.add(String(JSON.parse(line).id));
    }
  }
  const pending = scenarios.filter((scenario) => !completed.has(String(scenario.id)));
  const tasks = [];
  const generatedByScenario = new Map();
  const scenarioById = new Map(pending.map((scenario) => [String(scenario.id), scenario]));
  const emitted = new Set();
  const emitScenario = (scenario, generated = null) => {
    const id = String(scenario.id);
    if (emitted.has(id)) return;
    const enriched = generated
      ? {
          ...scenario,
          responses: generated,
          response_prefetch: { provider, model: options.model, targeted: !options.allowToolMismatch },
        }
      : scenario;
    fs.appendFileSync(output, `${JSON.stringify(enriched)}\n`);
    emitted.add(id);
  };
  for (const scenario of pending) {
    if (!replace && Array.isArray(scenario.responses) && scenario.responses.length > 0) {
      emitScenario(scenario);
      continue;
    }
    const steps = Math.max(1, Number(scenario.max_steps || 1));
    for (let step = 0; step < steps; step++) {
      tasks.push({
        id: String(scenario.id),
        step,
        goal: String(scenario.prompt || ""),
        expected_tool: scenario.expected_tool || null,
      });
    }
  }

  async function completeBatch(batch) {
    let lastError;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const result = await requestBatch(batch, options);
        fs.appendFileSync(trace, `${JSON.stringify({
          ids: batch.map((task) => `${task.id}#${task.step}`),
          provider,
          model: options.model,
          attempt,
          completed: true,
        })}\n`);
        return result.calls;
      } catch (error) {
        lastError = error;
        fs.appendFileSync(trace, `${JSON.stringify({
          ids: batch.map((task) => `${task.id}#${task.step}`),
          provider,
          model: options.model,
          attempt,
          completed: false,
          error: String(error?.message || error),
        })}\n`);
        if (attempt < retries) await sleep(250 * (attempt + 1));
      }
    }
    if (batch.length > 1) {
      const midpoint = Math.ceil(batch.length / 2);
      return [
        ...(await completeBatch(batch.slice(0, midpoint))),
        ...(await completeBatch(batch.slice(midpoint))),
      ];
    }
    throw lastError;
  }

  for (let offset = 0; offset < tasks.length; offset += batchSize) {
    const batch = tasks.slice(offset, offset + batchSize);
    const calls = await completeBatch(batch);
    for (let index = 0; index < batch.length; index++) {
      const list = generatedByScenario.get(batch[index].id) || [];
      list[batch[index].step] = calls[index];
      generatedByScenario.set(batch[index].id, list);
    }
    for (const id of new Set(batch.map((task) => task.id))) {
      const scenario = scenarioById.get(id);
      const generated = generatedByScenario.get(id);
      const steps = Math.max(1, Number(scenario?.max_steps || 1));
      if (scenario && generated && generated.filter(Boolean).length === steps) {
        emitScenario(scenario, generated);
      }
    }
    console.log(`[prefetch] ${Math.min(offset + batch.length, tasks.length)}/${tasks.length} responses`);
  }

  for (const scenario of pending) {
    const generated = generatedByScenario.get(String(scenario.id));
    if (!emitted.has(String(scenario.id))) {
      if (!generated) throw new Error(`scenario ${scenario.id} did not receive responses`);
      emitScenario(scenario, generated);
    }
  }
  console.log(`[prefetch] wrote ${pending.length} scenarios (${tasks.length} generated responses) to ${output}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(`[prefetch] ${error?.stack || error}`);
    process.exitCode = 1;
  });
}
