// ============================================================================
// FerrumOS - D1 App Window Framework Verification
// ============================================================================
// Proves the generic app-window primitive works end to end for a process
// that is NOT one of the kernel's 4 hardcoded window types:
//   1. `gui-smoke-test` calls CreateWindow + PresentWindow with a known
//      fill color; a QEMU screendump is sampled to confirm those pixels
//      actually reached the framebuffer (not just that the syscalls
//      returned success).
//   2. A real keystroke sent through the QEMU monitor is delivered back to
//      the app via PollWindowInput, proving the input path (not just the
//      draw path) works for an arbitrary process.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45482);
const serialLog = path.join(repo, "target", "app-window-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const screenshotPath = path.join(repo, "target", "app-window-verify.ppm");
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

console.log("[test] starting QEMU for app-window framework verification...");
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

/// Parse a binary PPM (P6) file into { width, height, pixelAt(x,y) }.
function parsePpm(buf) {
  if (buf[0] !== 0x50 || buf[1] !== 0x36) { // "P6"
    throw new Error("not a P6 PPM file");
  }
  let offset = 2;
  const tokens = [];
  while (tokens.length < 3) {
    while (buf[offset] === 0x20 || buf[offset] === 0x0a || buf[offset] === 0x0d || buf[offset] === 0x09) offset++;
    if (buf[offset] === 0x23) { // '#' comment line
      while (buf[offset] !== 0x0a) offset++;
      continue;
    }
    let start = offset;
    while (buf[offset] > 0x20) offset++;
    tokens.push(buf.slice(start, offset).toString("ascii"));
  }
  offset += 1; // single whitespace byte after maxval
  const [width, height] = [parseInt(tokens[0], 10), parseInt(tokens[1], 10)];
  const dataStart = offset;
  return {
    width,
    height,
    pixelAt(x, y) {
      const idx = dataStart + (y * width + x) * 3;
      return { r: buf[idx], g: buf[idx + 1], b: buf[idx + 2] };
    },
  };
}

try {
  await waitForSerial("FerrumOS:~$", 35);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Write the app-window test trigger file.
  await sendText("write /tmp/gui_test 1");
  await sendKey("ret");
  await sleep(400);

  // Start init, which spawns gui-smoke-test (since the flag is present).
  await sendText("ring3 init");
  await sendKey("ret");

  const createdLog = await waitForSerial("[gui-smoke-test] window created id=", 30, start);
  check("gui-smoke-test created an app window", true);
  const createOffset = serialText().indexOf("[gui-smoke-test] window created id=", start);

  const m = createdLog.match(/window created id=(\d+) canvas_w=(\d+) canvas_h=(\d+)/);
  check("parsed window id/canvas dimensions from log", !!m);
  const canvasW = m ? parseInt(m[2], 10) : 0;
  const canvasH = m ? parseInt(m[3], 10) : 0;

  await waitForSerial("[gui-smoke-test] presented fill r=17 g=102 b=204 res=0", 10, createOffset);
  check("PresentWindow accepted the fill buffer (res=0)", true);

  // These must match src/gui/app_window.rs's DEFAULT_APP_X/Y and
  // src/gui/window.rs's CHROME_SIDE/CHROME_TOP constants.
  const CHROME_SIDE = 2;
  const CHROME_TOP = 22;
  const DEFAULT_APP_X = 150;
  const DEFAULT_APP_Y = 150;

  // Note: this deliberately does NOT type "desktop" at the shell. The
  // compositor renders and processes input independently of the
  // "desktop" command: heliox-daemon's own ambient loop periodically
  // calls SYS_HUD_UPDATE, which pumps `cursor::process_input()` +
  // `compositor::render()` on its own (src/syscall/hud.rs). Waiting for
  // one of those cycles is enough to get both a real framebuffer frame
  // and real input delivery. The shell now genuinely shares the CPU with
  // heliox-daemon after `ring3 init` instead of abandoning the shell
  // prompt one-way (see REPORT.md's shell/agent coexistence fix), so
  // that ambient pump makes slower wall-clock progress than the old
  // exclusive-CPU baseline this wait was sized for.
  await sleep(6000);

  fs.rmSync(screenshotPath, { force: true });
  await mon(`screendump ${screenshotPath}`, 500);

  check("screendump file was written", fs.existsSync(screenshotPath));
  if (fs.existsSync(screenshotPath)) {
    const ppm = parsePpm(fs.readFileSync(screenshotPath));
    // Sample well inside the canvas (avoid edges/rounding) rather than at (0,0).
    const sampleX = DEFAULT_APP_X + CHROME_SIDE + Math.min(10, canvasW - 1);
    const sampleY = DEFAULT_APP_Y + CHROME_TOP + Math.min(10, canvasH - 1);
    const px = ppm.pixelAt(sampleX, sampleY);
    console.log(`[test] sampled pixel at (${sampleX},${sampleY}): r=${px.r} g=${px.g} b=${px.b}`);
    check(
      `framebuffer shows the app's presented fill color at (${sampleX},${sampleY})`,
      px.r === 0x11 && px.g === 0x66 && px.b === 0xcc,
      `got r=${px.r} g=${px.g} b=${px.b}`
    );
  }

  // CreateWindow focuses the new app window immediately, and the compositor
  // now preserves focus on it across `spawn_demo_windows()` (triggered by
  // entering "desktop" above) rather than always reverting to the
  // terminal — so the app window is still focused here without needing to
  // click it (QEMU's PS/2 mouse is relative-delta only, which would make
  // clicking at a precise absolute coordinate through the monitor unreliable).
  const beforeKey = serialText().length;
  await sendKey("q");
  await waitForSerial("[gui-smoke-test] received key ascii=113", 10, beforeKey);
  check("app window received the 'q' keystroke via PollWindowInput", true);
  await waitForSerial("[gui-smoke-test] exit key received", 5, beforeKey);
  check("gui-smoke-test exited cleanly after receiving input", true);

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
