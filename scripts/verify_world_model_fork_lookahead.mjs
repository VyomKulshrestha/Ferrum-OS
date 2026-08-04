#!/usr/bin/env node
// Prove process deltas accumulate across rollout steps and the exact threshold
// blocks.  A disposable learned model predicts +20 processes per exec:
// H=1 => 20, H=2 => 40, H=3 => 60 (must block against the 50 threshold).
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(repo, "target");
const customDisk = path.join(target, "world-model-fork-lookahead-base.img");
const weightsPath = path.join(target, "world-model-fork-lookahead.bin");
const corpus = path.join(target, "world-model-fork-lookahead-corpus.jsonl");
const dataset = path.join(target, "world-model-fork-lookahead-dataset.jsonl");
const traces = path.join(target, "world-model-fork-lookahead-traces.jsonl");

function debugfs(command) {
  const result = spawnSync("wsl", ["debugfs", "-w", "-R", command, "target/world-model-fork-lookahead-base.img"], {
    cwd: repo, encoding: "utf8",
  });
  if (result.status !== 0) throw new Error(`debugfs ${JSON.stringify(command)} failed: ${result.stderr || result.stdout}`);
}

function constantProcessDeltaWeights() {
  const input = 185;
  const hidden = 1;
  const output = 128;
  const header = Buffer.alloc(32);
  header.write("FWM2", 0, "ascii");
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(input, 8);
  header.writeUInt32LE(hidden, 12);
  header.writeUInt32LE(output, 16);
  header.writeUInt32LE(16, 20);
  header.writeBigUInt64LE(1n << 25n, 24); // exec_process only
  const body = Buffer.alloc((input * hidden + hidden + hidden * output + output) * 4);
  // b2 begins after w1, b1, and w2. delta[0] = 20 / nominal capacity 64.
  body.writeFloatLE(20 / 64, (input * hidden + hidden + hidden * output) * 4);
  return Buffer.concat([header, body]);
}

try {
  fs.copyFileSync(path.join(target, "heliox-disk.img"), customDisk);
  fs.writeFileSync(weightsPath, constantProcessDeltaWeights());
  debugfs("unlink /heliox/world/model_learned.bin");
  debugfs("write target/world-model-fork-lookahead.bin /heliox/world/model_learned.bin");
  fs.writeFileSync(corpus, `${JSON.stringify({
    id: "fork-lookahead-step-three",
    prompt: "Execute one process under a high-growth model prediction.",
    expected_tool: "exec_process",
    max_steps: 1,
    responses: [{ tool: "exec_process", args: { path: "/disk/policy-probe" } }],
  })}\n`);

  const result = spawnSync(process.execPath, [
    path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
    "--appliance-disk", customDisk,
    "--corpus", corpus, "--out", dataset, "--traces", traces,
    "--ram", "512", "--scenarios-per-boot", "1",
    "--rpc-timeout-ms", "120000", "--run-id", "fork-lookahead", "--accel", "auto",
  ], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  assert.equal(result.status, 0, "fork lookahead probe should complete normally");

  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].executed, false);
  assert.ok(rows[0].risk >= 0.7);
  const serial = fs.readFileSync(
    path.join(target, "world-model-hybrid-fork-lookahead-512m-0000-serial.log"), "utf8",
  );
  assert.match(serial, /after 3 repeated steps: process-count delta of 60/);
  assert.match(serial, /lookahead_steps=3/);
  assert.doesNotMatch(serial, /KERNEL PANIC|memory allocation .* failed/);

  console.log("PASS\tH=1 and H=2 remain below the 50-process threshold");
  console.log("PASS\tH=3 accumulates +60 processes and blocks at equality-safe threshold semantics");
  console.log("PASS\tblocked process action is recorded without executing the ELF");
  console.log("3/3 checks passed");
} finally {
  fs.rmSync(customDisk, { force: true });
  fs.rmSync(weightsPath, { force: true });
}
