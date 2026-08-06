#!/usr/bin/env node
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "ferrumos-hud-bounds-"));
const corpus = path.join(temp, "corpus.jsonl");
const dataset = path.join(temp, "dataset.jsonl");
const traces = path.join(temp, "traces.jsonl");
const runId = `hud-bounds-verify-${process.pid}`;
const serial = path.join(repo, "target", `world-model-hybrid-${runId}-512m-0000-serial.log`);

try {
  execFileSync(process.execPath, [
    path.join(repo, "scripts", "generate_world_model_hybrid_corpus.mjs"),
    "--count", "12", "--offset", "120000", "--seed", "20260806",
    "--mode", "controlled", "--only-tool", "hud_update", "--out", corpus,
  ], { cwd: repo, stdio: "pipe" });
  execFileSync(process.execPath, [
    path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
    "--corpus", corpus, "--out", dataset, "--traces", traces,
    "--ram", "512", "--scenarios-per-boot", "12", "--run-id", runId,
    "--rpc-timeout-ms", "30000",
  ], { cwd: repo, stdio: "pipe", timeout: 180_000 });

  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  const traceRows = fs.readFileSync(traces, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  const finalEpisodes = traceRows.filter((row) => row.step === undefined);
  assert.equal(rows.length, 12);
  assert.equal(new Set(rows.map((row) => row.episode_id)).size, 12);
  assert.ok(rows.every((row) => row.action === 29 && row.executed && row.success));
  assert.equal(new Set(rows.map((row) => row.action_features[1])).size, 12);
  assert.ok(finalEpisodes.every((row) => row.completed && !row.failed && row.transition_count === 1));

  const serialText = fs.readFileSync(serial, "utf8");
  assert.doesNotMatch(serialText, /KERNEL PANIC|panicked at|userspace fault|page fault/i);
  assert.match(serialText, /world-model-dataset-v2/);
  console.log("PASS\t12 HUD payload regimes execute and emit one transition each");
  console.log("PASS\tzero, boundary, and over-clamp suggestion lengths remain distinct model inputs");
  console.log("PASS\tfull-width HUD suggestions do not panic or fault the guest");
  console.log("3/3 checks passed");
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
  fs.rmSync(serial, { force: true });
}
