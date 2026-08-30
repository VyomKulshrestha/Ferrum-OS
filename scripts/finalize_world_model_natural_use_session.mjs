// Stop one disposable natural-use session and record immutable log/disk hashes.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const valueAfter = (name) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
};
const runtimePath = path.resolve(repo, valueAfter("--runtime"));
const outputPath = path.resolve(repo, valueAfter("--output"));
const runtime = JSON.parse(fs.readFileSync(runtimePath, "utf8"));
const sourceDisk = path.join(repo, runtime.source_disk);
const runDisk = path.join(repo, runtime.run_disk);
const serialLog = path.join(repo, runtime.serial_log);
const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
try { process.kill(runtime.pid, "SIGKILL"); } catch {}
try { process.kill(runtime.controller_pid, "SIGKILL"); } catch {}
await new Promise((resolve) => setTimeout(resolve, 600));
if (!fs.existsSync(serialLog)) throw new Error("session serial log was not created");
const log = fs.readFileSync(serialLog, "utf8");
const record = {
  schema_version: 1,
  session: runtime.session,
  acquisition: runtime.input_boundary,
  serial_log: runtime.serial_log,
  serial_sha256: digest(serialLog),
  serial_bytes: fs.statSync(serialLog).size,
  telemetry_records: (log.match(/\[world-model-telemetry-v1\]/g) || []).length,
  action_classes: [...new Set([...log.matchAll(/\[world-model-telemetry-v1\].* action=([a-z0-9_]+)/g)].map((match) => match[1]))].sort(),
  synthetic_collection_marker_present: log.includes("running world-model data collection"),
  direct_json_rpc_execution_used: false,
  guest_fault_present: /panicked at|Page Fault|General Protection Fault|terminating userspace task/i.test(log),
  transition: { path: runtime.transition, sha256: runtime.transition_sha256 },
  source_disk_sha256_before: runtime.source_disk_sha256_before,
  source_disk_sha256_after: digest(sourceDisk),
  source_disk_unchanged: runtime.source_disk_sha256_before === digest(sourceDisk),
  disposable_disk_sha256_after: fs.existsSync(runDisk) ? digest(runDisk) : null,
  physical_actuator_attempts: 0,
  physical_actuator_deliveries: 0,
};
fs.writeFileSync(outputPath, JSON.stringify(record, null, 2) + "\n");
fs.rmSync(runDisk, { force: true });
console.log(JSON.stringify({ output: outputPath, telemetry_records: record.telemetry_records, action_classes: record.action_classes }, null, 2));
