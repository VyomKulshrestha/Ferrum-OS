// ============================================================================
// FerrumOS - Phase H3 Local SLM Inference Verification
// ============================================================================
// Boots the kernel in QEMU, writes the Phase H3 verification trigger,
// spawns heliox-daemon, connects to the WebSocket server on port 8785,
// runs a local inference request, and asserts the output sequence.
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
const fallbackQemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45463);
const serialLog = path.join(repo, "target", "inference-verify-serial.log");
const visible = process.argv.includes("--visible");

const qemuExecutable = fs.existsSync(qemu) ? qemu : fallbackQemu;

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemuExecutable)) throw new Error(`qemu not found at ${qemu} or ${fallbackQemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  // heliox-daemon's heap is 64MB (sized for real model checkpoints - see
  // src/main.rs) - QEMU's tiny default RAM isn't enough to spawn it even
  // for this synthetic-fixture test, which otherwise barely touches memory.
  "-m", "512M",
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A process's ELF BSS (including heliox-daemon's static heap array) is
// mapped and zeroed eagerly at spawn time, not demand-paged like an mmap'd
// file - under pure TCG (software CPU emulation) that eager zeroing is slow
// enough to blow past any reasonable test timeout once the heap is sized
// for a real model. Every other script in this repo tries WHPX (hardware
// virtualization) first for exactly this reason; this one predates that
// pattern and hardcoded TCG - bring it in line.
console.log(`Starting QEMU using ${qemuExecutable}...`);
let qemuProcess = spawn(qemuExecutable, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  qemuProcess = spawn(qemuExecutable, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: !visible });
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
  "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", "0": "0",
  "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe", ",": "comma", ":": "shift-semicolon"
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
  await waitForSerial("FerrumOS:~$", 180);
  check("boot reaches shell prompt", true);

  console.log("Running Phase H3 Local SLM Inference Verification Suite...");
  let start = serialText().length;
  await sendText("write /tmp/init_test 4");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  // heliox-assistant-panel auto-launches on missing config as part of raw
  // kernel boot (main.rs, before the interactive shell prompt even exists -
  // see REPORT.md's Phase D5 section), so there's no way for a command
  // typed here to prevent it; it's real, if lightweight, background
  // scheduling competition for whatever init's test-mode-4 setup needs to
  // do. Patience, not avoidance.
  await waitForSerial("--- Phase H3 Verification Suite ---", 90, start);
  check("entered Phase H3 verification suite", true);

  await waitForSerial("[test] Spawned heliox-daemon successfully", 90, start);
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 90, start);
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
      }
    } catch (e) {
      console.error("Error parsing WS message:", e);
    }
  };

  // Wait for WS local inference response
  const wsDeadline = Date.now() + 60_000;
  while (Date.now() < wsDeadline && !localInferenceResponse) {
    if (wsError) throw wsError;
    await sleep(200);
  }

  if (!localInferenceResponse) {
    throw new Error("Timeout waiting for WebSocket local_inference response");
  }

  const success = localInferenceResponse.success;
  const output = localInferenceResponse.output;
  
  console.log("Local inference output:", output);
  
  // The expected sequence starting from token 111 (last char 'o' of prompt "hello") is:
  // 112 ('p'), 113 ('q'), 114 ('r'), 115 ('s'), 116 ('t').
  // Let's assert that the output starts with "pqrst".
  const startsWithExpected = output.startsWith("pqrst");
  check("local offline inference execution (deterministic sequence generation matches expected pqrst)",
    success && startsWithExpected, `Got output: ${JSON.stringify(output)}`);

  // Verify no page fault/panic occurred
  const full = serialText().slice(start);
  check("no userspace fault/panic during local inference",
    !/terminating|General Protection|Page Fault/.test(full));

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
