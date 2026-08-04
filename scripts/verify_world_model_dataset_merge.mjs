#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { mergeDatasets } from "./merge_world_model_datasets.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const first = path.join(repo, "target", "world_model_merge_verify_a.jsonl");
const second = path.join(repo, "target", "world_model_merge_verify_b.jsonl");
const base = {
  source: "merge-test", episode_id: "episode-a", step: 0, transition_in_step: 0,
  ram_mb: 512, action: 0, action_features: Array(16).fill(0),
  before: Array(128).fill(0), after: Array(128).fill(0), executed: true,
};
const next = { ...base, episode_id: "episode-b", action: 1 };
fs.writeFileSync(first, `${JSON.stringify(base)}\n`);
fs.writeFileSync(second, `${JSON.stringify(base)}\n${JSON.stringify(next)}\n`);
const merged = mergeDatasets([first, second]);
assert.equal(merged.rows.length, 2);
assert.equal(merged.duplicateRows, 1);

fs.writeFileSync(second, `${JSON.stringify({ ...base, reward: 1 })}\n`);
assert.throws(() => mergeDatasets([first, second]), /conflicting transition/);

console.log("PASS\tmerge removes exact duplicate transition rows");
console.log("PASS\tmerge rejects conflicting ground truth for the same transition key");
console.log("2/2 checks passed");
