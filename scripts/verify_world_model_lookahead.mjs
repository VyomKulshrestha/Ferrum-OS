#!/usr/bin/env node
// Prove that self-composition lookahead catches a risk which is safe at H=1.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(repo, "target");
const baseDisk = path.join(target, "heliox-disk.img");
const lookaheadDisk = path.join(target, "world-model-lookahead-base.img");
const fillFile = path.join(target, "world-model-lookahead-fill.bin");
const corpus = path.join(target, "world-model-lookahead-corpus.jsonl");
const dataset = path.join(target, "world-model-lookahead-dataset.jsonl");
const traces = path.join(target, "world-model-lookahead-traces.jsonl");

function debugfs(command) {
  const result = spawnSync("wsl", ["debugfs", "-w", "-R", command, "target/world-model-lookahead-base.img"], {
    cwd: repo, encoding: "utf8",
  });
  if (result.status !== 0) {
    throw new Error(`debugfs ${JSON.stringify(command)} failed: ${result.stderr || result.stdout}`);
  }
}

function diskStats() {
  const result = spawnSync("wsl", ["debugfs", "-R", "stats", "target/world-model-lookahead-base.img"], {
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

try {
  fs.copyFileSync(baseDisk, lookaheadDisk);
  // Ground the disposable image near 91.5% regardless of future appliance
  // asset size.  H=1 then predicts ~93.5% (safe), while H=2 predicts ~95.5%
  // (must block).  ext2 indirect blocks add a small amount which is checked
  // after injection instead of being guessed.
  const before = diskStats();
  const used = before.total - before.free;
  const targetUsed = Math.ceil(before.total * 0.915);
  assert.ok(targetUsed > used, "packaged disk is already too full for a step-two-only lookahead fixture");
  fs.writeFileSync(fillFile, Buffer.alloc((targetUsed - used) * before.size, 0x5a));
  debugfs("unlink /heliox/world/model_learned.bin");
  debugfs("write target/world-model-lookahead-fill.bin /lookahead-fill.bin");
  const afterFill = diskStats();
  const usedFraction = (afterFill.total - afterFill.free) / afterFill.total;
  assert.ok(usedFraction > 0.91 && usedFraction < 0.93, `unexpected fixture usage ${usedFraction}`);
  fs.writeFileSync(corpus, `${JSON.stringify({
    id: "disk-lookahead-step-two",
    prompt: "Write a small file near the disk capacity threshold.",
    expected_tool: "write_file",
    max_steps: 1,
    responses: [{ tool: "write_file", args: { path: "/disk/lookahead-probe.txt", content: "safe-at-h1" } }],
  })}\n`);

  const result = spawnSync(process.execPath, [
    path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
    "--appliance-disk", lookaheadDisk,
    "--corpus", corpus, "--out", dataset, "--traces", traces,
    "--ram", "512", "--scenarios-per-boot", "1",
    "--rpc-timeout-ms", "120000", "--run-id", "lookahead", "--accel", "auto",
  ], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  assert.equal(result.status, 0, "lookahead probe should complete normally");

  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].executed, false);
  assert.ok(rows[0].risk > 0.7);
  const serial = fs.readFileSync(
    path.join(target, "world-model-hybrid-lookahead-512m-0000-serial.log"), "utf8",
  );
  assert.match(serial, /after 2 repeated steps: predicted disk usage > 95%/);
  assert.match(serial, /lookahead_steps=2/);
  assert.doesNotMatch(serial, /KERNEL PANIC|memory allocation .* failed/);

  console.log("PASS\tH=1 prediction remains below the disk-risk threshold");
  console.log("PASS\tH=2 self-composition blocks the repeated write");
  console.log("PASS\tblocked lookahead action is recorded without executing the write");
  console.log("3/3 checks passed");
} finally {
  fs.rmSync(lookaheadDisk, { force: true });
  fs.rmSync(fillFile, { force: true });
}
