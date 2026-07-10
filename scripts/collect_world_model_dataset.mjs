// ============================================================================
// FerrumOS - World Model Training Data Collector
// ============================================================================
// Triggers heliox-daemon's real data-collection loop
// (Orchestrator::run_data_collection, see cognitive/world_model/mod.rs's
// synthetic_action doc comment) via the same /tmp/<name>_test flag-file
// pattern this project already uses for mmap/net/audio test hooks. Every
// collected example is a real (state, action, next_state, reward) tuple
// - real syscalls, real snapshots, real gate decisions - just proposed by
// a fast in-daemon rotation instead of waiting on an LLM/HTTP round-trip
// per action, which would make gathering hundreds of examples far too
// slow for this to run in one sitting.
//
// Parses the "[world-model-dataset]" lines the daemon prints (hex-encoded
// full 128-float embeddings - the compact exp.bin record can't hold
// these) out of the serial log into a host-side JSONL dataset file for
// scripts/train_world_model.py to train on.
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

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45499);
const serialLog = path.join(repo, "target", "world-model-collect-serial.log");
const outPath = path.join(repo, "target", "world_model_dataset.jsonl");
const count = Number(process.argv[2] || process.env.WM_COLLECT_COUNT || 300);
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`appliance disk image not found: ${diskImage} - run scripts/make-appliance.ps1 first`);

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

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-2000)}`);
}

try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  "-m", "512M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log(`Starting QEMU to collect ${count} world-model training examples...`);
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

async function mon(cmd, waitMs = 150) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}
const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
  "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe", ",": "comma", ":": "shift-semicolon",
}));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
async function runCommand(cmd, start) {
  await sendText(cmd);
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, start);
  await sleep(100);
}

let exitCode = 0;
try {
  let start = serialText().length;
  await waitForSerial("FerrumOS:~$", 60, start);
  console.log("boot reached shell prompt");

  // auto_approve_tier=4: without this, Tier 3/4 actions (most of the
  // synthetic rotation - write_file, create_directory, exec_process,
  // service_start/stop) hit the interactive ConfirmationGate and never
  // actually execute, so their "after" snapshot would show no real
  // change - teaching a learned model the wrong ground truth. This
  // automated collection run can't answer an interactive y/n prompt, so
  // auto-approve everything and let real outcomes happen.
  start = serialText().length;
  await runCommand("rm /disk/heliox/config.json", start);
  const configStr = '{"provider":"auto","auto_approve_tier":4}';
  await runCommand(`write /disk/heliox/config.json ${configStr}`, start);

  start = serialText().length;
  await runCommand(`write /tmp/world_model_collect ${count}`, start);

  start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("data collection complete", Math.max(60, count * 2), start);
  console.log("data collection complete, parsing dataset...");

  const full = serialText();
  const lineRe = /\[world-model-dataset\] tick=(\d+) action=(\d+) reward=([\-0-9.]+) before=([0-9a-f]+) after=([0-9a-f]+)/g;
  const rows = [];
  let m;
  while ((m = lineRe.exec(full)) !== null) {
    const hexToFloats = (hex) => {
      const out = [];
      for (let i = 0; i < hex.length; i += 8) {
        const bits = parseInt(hex.slice(i, i + 8), 16);
        const buf = new ArrayBuffer(4);
        new DataView(buf).setUint32(0, bits, false);
        out.push(new DataView(buf).getFloat32(0, false));
      }
      return out;
    };
    rows.push({
      tick: Number(m[1]),
      action: Number(m[2]),
      reward: Number(m[3]),
      before: hexToFloats(m[4]),
      after: hexToFloats(m[5]),
    });
  }

  fs.writeFileSync(outPath, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  console.log(`wrote ${rows.length} examples to ${outPath}`);
  if (rows.length === 0) {
    console.error("no dataset rows parsed - check the serial log for [world-model-dataset] lines");
    exitCode = 1;
  }
} catch (err) {
  console.error("collection failed:", err && err.message ? err.message : String(err));
  exitCode = 1;
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}
process.exit(exitCode);
