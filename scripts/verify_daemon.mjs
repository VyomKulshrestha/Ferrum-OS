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
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45460);
const serialLog = path.join(repo, "target", "daemon-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Without an explicit accelerator, QEMU falls back to plain (unaccelerated)
// TCG at whatever default memory/speed it happens to pick - heliox-daemon's
// ELF alone needs to map ~16,385 pages for its ~64MB heap arena
// (src/process/mod.rs's map_user_range), and this reliably took long enough
// under unaccelerated/under-provisioned QEMU to blow through every timeout
// in this script, every run - not because anything was actually hung.
let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("[test] WHPX unsupported or failed, falling back to TCG...");
  qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: !visible });
  await sleep(1500);
}

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
  // Generous boot budget - see the accelerator comment above.
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell prompt", true);

  const start = serialText().length;
  // Create daemon trigger and start init supervisor
  await sendText("write /tmp/daemon_exit_once 1");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: init spawns and daemon starts and prints console message in Ring-3
  await waitForSerial("[init] Spawning heliox-daemon...", 45, start);
  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 45, start);
  check("daemon starts under init supervisor", true);

  // Step 2: daemon triggers supervision test and exits, and init restarts it.
  // `userland/init/src/main.rs` logs the exit as
  // "...status=<N>" (no "Restarting..." suffix - that text never actually
  // existed in the code) and only *implicitly* restarts by looping back to
  // "[init] Spawning heliox-daemon..."; waiting on the real message first,
  // confirming the actual restart via the second, later
  // "Spawning heliox-daemon..." line.
  await waitForSerial("[heliox-daemon] exiting for supervision test", 45, start);
  const exitLogOffset = serialText().indexOf("[heliox-daemon] exiting for supervision test", start);
  await waitForSerial("[init] heliox-daemon exited or crashed! status=", 45, start);
  await waitForSerial("[init] Spawning heliox-daemon...", 45, exitLogOffset);
  check("init detects exit and triggers daemon restart", true);

  // Step 3: restarted daemon announces readiness and starts its tick loop
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 45, start);
  check("restarted daemon sends IPC announcement (capability checks pass)", true);

  await waitForSerial("[heliox-daemon] loop tick complete, sleeping...", 45, start);
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
