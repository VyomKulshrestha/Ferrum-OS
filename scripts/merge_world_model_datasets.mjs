#!/usr/bin/env node
// Merge append-only transition corpora without silently duplicating episodes or
// accepting conflicting ground-truth rows.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { auditRows } from "./audit_world_model_dataset.mjs";

function rowKey(row, index, sourceFile) {
  if (row.episode_id != null) {
    return [
      row.source || "unspecified",
      row.episode_id,
      row.step ?? 0,
      row.transition_in_step ?? 0,
      row.ram_mb ?? "unknown",
      row.action,
    ].join("|");
  }
  return `legacy|${sourceFile}|${index}`;
}

export function mergeDatasets(inputs) {
  const merged = [];
  const seen = new Map();
  let duplicateRows = 0;
  for (const input of inputs) {
    const rows = fs.readFileSync(input, "utf8").split(/\r?\n/).filter((line) => line.trim());
    rows.forEach((line, index) => {
      const row = JSON.parse(line);
      const key = rowKey(row, index, input);
      const canonical = JSON.stringify(row);
      if (seen.has(key)) {
        if (seen.get(key) !== canonical) throw new Error(`conflicting transition for ${key}`);
        duplicateRows++;
        return;
      }
      seen.set(key, canonical);
      merged.push(row);
    });
  }
  return { rows: merged, duplicateRows };
}

function values(name) {
  const result = [];
  for (let index = 0; index < process.argv.length; index++) {
    if (process.argv[index] === name && process.argv[index + 1]) result.push(process.argv[index + 1]);
  }
  return result;
}

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function main() {
  const inputs = values("--input").map((input) => path.resolve(input));
  if (inputs.length < 2) throw new Error("provide at least two --input PATH arguments");
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const output = path.resolve(arg("--out", path.join(repo, "target", "world_model_dataset_merged.jsonl")));
  if (inputs.includes(output)) throw new Error("--out must not overwrite an input dataset");
  const { rows, duplicateRows } = mergeDatasets(inputs);
  const audit = auditRows(rows, {
    requiredTools: 0,
    minExecutedPerTool: 1,
    minArgumentVariants: 1,
    minEpisodes: 0,
    minMultistepEpisodes: 0,
    minRamProfiles: 0,
  });
  if (audit.errors.length > 0) throw new Error(`merged dataset failed schema audit: ${audit.errors[0]}`);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
  console.log(`merged ${inputs.length} datasets into ${rows.length} unique rows (${duplicateRows} exact duplicates removed)`);
  console.log(`wrote ${output}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { main(); }
  catch (error) {
    console.error(`[merge] ${error?.stack || error}`);
    process.exitCode = 1;
  }
}
