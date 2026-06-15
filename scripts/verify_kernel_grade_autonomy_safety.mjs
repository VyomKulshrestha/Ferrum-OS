import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const qemu = process.env.QEMU || "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45461);
const serialLog = path.join(repo, "target", "phase-e-verify-serial.log");
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

console.log("Starting QEMU...");
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
  await waitForSerial("FerrumOS:~$", 30);
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
  await waitForSerial("Operator confirmation required. Press 'y' to approve", 10, start32);
  console.log("Sending physical 'y' key...");
  await sendKey("y");
  await waitForSerial("[test] sub-test 3.2 result: 0", 10, start32);
  check("confirmation gate approved by physical 'y' (returns 0)", true);

  // Injected rejection
  // Update start to current serial length to prevent early match on the timeout prompt
  let start33 = serialText().length;
  await waitForSerial("[test] sub-test 3.3: injected key (should timeout/deny)", 10, start33);
  await waitForSerial("[test] sub-test 3.3 result: -2", 15, start33);
  check("confirmation gate rejects agent-injected key (returns -2 on timeout)", true);

  await waitForSerial("--- Verification Suite Complete ---", 10, start);
  await waitForSerial("FerrumOS:~$", 15, start);

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
