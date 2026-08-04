#!/usr/bin/env node
// Validate a persisted model-generated response corpus before any QEMU action
// is executed. This is stricter than transport parsing: every scenario, step,
// target tool, argument schema, provenance record, and ID must be complete.
import fs from "node:fs";
import path from "node:path";
import { validateArguments } from "./prefetch_world_model_responses.mjs";

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const corpus = path.resolve(arg("--corpus", "target/world_model_hybrid_prefetched.jsonl"));
const minScenarios = Math.max(1, Number(arg("--min-scenarios", "1")));
const rows = fs.readFileSync(corpus, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
if (rows.length < minScenarios) throw new Error(`only ${rows.length} scenarios; require ${minScenarios}`);
const ids = new Set();
let responses = 0;
const models = new Set();
for (const [index, row] of rows.entries()) {
  const id = String(row.id || "");
  if (!id || ids.has(id)) throw new Error(`row ${index} has a missing or duplicate id`);
  ids.add(id);
  if (!row.response_prefetch?.provider || !row.response_prefetch?.model) {
    throw new Error(`${id} lacks response_prefetch provenance`);
  }
  models.add(`${row.response_prefetch.provider}:${row.response_prefetch.model}`);
  const steps = Math.max(1, Number(row.max_steps || 1));
  if (!Array.isArray(row.responses) || row.responses.length !== steps) {
    throw new Error(`${id} has ${row.responses?.length || 0} responses for ${steps} steps`);
  }
  for (const response of row.responses) {
    if (row.expected_tool && response.tool !== row.expected_tool) {
      throw new Error(`${id} returned ${response.tool}; expected ${row.expected_tool}`);
    }
    if (!response.args || typeof response.args !== "object" || Array.isArray(response.args)) {
      throw new Error(`${id} response args must be an object`);
    }
    validateArguments(response.tool, response.args);
    responses++;
  }
}
console.log(`PASS\t${rows.length} unique scenarios contain ${responses} schema-valid targeted responses`);
console.log(`PASS\tprovenance retained for ${[...models].sort().join(", ")}`);
console.log("2/2 checks passed");
