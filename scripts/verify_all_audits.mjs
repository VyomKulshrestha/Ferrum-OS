// ============================================================================
// FerrumOS - Consolidated Shell Command Audits
// ============================================================================
// Runs the fast command/usage sweep and the exhaustive command catalog audit
// sequentially. Each child owns its QEMU lifecycle; stopping on the first
// failure prevents a later green result from hiding an earlier regression.
// ============================================================================
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const audits = [
  "command_sweep.mjs",
  "audit_all_commands.mjs",
];

function runAudit(script) {
  return new Promise((resolve, reject) => {
    console.log(`\n=== ${script} ===`);
    const child = spawn(process.execPath, [path.join(scriptDir, script)], {
      cwd: path.resolve(scriptDir, ".."),
      env: process.env,
      stdio: "inherit",
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (signal) {
        reject(new Error(`${script} terminated by signal ${signal}`));
      } else if (code !== 0) {
        reject(new Error(`${script} failed with exit code ${code}`));
      } else {
        resolve();
      }
    });
  });
}

try {
  for (const audit of audits) {
    await runAudit(audit);
  }
  console.log("\nAll shell command audits passed.");
} catch (error) {
  console.error(`\nCommand audit failure: ${error.message}`);
  process.exitCode = 1;
}
