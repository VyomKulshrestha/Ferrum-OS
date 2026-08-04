#!/usr/bin/env node
import assert from "node:assert/strict";
import { auditRows, TOOL_NAMES } from "./audit_world_model_dataset.mjs";

function row(action, episodeId, step, executed = true) {
  const before = Array(128).fill(0);
  const after = before.slice();
  after[action % 7] = (step + 1) / 100;
  const actionFeatures = Array(16).fill(0);
  actionFeatures[0] = (step + 1) / 10;
  return {
    action,
    action_features: actionFeatures,
    before,
    after,
    executed,
    episode_id: episodeId,
    ram_mb: 512,
    source: "audit-test",
    observation_schema: "ext2-usage-v1",
  };
}

const rows = [];
for (let action = 0; action < TOOL_NAMES.length; action++) {
  rows.push(row(action, `episode-${action}`, 0));
  rows.push(row(action, `episode-${action}`, 1));
}
const passing = auditRows(rows, {
  requiredTools: TOOL_NAMES.length,
  minExecutedPerTool: 2,
  minArgumentVariants: 2,
  minEpisodes: TOOL_NAMES.length,
  minMultistepEpisodes: TOOL_NAMES.length,
  minRamProfiles: 1,
  requireObservationSchema: true,
});
assert.equal(passing.passed, true);
assert.equal(passing.per_tool.length, TOOL_NAMES.length);
assert.equal(passing.multistep_episodes, TOOL_NAMES.length);

const missingTool = auditRows(rows.filter((item) => item.action !== 40), {
  requiredTools: TOOL_NAMES.length,
  minExecutedPerTool: 2,
  minArgumentVariants: 2,
  minEpisodes: 1,
  minMultistepEpisodes: 1,
  minRamProfiles: 1,
});
assert.equal(missingTool.passed, false);
assert.equal(missingTool.gates.find((gate) => gate.name === "tool_coverage").actual, 40);

const malformed = auditRows([{ ...row(0, "bad", 0), before: [Number.NaN] }], {
  requiredTools: 1,
  minExecutedPerTool: 1,
  minArgumentVariants: 1,
  minEpisodes: 1,
  minMultistepEpisodes: 0,
  minRamProfiles: 1,
});
assert.equal(malformed.passed, false);
assert.match(malformed.errors[0], /before must contain 128 finite numbers/);

const unspecifiedObservation = auditRows([
  { ...row(0, "missing-schema", 0), observation_schema: undefined },
], {
  requiredTools: 1,
  minExecutedPerTool: 1,
  minArgumentVariants: 1,
  minEpisodes: 1,
  minMultistepEpisodes: 0,
  minRamProfiles: 1,
  requireObservationSchema: true,
});
assert.equal(unspecifiedObservation.passed, false);
assert.match(unspecifiedObservation.errors[0], /observation_schema is required/);

console.log("PASS\tdataset audit accepts balanced, diverse transition coverage");
console.log("PASS\tdataset audit rejects missing tool coverage");
console.log("PASS\tdataset audit rejects malformed vectors");
console.log("PASS\tdataset audit rejects unversioned observation semantics");
console.log("4/4 checks passed");
