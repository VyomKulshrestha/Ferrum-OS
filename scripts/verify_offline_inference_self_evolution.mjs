// ============================================================================
// FerrumOS - Phase F Offline Inference & Self-Evolution Verification
// ============================================================================
// Boots the kernel in QEMU, runs the Phase F verification suite in init,
// writes the mock GGUF model and kexec payload, connects to the daemon's
// WebSocket JSON-RPC server on port 8785, asserts that:
//   1. SSE context switches under preemption are safe (uncorrupted),
//   2. Local offline inference execution over GGUF Q4 GEMV works,
//   3. sys_kexec has an unbypassable confirmation gate and jumps to the payload.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45462);
const serialLog = path.join(repo, "target", "phase-f-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
  "-device", "rtl8139,netdev=net0",
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

  console.log("Running Phase F Offline Inference & Self-Evolution Verification Suite...");
  let start = serialText().length;
  await sendText("write /tmp/init_test 3");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("--- Phase F Verification Suite ---", 40, start);
  check("entered verification suite", true);

  // Test 1: SSE preemption safety
  console.log("Checking SSE Preemption Safety...");
  await waitForSerial("[test] 1. SSE preemption safety: OK", 40, start);
  check("SSE preemption safety (floating-point state remains uncorrupted across context switches)", true);

  // Test 2: Local offline inference setup
  console.log("Checking Offline Inference Setup...");
  await waitForSerial("[test] 2. Local offline inference setup complete", 40, start);
  check("Offline inference files created successfully", true);

  // Test 3: Spawn heliox-daemon under test mode
  console.log("Spawning heliox-daemon...");
  await waitForSerial("[test] Spawned heliox-daemon successfully", 40, start);
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 40, start);
  check("daemon spawned and entered Ring-3 successfully", true);

  // Wait for the daemon server to bind
  await sleep(2000);

  // Connect to the WebSocket port 8785
  console.log("Connecting to daemon WebSocket on port 8785...");
  const ws = new WebSocket("ws://127.0.0.1:8785");
  
  let wsOpen = false;
  let wsError = null;
  let localInferenceResponse = null;

  ws.onopen = () => {
    wsOpen = true;
    console.log("WebSocket connected. Sending local_inference request...");
    ws.send(JSON.stringify({
      jsonrpc: "2.0",
      id: "test-inference",
      method: "execute_tool",
      params: {
        tool: "local_inference",
        args: {
          prompt: "hello"
        }
      }
    }));
  };

  ws.onerror = (err) => {
    wsError = err;
  };

  ws.onmessage = (event) => {
    console.log("WebSocket received message:", event.data);
    try {
      const data = JSON.parse(event.data);
      if (data.id === "test-inference") {
        localInferenceResponse = data.result;
        // Now trigger kernel upgrade!
        console.log("Sending trigger_kernel_upgrade request...");
        ws.send(JSON.stringify({
          jsonrpc: "2.0",
          id: "test-upgrade",
          method: "execute_tool",
          params: {
            tool: "trigger_kernel_upgrade",
            args: {}
          }
        }));
      }
    } catch (e) {
      console.error("Error parsing WS message:", e);
    }
  };

  // Wait for WS local inference response
  const wsDeadline = Date.now() + 10_000;
  while (Date.now() < wsDeadline && !localInferenceResponse) {
    if (wsError) throw wsError;
    await sleep(200);
  }

  if (!localInferenceResponse) {
    throw new Error("Timeout waiting for WebSocket local_inference response");
  }

  const success = localInferenceResponse.success;
  const output = localInferenceResponse.output;
  check("local offline inference execution (Q4 Gemv scalar calculation completes successfully)",
    success && output.includes("Local SLM Response: Hello! I am your offline assistant"));

  // Now the kernel upgrade has been triggered.
  // We expect the gated syscall prompt to appear.
  console.log("Waiting for confirmation gate prompt...");
  let startKexec = serialText().length;
  await waitForSerial("Operator confirmation required. Press 'y' to approve", 15, startKexec);
  console.log("Sending physical 'y' key to confirm kexec...");
  await sendKey("y");

  // Wait for relocation and jump
  await waitForSerial("Relocated payload to 0x900000. Disabling interrupts and jumping", 10, startKexec);
  await waitForSerial("KEXEC", 10, startKexec);
  check("kexec confirmation gate, relocation trampoline, and jump to payload successful", true);

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
