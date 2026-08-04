#!/usr/bin/env node
// Two local-inference actions in one daemon process: the first may page in the
// checkpoint, while the second must reuse that exact read-only mapping.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "local-inference-cache-corpus.jsonl");
const dataset = path.join(repo, "target", "local-inference-cache-dataset.jsonl");
const traces = path.join(repo, "target", "local-inference-cache-traces.jsonl");
const scenarios = [0, 1].map((index) => ({
  id: `local-inference-cache-${index}`,
  prompt: `Run a one-token local inference cache probe ${index}.`,
  expected_tool: "local_inference",
  max_steps: 1,
  responses: [{ tool: "local_inference", args: { prompt: `cache probe ${index}`, max_tokens: 1 } }],
}));
fs.writeFileSync(corpus, `${scenarios.map(JSON.stringify).join("\n")}\n`);
const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--scenarios-per-boot", "2",
  "--rpc-timeout-ms", "600000",
  "--run-id", "inference-cache",
  "--accel", "auto",
], { cwd: repo, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.equal(result.status, 0, "both local inference probes must complete");
const stepRows = fs.readFileSync(traces, "utf8").split(/\r?\n/).filter(Boolean)
  .map(JSON.parse).filter((row) => row.step === 0 && !row.error);
assert.equal(stepRows.length, 2);
assert.ok(stepRows.every((row) => row.transition_count === 1));
const serial = fs.readFileSync(path.join(repo, "target", "world-model-hybrid-inference-cache-512m-0000-serial.log"), "utf8");
assert.match(serial, /prefaulted and cached local model mapping/);
assert.match(serial, /reused local model mapping/);
console.log("PASS\tfirst inference prefaults and caches the checkpoint mapping");
console.log("PASS\tsecond inference reuses the mapping and emits a transition");
console.log("2/2 checks passed");
