// ============================================================================
// FerrumOS - Scheduler Bookkeeping Stub Verification
// ============================================================================
// work.md findings 2.3 and 2.4: scheduler::init() unconditionally created two
// "bookkeeping stub" tasks (pid 100 "kernel", pid 101 "shell") purely so `ps`
// had something to show before real tasks existed. Once D13 made the shell
// prompt a genuine, live kernel task registered at boot, the pid-101 "shell"
// stub became a permanently-Ready duplicate alongside the real, running
// "shell" task - confusing and easy to mistake for a stuck/leaked task (2.3).
// Separately, the pid-100 "kernel" stub's `state` was hardcoded to `Running`
// once and never updated, inflating `scheduler`'s "running" count forever,
// even though it's never actually dispatched (2.4).
//
// This verifies: `ps`/`users` show exactly one "shell" row (the real, live
// one), and `scheduler`'s aggregate counts aren't inflated by the kernel
// bookkeeping stub.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");

let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45502);
const serialLog = path.join(repo, "target", "scheduler-stubs-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function connectMonitor() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(200); }
  }
  throw new Error("could not connect to QEMU monitor");
}

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(120);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-2000)}`);
}

const qemuArgs = [
  "-m", "512M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for scheduler-stub verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX failed, falling back to TCG...");
  let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) { monitor.write(`${cmd}\n`); await sleep(waitMs); }
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
async function runCommand(cmd) {
  const start = serialText().length;
  await sendText(cmd);
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, start);
  await sleep(100);
  return serialText().slice(start);
}

try {
  await waitForSerial("FerrumOS:~$", 45, 0);
  check("boot reaches shell prompt", true);

  const psOut = await runCommand("ps");
  const psShellRows = (psOut.match(/^\s*\d+\s+\S+\s+\S+\s+\d+\s+shell\s*$/gm) || []);
  check("ps shows exactly one `shell` row, not a duplicate", psShellRows.length === 1, psOut.trim());
  check("ps still shows a `kernel` row", /\bkernel\b/.test(psOut), psOut.trim());

  const usersOut = await runCommand("users");
  const usersShellRows = (usersOut.match(/^\s*\d+\s+\S+\s+\S+\s+\S+\s+shell\s*$/gm) || []);
  check("users shows exactly one `shell` row, not a duplicate", usersShellRows.length === 1, usersOut.trim());

  const schedOut = await runCommand("scheduler");
  const activeMatch = schedOut.match(/active tasks:\s*(\d+)/);
  const runningMatch = schedOut.match(/running:\s*(\d+)/);
  check("scheduler reports active/running counts", !!activeMatch && !!runningMatch, schedOut.trim());
  const running = runningMatch ? parseInt(runningMatch[1], 10) : -1;
  // Only the real, live `shell` task is ever genuinely Running at a plain
  // idle prompt - the permanently-frozen `kernel` bookkeeping stub used to
  // inflate this to 2. init hasn't been dispatched yet at this point either
  // (no `ring3 init` was run), so exactly 1 is the honest count.
  check("scheduler's running count is not inflated by the kernel bookkeeping stub", running === 1, schedOut.trim());

  const full = serialText();
  check("no userspace fault or page fault panic", !/terminating|General Protection|Page Fault/.test(full));
} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
