// ============================================================================
// FerrumOS - Heliox Assistant Panel Verification
// ============================================================================
// Proves the kernel-hardcoded WindowType::AgentHud retirement actually
// works end to end as a real D1 app:
//   1. heliox-assistant-panel auto-launches (missing-config check, mirroring
//      the old AgentHud auto-spawn) and its window is created as a real
//      process window, not kernel-drawn.
//   2. Its setup wizard writes /disk/heliox/config.json and wakes the
//      daemon via CONFIG_UPDATED, same contract as before, just driven by
//      app code instead of compositor.rs.
//   3. A normal chat message sent from the app (GOAL: over IPC) reaches
//      the orchestrator, and the orchestrator's "thinking"/"done" chat
//      updates (CHAT: over IPC, a new channel distinct from the general
//      TELEMETRY stream) come back and are visible to the app.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45487);
const serialLog = path.join(repo, "target", "assistant-panel-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");

// Deliberately no secondary disk drive attached here (unlike
// verify_real_model.mjs): this test never waits for an actual inference
// response (that's verify_real_model.mjs's job - see the comment further
// down), so /disk/heliox/ falls back to RamFS, which resets on every boot.
// That's important, not just simpler - a persistent disk's config.json
// would carry over between runs, and the assistant panel's auto-launch
// check happens during raw kernel boot (main.rs, before the interactive
// shell prompt even exists), so a "rm" typed at the prompt afterward would
// always be too late to affect it.

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
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
}

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon"
}));
async function sendKey(k, mon) { mon.write(`sendkey ${k}\n`); await sleep(45); }
async function sendText(t, mon) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch), mon);
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase(), mon);
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
async function typeLine(text, mon) {
  await sendText(text, mon);
  await sendKey("ret", mon);
  await sleep(250);
}

const qemuArgs = [
  "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-vga", "std",
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");

console.log("[test] starting QEMU for assistant panel verification...");
let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

try {
  const start = serialText().length;
  await waitForSerial("FerrumOS:~$", 45, start);
  check("boot reaches shell prompt", true);

  await sendText("ring3 init", monitor);
  await sendKey("ret", monitor);

  // No config exists now - the panel should auto-launch itself and open
  // its window, exactly like the old AgentHud auto-spawn. heliox-daemon
  // stays idle (no autonomous THINK loop) until config.json actually
  // exists (see config.rs's `file_existed` gate), so this isn't racing
  // against real inference the way it would before that fix.
  await waitForSerial("[heliox-assistant-panel] alive in ring 3", 30, start);
  await waitForSerial("[heliox-assistant-panel] window created id=", 10, start);
  check("assistant panel auto-launched as a real app window on missing config", true);

  await sleep(1500); // let it actually gain focus and start polling input

  // Fast path through the wizard: Local -> tiny.
  await typeLine("local", monitor);
  await typeLine("tiny", monitor);

  // `afterSetup` is everything from `start` through this point, which
  // also contains the daemon's *earlier* startup line
  // "[heliox-daemon] active provider: auto" (from before setup ran) -
  // matching the general "active provider: (\S+)" pattern against the
  // whole span would find that one first. Anchor on the specific
  // "config reloaded" line's own value instead.
  const afterSetup = await waitForSerial("[heliox-daemon] config reloaded via IPC, active provider:", 15, start);
  const provMatch = afterSetup.match(/config reloaded via IPC, active provider: (\S+)/);
  check(
    "setup wizard (driven from the app, not the kernel) wrote config and daemon reloaded it",
    !!provMatch && provMatch[1].startsWith("local-"),
    provMatch ? provMatch[1] : "no match"
  );

  // Now exercise the chat path: type a message, confirm the daemon
  // receives it as a real IPC goal. `ipc_poll()` runs on every tick
  // regardless of `tick_interval` (only the THINK/inference step itself is
  // gated by it), so this doesn't have to wait for a tick-interval window.
  // Whether the agent's *response* is coherent is verify_real_model.mjs's
  // job - it already covers that end to end without the added variable of
  // driving it through simulated keystrokes into a second real process.
  // sendText/keyMap below only knows lowercase key names (QEMU's monitor
  // "sendkey" takes a raw key, not a shifted character), so the message
  // must be all-lowercase or it would type differently than it reads here.
  await typeLine("tell me something interesting", monitor);
  await waitForSerial("[heliox-daemon] New goal set via IPC: tell me something interesting", 10, start);
  check("chat message reached the daemon as a goal over IPC", true);

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
