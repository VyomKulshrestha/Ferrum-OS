#!/usr/bin/env node
// Proves the disk-utilization feature in the runtime state embedding comes
// from the mounted ext2 superblock rather than the former top-level file-count
// proxy. The collector exercises the real kernel query and ring-3 encoder.
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "world-model-observation-corpus.jsonl");
const dataset = path.join(repo, "target", "world-model-observation-dataset.jsonl");
const traces = path.join(repo, "target", "world-model-observation-traces.jsonl");
const image = path.join(repo, "target", "heliox-disk.img");

fs.writeFileSync(corpus, `${JSON.stringify({
  id: "disk-observation",
  prompt: "Yield the CPU after observing persistent disk usage.",
  expected_tool: "yield_cpu",
  max_steps: 1,
  responses: [{ tool: "yield_cpu", args: {} }],
})}\n`);

const collector = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--max-scenarios", "1",
  "--scenarios-per-boot", "1",
  "--accel", "auto",
], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
if (collector.stdout) process.stdout.write(collector.stdout);
if (collector.stderr) process.stderr.write(collector.stderr);
assert.equal(collector.status, 0, "one-step observation collection must succeed");

const row = JSON.parse(fs.readFileSync(dataset, "utf8").trim());
const observed = row.before[3];
assert.ok(Number.isFinite(observed) && observed > 0 && observed < 1,
  `disk feature must be a finite utilization fraction, got ${observed}`);
assert.equal(row.after[3], observed, "yield_cpu must not alter persistent disk utilization");

// WSL inherits this process's repository cwd, so a slash-normalized relative
// path resolves on the mounted Windows drive. Passing a raw `C:\\...` path
// would instead be interpreted as a Linux filename.
const wslImage = path.relative(repo, image).replaceAll("\\", "/");
const header = execFileSync("wsl.exe", ["dumpe2fs", "-h", wslImage], {
  cwd: repo,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "ignore"],
});
const field = (name) => Number(header.match(new RegExp(`^${name}:\\s+(\\d+)$`, "m"))?.[1]);
const blocks = field("Block count");
const free = field("Free blocks");
assert.ok(blocks > 0 && free >= 0 && free < blocks, "dumpe2fs must expose valid block counts");
const imageFraction = (blocks - free) / blocks;

// The disposable guest writes its config after copying the image, which can
// allocate a small number of extra blocks. A 0.5% bound allows that mutation
// but is far too tight for the old file-count heuristic to pass accidentally.
assert.ok(Math.abs(observed - imageFraction) < 0.005,
  `runtime ${observed} must match ext2 superblock ${imageFraction}`);

console.log(`PASS\truntime disk fraction ${observed.toFixed(6)} matches ext2 ${imageFraction.toFixed(6)}`);
console.log("PASS\tnon-storage action leaves observed disk utilization unchanged");
console.log("2/2 checks passed");
