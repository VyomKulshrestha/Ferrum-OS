import fs from "node:fs";
import path from "node:path";

function jsonLines(file) {
  if (!fs.existsSync(file)) return [];
  return fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean).map((line, index) => {
    try { return JSON.parse(line); }
    catch (error) { throw new Error(`${path.basename(file)} line ${index + 1}: ${error.message}`); }
  });
}

export function reconcileWorldModelDataset(datasetPath, tracePath, outputPath = datasetPath) {
  const transitions = jsonLines(datasetPath);
  const traces = jsonLines(tracePath);
  const completedCounts = new Map();
  for (const row of traces) {
    if (row.completed && row.episode_id) {
      completedCounts.set(String(row.episode_id), Number(row.transition_count || 0));
    }
  }

  const byEpisode = new Map();
  transitions.forEach((row, index) => {
    if (!row.episode_id) throw new Error(`dataset row ${index + 1} lacks episode_id`);
    const id = String(row.episode_id);
    if (!byEpisode.has(id)) byEpisode.set(id, []);
    byEpisode.get(id).push({ row, index });
  });

  const keep = new Set();
  let droppedOrphans = 0;
  let recoveredEpisodes = 0;
  for (const [episodeId, entries] of byEpisode) {
    if (!completedCounts.has(episodeId)) {
      droppedOrphans += entries.length;
      continue;
    }
    const expected = completedCounts.get(episodeId);
    if (!Number.isInteger(expected) || expected < 0) {
      throw new Error(`${episodeId} has invalid completed transition_count ${expected}`);
    }
    if (entries.length < expected) {
      throw new Error(`${episodeId} completed with ${expected} transitions but dataset has ${entries.length}`);
    }
    const selected = expected === 0 ? [] : entries.slice(entries.length - expected);
    const keys = new Set(selected.map(({ row }) => `${row.step ?? 0}|${row.transition_in_step ?? 0}`));
    if (keys.size !== selected.length) {
      throw new Error(`${episodeId} complete suffix still contains duplicate step transitions`);
    }
    selected.forEach(({ index }) => keep.add(index));
    const extra = entries.length - selected.length;
    droppedOrphans += extra;
    if (extra) recoveredEpisodes++;
  }

  const reconciled = transitions.filter((_, index) => keep.has(index));
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  const temp = `${outputPath}.reconcile-${process.pid}.tmp`;
  fs.writeFileSync(temp, reconciled.length ? `${reconciled.map(JSON.stringify).join("\n")}\n` : "");
  fs.renameSync(temp, outputPath);
  return {
    input_rows: transitions.length,
    output_rows: reconciled.length,
    completed_episodes: completedCounts.size,
    dropped_orphan_rows: droppedOrphans,
    recovered_episodes: recoveredEpisodes,
  };
}
