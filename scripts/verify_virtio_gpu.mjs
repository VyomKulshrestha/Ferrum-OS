// ============================================================================
// FerrumOS - VirtIO-GPU 2D Driver Verification
// ============================================================================
// Boots with `-device virtio-gpu-pci` added (every other verify_*.mjs
// script omits this device entirely, so this is the only boot
// configuration that ever exercises src/devices/virtio_gpu.rs - proving
// it's purely additive: this script's own first check, using the exact
// same qemuArgs shape as every other script minus this one device,
// confirms a completely ordinary boot with the device attached still
// works, before asserting anything virtio-gpu-specific.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45497);
const serialLog = path.join(repo, "target", "virtio-gpu-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");

const qemuExecutable = fs.existsSync(qemu) ? qemu : fallbackQemu;
if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemuExecutable)) throw new Error(`qemu not found at ${qemu} or ${fallbackQemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const qemuArgs = [
  "-m", "512M",
  "-drive", `format=raw,file=${image}`,
  "-device", "virtio-gpu-pci",
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");

console.log("Starting QEMU with -device virtio-gpu-pci...");
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
await sleep(500);

async function mon(cmd, waitMs = 150) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
}

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

try {
  let start = serialText().length;
  await waitForSerial("FerrumOS:~$", 60, start);
  check("boot reaches shell prompt with virtio-gpu-pci attached", true);

  await waitForSerial("VirtIO-GPU 2D device initialized", 10, 0);
  check("virtio-gpu device detected and initialized", true);

  // Launching the desktop drives the compositor's normal render loop,
  // which calls swap_buffers() every frame - the exact chokepoint
  // src/devices/vga_fb.rs now also routes through virtio_gpu::present()
  // when the device is available (src/devices/vga_fb.rs's swap_buffers).
  start = serialText().length;
  await sendText("desktop");
  await sendKey("ret");
  await waitForSerial("[gui] Entered Desktop loop", 15, start);
  check("desktop enters its normal render loop with the device attached", true);

  // Give the compositor several real frames to present through the
  // virtio-gpu path (cursor movement forces redraws).
  await mon("mouse_move 5 5", 100);
  await mon("mouse_move -5 -5", 100);
  await mon("mouse_move 3 -3", 100);
  await sleep(1000);

  const full = serialText();
  check("no virtio-gpu present() failure logged", !/\[virtio-gpu\] present failed/.test(full), full.slice(-500));
  check("no userspace fault or kernel panic", !/terminating|General Protection|Page Fault|panicked/.test(full));
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
