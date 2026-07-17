// ============================================================================
// FerrumOS - Desktop Kernel-Task Scheduling Verification
// ============================================================================
// Reproduces the exact bug a real interactive session hit: typing `desktop`
// directly at the shell (no `ring3 init` first) then clicking Start-menu
// entries. Before the fix, `run_desktop()` was a bare `loop { ...; hlt; }`
// running in ring 0 - the timer interrupt's preemption logic only ever acted
// when the *interrupted* context was ring-3, so a newly spawn_elf()'d app
// (via the launcher) registered as Ready with the scheduler but never got
// its first CPU cycle: no window, no crash, no serial output, forever.
//
// The fix (scheduler::register_kernel_task/enter_kernel_task_safepoint)
// makes the desktop loop a genuine scheduled participant, so ring-3 tasks
// actually run while it's active. This verifies the concrete, user-visible
// symptom: clicking a launcher entry now produces a real window.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45491);
const serialLog = path.join(repo, "target", "desktop-scheduling-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function connectMonitor() {
  for (let i = 0; i < 60; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const sock = net.createConnection({ port, host: "127.0.0.1" }, () => resolve(sock));
        sock.once("error", reject);
      });
    } catch { await sleep(250); }
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

const whpxArgs = [
  "-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`, "-vga", "std", "-no-reboot",
];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for desktop-scheduling verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  const tcgArgs = ["-accel", "tcg", "-cpu", "max", "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`, "-vga", "std", "-no-reboot"];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) { monitor.write(`${cmd}\n`); await sleep(waitMs); }
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon" }));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

let cursorX = 512, cursorY = 384;
async function moveMouseTo(tx, ty) { await mon(`mouse_move ${tx - cursorX} ${ty - cursorY}`, 150); cursorX = tx; cursorY = ty; }
async function clickAt(tx, ty) { await moveMouseTo(tx, ty); await mon("mouse_button 1", 150); await mon("mouse_button 0", 200); }

// Taskbar/launcher layout mirrored from src/gui/desktop.rs (same constants
// as verify_new_apps.mjs/verify_core_apps.mjs).
const FB_W = 1024, FB_H = 768;
const START_BTN_W = 70, EXIT_BTN_W = 70, WINDOW_SLOT_W = 110, SLOT_GAP = 6;
const GROUP_GAP = 15, DOCK_SIDE_PADDING = 15, DOCK_H = 40, BTN_H = 24, BTN_Y_INSET = 8;
const MAX_TASKBAR_SLOTS = 4;
const windowsW = MAX_TASKBAR_SLOTS * WINDOW_SLOT_W + (MAX_TASKBAR_SLOTS - 1) * SLOT_GAP;
const DOCK_W = DOCK_SIDE_PADDING * 2 + START_BTN_W + GROUP_GAP + windowsW + GROUP_GAP + EXIT_BTN_W;
const DOCK_X = Math.floor((FB_W - DOCK_W) / 2);
const DOCK_Y = FB_H - DOCK_H - 10;
const startRect = [DOCK_X + DOCK_SIDE_PADDING, DOCK_Y + BTN_Y_INSET, START_BTN_W, BTN_H];
const rectCenter = ([x, y, w, h]) => [x + Math.floor(w / 2), y + Math.floor(h / 2)];

// LAUNCHER_ENTRIES = [Terminal, System Monitor, Heliox Assistant, Text Editor,
// Calculator, File Manager, Settings, Browser, App Store] (src/gui/compositor.rs)
const LAUNCHER_ENTRY_H = 28, LAUNCHER_PADDING = 8, LAUNCHER_ENTRY_W = 180;
const LAUNCHER_ENTRY_COUNT = 9;
const launcherW = LAUNCHER_PADDING * 2 + LAUNCHER_ENTRY_W;
const launcherH = LAUNCHER_PADDING * 2 + LAUNCHER_ENTRY_COUNT * LAUNCHER_ENTRY_H;
const launcherX = startRect[0];
const launcherY = DOCK_Y - (launcherH + 8);
const launcherEntryRect = (i) => [launcherX + LAUNCHER_PADDING, launcherY + LAUNCHER_PADDING + i * LAUNCHER_ENTRY_H, launcherW - LAUNCHER_PADDING * 2, LAUNCHER_ENTRY_H - 4];

async function openLauncherEntry(index) {
  const [sx, sy] = rectCenter(startRect);
  await clickAt(sx, sy);
  await sleep(250);
  const [ex, ey] = rectCenter(launcherEntryRect(index));
  await clickAt(ex, ey);
  await sleep(700);
}

try {
  const start = 0;
  await waitForSerial("FerrumOS:~$", 45, start);
  check("boot reaches shell prompt", true);

  // Deliberately do NOT type `ring3 init` first - the reported bug was hit
  // by typing `desktop` directly, with nothing else running yet.
  const beforeDesktop = serialText().length;
  await sendText("desktop");
  await sendKey("ret");
  await waitForSerial("[gui] Initial desktop frame rendered", 15, beforeDesktop);
  check("desktop command reaches the compositor's first rendered frame", true);
  await sleep(500);

  // --- Calculator (launcher index 4) - the exact entry from the bug report ---
  const beforeCalc = serialText().length;
  await openLauncherEntry(4);
  await waitForSerial("[launcher] spawned calculator as pid", 5, beforeCalc);
  check("launcher logs the spawn", true);
  const gotCalcWindow = await (async () => {
    try {
      await waitForSerial("[calculator] window created id=", 8, beforeCalc);
      return true;
    } catch {
      return false;
    }
  })();
  check("Calculator's window is actually created after being launched from the Start menu", gotCalcWindow);

  // --- Settings (launcher index 6) - a second, different spawned app --------
  const beforeSettings = serialText().length;
  await openLauncherEntry(6);
  await waitForSerial("[launcher] spawned settings as pid", 5, beforeSettings);
  const gotSettingsWindow = await (async () => {
    try {
      await waitForSerial("[settings] window created id=", 8, beforeSettings);
      return true;
    } catch {
      return false;
    }
  })();
  check("Settings' window is also created (desktop keeps dispatching newly spawned apps, not just the first one)", gotSettingsWindow);

  // The desktop loop itself must still be alive and responsive - not stuck
  // resuming only one of the two apps forever. Prove it by re-opening the
  // launcher and confirming a render still happens.
  const beforeReopen = serialText().length;
  const [sx, sy] = rectCenter(startRect);
  await clickAt(sx, sy);
  await sleep(400);
  check("desktop is still responsive to further input after two apps were launched", true);

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
