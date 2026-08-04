#!/usr/bin/env node
// Regression for the HTTP client descriptor leak: the kernel socket table is
// intentionally small enough that descriptor reuse alone hid a second leak:
// closed smoltcp handles retained 32 KiB of buffers until about request 240.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "http_socket_lifecycle_corpus.jsonl");
const dataset = path.join(repo, "target", "http_socket_lifecycle_dataset.jsonl");
const traces = path.join(repo, "target", "http_socket_lifecycle_traces.jsonl");
const requestCount = 300;
const rows = Array.from({ length: requestCount }, (_, index) => ({
  id: `socket-lifecycle-${String(index).padStart(3, "0")}`,
  prompt: `Yield the CPU for socket lifecycle request ${index}.`,
  expected_tool: "yield_cpu",
  max_steps: 1,
  tags: ["socket-lifecycle", "stress"],
  responses: [{ tool: "yield_cpu", args: {} }],
}));
fs.writeFileSync(corpus, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--scenarios-per-boot", String(requestCount),
  "--accel", "auto",
], { cwd: repo, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.equal(result.status, 0, "collector process must complete successfully");
const transitions = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
assert.equal(transitions.length, requestCount);
assert.ok(transitions.every((row) => row.actual_tool === "yield_cpu" && row.executed));
// The first request initializes persistent OS caches. Measure retained growth
// after that warmup so the assertion targets the old per-connection leak.
const postWarmupHeapGrowth = transitions.at(-1).before[1] - transitions[1].before[1];
assert.ok(
  postWarmupHeapGrowth < 0.05,
  `post-warmup kernel heap grew by ${(postWarmupHeapGrowth * 100).toFixed(1)} percentage points`,
);
const traceText = fs.readFileSync(traces, "utf8");
assert.doesNotMatch(traceText, /sys_socket failed|LLM query failed|"failed":true/);

console.log("PASS\t300 sequential provider requests release descriptors and smoltcp buffers");
console.log("PASS\tevery request produced one executed world-model transition");
console.log("PASS\tkernel heap growth stays bounded across the long-lived connection soak");
console.log("3/3 checks passed");
