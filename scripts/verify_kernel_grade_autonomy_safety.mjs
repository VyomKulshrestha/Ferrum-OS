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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45461);
const serialLog = path.join(repo, "target", "phase-e-verify-serial.log");
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

console.log("Starting QEMU...");
// Without an explicit accelerator, QEMU falls back to plain (unaccelerated)
// TCG at whatever default memory/speed it happens to pick, which reliably
// took long enough to blow through every timeout in this script, every run -
// not because anything was actually hung.
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

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
  "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "0": "0"
}));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z]$/.test(ch)) await sendKey(ch);
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
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell prompt", true);

  console.log("Running Phase E Autonomy & Safety Verification Suite...");
  let start = serialText().length;
  await sendText("write /tmp/init_test 2");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("--- Phase E Verification Suite ---", 10, start);
  check("entered verification suite", true);

  // Test 1: Rate limit quota
  console.log("Checking Syscall Rate Quota...");
  await waitForSerial("[test] 1. Syscall Rate Limit Quota", 10, start);
  await waitForSerial("[AUDIT] ProcessKilled: Task killed: syscall rate quota exceeded", 15, start);
  await waitForSerial("[test] child exited with status 140", 10, start);
  check("syscall rate quota enforced (violator killed with status 140)", true);

  // Test 2: Memory quota
  console.log("Checking Memory Quota...");
  await waitForSerial("[test] 2. Memory Quota", 10, start);
  await waitForSerial("[test] exec huge-test returned: -3", 10, start);
  check("memory quota enforced (huge-test load rejected with status -3)", true);

  // Test 3: Confirmation Gates
  console.log("Checking Confirmation Gates...");
  await waitForSerial("[test] 3. Confirmation Gates", 10, start);
  
  // Timeout
  await waitForSerial("[test] sub-test 3.1: timeout (wait 5s)", 10, start);
  await waitForSerial("[test] sub-test 3.1 result: -2", 15, start);
  check("confirmation gate timeout default-denies (returns -2)", true);

  // Physical approval
  await waitForSerial("[test] sub-test 3.2: physical key approval (wait for y)", 10, start);
  // Update start to current serial length so we don't match the prompt from sub-test 3.1
  let start32 = serialText().length;
  const confirmationSeenAt = Date.now();
  // Send the keypress a few times in quick succession (not spaced out) so
  // that if one PS/2 scancode is lost to the same interrupt-timing race
  // documented in work.md (§1.1) - which can happen even with nothing else
  // running - a subsequent one still lands well inside the kernel's own 5s
  // confirmation window. A real user facing a dropped keystroke would just
  // press again; spacing retries out (each with its own wait) would instead
  // eat into that same 5s budget and could make things worse, not better.
  for (let attempt = 0; attempt < 3; attempt++) {
    console.log(`[test] sending physical 'y' key (attempt ${attempt + 1})...`);
    await sendKey("y");
  }
  const remainingMs = 5000 - (Date.now() - confirmationSeenAt);
  const remainingSeconds = Math.max(1, remainingMs / 1000) + 2; // +2s margin for the kernel to notice and print the result
  const approved = !!(await waitForSerial("[test] sub-test 3.2 result: 0", remainingSeconds, start32).catch(() => null));
  check("confirmation gate approved by physical 'y' (returns 0)", approved);

  // Injected rejection. Deliberately keep using `start32` (not a freshly
  // re-read `serialText().length`) as the search floor: the guest can print
  // its next line (here, sub-test 3.3's own announcement) before this host
  // script's very next statement gets to re-read the log, so re-pinning the
  // offset right after a match resolves races the guest and can start the
  // next search *after* the very text it's about to look for. Each of these
  // strings is unique, so there's nothing to gain by narrowing the window.
  await waitForSerial("[test] sub-test 3.3: injected key (should timeout/deny)", 10, start32);
  await waitForSerial("[test] sub-test 3.3 result: -2", 15, start32);
  check("confirmation gate rejects agent-injected key (returns -2 on timeout)", true);

  await waitForSerial("--- Verification Suite Complete ---", 10, start);
  await waitForSerial("FerrumOS:~$", 45, start);

  // Test 4: Persistent Audit Log
  console.log("Checking Persistent Audit Log...");
  await sleep(1000); // Wait for shell prompt and CPU to settle after process exit
  start = serialText().length;
  await sendText("cat /disk/heliox/audit.log");
  await sendKey("ret");
  
  await waitForSerial("Task killed: syscall rate quota exceeded", 10, start);
  await waitForSerial("DeleteFile syscall confirmation required", 10, start);
  check("persistent audit log contains expected events on disk", true);

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
