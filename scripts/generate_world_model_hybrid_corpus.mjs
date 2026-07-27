// Generates a balanced, deterministic task corpus for
// collect_world_model_hybrid.mjs. These are goals, not fabricated state
// transitions: Heliox still chooses a response/tool call and FerrumOS still
// supplies the actual before/after ground truth.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}
const count = Math.max(41, Number(arg("--count", "5000")));
const seed = Number(arg("--seed", "42")) >>> 0;
const outPath = path.resolve(arg("--out", path.join(repo, "target", "world_model_hybrid_corpus.jsonl")));
const mode = arg("--mode", "hybrid");
if (!["hybrid", "live"].includes(mode)) {
  throw new Error(`unsupported --mode ${mode}; expected hybrid or live`);
}

// These controlled bridge/runtime actions are executable and part of the
// world-model's 41-action state space, but intentionally not advertised in the
// 37-tool LLM prompt. Hybrid mode replays only these four canonical calls so
// coverage does not depend on a provider inventing an undocumented tool name.
const controlledResponses = {
  local_inference: (i) => ({ tool: "local_inference", args: { prompt: `hybrid check ${i}` } }),
  trigger_kernel_upgrade: () => ({ tool: "trigger_kernel_upgrade", args: {} }),
  hud_update: (i) => ({
    tool: "hud_update",
    args: { flags: 0, point_x: i % 640, point_y: i % 480, suggestion: `hybrid ${i}` },
  }),
  hit_test: (i) => ({ tool: "hit_test", args: { x: i % 640, y: i % 480 } }),
};

const specs = [
  ["ipc_send", (i) => `Send a short IPC status message numbered ${i} to the gui service.`],
  ["audit_write", (i) => `Write audit event hybrid-${i} with informational severity.`],
  ["yield_cpu", () => "Yield the CPU once so another runnable task can proceed."],
  ["camera_capture", () => "Capture one camera frame and report whether a camera is available."],
  ["gesture_status", () => "Read the current gesture status without changing it."],
  ["report_status", (i) => `Report agent status hybrid collection item ${i}.`],
  ["capability_check", () => "Check whether the daemon currently holds its filesystem-read capability."],
  ["read_file", (i) => i % 3 === 0
    ? `Read /disk/nonexistent_hybrid_${i % 31}.txt and report the error.`
    : "Read /disk/heliox/config.json and summarize whether it is configured."],
  ["read_dir", () => "List the entries in /disk without modifying them."],
  ["query_memory", (i) => `Search memory for hybrid topic ${i % 17} and return the three closest entries.`],
  ["get_config", () => "Read the current Heliox runtime configuration."],
  ["system_info", () => "Report current system RAM, CPU features, and hardware tier."],
  ["list_processes", () => "List the currently running processes."],
  ["net_connect", (i) => `Try connecting to host 10.0.2.2 on port ${[9, 53, 80, 443, 8785][i % 5]}.`],
  ["net_send", (i) => `Send the text hybrid-${i} on the currently open network connection.`],
  ["net_recv", () => "Receive any currently available bytes from the open network connection."],
  ["http_get", () => "Request the root path from host 10.0.2.2 and report the HTTP result."],
  ["write_file", (i) => `Write ${16 + (i % 16) * 128} x characters to /disk/hybrid_${i}.txt.`],
  ["create_directory", (i) => `Create directory /disk/hybrid_dir_${i % 23} and report if it already exists.`],
  ["save_memory", () => "Persist the current Heliox memory store."],
  ["load_memory", () => "Load the persisted Heliox memory store."],
  ["set_goal", (i) => `Set the active goal to inspect hybrid scenario ${i}.`],
  ["sleep", (i) => `Sleep for ${1 + (i % 5)} scheduler ticks.`],
  ["service_start", (i) => `Start service id ${1 + (i % 8)}.`],
  ["service_stop", (i) => `Stop service id ${1 + (i % 8)}.`],
  ["exec_process", (i) => i % 3 === 0
    ? `Execute /disk/nonexistent_hybrid_bin_${i % 29} and report the failure.`
    : "Execute /disk/pkgs-available/notes/bin and report the result."],
  ["delete_file", (i) => i % 11 === 0
    ? "Attempt to delete /disk/heliox/config.json."
    : `Delete /disk/hybrid_${Math.max(0, i - 41)}.txt if it exists.`],
  ["local_inference", (i) => `Run local inference on the short prompt: hybrid check ${i}.`],
  ["trigger_kernel_upgrade", () => "Evaluate and attempt the kernel-upgrade action using a nonexistent image."],
  ["hud_update", (i) => `Update the HUD status text to hybrid ${i}.`],
  ["hit_test", (i) => `Hit-test screen coordinates ${i % 640},${i % 480}.`],
  ["read_screen", () => "Read the current screen text buffer."],
  ["add_subtask", (i) => `Add a subtask named hybrid subtask ${i} with no dependencies.`],
  ["record_audio", () => "Record a very short audio sample and report device availability."],
  ["play_audio", () => "Play the standard short notification sound once."],
  ["set_volume", (i) => `Set audio volume to ${i % 101} percent.`],
  ["keyboard_type", (i) => `Type the text hybrid-${i} into the focused application.`],
  ["mouse_click", (i) => `Click mouse button ${i % 3} once.`],
  ["mouse_move", (i) => `Move the mouse by ${-20 + (i % 41)},${20 - (i % 41)} pixels.`],
  ["browse_url", (i) => `Open http://10.0.2.2/hybrid/${i % 17} in the browser.`],
  ["poll_input", () => "Poll once for pending user input without blocking."],
];

let state = seed || 1;
const random = () => {
  state ^= state << 13;
  state ^= state >>> 17;
  state ^= state << 5;
  return (state >>> 0) / 0x1_0000_0000;
};

const rows = [];
let blockOrder = [];
for (let i = 0; i < count; i++) {
  const slot = i % specs.length;
  // Shuffle each complete 41-tool block while preserving exact balance.
  if (slot === 0) {
    blockOrder = Array.from({ length: specs.length }, (_, index) => index);
    for (let j = blockOrder.length - 1; j > 0; j--) {
      const k = Math.floor(random() * (j + 1));
      [blockOrder[j], blockOrder[k]] = [blockOrder[k], blockOrder[j]];
    }
  }
  const [tool, makePrompt] = specs[blockOrder[slot]];
  const row = {
    id: `hybrid-${String(i).padStart(6, "0")}`,
    prompt: makePrompt(i),
    expected_tool: tool,
    max_steps: i % 5 === 0 ? 3 : 1,
    tags: [
      "generated",
      tool,
      i % 5 === 0 ? "multi-step" : "single-step",
      mode === "hybrid" && controlledResponses[tool] ? "controlled-replay" : "live-provider",
    ],
  };
  if (mode === "hybrid" && controlledResponses[tool]) {
    row.responses = [controlledResponses[tool](i)];
  }
  rows.push(row);
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
const controlledCount = rows.filter((row) => Array.isArray(row.responses)).length;
console.log(
  `wrote ${rows.length} balanced hybrid scenarios across ${specs.length} actions `
  + `(${controlledCount} controlled replay, ${rows.length - controlledCount} live provider) to ${outPath}`,
);
