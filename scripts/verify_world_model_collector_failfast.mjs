#!/usr/bin/env node
// An RPC timeout does not cancel work already running inside the guest. The
// collector must terminate that disposable boot immediately instead of racing
// a second scenario against the still-in-flight first request.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "collector-failfast-corpus.jsonl");
const dataset = path.join(repo, "target", "collector-failfast-dataset.jsonl");
const traces = path.join(repo, "target", "collector-failfast-traces.jsonl");
const scenarios = [0, 1].map((index) => ({
  id: `collector-failfast-${index}`,
  prompt: `Yield CPU in fail-fast scenario ${index}.`,
  expected_tool: "yield_cpu",
  max_steps: 1,
  responses: [{ tool: "yield_cpu", args: {} }],
}));
fs.writeFileSync(corpus, `${scenarios.map(JSON.stringify).join("\n")}\n`);

const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--scenarios-per-boot", "2",
  "--rpc-timeout-ms", "50",
  "--provider-delay-ms", "1000",
  "--run-id", "failfast",
  "--accel", "auto",
], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.notEqual(result.status, 0, "forced RPC timeout must fail the collection run");

const rows = fs.readFileSync(traces, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
assert.ok(rows.some((row) => row.episode_id === "collector-failfast-0-512m" && row.error),
  "first timed-out episode must be recorded");
assert.ok(!rows.some((row) => row.episode_id === "collector-failfast-1-512m"),
  "collector must not begin a second episode on the unsafe boot");
assert.match(`${result.stdout}\n${result.stderr}`, /in-flight RPC cannot be safely reused/);

console.log("PASS\tRPC timeout is persisted for resumable diagnosis");
console.log("PASS\tcollector kills the disposable boot before starting another episode");
console.log("2/2 checks passed");
