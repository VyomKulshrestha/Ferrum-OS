#!/usr/bin/env node
// Normalize observation semantics before combining historical and current
// corpora. Legacy rows used before[3]/after[3] for a top-level file-count
// heuristic; current rows use the ext2 allocated-block fraction. Those values
// must never share one training feature without an explicit migration.
import fs from "node:fs";
import path from "node:path";

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

const input = path.resolve(arg("--input", "target/world_model_dataset_release.jsonl"));
const output = path.resolve(arg("--out", "target/world_model_dataset_normalized.jsonl"));
if (input === output) throw new Error("--input and --out must differ");
const rows = fs.readFileSync(input, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
let current = 0;
let masked = 0;
const normalized = rows.map((row, index) => {
  if (!Array.isArray(row.before) || !Array.isArray(row.after)
      || row.before.length !== 128 || row.after.length !== 128) {
    throw new Error(`row ${index} must contain 128-float before/after embeddings`);
  }
  const isCurrent = row.observation_schema === "ext2-usage-v1" || row.source === "hybrid";
  if (isCurrent) {
    current++;
    return { ...row, observation_schema: "ext2-usage-v1" };
  }
  const before = [...row.before];
  const after = [...row.after];
  before[3] = 0;
  after[3] = 0;
  masked++;
  return {
    ...row,
    before,
    after,
    observation_schema: "legacy-disk-masked-v1",
    masked_features: [...new Set([...(row.masked_features || []), 3])].sort((a, b) => a - b),
  };
});
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, `${normalized.map(JSON.stringify).join("\n")}\n`);
console.log(`normalized ${normalized.length} rows: ${current} ext2-current, ${masked} legacy disk features masked`);
