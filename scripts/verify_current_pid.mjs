// ============================================================================
// FerrumOS - CURRENT_PID Integrity Verification
// ============================================================================
// work.md finding 2.6: `test-syscall sleep` reported `ran=false` while
// `test-syscall yield` reported `ran=true` in the same debug session, with
// no clear reason why the two would differ - they're structurally
// identical (`yield_current`/`sleep_current` both bail out early unless
// `CURRENT_PID` is nonzero).
//
// Root cause: `scheduler::schedule_next()` unconditionally overwrote the
// global `CURRENT_PID` with whatever pid it picked next, without checking
// whether that pid was a genuine ring-3 user process or one of our own
// kernel tasks (shell/dashboard/desktop, always `cr3: 0`). `CURRENT_PID`'s
// own doc says "0 means kernel main context" - since D13 let the shell
// round-robin with everything else via this same generic scheduling path,
// picking the shell task as "next" silently clobbered CURRENT_PID with the
// shell's own pid, making `test-syscall yield/sleep` (run from the shell's
// own context) nondeterministically report `ran=true` depending entirely on
// incidental scheduling history - not a real signal of anything.
//
// This verifies the fix: `test-syscall yield` and `test-syscall sleep`,
// run back to back from the plain shell prompt, both deterministically
// report `ran=false` (the shell is never itself a schedulable ring-3
// process it can yield/sleep as), and `ps` confirms the shell task stays
// `RUNNING` throughout instead of flipping to `READY` on a "successful"
// (bogus) yield.
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

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45505);
const serialLog = path.join(repo, "target", "current-pid-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
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

console.log("[test] starting QEMU for CURRENT_PID verification...");
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
    if (ch === " ") await sendKey("spc");
    else if (ch === "-") await sendKey("minus");
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
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

  const yieldOut1 = await runCommand("test-syscall yield");
  check("first yield: ran=false (shell isn't a schedulable ring-3 process)", /yield: ran=false/.test(yieldOut1), yieldOut1.trim());

  const sleepOut = await runCommand("test-syscall sleep");
  check("sleep: ran=false, matching yield (no longer inconsistent)", /sleep\(2\): ran=false/.test(sleepOut), sleepOut.trim());

  const yieldOut2 = await runCommand("test-syscall yield");
  check("second yield: still ran=false (deterministic, not incidental)", /yield: ran=false/.test(yieldOut2), yieldOut2.trim());

  const psOut = await runCommand("ps");
  check("ps shows the shell task still RUNNING (never flipped to READY by a bogus yield)", /\d+\s+RUNNING\s+\S+\s+\d+\s+shell/.test(psOut), psOut.trim());

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
