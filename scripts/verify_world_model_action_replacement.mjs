import assert from "node:assert/strict";
import { replaceActionRows } from "./replace_world_model_action_rows.mjs";

const base = [
  { episode_id: "old-ipc", action: 0, success: false },
  { episode_id: "old-ipc", action: 7, success: true },
  { episode_id: "keep-read", action: 7, success: true },
];
const fresh = [
  { episode_id: "new-ipc-a", action: 0, success: true },
  { episode_id: "new-ipc-b", action: 0, success: true },
];
const result = replaceActionRows(base, fresh, 0);
assert.equal(result.removed, 2);
assert.equal(result.removedActionRows, 1);
assert.deepEqual(result.rows, [base[2], ...fresh]);
assert.throws(() => replaceActionRows(base, [{ episode_id: "bad", action: 1 }], 0));
assert.throws(() => replaceActionRows(base, [{ episode_id: "keep-read", action: 0 }], 0));
console.log("PASS\taction repair replaces stale rows and rejects mixed/colliding data");
console.log("1/1 checks passed");
