#!/usr/bin/env node
// A covered learned action must not replace the deterministic safety estimate.
// Inject a valid learned model that falsely predicts zero write_file delta and
// prove the combined gate still catches deterministic disk exhaustion.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(repo, "target");
const customDisk = path.join(target, "world-model-combined-gate-base.img");
const fillFile = path.join(target, "world-model-combined-gate-fill.bin");
const weightsFile = path.join(target, "world-model-combined-gate.bin");
const corpus = path.join(target, "world-model-combined-gate-corpus.jsonl");
const dataset = path.join(target, "world-model-combined-gate-dataset.jsonl");
const traces = path.join(target, "world-model-combined-gate-traces.jsonl");

function debugfs(command) {
  const result = spawnSync("wsl", ["debugfs", "-w", "-R", command, "target/world-model-combined-gate-base.img"], {
    cwd: repo, encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`debugfs ${JSON.stringify(command)} failed: ${result.stderr || result.stdout}`);
  }
}

function diskStats() {
  const result = spawnSync("wsl", ["debugfs", "-R", "stats", "target/world-model-combined-gate-base.img"], {
    cwd: repo, encoding: "utf8",
  });
  if (result.status !== 0) throw new Error(`debugfs stats failed: ${result.stderr || result.stdout}`);
  const number = (label) => {
    const match = result.stdout.match(new RegExp(`${label}:\\s+(\\d+)`));
    if (!match) throw new Error(`debugfs stats omitted ${label}`);
    return Number(match[1]);
  };
  return { total: number("Block count"), free: number("Free blocks"), size: number("Block size") };
}

function falseSafeWriteWeights() {
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
  header.writeBigUInt64LE(1n << 17n, 24); // write_file is valid learned coverage
  const body = Buffer.alloc((input * hidden + hidden + hidden * output + output) * 4);
  return Buffer.concat([header, body]);
}

try {
  fs.copyFileSync(path.join(target, "heliox-disk.img"), customDisk);
  const before = diskStats();
  const used = before.total - before.free;
  // Leave four blocks for the large fixture file's indirect-block metadata.
  const targetUsed = Math.floor(before.total * 0.95) - 6;
  assert.ok(targetUsed > used, "packaged disk is already too full for the combined-gate fixture");
  fs.writeFileSync(fillFile, Buffer.alloc((targetUsed - used) * before.size, 0x5a));
  fs.writeFileSync(weightsFile, falseSafeWriteWeights());
  debugfs("unlink /heliox/world/model_learned.bin");
  debugfs("write target/world-model-combined-gate.bin /heliox/world/model_learned.bin");
  debugfs("write target/world-model-combined-gate-fill.bin /combined-gate-fill.bin");

  const afterFill = diskStats();
  const usedFraction = (afterFill.total - afterFill.free) / afterFill.total;
  assert.ok(usedFraction > 0.949 && usedFraction <= 0.95, `unexpected fixture usage ${usedFraction}`);
  fs.writeFileSync(corpus, `${JSON.stringify({
    id: "combined-gate-false-safe-learned",
    prompt: "Write a small file near the disk capacity threshold.",
    expected_tool: "write_file",
    max_steps: 1,
    responses: [{ tool: "write_file", args: { path: "/disk/combined-gate.txt", content: "safe-at-h1" } }],
  })}\n`);

  const result = spawnSync(process.execPath, [
    path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
    "--appliance-disk", customDisk,
    "--corpus", corpus, "--out", dataset, "--traces", traces,
    "--ram", "512", "--scenarios-per-boot", "1",
    "--rpc-timeout-ms", "120000", "--run-id", "combined-gate", "--accel", "auto",
  ], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  assert.equal(result.status, 0, "combined-gate probe should complete normally");

  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].executed, false);
  assert.ok(rows[0].risk >= 0.8);
  const serial = fs.readFileSync(
    path.join(target, "world-model-hybrid-combined-gate-512m-0000-serial.log"), "utf8",
  );
  assert.match(serial, /loaded learned transition model .*coverage=0x20000/);
  assert.match(serial, /predicted disk usage > 95%/);
  assert.match(serial, /lookahead_steps=\d+/);

  console.log("PASS\tvalid learned write_file weights loaded and predicted a false-safe zero delta");
  console.log("PASS\tdeterministic estimate remained active and blocked disk exhaustion");
  console.log("PASS\tcombined gate prevented execution before the real write");
  console.log("3/3 checks passed");
} finally {
  for (const file of [customDisk, fillFile, weightsFile]) fs.rmSync(file, { force: true });
}
