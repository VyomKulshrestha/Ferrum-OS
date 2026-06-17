// ============================================================================
// FerrumOS - Memory Mapping & Demand Paging Verification
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45480);
const serialLog = path.join(repo, "target", "mmap-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

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

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon"
}));

// We try launching with WHPX first, falling back to TCG
const whpxArgs = [
  "-accel", "whpx,kernel-irqchip=off",
  "-cpu", "Haswell",
  "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
  "-device", "rtl8139,netdev=net0",
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for mmap verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });

// Wait to see if it exits immediately (WHPX unsupported)
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  const tcgArgs = [
    "-accel", "tcg",
    "-cpu", "max",
    "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
    "-device", "rtl8139,netdev=net0",
    "-device", "intel-hda",
    "-device", "hda-duplex",
    "-no-reboot",
  ];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}

async function sendKey(k) { await mon(`sendkey ${k}`, 45); }

async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

function parseFrames(text) {
  const lines = text.split("\n");
  for (const line of lines) {
    if (line.includes("heliox-daemon")) {
      const parts = line.trim().split(/\s+/);
      if (parts.length >= 2) {
        const frames = parseInt(parts[1], 10);
        if (!isNaN(frames)) return frames;
      }
    }
  }
  return null;
}

try {
  await waitForSerial("FerrumOS:~$", 35);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Write the mmap test trigger file
  await sendText("write /tmp/mmap_test 1");
  await sendKey("ret");
  await sleep(400);

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: Wait until the daemon has mapped the file but before touching pages
  await waitForSerial("[heliox-daemon] ready for initial frame check", 25, start);
  check("daemon starts and maps test file", true);

  // Step 2: Query initial frame count
  const mark1 = serialText().length;
  await sendText("process");
  await sendKey("ret");
  await sleep(500);
  
  const text1 = serialText().slice(mark1);
  const initialFrames = parseFrames(text1);
  check(`parsed initial frames: ${initialFrames}`, initialFrames !== null);

  // Step 3: Wait for daemon to finish mmap validation
  await waitForSerial("[heliox-daemon] mmap validation success: bytes match!", 20, start);
  check("daemon touched pages and validated matching bytes", true);

  // Step 4: Query final frame count
  const mark2 = serialText().length;
  await sendText("process");
  await sendKey("ret");
  await sleep(500);

  const text2 = serialText().slice(mark2);
  const finalFrames = parseFrames(text2);
  check(`parsed final frames: ${finalFrames}`, finalFrames !== null);

  if (initialFrames !== null && finalFrames !== null) {
    const diff = finalFrames - initialFrames;
    check(`exactly 3 pages paged in (diff: ${diff})`, diff === 3);
  }

  // Step 5: Verify no page fault/panic/leaks
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
