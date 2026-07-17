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

function parseKernelFrames(text) {
  const matches = [...text.matchAll(/\[kernel-mmap\].*user_frames=(\d+)/g)];
  if (matches.length > 0) {
    return matches.map(m => parseInt(m[1], 10));
  }
  return [];
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

  // Step 1: Wait until the daemon has finished mmap validation
  await waitForSerial("[heliox-daemon] mmap validation success: bytes match!", 30, start);
  check("daemon touched pages and validated matching bytes", true);

  // Parse the kernel mmap frames log
  const fullLog = serialText().slice(start);
  const frameCounts = parseKernelFrames(fullLog);
  console.log(`[test] Parsed user_frames timeline: ${JSON.stringify(frameCounts)}`);

  check("found kernel-mmap logging entries", frameCounts.length >= 3);

  if (frameCounts.length >= 3) {
    const initialFrames = frameCounts[0];
    const finalFrames = frameCounts[frameCounts.length - 1];
    const diff = finalFrames - initialFrames;
    check(`initial user_frames baseline parsed: ${initialFrames}`, true);
    check(`final user_frames parsed: ${finalFrames}`, true);
    // fault_in() reads ahead up to 64 pages per fault (batching amortizes
    // the VFS path/inode resolution cost that dominates loading a real,
    // multi-megabyte mmap'd file - see REPORT.md's Phase D4 section), so
    // touching 3 far-apart offsets in this 64MiB region now pulls in up to
    // 3*64 = 192 pages total, not exactly 3 - readahead deliberately
    // over-fetches neighboring pages it hasn't been asked for yet. What
    // still matters here is that real, non-trivial paging happened (more
    // than the 3 bytes actually touched) and stayed within the batch cap.
    check(`readahead paged in more than the 3 touched bytes but no more than 3 batches' worth (diff: ${diff})`, diff > 3 && diff <= 3 * 64);
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
