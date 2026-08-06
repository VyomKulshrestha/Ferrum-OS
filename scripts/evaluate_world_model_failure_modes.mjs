#!/usr/bin/env node
// Run the model-artifact failure matrix and persist a reviewable summary.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputArg = process.argv.indexOf("--json-out");
const output = path.resolve(repo, outputArg >= 0 ? process.argv[outputArg + 1] : "docs/research/world_model_failure_modes.json");
const cases = [
  { id: "valid_learned_artifacts", command: [process.execPath, "scripts/verify_world_model_learned.mjs"], injection: "none" },
  { id: "missing_artifacts", command: [process.execPath, "scripts/verify_world_model_missing_weights.mjs"], injection: "remove encoder and transition" },
  { id: "nonfinite_artifacts", command: [process.execPath, "scripts/verify_world_model_weight_integrity.mjs"], injection: "valid-shape NaN encoder and transition" },
  { id: "forbidden_coverage_metadata", command: [process.execPath, "scripts/verify_world_model_policy_weights.mjs"], injection: "transition claims policy-only kernel-upgrade coverage" },
  { id: "collapsed_jepa_trial", command: ["python", "scripts/verify_world_model_jepa_rejection.py"], injection: "constant-state representation" },
];

const results = [];
for (const test of cases) {
  console.log(`[failure-matrix] ${test.id}`);
  const [program, ...args] = test.command;
  const run = spawnSync(program, args, { cwd: repo, encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  if (run.stdout) process.stdout.write(run.stdout);
  if (run.stderr) process.stderr.write(run.stderr);
  const passLines = (run.stdout || "").split(/\r?\n/).filter((line) => line.startsWith("PASS"));
  results.push({
    id: test.id,
    injection: test.injection,
    command: [program === process.execPath ? "node" : program, ...args].join(" "),
    passed: run.status === 0,
    exit_code: run.status,
    checks: passLines.map((line) => line.replace(/^PASS\s+/, "")),
  });
  if (run.status !== 0) break;
}

const report = {
  schema_version: 1,
  environment: "FerrumOS disposable QEMU guests except collapsed_jepa_trial (host trainer rejection)",
  result: results.length === cases.length && results.every((entry) => entry.passed) ? "pass" : "fail",
  cases: results,
  safety_contract: [
    "A valid learned model loads and is exercised in the guest.",
    "Missing, non-finite, or forbidden-coverage learned artifacts cannot disable deterministic safety checks.",
    "A collapsed JEPA training run preserves metrics but emits no promotable artifacts.",
  ],
};
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
console.log(`[failure-matrix] wrote ${path.relative(repo, output)} (${report.result})`);
if (report.result !== "pass") process.exitCode = 1;
