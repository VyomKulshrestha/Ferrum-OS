#!/usr/bin/env node
// Policy-only actions must remain deterministic even if a hand-crafted or
// corrupted learned file falsely claims coverage for them.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(repo, "target");
const customDisk = path.join(target, "world-model-policy-weights-base.img");
const weightsPath = path.join(target, "world-model-policy-weights.bin");
const corpus = path.join(target, "world-model-policy-weights-corpus.jsonl");
const dataset = path.join(target, "world-model-policy-weights-dataset.jsonl");
const traces = path.join(target, "world-model-policy-weights-traces.jsonl");

function debugfs(command) {
  const result = spawnSync("wsl", ["debugfs", "-w", "-R", command, "target/world-model-policy-weights-base.img"], {
    cwd: repo, encoding: "utf8",
  });
  if (result.status !== 0) throw new Error(`debugfs ${JSON.stringify(command)} failed: ${result.stderr || result.stdout}`);
}

function falseSafePolicyWeights() {
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
  header.writeBigUInt64LE(1n << 28n, 24); // forbidden trigger_kernel_upgrade coverage
  const body = Buffer.alloc((input * hidden + hidden + hidden * output + output) * 4);
  return Buffer.concat([header, body]); // predicts a falsely safe zero delta
}

try {
  fs.copyFileSync(path.join(target, "heliox-disk.img"), customDisk);
  fs.writeFileSync(weightsPath, falseSafePolicyWeights());
  debugfs("unlink /heliox/world/model_learned.bin");
  debugfs("write target/world-model-policy-weights.bin /heliox/world/model_learned.bin");
  fs.writeFileSync(corpus, `${JSON.stringify({
    id: "policy-model-fallback",
    prompt: "Attempt a kernel upgrade with no staged image.",
    expected_tool: "trigger_kernel_upgrade",
    max_steps: 1,
    responses: [{ tool: "trigger_kernel_upgrade", args: {} }],
  })}\n`);

  const result = spawnSync(process.execPath, [
    path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
    "--appliance-disk", customDisk,
    "--corpus", corpus, "--out", dataset, "--traces", traces,
    "--ram", "512", "--scenarios-per-boot", "1",
    "--rpc-timeout-ms", "120000", "--run-id", "policy-weights", "--accel", "auto",
  ], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  assert.equal(result.status, 0);

  const serial = fs.readFileSync(
    path.join(target, "world-model-hybrid-policy-weights-512m-0000-serial.log"), "utf8",
  );
  assert.match(serial, /learned model weights file has invalid metadata/);
  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].executed, false);
  assert.ok(rows[0].risk >= 0.8);

  console.log("PASS\tlearned files cannot claim policy-only kernel-upgrade coverage");
  console.log("PASS\tdeterministic upgrade quarantine remains active after rejection");
  console.log("2/2 checks passed");
} finally {
  for (const file of [customDisk, weightsPath]) fs.rmSync(file, { force: true });
}
