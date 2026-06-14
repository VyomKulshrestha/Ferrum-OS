// ============================================================================
// FerrumOS - heliox-daemon Ring-3 verification
// ============================================================================
// Boots the kernel in QEMU, drives `ring3 heliox-daemon` from the shell,
// and asserts that the daemon:
//   1. enters ring 3 and starts execution successfully,
//   2. sends its readiness IPC announcement ("HELIOX_READY") via capability-gated syscall,
//   3. executes its main tick loop and cooperatively sleeps (SYS_SLEEP).
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const qemu = process.env.QEMU || "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45460);
const serialLog = path.join(repo, "target", "daemon-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");

const qemuProcess = spawn(qemu, qemuArgs, { windowsHide: !visible });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
let monitorBuffer = "";
monitor.on("data", (d) => { monitorBuffer += d; });
await sleep(500);

async function mon(cmd, waitMs = 60) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}

const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus" }));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/.test(ch)) await sendKey(ch);
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
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

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

try {
  await waitForSerial("FerrumOS:~$", 30);
  check("boot reaches shell prompt", true);

  const start = serialText().length;
  // Create daemon trigger and start init supervisor
  await sendText("write /tmp/daemon_exit_once 1");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: init spawns and daemon starts and prints console message in Ring-3
  await waitForSerial("[init] Spawning heliox-daemon...", 12, start);
  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 12, start);
  check("daemon starts under init supervisor", true);

  // Step 2: daemon triggers supervision test and exits, and init restarts it
  await waitForSerial("[heliox-daemon] exiting for supervision test", 12, start);
  await waitForSerial("[init] heliox-daemon exited or crashed! Restarting...", 12, start);
  check("init detects exit and triggers daemon restart", true);

  // Step 3: restarted daemon announces readiness and starts its tick loop
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 15, start);
  check("restarted daemon sends IPC announcement (capability checks pass)", true);

  await waitForSerial("[heliox-daemon] loop tick complete, sleeping...", 15, start);
  check("restarted daemon enters main tick loop and sleeps", true);

  // Step 4: negative control check for any userspace faults
  const full = serialText().slice(start);
  check("no userspace fault/panic during daemon run",
    !/terminating|General Protection|Page Fault/.test(full));

} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
