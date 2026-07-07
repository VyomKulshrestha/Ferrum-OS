// ============================================================================
// FerrumOS - Desktop Shell Verification (wallpaper, taskbar, launcher,
// minimize/maximize)
// ============================================================================
// Proves the desktop reads as a real shell, not a fixed 3-window demo:
//   1. The debug measurement grid is gone from the background.
//   2. The taskbar has a Start button, an Exit button, and (separately
//      verified) one entry per open window instead of 3 hardcoded ones.
//   3. Clicking a window's minimize button hides it (still gone from the
//      framebuffer) and its taskbar entry can bring it back.
//   4. Clicking a window's maximize button grows it to fill most of the
//      screen.
//   5. The Start button opens a launcher that can relaunch a closed
//      built-in window.
//
// Mouse interaction is done via QEMU's relative PS/2 `mouse_move` deltas
// from the cursor's known boot position (512, 384) - this driver applies
// deltas as literal pixels with no acceleration curve (see
// `cursor::process_input`), so cumulative relative moves land at exact
// absolute coordinates deterministically.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45483);
const serialLog = path.join(repo, "target", "desktop-shell-verify-serial.log");
const screenshotPath = path.join(repo, "target", "desktop-shell-verify.ppm");
const visible = process.argv.includes("--visible");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function connectMonitor() {
  for (let i = 0; i < 60; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const sock = net.createConnection({ port, host: "127.0.0.1" }, () => resolve(sock));
        sock.once("error", reject);
      });
    } catch {
      await sleep(250);
    }
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

const whpxArgs = [
  "-accel", "whpx,kernel-irqchip=off",
  "-cpu", "Haswell",
  "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-vga", "std",
  "-no-reboot",
];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for desktop shell verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });

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
    "-vga", "std",
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

// Cursor tracking: the driver starts at (512, 384) and applies relative
// deltas as literal pixels (src/gui/cursor.rs), so we can track absolute
// position purely in JS and always know exactly where a click will land.
let cursorX = 512;
let cursorY = 384;
async function moveMouseTo(tx, ty) {
  const dx = tx - cursorX;
  const dy = ty - cursorY;
  await mon(`mouse_move ${dx} ${dy}`, 150);
  cursorX = tx;
  cursorY = ty;
}
async function clickAt(tx, ty) {
  await moveMouseTo(tx, ty);
  await mon("mouse_button 1", 150);
  await mon("mouse_button 0", 200);
}

function parsePpm(buf) {
  if (buf[0] !== 0x50 || buf[1] !== 0x36) throw new Error("not a P6 PPM file");
  let offset = 2;
  const tokens = [];
  while (tokens.length < 3) {
    while (buf[offset] === 0x20 || buf[offset] === 0x0a || buf[offset] === 0x0d || buf[offset] === 0x09) offset++;
    if (buf[offset] === 0x23) { while (buf[offset] !== 0x0a) offset++; continue; }
    let start = offset;
    while (buf[offset] > 0x20) offset++;
    tokens.push(buf.slice(start, offset).toString("ascii"));
  }
  offset += 1;
  const [width, height] = [parseInt(tokens[0], 10), parseInt(tokens[1], 10)];
  const dataStart = offset;
  return {
    width, height,
    pixelAt(x, y) {
      const idx = dataStart + (y * width + x) * 3;
      return { r: buf[idx], g: buf[idx + 1], b: buf[idx + 2] };
    },
  };
}

async function screendump() {
  fs.rmSync(screenshotPath, { force: true });
  await mon(`screendump ${screenshotPath}`, 500);
  if (!fs.existsSync(screenshotPath)) throw new Error("screendump did not produce a file");
  return parsePpm(fs.readFileSync(screenshotPath));
}

// Layout constants mirrored from src/gui/desktop.rs::compute_taskbar_layout
// and src/gui/window.rs's title-bar button geometry. Kept in sync manually
// (same tradeoff the Rust code itself documents for why it centralized
// this into one function instead of duplicating magic numbers).
const FB_W = 1024, FB_H = 768;
const START_BTN_W = 70, EXIT_BTN_W = 70, WINDOW_SLOT_W = 110, SLOT_GAP = 6;
const GROUP_GAP = 15, DOCK_SIDE_PADDING = 15, DOCK_H = 40, BTN_H = 24, BTN_Y_INSET = 8;
const MAX_TASKBAR_SLOTS = 4;
const windowsW = MAX_TASKBAR_SLOTS * WINDOW_SLOT_W + (MAX_TASKBAR_SLOTS - 1) * SLOT_GAP;
const DOCK_W = DOCK_SIDE_PADDING * 2 + START_BTN_W + GROUP_GAP + windowsW + GROUP_GAP + EXIT_BTN_W;
const DOCK_X = Math.floor((FB_W - DOCK_W) / 2);
const DOCK_Y = FB_H - DOCK_H - 10;
const startRect = [DOCK_X + DOCK_SIDE_PADDING, DOCK_Y + BTN_Y_INSET, START_BTN_W, BTN_H];
const windowSlotRects = [];
{
  let cx = startRect[0] + START_BTN_W + GROUP_GAP;
  for (let i = 0; i < MAX_TASKBAR_SLOTS; i++) {
    windowSlotRects.push([cx, DOCK_Y + BTN_Y_INSET, WINDOW_SLOT_W, BTN_H]);
    cx += WINDOW_SLOT_W + SLOT_GAP;
  }
}
const exitRect = [DOCK_X + DOCK_W - DOCK_SIDE_PADDING - EXIT_BTN_W, DOCK_Y + BTN_Y_INSET, EXIT_BTN_W, BTN_H];
const rectCenter = ([x, y, w, h]) => [x + Math.floor(w / 2), y + Math.floor(h / 2)];

// Launcher popup geometry mirrored from desktop.rs::launcher_rect / launcher_entry_rect.
const LAUNCHER_ENTRY_H = 28, LAUNCHER_PADDING = 8, LAUNCHER_ENTRY_W = 180;
// Terminal, System Monitor, Heliox Assistant, Text Editor, Calculator,
// File Manager, Settings, Browser, App Store
// (src/gui/compositor.rs::LAUNCHER_ENTRIES).
const launcherEntries = 9;
const launcherW = LAUNCHER_PADDING * 2 + LAUNCHER_ENTRY_W;
const launcherH = LAUNCHER_PADDING * 2 + launcherEntries * LAUNCHER_ENTRY_H;
const launcherX = startRect[0];
const launcherY = DOCK_Y - (launcherH + 8);
const launcherEntryRect = (i) => [launcherX + LAUNCHER_PADDING, launcherY + LAUNCHER_PADDING + i * LAUNCHER_ENTRY_H, launcherW - LAUNCHER_PADDING * 2, LAUNCHER_ENTRY_H - 4];

// SystemMonitor's fixed spawn geometry (src/gui/compositor.rs::spawn_demo_windows).
const SYSMON_X = 100, SYSMON_Y = 100, SYSMON_W = 300, SYSMON_H = 200;
const TITLE_BTN_SIZE = 16, TITLE_BTN_GAP = 4;
const closeBtnRect = (x, y, w) => [x + w - (TITLE_BTN_SIZE + 4), y + 2, TITLE_BTN_SIZE, TITLE_BTN_SIZE];
const maximizeBtnRect = (x, y, w) => { const [cx, cy] = closeBtnRect(x, y, w); return [cx - (TITLE_BTN_SIZE + TITLE_BTN_GAP), cy, TITLE_BTN_SIZE, TITLE_BTN_SIZE]; };
const minimizeBtnRect = (x, y, w) => { const [mx, my] = maximizeBtnRect(x, y, w); return [mx - (TITLE_BTN_SIZE + TITLE_BTN_GAP), my, TITLE_BTN_SIZE, TITLE_BTN_SIZE]; };

try {
  await waitForSerial("FerrumOS:~$", 35);
  check("boot reaches shell prompt", true);

  const start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");

  // Give the daemon's ambient loop time to spin up and pump at least one
  // compositor render cycle (via SYS_HUD_UPDATE - see D1's investigation
  // into why "desktop" isn't actually reachable as a shell command after
  // ring3 init). Wait for an actual readiness marker rather than a fixed
  // sleep - heliox-daemon's heap grew from 16MB to 64MB to support real
  // model checkpoints (see REPORT.md's Phase D4 section), and the ELF's
  // BSS is zeroed eagerly at spawn time, so a fixed 2s budget that was
  // fine for the old heap size no longer reliably covers spawn-to-ready.
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 30, start);
  await sleep(1000);

  // --- 1. Wallpaper: the debug grid is gone ---------------------------
  let ppm = await screendump();
  const bgA = ppm.pixelAt(64, 500);   // was on a grid line under the old 32px grid
  const bgB = ppm.pixelAt(70, 500);   // was off the grid line, same y
  check(
    "background has no visible measurement grid",
    bgA.r === bgB.r && bgA.g === bgB.g && bgA.b === bgB.b,
    `on-old-gridline=(${bgA.r},${bgA.g},${bgA.b}) off-old-gridline=(${bgB.r},${bgB.g},${bgB.b})`
  );

  // --- 2. Taskbar: Start and Exit buttons exist at computed positions --
  const startBorder = ppm.pixelAt(startRect[0], startRect[1]);
  const exitBorder = ppm.pixelAt(exitRect[0], exitRect[1]);
  check(
    "Start button renders at its computed dock position",
    startBorder.r === 0x44 && startBorder.g === 0x44 && startBorder.b === 0x44,
    `got (${startBorder.r},${startBorder.g},${startBorder.b}) at (${startRect[0]},${startRect[1]})`
  );
  check(
    "Exit button renders at its computed dock position",
    exitBorder.r === 0x44 && exitBorder.g === 0x44 && exitBorder.b === 0x44,
    `got (${exitBorder.r},${exitBorder.g},${exitBorder.b}) at (${exitRect[0]},${exitRect[1]})`
  );

  // --- 3. Minimize: click SystemMonitor's minimize button --------------
  const sysmonMidPx = ppm.pixelAt(SYSMON_X + 20, SYSMON_Y + 60);
  check("SystemMonitor window is visible before minimizing", sysmonMidPx.r === 0x1e && sysmonMidPx.g === 0x1e && sysmonMidPx.b === 0x1e,
    `got (${sysmonMidPx.r},${sysmonMidPx.g},${sysmonMidPx.b})`);

  const [minX, minY] = minimizeBtnRect(SYSMON_X, SYSMON_Y, SYSMON_W).slice(0, 2);
  await clickAt(minX + 8, minY + 8);
  await sleep(600);

  ppm = await screendump();
  const afterMinimize = ppm.pixelAt(SYSMON_X + 20, SYSMON_Y + 60);
  check(
    "SystemMonitor is hidden from the framebuffer after clicking minimize",
    !(afterMinimize.r === 0x1e && afterMinimize.g === 0x1e && afterMinimize.b === 0x1e),
    `got (${afterMinimize.r},${afterMinimize.g},${afterMinimize.b})`
  );

  // --- Restore via its taskbar entry. Clicking SystemMonitor's minimize
  // button first resolves the click against it (hit-testing works by
  // id/z-order, not slot), which also raises it to the front of the
  // window list like any other click. A fresh boot with no
  // /disk/heliox/config.json also auto-spawns the Agent HUD as a 3rd
  // window (src/gui/compositor.rs::spawn_demo_windows), so the open set
  // is [Terminal, AgentHud, SystemMonitor] after minimizing - SystemMonitor
  // is now last, i.e. taskbar slot 2.
  const [slot2x, slot2y] = rectCenter(windowSlotRects[2]);
  await clickAt(slot2x, slot2y);
  await sleep(600);
  ppm = await screendump();
  const afterRestore = ppm.pixelAt(SYSMON_X + 20, SYSMON_Y + 60);
  check(
    "clicking its taskbar entry restores the minimized window",
    afterRestore.r === 0x1e && afterRestore.g === 0x1e && afterRestore.b === 0x1e,
    `got (${afterRestore.r},${afterRestore.g},${afterRestore.b})`
  );

  // --- 4. Maximize: click SystemMonitor's maximize button ---------------
  const [maxX, maxY] = maximizeBtnRect(SYSMON_X, SYSMON_Y, SYSMON_W).slice(0, 2);
  await clickAt(maxX + 8, maxY + 8);
  await sleep(600);
  ppm = await screendump();
  // Far from the original 300x200 rect, well inside the desktop content area.
  const farPoint = ppm.pixelAt(700, 400);
  check(
    "maximize grows the window to fill most of the desktop",
    farPoint.r === 0x1e && farPoint.g === 0x1e && farPoint.b === 0x1e,
    `got (${farPoint.r},${farPoint.g},${farPoint.b}) at (700,400)`
  );

  // Restore it back down so it doesn't interfere with the launcher test below.
  await clickAt(maxX + 8, maxY + 8);
  await sleep(400);

  // --- 5. Launcher: close the Terminal, relaunch it from the Start menu -
  // Terminal is window id 2, spawned at (450,150,400,400).
  const TERM_X = 450, TERM_Y = 150, TERM_W = 400;
  const [closeX, closeY] = closeBtnRect(TERM_X, TERM_Y, TERM_W).slice(0, 2);
  await clickAt(closeX + 8, closeY + 8);
  await sleep(400);

  ppm = await screendump();
  const termGoneAt = ppm.pixelAt(TERM_X + 100, TERM_Y + 200);
  check("Terminal window closes when its close button is clicked", !(termGoneAt.r === 0x1a && termGoneAt.g === 0x1a && termGoneAt.b === 0x1a),
    `got (${termGoneAt.r},${termGoneAt.g},${termGoneAt.b})`);

  const [startX, startY] = rectCenter(startRect);
  await clickAt(startX, startY);
  await sleep(300);
  ppm = await screendump();
  const launcherBg = ppm.pixelAt(launcherX + 2, launcherY + 2);
  check("clicking Start opens the launcher popup", launcherBg.r === 0x18 && launcherBg.g === 0x1c && launcherBg.b === 0x28,
    `got (${launcherBg.r},${launcherBg.g},${launcherBg.b})`);

  const [termEntryX, termEntryY] = launcherEntryRect(0);
  await clickAt(termEntryX + 40, termEntryY + 12);
  await sleep(600);

  ppm = await screendump();
  const termBackAt = ppm.pixelAt(TERM_X + 100, TERM_Y + 200);
  check("launching Terminal from the Start menu reopens it", termBackAt.r === 0x1a && termBackAt.g === 0x1a && termBackAt.b === 0x1a,
    `got (${termBackAt.r},${termBackAt.g},${termBackAt.b})`);

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
