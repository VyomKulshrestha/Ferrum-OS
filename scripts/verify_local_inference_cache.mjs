#!/usr/bin/env node
// A mixed-workload local-inference soak in one 512 MiB guest: the first model
// call may page in the checkpoint, while later calls must reuse that exact
// mapping without fragmenting/exhausting the daemon heap.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "local-inference-cache-corpus.jsonl");
const dataset = path.join(repo, "target", "local-inference-cache-dataset.jsonl");
const traces = path.join(repo, "target", "local-inference-cache-traces.jsonl");
const scenarios = [];
for (let index = 0; index < 49; index += 1) {
  const inference = index % 16 === 0;
  scenarios.push({
    id: `local-inference-cache-${index}`,
    prompt: inference
      ? `Run a one-token local inference cache probe ${index}.`
      : `Yield during local inference heap soak ${index}.`,
    expected_tool: inference ? "local_inference" : "yield_cpu",
    max_steps: 1,
    responses: [{
      tool: inference ? "local_inference" : "yield_cpu",
      args: inference ? { prompt: `cache probe ${index}`, max_tokens: 1 } : {},
    }],
  });
}
fs.writeFileSync(corpus, `${scenarios.map(JSON.stringify).join("\n")}\n`);
const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--scenarios-per-boot", String(scenarios.length),
  "--rpc-timeout-ms", "600000",
  "--run-id", "inference-cache",
  "--accel", "auto",
], { cwd: repo, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.equal(result.status, 0, "the mixed local-inference soak must complete");
const stepRows = fs.readFileSync(traces, "utf8").split(/\r?\n/).filter(Boolean)
  .map(JSON.parse).filter((row) => row.step === 0 && !row.error);
assert.equal(stepRows.length, scenarios.length);
assert.ok(stepRows.every((row) => row.transition_count === 1));
const serial = fs.readFileSync(path.join(repo, "target", "world-model-hybrid-inference-cache-512m-0000-serial.log"), "utf8");
assert.match(serial, /prefaulted and cached local model mapping/);
assert.equal((serial.match(/reused local model mapping/g) ?? []).length, 3);
assert.match(serial, /parsed and cached local tokenizer/);
assert.equal((serial.match(/reused local tokenizer/g) ?? []).length, 3);
assert.doesNotMatch(serial, /KERNEL PANIC|memory allocation .* failed/);
console.log("PASS\tfirst inference prefaults and caches the checkpoint mapping");
console.log("PASS\tthree later inferences reuse the model mapping and parsed tokenizer");
console.log("PASS\t512 MiB mixed-workload soak completes without heap exhaustion");
console.log("3/3 checks passed");
