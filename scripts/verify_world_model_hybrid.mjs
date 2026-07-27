// ============================================================================
// FerrumOS - Hybrid World-Model Pipeline Verification
// ============================================================================
// Verifies both halves of the hybrid pipeline:
//   1. the generated goal corpus is deterministic and balanced across 41 tools;
//   2. replayed provider responses travel through Heliox's real ReAct path in
//      QEMU and produce argument-conditioned, episode-labelled transition rows.
// ============================================================================

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const target = path.join(repo, "target");
const corpusOut = path.join(target, "world-model-hybrid-verify-corpus.jsonl");
const datasetOut = path.join(target, "world-model-hybrid-verify-dataset.jsonl");
const tracesOut = path.join(target, "world-model-hybrid-verify-traces.jsonl");
const fixture = path.join(scriptDir, "fixtures", "world_model_hybrid_smoke.jsonl");

fs.mkdirSync(target, { recursive: true });
for (const file of [corpusOut, datasetOut, tracesOut]) fs.rmSync(file, { force: true });

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? `\t${detail}` : ""}`);
  return ok;
}

function run(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(scriptDir, script), ...args], {
      cwd: repo,
      env: process.env,
      stdio: "inherit",
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (signal) reject(new Error(`${script} terminated by signal ${signal}`));
      else if (code !== 0) reject(new Error(`${script} failed with exit code ${code}`));
      else resolve();
    });
  });
}

function readJsonl(file) {
  return fs.readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line));
}

try {
  await run("generate_world_model_hybrid_corpus.mjs", [
    "--count", "82",
    "--seed", "1234",
    "--out", corpusOut,
  ]);
  const corpus = readJsonl(corpusOut);
  const toolCounts = new Map();
  for (const row of corpus) {
    toolCounts.set(row.expected_tool, (toolCounts.get(row.expected_tool) || 0) + 1);
  }
  check("generated corpus contains requested scenario count", corpus.length === 82);
  check(
    "generated corpus balances every canonical action exactly twice",
    toolCounts.size === 41 && [...toolCounts.values()].every((count) => count === 2),
    `${toolCounts.size} tools`,
  );
  check(
    "generated corpus ids are unique",
    new Set(corpus.map((row) => row.id)).size === corpus.length,
  );
  check(
    "hybrid corpus replays only the four intentionally non-advertised actions",
    corpus.filter((row) => Array.isArray(row.responses)).length === 8
      && new Set(
        corpus.filter((row) => Array.isArray(row.responses)).map((row) => row.expected_tool),
      ).size === 4,
  );

  await run("collect_world_model_hybrid.mjs", [
    "--corpus", fixture,
    "--out", datasetOut,
    "--traces", tracesOut,
    "--ram", process.env.WM_VERIFY_RAM_MB || "512",
  ]);
  const rows = readJsonl(datasetOut);
  const traces = readJsonl(tracesOut);
  const terminalTraces = traces.filter((row) => row.completed === true);
  const actionTraces = traces.filter((row) => Array.isArray(row.actions));
  const actualTools = actionTraces.flatMap((row) => row.actions.map((action) => action.tool));

  check("QEMU ReAct smoke emits four real transitions", rows.length === 4);
  check(
    "every transition uses hybrid schema v2 with 16 argument features",
    rows.every(
      (row) =>
        row.schema_version === 2
        && Array.isArray(row.action_features)
        && row.action_features.length === 16
        && Array.isArray(row.before)
        && row.before.length === 128
        && Array.isArray(row.after)
        && row.after.length === 128,
    ),
  );
  check(
    "provider identity is audit metadata, not a numeric model feature",
    rows.every((row) => row.provider === "replay" && row.provider_model === null),
  );
  check(
    "collector records actual tool coverage and expected-tool agreement",
    rows.every(
      (row) => row.actual_tool === row.expected_tool && row.expected_tool_match === true,
    ),
  );
  check(
    "each scenario has a durable completed episode marker",
    terminalTraces.length === 4
      && new Set(terminalTraces.map((row) => row.episode_id)).size === 4,
  );
  check(
    "replayed tool choices reach the Heliox action dispatcher",
    ["write_file", "read_file", "read_file", "delete_file"].every(
      (tool, index) => actualTools[index] === tool,
    ),
    actualTools.join(","),
  );
  check(
    "success, failure, and world-model block outcomes are all captured",
    rows.filter((row) => row.success).length === 2
      && rows.filter((row) => !row.success).length === 2
      && rows.filter((row) => row.executed).length === 3
      && rows.filter((row) => !row.executed).length === 1
      && actionTraces.some((row) =>
        row.actions.some((action) => action.output.includes("Blocked by world-model safety gate"))),
  );
  check(
    "raw provider responses are retained for audit/replay",
    actionTraces.every((row) => typeof row.raw_response === "string" && row.raw_response.length > 0),
  );
} catch (error) {
  check("hybrid pipeline verification completed", false, error?.message || String(error));
}

console.log(`\n${results.join("\n")}`);
const failed = results.filter((row) => row.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
