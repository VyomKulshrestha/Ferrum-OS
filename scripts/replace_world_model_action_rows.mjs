#!/usr/bin/env node
// Replace every row for one canonical action with a freshly collected set.
// This is intended for syscall/tool ABI repairs where retaining historical
// outcomes would teach the transition model behavior that no longer exists.
import fs from "node:fs";
import path from "node:path";
import { TOOL_NAMES } from "./audit_world_model_dataset.mjs";

function arg(name, fallback = undefined) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

function readJsonl(file) {
  return fs.readFileSync(file, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line, index) => {
      try { return JSON.parse(line); }
      catch (error) { throw new Error(`${file}:${index + 1}: ${error.message}`); }
    });
}

export function replaceActionRows(baseRows, replacementRows, actionId) {
  if (!Number.isInteger(actionId) || actionId < 0 || actionId >= TOOL_NAMES.length) {
    throw new Error(`action must be an integer from 0 to ${TOOL_NAMES.length - 1}`);
  }
  if (replacementRows.length === 0) throw new Error("replacement dataset is empty");
  if (replacementRows.some((row) => row.action !== actionId)) {
    throw new Error("replacement dataset contains a different canonical action");
  }
  const selected = baseRows.filter((row) => row.action === actionId);
  if (selected.length === 0) throw new Error("base dataset has no rows for the selected action");
  // Splits and rollout evaluation are episode-atomic. If the repaired action
  // appeared in a multi-step episode, replace the whole episode rather than
  // silently leaving a truncated trajectory behind.
  const affectedEpisodes = new Set(selected.map((row) => row.episode_id).filter(Boolean));
  const retained = baseRows.filter((row) => {
    if (row.episode_id && affectedEpisodes.has(row.episode_id)) return false;
    return row.action !== actionId;
  });
  const removed = baseRows.length - retained.length;
  const episodeIds = new Set(retained.map((row) => row.episode_id).filter(Boolean));
  for (const row of replacementRows) {
    if (row.episode_id && episodeIds.has(row.episode_id)) {
      throw new Error(`replacement episode collides with retained episode ${row.episode_id}`);
    }
  }
  return {
    rows: [...retained, ...replacementRows],
    removed,
    removedActionRows: selected.length,
    removedEpisodes: affectedEpisodes.size,
  };
}

if (process.argv[1] && import.meta.url === new URL(`file:///${process.argv[1].replace(/\\/g, "/")}`).href) {
  const base = path.resolve(arg("--base", "target/world_model_dataset_release.jsonl"));
  const replacement = path.resolve(arg("--replacement"));
  const output = path.resolve(arg("--out", "target/world_model_dataset_repaired.jsonl"));
  const actionArg = String(arg("--action", ""));
  const actionId = /^\d+$/.test(actionArg) ? Number(actionArg) : TOOL_NAMES.indexOf(actionArg);
  if (!replacement) throw new Error("--replacement is required");
  if (output === base || output === replacement) throw new Error("--out must not overwrite an input");

  const result = replaceActionRows(readJsonl(base), readJsonl(replacement), actionId);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${result.rows.map((row) => JSON.stringify(row)).join("\n")}\n`);
  console.log(
    `replaced ${result.removedActionRows} ${TOOL_NAMES[actionId]} row(s) across `
    + `${result.removedEpisodes} episode(s), removing ${result.removed} total stale episode row(s), with `
    + `${result.rows.length - (readJsonl(base).length - result.removed)} fresh row(s); `
    + `wrote ${result.rows.length} rows to ${output}`,
  );
}
