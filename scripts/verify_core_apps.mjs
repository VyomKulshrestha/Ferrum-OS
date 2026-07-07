// ============================================================================
// FerrumOS - Core App Suite Verification (Text Editor, Calculator, File Manager)
// ============================================================================
// Proves the launcher can spawn *real* new ELF processes (not just the 3
// kernel-drawn built-ins) via `crate::process::spawn_elf`, and that each
// app actually works end to end on the D1 app-window framework:
//   - Text Editor: type text, save with Escape, confirm it wrote to disk.
//   - Calculator: click a sequence of buttons, confirm the arithmetic
//     pipeline (mouse-down -> button hit-test -> compute) is correct.
//   - File Manager: list /disk, click a known file, confirm it previews
//     the right content.
//
// Mouse interaction uses cumulative relative deltas from the cursor's
// known boot position, same technique as verify_desktop_shell.mjs.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45484);
const serialLog = path.join(repo, "target", "core-apps-verify-serial.log");
const screenshotPath = path.join(repo, "target", "core-apps-verify.ppm");
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

console.log("[test] starting QEMU for core app suite verification...");
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

let cursorX = 512, cursorY = 384;
async function moveMouseTo(tx, ty) {
  await mon(`mouse_move ${tx - cursorX} ${ty - cursorY}`, 150);
  cursorX = tx; cursorY = ty;
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
  return { width, height, pixelAt(x, y) { const idx = dataStart + (y * width + x) * 3; return { r: buf[idx], g: buf[idx + 1], b: buf[idx + 2] }; } };
}
async function screendump() {
  fs.rmSync(screenshotPath, { force: true });
  await mon(`screendump ${screenshotPath}`, 500);
  if (!fs.existsSync(screenshotPath)) throw new Error("screendump did not produce a file");
  return parsePpm(fs.readFileSync(screenshotPath));
}

// Taskbar layout mirrored from src/gui/desktop.rs::compute_taskbar_layout.
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

// Launcher popup geometry mirrored from desktop.rs::launcher_rect / launcher_entry_rect.
// LAUNCHER_ENTRIES = [Terminal, System Monitor, Heliox Assistant, Text Editor, Calculator, File Manager]
const LAUNCHER_ENTRY_H = 28, LAUNCHER_PADDING = 8, LAUNCHER_ENTRY_W = 180;
const LAUNCHER_ENTRY_COUNT = 6;
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

// App windows always spawn at this fixed position (src/gui/app_window.rs).
const APP_X = 150, APP_Y = 150;
const CHROME_SIDE = 2, CHROME_TOP = 22;
const TITLE_BTN_SIZE = 16, TITLE_BTN_GAP = 4;
const closeBtnRect = (w) => [APP_X + w - (TITLE_BTN_SIZE + 4), APP_Y + 2, TITLE_BTN_SIZE, TITLE_BTN_SIZE];
async function closeAppWindow(canvasW) {
  // Total window width = canvas + 2*CHROME_SIDE.
  const totalW = canvasW + 2 * CHROME_SIDE;
  const [cx, cy] = closeBtnRect(totalW);
  await clickAt(cx + 8, cy + 8);
  await sleep(400);
}

try {
  await waitForSerial("FerrumOS:~$", 35);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Pre-create a known file so File Manager's listing is deterministic
  // regardless of whatever else this shared bootimage's disk accumulated
  // from other verify scripts.
  await sendText("write /disk/fm_test.txt hello");
  await sendKey("ret");
  await sleep(300);

  await sendText("ring3 init");
  await sendKey("ret");
  // Wait for an actual readiness marker rather than a fixed sleep -
  // heliox-daemon's heap grew from 16MB to 64MB to support real model
  // checkpoints (see REPORT.md's Phase D4 section), and its ELF's BSS is
  // zeroed eagerly at spawn time, so a fixed 2s budget sized for the old
  // heap no longer reliably covers spawn-to-ready.
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 30, start);
  await sleep(1000);

  // --- Text Editor ------------------------------------------------------
  await openLauncherEntry(3);
  await waitForSerial("[text-editor] alive in ring 3", 10, start);
  await waitForSerial("[text-editor] window created id=", 5, start);
  check("Text Editor launched as a real new process", true);

  // Text Editor's window is focused immediately after CreateWindow, so
  // typed keys go straight to it.
  const beforeType = serialText().length;
  await sendText("hi");
  await sendKey("ret"); // newline in the buffer, not a save
  await sendKey("ret");
  await sleep(200);
  const escOffset = serialText().length;
  await mon("sendkey esc", 200);
  await waitForSerial("[text-editor] saved", 5, escOffset);
  check("Text Editor saves on Escape", true);

  await closeAppWindow(480);

  // Relaunch Text Editor as a brand new process and confirm it reads the
  // saved content back from disk - proof the save actually persisted,
  // not just that the same process's own self-report can be trusted.
  // (Re-running a shell command like `cat` isn't an option here: once
  // `ring3 init` has run, the plain shell prompt never processes another
  // typed line - see D1's investigation into why "desktop" couldn't be
  // typed as a follow-up command either.)
  const beforeReload = serialText().length;
  await openLauncherEntry(3);
  await waitForSerial("[text-editor] loaded:", 10, beforeReload);
  const reloadLog = await waitForSerial("[text-editor] window created id=", 5, beforeReload);
  const loadedLine = serialText().slice(beforeReload).split("\n").find(l => l.includes("[text-editor] loaded:"));
  check("relaunching Text Editor reads the saved text back from disk", !!loadedLine && loadedLine.includes("hi"),
    loadedLine);

  await closeAppWindow(480);

  // --- Calculator ---------------------------------------------------------
  await openLauncherEntry(4);
  await waitForSerial("[calculator] alive in ring 3", 10, start);
  await waitForSerial("[calculator] window created id=", 5, start);
  check("Calculator launched as a real new process", true);

  // Calculator canvas: 200x280, DISPLAY_H=50, 4 cols x 5 rows, BTN_W=50, BTN_H=46.
  const CW = 200, DISPLAY_H = 50, BTN_W = 50, BTN_H = 46;
  const btnCenter = (row, col) => {
    const localX = col * BTN_W + BTN_W / 2;
    const localY = DISPLAY_H + row * BTN_H + BTN_H / 2;
    return [APP_X + CHROME_SIDE + localX, APP_Y + CHROME_TOP + localY];
  };
  // LABELS is row-major [7,8,9,/, 4,5,6,*, 1,2,3,-, 0,.,=,+], so "5" is
  // row 1 col 1, not row 1 col 0 (that's "4").
  const calcBeforeStart = serialText().length;
  await clickAt(...btnCenter(1, 1)); // "5"
  await sleep(200);
  await clickAt(...btnCenter(3, 3)); // "+"
  await sleep(200);
  await clickAt(...btnCenter(2, 2)); // "3"
  await sleep(200);
  await clickAt(...btnCenter(3, 2)); // "="
  await sleep(300);

  const calcLog = serialText().slice(calcBeforeStart);
  check("calculator registered the '5' press", calcLog.includes("[calculator] pressed 5"));
  check("calculator registered the '+' press", calcLog.includes("[calculator] pressed +"));
  check("calculator registered the '3' press", calcLog.includes("[calculator] pressed 3"));
  check("calculator computed 5+3=8 correctly", calcLog.includes("[calculator] result=8"), calcLog);

  await closeAppWindow(CW);

  // --- File Manager ---------------------------------------------------
  await openLauncherEntry(5);
  await waitForSerial("[file-manager] alive in ring 3", 10, start);
  const listingLog = await waitForSerial("[file-manager] listing /disk count=", 5, start);
  check("File Manager launched as a real new process and listed /disk", true);

  const listingStart = serialText().indexOf("[file-manager] listing /disk count=", start);
  const listingText = serialText().slice(listingStart);
  const entryLines = [...listingText.matchAll(/\[file-manager\] entry ([df]) (.+)/g)]
    .map(m => ({ kind: m[1], name: m[2].trim() }))
    // Only take the first listing's worth of entries (stop at the next
    // "listing" header, in case the app re-lists later).
    .slice(0, 200);
  // Find where "count=" is to know how many entries belong to this listing.
  const countMatch = listingLog.match(/count=(\d+)/);
  const entryCount = countMatch ? parseInt(countMatch[1], 10) : entryLines.length;
  const firstListing = entryLines.slice(0, entryCount);
  const targetIdx = firstListing.findIndex(e => e.kind === "f" && e.name === "fm_test.txt");
  check("fm_test.txt appears in the /disk listing", targetIdx >= 0, JSON.stringify(firstListing));

  if (targetIdx >= 0) {
    const LINE_HEIGHT = 18;
    const rowCenterY = LINE_HEIGHT * (targetIdx + 1) + LINE_HEIGHT / 2;
    const clickX = APP_X + CHROME_SIDE + 30;
    const clickY = APP_Y + CHROME_TOP + rowCenterY;
    const beforePreview = serialText().length;
    await clickAt(clickX, clickY);
    await sleep(400);
    await waitForSerial("[file-manager] previewing /disk/fm_test.txt", 5, beforePreview);
    check("clicking fm_test.txt opens its preview", true);
  }

  await closeAppWindow(420);

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
