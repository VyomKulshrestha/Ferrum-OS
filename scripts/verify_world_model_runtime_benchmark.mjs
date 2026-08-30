#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const reportPath = path.resolve(process.argv[2] || path.join(repo, "docs", "research", "world_model_runtime_benchmark.json"));
const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
assert.ok(["in-guest-world-model-runtime-benchmark-v2", "in-guest-world-model-runtime-benchmark-v3"].includes(report.protocol));
assert.equal(report.warmup_previews, 64);
assert.deepEqual(report.horizons.map((row) => row.horizon), [1, 2, 3, 4, 5]);
assert.ok(report.horizons.every((row) => row.iterations === report.iterations_per_horizon));
assert.ok(report.horizons.every((row) => row.p95_cycles >= row.median_cycles && row.max_cycles >= row.p95_cycles));
assert.ok(report.horizons.every((row) => row.p95_microseconds >= row.median_microseconds));
if (report.protocol.endsWith("v3")) {
  assert.ok(report.horizons.every((row) => row.p99_cycles >= row.p95_cycles && row.max_cycles >= row.p99_cycles));
  assert.ok(report.horizons.every((row) => row.p99_microseconds >= row.p95_microseconds));
  assert.equal(report.authority_disabled, true);
  assert.equal(report.packaged_source_disk.unchanged, true);
}
assert.equal(report.memory.runtime_parameters, 193229);
assert.ok(report.memory.encoder_loaded && report.memory.transition_loaded);
assert.ok(report.model_load.cycles > 0);
assert.equal(report.model_load.pit_elapsed_microseconds, report.model_load.pit_ticks * 1000);
assert.ok(report.model_load.encoder_loaded && report.model_load.transition_loaded);
assert.ok(Array.isArray(report.limitations) && report.limitations.length >= 3);
console.log("PASS\tbenchmark contains H=1..5 median/p95 measurements and p99 when registered");
console.log("PASS\tmodel load time, memory/load state, and parameter count are recorded");
console.log("PASS\tvirtualization and scope limitations are explicit");
console.log("3/3 checks passed");
