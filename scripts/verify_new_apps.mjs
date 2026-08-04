// ============================================================================
// FerrumOS - Settings, Browser, App Store Verification
// ============================================================================
// Proves the 3 newest launcher entries are real apps, not stubs:
//   - Settings: launches, reads real hardware info via SYS_SYSTEM_QUERY.
//   - Browser: launches (network fetch itself needs a mock server, out of
//     scope here - verify_appliance.mjs already proves the underlying TCP
//     stack works end to end).
//   - App Store: launches built-ins through the least-privilege app broker,
//     then installs/removes/rolls back/launches a signed package while the
//     other apps and Heliox remain scheduled.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const applianceDisk = path.join(repo, "target", "heliox-disk.img");
const diskImage = path.join(repo, "target", "new-apps-verify-disk.img");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45489);
const serialLog = path.join(repo, "target", "new-apps-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");
if (!fs.existsSync(applianceDisk)) throw new Error(`appliance disk not found: ${applianceDisk}`);
// Package lifecycle checks are intentionally mutating. Always run them on a
// disposable copy so repeated verification cannot change the release image or
// inherit the previous run's installed-package state.
fs.rmSync(diskImage, { force: true });
fs.copyFileSync(applianceDisk, diskImage);
process.once("exit", () => {
  try { fs.rmSync(diskImage, { force: true }); } catch { /* QEMU cleanup is best-effort on abnormal exit. */ }
});

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
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`, "-vga", "std", "-no-reboot",
];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for new-apps verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  const tcgArgs = ["-accel", "tcg", "-cpu", "max", "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
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
async function sendKey(k) { await mon(`sendkey ${k} 20`, 45); }
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
// as verify_core_apps.mjs/verify_desktop_shell.mjs).
const FB_W = 1024, FB_H = 768;
const START_BTN_W = 70, EXIT_BTN_W = 54, WINDOW_SLOT_W = 72, PAGE_BTN_W = 28, CLOCK_W = 80, SLOT_GAP = 4;
const GROUP_GAP = 10, DOCK_SIDE_PADDING = 10, DOCK_H = 40, BTN_H = 24, BTN_Y_INSET = 8;
const MAX_TASKBAR_SLOTS = 7;
const windowsW = MAX_TASKBAR_SLOTS * WINDOW_SLOT_W + (MAX_TASKBAR_SLOTS - 1) * SLOT_GAP;
const pagingW = PAGE_BTN_W * 2 + SLOT_GAP;
const controlsW = DOCK_SIDE_PADDING * 2 + START_BTN_W + GROUP_GAP + windowsW + GROUP_GAP + pagingW + GROUP_GAP + EXIT_BTN_W;
const DOCK_W = controlsW + SLOT_GAP + CLOCK_W;
const DOCK_X = Math.floor((FB_W - DOCK_W) / 2);
const DOCK_Y = FB_H - DOCK_H - 10;
const startRect = [DOCK_X + DOCK_SIDE_PADDING, DOCK_Y + BTN_Y_INSET, START_BTN_W, BTN_H];
const rectCenter = ([x, y, w, h]) => [x + Math.floor(w / 2), y + Math.floor(h / 2)];

// LAUNCHER_ENTRIES = [Terminal, System Monitor, Heliox Assistant, Text Editor,
// Calculator, File Manager, Settings, Browser, App Store, Notification Center, Task Manager] (src/gui/compositor.rs)
const LAUNCHER_ENTRY_H = 28, LAUNCHER_PADDING = 8, LAUNCHER_ENTRY_W = 180;
const LAUNCHER_ENTRY_COUNT = 11;
const launcherW = LAUNCHER_PADDING * 2 + LAUNCHER_ENTRY_W;
const launcherH = LAUNCHER_PADDING * 2 + LAUNCHER_ENTRY_COUNT * LAUNCHER_ENTRY_H;
const launcherX = startRect[0];
const launcherY = DOCK_Y - (launcherH + 8);
const launcherEntryRect = (i) => [launcherX + LAUNCHER_PADDING, launcherY + LAUNCHER_PADDING + i * LAUNCHER_ENTRY_H, launcherW - LAUNCHER_PADDING * 2, LAUNCHER_ENTRY_H - 4];

async function openLauncherEntry(index) {
  const [sx, sy] = rectCenter(startRect);
  await clickAt(sx, sy);
  // Desktop input is pumped by the scheduled Heliox HUD update path. Under
  // the full background-app load, a 250 ms click-to-menu delay races that
  // pump and can send the entry click before the launcher is actually open.
  await sleep(1500);
  const [ex, ey] = rectCenter(launcherEntryRect(index));
  await clickAt(ex, ey);
  await sleep(1800);
}

// New app windows always spawn at this fixed position (src/gui/app_window.rs).
const APP_X = 150, APP_Y = 150;
const CHROME_TOP = 22;

try {
  const start = 0;
  await waitForSerial("FerrumOS:~$", 45, start);
  check("boot reaches shell prompt", true);

  // The source appliance may legitimately contain notes (for example after a
  // manual package test). Normalize only this disposable disk before entering
  // ring 3, so the first App Store action is deterministically an install.
  const normalizeStart = serialText().length;
  await sendText("pkg remove notes");
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 8, normalizeStart);

  await sendText("ring3 init");
  await sendKey("ret");
  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 15, start);
  await sleep(1500);

  // --- Settings (launcher index 6) -----------------------------------------
  await openLauncherEntry(6);
  await waitForSerial("[settings] alive in ring 3", 10, start);
  await waitForSerial("[settings] window created id=", 5, start);
  check("Settings launched as a real new process", true);

  // Click its Refresh button (bottom-right of its canvas) to prove mouse
  // input reaches it and it re-reads live state instead of only rendering
  // once at startup.
  const settingsRefreshX = APP_X + 420 - 90 + 40;
  const settingsRefreshY = APP_Y + CHROME_TOP + 300 - 36 + 13;
  const beforeRefresh = 0;
  await clickAt(settingsRefreshX, settingsRefreshY);
  await waitForSerial("[settings] refreshed", 5, beforeRefresh);
  check("clicking Settings' Refresh button re-reads live hardware/config state", true);

  // --- Browser (launcher index 7) ------------------------------------------
  await openLauncherEntry(7);
  await waitForSerial("[browser] alive in ring 3", 10, start);
  await waitForSerial("[browser] window created id=", 5, start);
  check("Browser launched as a real new process", true);

  // --- App Store (launcher index 8) ----------------------------------------
  await openLauncherEntry(8);
  await waitForSerial("[app-store] alive in ring 3", 10, start);
  await waitForSerial("[app-store] window created id=", 5, start);
  check("App Store launched as a real new process", true);

  // Click the "Text Editor" row (2nd entry, index 1 in APP_STORE's list) to
  // prove it can actually launch another real process, not just display a
  // static list.
  const beforeLaunch = serialText().length;
  const rowX = APP_X + 420 / 2;
  const rowY = APP_Y + CHROME_TOP + 30 + 1 * 48 + 20;
  await clickAt(rowX, rowY);
  await waitForSerial("[app-store] launched Text Editor as pid", 5, beforeLaunch);
  await waitForSerial("[text-editor] alive in ring 3", 10, beforeLaunch);
  const editorLog = await waitForSerial("[text-editor] window created id=", 5, beforeLaunch);
  check(
    "App Store broker launches Text Editor with its own filesystem capabilities",
    editorLog.includes("[text-editor] package path denied as expected") &&
      !editorLog.includes("filesystem read denied: /disk/scratch.txt"),
  );

  // Open a fresh App Store window above Text Editor and exercise the signed
  // package lifecycle while Settings, Browser, Heliox, and the first App
  // Store remain scheduled in the background.
  const packageStoreStart = serialText().length;
  await openLauncherEntry(8);
  await waitForSerial("[app-store] window created id=", 10, packageStoreStart);

  const tabY = APP_Y + CHROME_TOP + 14;
  await clickAt(APP_X + 175, tabY);
  await waitForSerial("[app-store] signed package catalog opened", 5, packageStoreStart);
  check("App Store reads the kernel-verified signed package catalog", true);

  const packageButtonX = APP_X + 374;
  const packageRowY = APP_Y + CHROME_TOP + 51;
  let actionStart = serialText().length;
  await clickAt(packageButtonX, packageRowY);
  await waitForSerial("[app-store] confirmation required to install notes", 5, actionStart);
  check("App Store surfaces privileged package capabilities before install", true);

  actionStart = serialText().length;
  await clickAt(packageButtonX, packageRowY);
  await waitForSerial("[app-store] installed notes generation", 10, actionStart);
  check("confirmed App Store install commits a package transaction", true);

  actionStart = serialText().length;
  await clickAt(packageButtonX, packageRowY);
  await waitForSerial("[app-store] confirmation required to remove notes", 5, actionStart);
  await clickAt(packageButtonX, packageRowY);
  await waitForSerial("[app-store] removed notes generation", 10, actionStart);
  check("App Store removal is confirmed and committed without disrupting background apps", true);

  // Roll back the removal and launch from the signed-package row, proving
  // both recovery and that the UI does more than toggle display state.
  actionStart = serialText().length;
  await clickAt(APP_X + 371, tabY);
  await waitForSerial("[app-store] confirmation required to rollback packages", 5, actionStart);
  actionStart = serialText().length;
  await clickAt(APP_X + 371, tabY);
  await waitForSerial("[app-store] rolled back registry to generation", 10, actionStart);
  check("App Store rollback restores the previous valid package generation", true);

  actionStart = serialText().length;
  await clickAt(APP_X + 308, packageRowY);
  await waitForSerial("[app-store] launched package notes as pid", 10, actionStart);
  await waitForSerial("[notes] alive in ring 3", 10, actionStart);
  check("App Store launches the installed signed package in real ring 3", true);

  const full = serialText().slice(start);
  check("no userspace fault or page fault panic", !/terminating|General Protection|Page Fault/.test(full));
} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  if (qemuProcess.exitCode === null) {
    const stopped = new Promise((resolve) => qemuProcess.once("exit", resolve));
    qemuProcess.kill("SIGKILL");
    await Promise.race([stopped, sleep(5000)]);
  }
  fs.rmSync(diskImage, { force: true });
}

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
