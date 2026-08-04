#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { reconcileWorldModelDataset } from "./lib/world_model_reconcile.mjs";

const root = fs.mkdtempSync(path.join(os.tmpdir(), "ferrumos-wm-reconcile-"));
const dataset = path.join(root, "dataset.jsonl");
const traces = path.join(root, "traces.jsonl");
const row = (episode_id, step, marker) => ({
  episode_id, step, transition_in_step: 0, marker,
});

try {
  fs.writeFileSync(dataset, [
    row("recovered", 0, "orphan-old-run"),
    row("recovered", 0, "complete-step-0"),
    row("recovered", 1, "complete-step-1"),
    row("incomplete", 0, "never-committed"),
    row("exact", 0, "exact-step-0"),
  ].map(JSON.stringify).join("\n") + "\n");
  fs.writeFileSync(traces, [
    { episode_id: "recovered", completed: true, transition_count: 2 },
    { episode_id: "incomplete", completed: false, transition_count: 1 },
    { episode_id: "exact", completed: true, transition_count: 1 },
  ].map(JSON.stringify).join("\n") + "\n");

  const report = reconcileWorldModelDataset(dataset, traces);
  const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
  assert.deepEqual(rows.map((item) => item.marker), [
    "complete-step-0", "complete-step-1", "exact-step-0",
  ]);
  assert.equal(report.dropped_orphan_rows, 2);
  assert.equal(report.recovered_episodes, 1);
  console.log("PASS\tcomplete suffix replaces an older interrupted episode attempt");
  console.log("PASS\trows without a completion marker are discarded before resume");
  console.log("PASS\texactly committed episodes remain unchanged and ordered");
  console.log("3/3 checks passed");
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
