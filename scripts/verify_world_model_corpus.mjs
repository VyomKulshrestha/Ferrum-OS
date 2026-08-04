#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TOOL_NAMES } from "./audit_world_model_dataset.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(repo, "target", "world_model_controlled_corpus_verify.jsonl");
execFileSync(process.execPath, [
  path.join(repo, "scripts", "generate_world_model_hybrid_corpus.mjs"),
  "--count", "410", "--seed", "99", "--mode", "controlled", "--out", output,
], { stdio: "pipe" });
const rows = fs.readFileSync(output, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
assert.equal(rows.length, 410);
const counts = Object.fromEntries(TOOL_NAMES.map((tool) => [tool, 0]));
for (const row of rows) {
  counts[row.expected_tool]++;
  assert.equal(row.responses.length, row.max_steps);
  assert.ok(row.responses.every((response) => response.tool === row.expected_tool));
}
assert.ok(Object.values(counts).every((count) => count === 10));

const filePaths = rows
  .flatMap((row) => row.responses)
  .filter((response) => ["write_file", "delete_file"].includes(response.tool))
  .map((response) => response.args.path)
  .filter((filePath) => filePath !== "/disk/heliox/config.json");
assert.ok(filePaths.every((filePath) => /^\/disk\/wm_pool_\d+\.txt$/.test(filePath)));
assert.ok(new Set(filePaths).size <= 64);

console.log("PASS\tcontrolled corpus balances all 41 canonical actions");
console.log("PASS\tevery multi-step scenario has a validated replay response per step");
console.log("PASS\tfilesystem mutations use a bounded 64-path pool");
console.log("3/3 checks passed");
