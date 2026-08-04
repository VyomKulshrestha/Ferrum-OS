#!/usr/bin/env node
import path from "node:path";
import { reconcileWorldModelDataset } from "./lib/world_model_reconcile.mjs";

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const dataset = path.resolve(arg("--dataset", "target/world_model_hybrid_dataset.jsonl"));
const traces = path.resolve(arg("--traces", "target/world_model_hybrid_traces.jsonl"));
const output = path.resolve(arg("--out", dataset));
const report = reconcileWorldModelDataset(dataset, traces, output);
console.log(JSON.stringify(report, null, 2));
console.log(`PASS\treconciled dataset written to ${output}`);
