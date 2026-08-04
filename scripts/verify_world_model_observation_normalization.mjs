#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const input = path.join(repo, "target", "observation-normalization-fixture.jsonl");
const output = path.join(repo, "target", "observation-normalization-output.jsonl");
const embedding = (disk) => Array.from({ length: 128 }, (_, index) => index === 3 ? disk : 0);
fs.writeFileSync(input, [
  { source: "synthetic-recovered-arguments", before: embedding(0.25), after: embedding(0.5) },
  { source: "hybrid", before: embedding(0.602), after: embedding(0.603) },
].map(JSON.stringify).join("\n") + "\n");
const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "normalize_world_model_observations.mjs"),
  "--input", input,
  "--out", output,
], { cwd: repo, encoding: "utf8" });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.equal(result.status, 0);
const [legacy, current] = fs.readFileSync(output, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
assert.equal(legacy.before[3], 0);
assert.equal(legacy.after[3], 0);
assert.deepEqual(legacy.masked_features, [3]);
assert.equal(legacy.observation_schema, "legacy-disk-masked-v1");
assert.equal(current.before[3], 0.602);
assert.equal(current.after[3], 0.603);
assert.equal(current.observation_schema, "ext2-usage-v1");
console.log("PASS\tlegacy file-count disk feature is masked explicitly");
console.log("PASS\tcurrent ext2 utilization telemetry is preserved exactly");
console.log("2/2 checks passed");
