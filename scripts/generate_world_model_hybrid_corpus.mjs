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
const offset = Math.max(0, Number(arg("--offset", "0")));
const outPath = path.resolve(arg("--out", path.join(repo, "target", "world_model_hybrid_corpus.jsonl")));
const mode = arg("--mode", "hybrid");
if (!["controlled", "hybrid", "live"].includes(mode)) {
  throw new Error(`unsupported --mode ${mode}; expected controlled, hybrid, or live`);
}

// Every action has a bounded canonical response for provider-independent bulk
// collection. Hybrid mode still reserves the four runtime-only actions (which
// are not advertised in the 37-tool LLM prompt) for controlled replay; live
// actions can be filled by prefetch_world_model_responses.mjs. Controlled mode
// replays all 41 actions and is the reliable coverage backbone.
const controlledResponses = {
  ipc_send: (i) => ({ tool: "ipc_send", args: { target_service: "heliox", message: `hybrid-${i}` } }),
  audit_write: (i) => ({ tool: "audit_write", args: { message: `hybrid audit ${i}` } }),
  yield_cpu: () => ({ tool: "yield_cpu", args: {} }),
  camera_capture: () => ({ tool: "camera_capture", args: {} }),
  gesture_status: () => ({ tool: "gesture_status", args: {} }),
  report_status: (i) => ({ tool: "report_status", args: { status: `hybrid status ${i}` } }),
  capability_check: (i) => ({ tool: "capability_check", args: { capability_id: 1 + (i % 8) } }),
  read_file: (i) => ({ tool: "read_file", args: { path: i % 3 === 0 ? `/disk/missing_${i % 31}.txt` : "/disk/heliox/config.json" } }),
  read_dir: (i) => ({
    tool: "read_dir",
    args: { path: ["/disk", "/disk/heliox", "/disk/pkgs-available"][i % 3] },
  }),
  query_memory: (i) => ({ tool: "query_memory", args: { query: `hybrid topic ${i % 17}`, top_k: 1 + (i % 5) } }),
  get_config: (i) => ({ tool: "get_config", args: { key: ["provider", "model_name", "tick_interval"][i % 3] } }),
  system_info: () => ({ tool: "system_info", args: {} }),
  list_processes: () => ({ tool: "list_processes", args: {} }),
  net_connect: (i) => ({ tool: "net_connect", args: { host: "10.0.2.2", port: [9, 53, 80, 443, 8785][i % 5] } }),
  net_send: (i) => ({ tool: "net_send", args: { fd: 3 + (i % 4), data: `hybrid-${i}` } }),
  net_recv: (i) => ({ tool: "net_recv", args: { fd: 3 + (i % 4) } }),
  http_get: (i) => ({ tool: "http_get", args: { host: "10.0.2.2", port: 80, path: `/hybrid/${i % 17}` } }),
  write_file: (i) => ({ tool: "write_file", args: { path: `/disk/wm_pool_${i % 64}.txt`, content: "x".repeat(16 + (i % 16) * 128) } }),
  create_directory: (i) => ({ tool: "create_directory", args: { path: `/disk/wm_dir_${i % 32}` } }),
  save_memory: () => ({ tool: "save_memory", args: {} }),
  load_memory: () => ({ tool: "load_memory", args: {} }),
  set_goal: (i) => ({ tool: "set_goal", args: { goal: `inspect hybrid scenario ${i}` } }),
  sleep: (i) => ({ tool: "sleep", args: { ms: 1 + (i % 5) } }),
  service_start: (i) => ({ tool: "service_start", args: { service_id: 1 + (i % 8) } }),
  service_stop: (i) => ({ tool: "service_stop", args: { service_id: 1 + (i % 8) } }),
  exec_process: (i) => ({ tool: "exec_process", args: { path: i % 3 === 0 ? `/disk/missing_bin_${i % 29}` : "/disk/pkgs-available/notes/bin" } }),
  delete_file: (i) => ({ tool: "delete_file", args: { path: i % 11 === 0 ? "/disk/heliox/config.json" : `/disk/wm_pool_${i % 64}.txt` } }),
  local_inference: (i) => ({ tool: "local_inference", args: { prompt: `hybrid check ${i}`, max_tokens: 1 } }),
  trigger_kernel_upgrade: () => ({ tool: "trigger_kernel_upgrade", args: {} }),
  hud_update: (i) => ({
    tool: "hud_update",
    args: { flags: 0, point_x: i % 640, point_y: i % 480, suggestion: `hybrid ${i}` },
  }),
  hit_test: (i) => ({ tool: "hit_test", args: { x: i % 640, y: i % 480 } }),
  read_screen: () => ({ tool: "read_screen", args: {} }),
  add_subtask: (i) => ({ tool: "add_subtask", args: { description: `hybrid subtask ${i}`, depends_on: "" } }),
  record_audio: (i) => ({ tool: "record_audio", args: { duration_ms: 1 + (i % 5) } }),
  play_audio: () => ({ tool: "play_audio", args: {} }),
  set_volume: (i) => ({ tool: "set_volume", args: { level: i % 128 } }),
  keyboard_type: (i) => ({ tool: "keyboard_type", args: { text: `hybrid-${i}` } }),
  mouse_click: (i) => ({ tool: "mouse_click", args: { button: i % 3 } }),
  mouse_move: (i) => ({ tool: "mouse_move", args: { dx: -20 + (i % 41), dy: 20 - (i % 41) } }),
  browse_url: (i) => ({
    tool: "browse_url",
    args: {
      url: [
        `http://10.0.2.2/a/${i % 17}`,
        `http://10.0.2.2/hybrid/${i % 17}`,
        `http://10.0.2.2/long/hybrid/path/${i % 17}`,
      ][i % 3],
    },
  }),
  poll_input: () => ({ tool: "poll_input", args: {} }),
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
  ["write_file", (i) => `Write ${16 + (i % 16) * 128} x characters to /disk/wm_pool_${i % 64}.txt.`],
  ["create_directory", (i) => `Create directory /disk/wm_dir_${i % 32} and report if it already exists.`],
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
    : `Delete /disk/wm_pool_${i % 64}.txt if it exists.`],
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
  const corpusIndex = offset + i;
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
    id: `hybrid-${String(corpusIndex).padStart(6, "0")}`,
    prompt: makePrompt(corpusIndex),
    expected_tool: tool,
    max_steps: i % 5 === 0 ? 3 : 1,
    tags: [
      "generated",
      tool,
      i % 5 === 0 ? "multi-step" : "single-step",
      mode === "controlled" || (mode === "hybrid" && ["local_inference", "trigger_kernel_upgrade", "hud_update", "hit_test"].includes(tool))
        ? "controlled-replay"
        : "live-provider",
    ],
  };
  const controlled = mode === "controlled"
    || (mode === "hybrid" && ["local_inference", "trigger_kernel_upgrade", "hud_update", "hit_test"].includes(tool));
  if (controlled) {
    row.responses = Array.from(
      { length: row.max_steps },
      (_, step) => controlledResponses[tool](corpusIndex + step),
    );
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
