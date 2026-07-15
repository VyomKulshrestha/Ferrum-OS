// ============================================================================
// FerrumOS - Dashboard Kernel-Task Scheduling Verification
// ============================================================================
// work.md finding 2.5: `dashboard`'s exit-wait loop busy-spun on
// `core::hint::spin_loop()` instead of `hlt`-ing at a registered safepoint,
// the same class of bug already found and fixed for the desktop GUI loop
// (D11) and the plain shell prompt (D13) - while dashboard was open, every
// ring-3 task (heliox-daemon, init, ...) was completely starved. This
// verifies the fix: heliox-daemon keeps getting real CPU turns while the
// dashboard is open, and the shell is still usable afterward.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const diskImage = path.join(repo, "target", "heliox-disk.img");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45497);
const serialLog = path.join(repo, "target", "dashboard-scheduling-verify-serial.log");
const visible = process.argv.includes("--visible");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function connectMonitor() {
  for (let i = 0; i < 60; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const sock = net.createConnection({ port, host: "127.0.0.1" }, () => resolve(sock));
        sock.once("error", reject);
      });
    } catch { await sleep(250); }
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
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
}

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`appliance disk image not found: ${diskImage} - run scripts/make-appliance.ps1 first`);

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for dashboard-scheduling verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) { monitor.write(`${cmd}\n`); await sleep(waitMs); }
const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon",
}));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
async function runCommand(cmd, start, waitSeconds = 10) {
  await sendText(cmd);
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", waitSeconds, start);
  await sleep(100);
}

try {
  let start = 0;
  await waitForSerial("FerrumOS:~$", 45, start);
  check("boot reaches shell prompt", true);

  // Dispatch heliox-daemon first so there's something real to starve.
  start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");
  await waitForSerial("Dispatching ring-3 init", 10, start);
  await waitForSerial("FerrumOS:~$", 10, start);
  check("shell prompt still usable after ring3 init", true);

  // Give heliox-daemon a moment to actually get running before opening
  // the dashboard, so its RESUME_TASK lines during the dashboard window
  // are unambiguous.
  await waitForSerial("[heliox-daemon] active provider:", 20, start);

  // Open the dashboard and leave it up for a few seconds.
  const beforeDashboard = serialText().length;
  await sendText("dashboard");
  await sendKey("ret");
  await waitForSerial("[dashboard] launching system dashboard", 10, beforeDashboard);
  check("dashboard launches", true);
  await sleep(3000);

  const duringDashboard = serialText().slice(beforeDashboard);
  const daemonResumesWhileOpen = (duringDashboard.match(/RESUME_TASK\] Resuming pid=\d+, name=heliox-daemon/g) || []).length;
  const dashboardResumes = (duringDashboard.match(/RESUME_TASK\] Resuming pid=\d+, name=dashboard/g) || []).length;
  check(
    "heliox-daemon keeps getting real CPU turns while the dashboard is open (not starved)",
    daemonResumesWhileOpen >= 2,
    `heliox-daemon resumed ${daemonResumesWhileOpen}x, dashboard resumed ${dashboardResumes}x while open`
  );

  // Exit the dashboard (ESC) and confirm the shell comes back and stays usable.
  const beforeExit = serialText().length;
  await sendKey("esc");
  await waitForSerial("[dashboard] exiting dashboard", 5, beforeExit);
  await waitForSerial("FerrumOS:~$", 10, beforeExit);
  check("dashboard exits and returns to the shell prompt", true);

  const beforeWhoami = serialText().length;
  await runCommand("whoami", beforeWhoami, 15);
  const whoamiOutput = serialText().slice(beforeWhoami);
  check(
    "shell remains fully responsive after the dashboard closes",
    whoamiOutput.includes("root") || whoamiOutput.includes("uid=")
  );

  const full = serialText().slice(start);
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
