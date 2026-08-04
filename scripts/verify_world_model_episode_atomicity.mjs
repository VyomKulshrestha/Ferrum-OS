#!/usr/bin/env node
// A failed second step must not leave the first step in the training dataset;
// the whole episode will be retried from a fresh disposable boot.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "episode-atomicity-corpus.jsonl");
const dataset = path.join(repo, "target", "episode-atomicity-dataset.jsonl");
const traces = path.join(repo, "target", "episode-atomicity-traces.jsonl");
fs.writeFileSync(corpus, `${JSON.stringify({
  id: "episode-atomicity",
  prompt: "Complete a two-step atomic collection probe.",
  expected_tool: null,
  max_steps: 2,
  responses: [
    { tool: "yield_cpu", args: {} },
    { tool: "local_inference", args: { prompt: "atomicity", max_tokens: 1 } },
  ],
})}\n`);
const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--scenarios-per-boot", "1",
  "--rpc-timeout-ms", "30000",
  "--run-id", "atomicity",
  "--accel", "auto",
], { cwd: repo, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.notEqual(result.status, 0, "second-step timeout must fail the episode");
const datasetRows = fs.existsSync(dataset)
  ? fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean)
  : [];
assert.equal(datasetRows.length, 0, "partial episode transitions must not enter training data");
const traceRows = fs.readFileSync(traces, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
assert.ok(traceRows.some((row) => row.step === 0 && row.transition_count === 1));
assert.ok(traceRows.some((row) => row.step === 1 && row.error));
console.log("PASS\tcompleted step remains visible in the diagnostic trace");
console.log("PASS\tfailed multi-step episode publishes zero training transitions");
console.log("2/2 checks passed");
