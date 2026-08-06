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
  "--count", "410", "--offset", "2000", "--seed", "99", "--mode", "controlled", "--out", output,
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
assert.equal(rows[0].id, "hybrid-002000");
assert.equal(rows.at(-1).id, "hybrid-002409");

for (const tool of ["read_dir", "mouse_click", "browse_url"]) {
  const signatures = new Set(rows
    .flatMap((row) => row.responses)
    .filter((response) => response.tool === tool)
    .map((response) => JSON.stringify(response.args)));
  assert.ok(signatures.size >= 3, `${tool} only produced ${signatures.size} argument variants`);
}

const filePaths = rows
  .flatMap((row) => row.responses)
  .filter((response) => ["write_file", "delete_file"].includes(response.tool))
  .map((response) => response.args.path)
  .filter((filePath) => filePath !== "/disk/heliox/config.json");
assert.ok(filePaths.every((filePath) => /^\/disk\/wm_pool_\d+\.txt$/.test(filePath)));
assert.ok(new Set(filePaths).size <= 64);

const hudOutput = path.join(repo, "target", "world_model_hud_boundary_corpus_verify.jsonl");
execFileSync(process.execPath, [
  path.join(repo, "scripts", "generate_world_model_hybrid_corpus.mjs"),
  "--count", "24", "--offset", "8000", "--seed", "99", "--mode", "controlled",
  "--only-tool", "hud_update", "--out", hudOutput,
], { stdio: "pipe" });
const hudRows = fs.readFileSync(hudOutput, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const hudLengths = new Set(hudRows.map((row) => row.responses[0].args.suggestion.length));
assert.equal(hudRows.length, 24);
assert.deepEqual([...hudLengths].sort((a, b) => a - b), [0, 1, 8, 32, 64, 96, 127, 128, 160, 256, 512, 1024]);
assert.ok(hudRows.every((row) => row.max_steps === 1 && row.expected_tool === "hud_update"));

console.log("PASS\tcontrolled corpus balances all 41 canonical actions");
console.log("PASS\tevery multi-step scenario has a validated replay response per step");
console.log("PASS\tfilesystem mutations use a bounded 64-path pool");
console.log("PASS\toffset IDs and argument-bearing tools produce distinct supplemental data");
console.log("PASS\tHUD boundary corpus spans zero through 1,024-byte suggestions around the 128-byte render clamp");
console.log("5/5 checks passed");
