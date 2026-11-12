// fi1 kernel harness: killing an app from the shell and launching another one.
//
// The shell is a kernel task registered with cr3 = 0, and `resume_task` used
// to leave CR3 untouched for such tasks, so after an app had run the shell kept
// running on that app's page tables. `kill <pid>` reaps the app and frees those
// tables while the CPU still uses them; the next launch reuses the freed L4
// frame (the allocator is LIFO), zeroes it, and the kernel stops. This harness
// runs that sequence three times.
//
//   node scripts/verify_process_reap_cr3.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);

let shell;
try {
  shell = await bootShell(repo, "process-reap-cr3-serial.log");
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);
  const pids = [];
  for (let round = 1; round <= 3; round++) {
    const from = shell.serial().length;
    const out = await shell.command("run calculator", 30);
    const pid = (out.match(/launched calculator as userspace pid (\d+)/) || [])[1];
    check(`round ${round}: calculator launched`, !!pid, pid ? `pid=${pid}` : out.trim().slice(-200));
    if (!pid) break;
    pids.push(pid);
    // Let the app run in ring 3 so the shell is resumed after it.
    await shell.waitFor("[calculator] window created", 30, from);
    await sleep(500);
    const killed = await shell.command(`kill ${pid}`, 30);
    check(`round ${round}: kill reaps pid ${pid}`, new RegExp(`reaped pid=${pid}\\b`).test(killed) && /Killed task/.test(killed));
  }
  const ps = await shell.command("process", 30);
  check("shell still responds after three launch/kill rounds", /Per-process Address Spaces/.test(ps));
  check("no kernel panic or fault", !/panicked at|PAGE FAULT|Page Fault|General Protection|DOUBLE FAULT/.test(shell.serial()));
} catch (error) {
  check("verification", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}
report("Process reap / CR3 verification", results);
