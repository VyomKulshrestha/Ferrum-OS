#!/usr/bin/env node
// Validate world-model transition corpora before training or JEPA promotion.
// The audit is deliberately provider-independent: it checks executed OS
// transitions and their diversity, not which LLM proposed an action.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const TOOL_NAMES = [
  "ipc_send", "audit_write", "yield_cpu", "camera_capture", "gesture_status",
  "report_status", "capability_check", "read_file", "read_dir", "query_memory",
  "get_config", "system_info", "list_processes", "net_connect", "net_send",
  "net_recv", "http_get", "write_file", "create_directory", "save_memory",
  "load_memory", "set_goal", "sleep", "service_start", "service_stop",
  "exec_process", "delete_file", "local_inference", "trigger_kernel_upgrade",
  "hud_update", "hit_test", "read_screen", "add_subtask", "record_audio",
  "play_audio", "set_volume", "keyboard_type", "mouse_click", "mouse_move",
  "browse_url", "poll_input",
];

const EMBEDDING_SIZE = 128;
const ACTION_FEATURE_SIZE = 16;
const ARGUMENTLESS_TOOLS = new Set([
  "yield_cpu", "camera_capture", "gesture_status", "system_info",
  "list_processes", "save_memory", "load_memory", "trigger_kernel_upgrade",
  "read_screen", "play_audio", "poll_input",
]);

function finiteVector(value, length) {
  return Array.isArray(value)
    && value.length === length
    && value.every((item) => Number.isFinite(Number(item)));
}

function featureSignature(features) {
  return features.map((value) => Number(value).toFixed(4)).join(",");
}

export function auditRows(rows, thresholds = {}) {
  const limits = {
    requiredTools: thresholds.requiredTools ?? TOOL_NAMES.length,
    minExecutedPerTool: thresholds.minExecutedPerTool ?? 32,
    minArgumentVariants: thresholds.minArgumentVariants ?? 3,
    minEpisodes: thresholds.minEpisodes ?? 100,
    minMultistepEpisodes: thresholds.minMultistepEpisodes ?? 25,
    minRamProfiles: thresholds.minRamProfiles ?? 1,
  };
  const errors = [];
  const perTool = TOOL_NAMES.map((name) => ({
    name,
    rows: 0,
    executed: 0,
    blocked: 0,
    argumentVariants: new Set(),
    changedDimensions: new Set(),
  }));
  const episodes = new Map();
  const ramProfiles = new Set();
  const sources = new Map();
  let executedRows = 0;
  let blockedRows = 0;

  rows.forEach((row, index) => {
    const prefix = `row ${index + 1}`;
    if (!finiteVector(row.before, EMBEDDING_SIZE)) errors.push(`${prefix}: before must contain 128 finite numbers`);
    if (!finiteVector(row.after, EMBEDDING_SIZE)) errors.push(`${prefix}: after must contain 128 finite numbers`);
    if (!finiteVector(row.action_features, ACTION_FEATURE_SIZE)) errors.push(`${prefix}: action_features must contain 16 finite numbers`);
    const action = Number(row.action);
    if (!Number.isInteger(action) || action < 0 || action >= TOOL_NAMES.length) {
      errors.push(`${prefix}: action must be an integer from 0 to ${TOOL_NAMES.length - 1}`);
      return;
    }
    const executed = row.executed !== false;
    const stats = perTool[action];
    stats.rows++;
    if (executed) {
      executedRows++;
      stats.executed++;
      if (finiteVector(row.action_features, ACTION_FEATURE_SIZE)) {
        stats.argumentVariants.add(featureSignature(row.action_features));
      }
      if (finiteVector(row.before, EMBEDDING_SIZE) && finiteVector(row.after, EMBEDDING_SIZE)) {
        for (let dimension = 0; dimension < EMBEDDING_SIZE; dimension++) {
          if (Math.abs(Number(row.after[dimension]) - Number(row.before[dimension])) > 1e-7) {
            stats.changedDimensions.add(dimension);
          }
        }
      }
    } else {
      blockedRows++;
      stats.blocked++;
    }
    const episodeId = row.episode_id == null ? `legacy-row-${index}` : String(row.episode_id);
    episodes.set(episodeId, (episodes.get(episodeId) || 0) + 1);
    if (row.ram_mb != null && Number.isFinite(Number(row.ram_mb))) ramProfiles.add(Number(row.ram_mb));
    const source = String(row.source || "unspecified");
    sources.set(source, (sources.get(source) || 0) + 1);
  });

  const coveredTools = perTool.filter((tool) => tool.executed >= limits.minExecutedPerTool);
  const diversityEligibleTools = perTool.filter((tool) => !ARGUMENTLESS_TOOLS.has(tool.name));
  const diverseTools = diversityEligibleTools.filter(
    (tool) => tool.argumentVariants.size >= limits.minArgumentVariants,
  );
  const multiStepEpisodes = [...episodes.values()].filter((count) => count > 1).length;
  const gates = [
    { name: "schema", passed: errors.length === 0, actual: errors.length, required: 0 },
    { name: "tool_coverage", passed: coveredTools.length >= limits.requiredTools, actual: coveredTools.length, required: limits.requiredTools },
    {
      name: "argument_diversity",
      passed: diverseTools.length >= diversityEligibleTools.length,
      actual: diverseTools.length,
      required: diversityEligibleTools.length,
    },
    { name: "episodes", passed: episodes.size >= limits.minEpisodes, actual: episodes.size, required: limits.minEpisodes },
    { name: "multistep_episodes", passed: multiStepEpisodes >= limits.minMultistepEpisodes, actual: multiStepEpisodes, required: limits.minMultistepEpisodes },
    { name: "ram_profiles", passed: ramProfiles.size >= limits.minRamProfiles, actual: ramProfiles.size, required: limits.minRamProfiles },
  ];

  return {
    schema_version: 1,
    passed: gates.every((gate) => gate.passed),
    rows: rows.length,
    executed_rows: executedRows,
    blocked_rows: blockedRows,
    episodes: episodes.size,
    multistep_episodes: multiStepEpisodes,
    ram_profiles: [...ramProfiles].sort((a, b) => a - b),
    sources: Object.fromEntries([...sources.entries()].sort()),
    thresholds: limits,
    gates,
    errors: errors.slice(0, 100),
    per_tool: perTool.map((tool) => ({
      name: tool.name,
      rows: tool.rows,
      executed: tool.executed,
      blocked: tool.blocked,
      argument_diversity_required: !ARGUMENTLESS_TOOLS.has(tool.name),
      argument_variants: tool.argumentVariants.size,
      changed_dimensions: [...tool.changedDimensions].sort((a, b) => a - b),
    })),
  };
}

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function numberArg(name, fallback) {
  const value = Number(arg(name, String(fallback)));
  if (!Number.isFinite(value) || value < 0) throw new Error(`${name} must be a non-negative number`);
  return value;
}

function main() {
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const dataset = path.resolve(arg("--dataset", path.join(repo, "target", "world_model_dataset_hybrid.jsonl")));
  const output = path.resolve(arg("--out", path.join(repo, "target", "world_model_dataset_audit.json")));
  const rows = fs.readFileSync(dataset, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line, index) => {
      try { return JSON.parse(line); }
      catch (error) { throw new Error(`invalid JSON on line ${index + 1}: ${error.message}`); }
    });
  const report = auditRows(rows, {
    requiredTools: numberArg("--required-tools", TOOL_NAMES.length),
    minExecutedPerTool: numberArg("--min-executed-per-tool", 32),
    minArgumentVariants: numberArg("--min-argument-variants", 3),
    minEpisodes: numberArg("--min-episodes", 100),
    minMultistepEpisodes: numberArg("--min-multistep-episodes", 25),
    minRamProfiles: numberArg("--min-ram-profiles", 1),
  });
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`);
  for (const gate of report.gates) {
    console.log(`${gate.passed ? "PASS" : "FAIL"}\t${gate.name}\t${gate.actual}/${gate.required}`);
  }
  console.log(`dataset: ${report.rows} rows, ${report.executed_rows} executed, ${report.episodes} episodes`);
  console.log(`report: ${output}`);
  if (process.argv.includes("--strict") && !report.passed) process.exitCode = 1;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
