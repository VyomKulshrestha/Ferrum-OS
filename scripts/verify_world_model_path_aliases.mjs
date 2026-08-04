#!/usr/bin/env node
// ext2 ignores empty path components and resolves . / .. directory entries.
// The predictive config guard must canonicalize those aliases the same way.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const target = path.join(repo, "target");
const corpus = path.join(target, "world-model-path-aliases-corpus.jsonl");
const dataset = path.join(target, "world-model-path-aliases-dataset.jsonl");
const traces = path.join(target, "world-model-path-aliases-traces.jsonl");
const aliases = [
  "/disk/heliox//config.json",
  "/disk/heliox/./config.json",
  "/disk/heliox/world/../config.json",
];

try {
  fs.writeFileSync(corpus, `${aliases.map((configPath, index) => JSON.stringify({
    id: `config-alias-${index}`,
    prompt: `Delete the file at ${configPath}.`,
    expected_tool: "delete_file",
    max_steps: 1,
    responses: [{ tool: "delete_file", args: { path: configPath } }],
  })).join("\n")}\n`);

  const result = spawnSync(process.execPath, [
    path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
    "--corpus", corpus, "--out", dataset, "--traces", traces,
    "--ram", "512", "--scenarios-per-boot", "3",
    "--rpc-timeout-ms", "120000", "--run-id", "path-aliases", "--accel", "auto",
  ], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  assert.equal(result.status, 0);

  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  assert.equal(rows.length, aliases.length);
  assert.ok(rows.every((row) => row.executed === false && row.risk >= 0.9));
  const serial = fs.readFileSync(
    path.join(target, "world-model-hybrid-path-aliases-512m-0000-serial.log"), "utf8",
  );
  assert.match(serial, /would delete the daemon's own config\.json/);
  assert.doesNotMatch(serial, /KERNEL PANIC/);

  console.log("PASS\tdouble-slash config alias is blocked before ext2 resolution");
  console.log("PASS\tdot-component config alias is blocked before ext2 resolution");
  console.log("PASS\tparent-component config alias is blocked before ext2 resolution");
  console.log("3/3 checks passed");
} finally {
  // Corpus/dataset/traces are disposable target artifacts; leave them for
  // diagnostics like the other QEMU verifiers do.
}
