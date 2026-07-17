// ============================================================================
// FerrumOS - Keyboard Input Integrity Under Background Load Verification
// ============================================================================
// New audit finding (fresh scripts/audit_all_commands.mjs pass): with a
// background ring-3 app polling on its own timer (e.g. `notes`, launched via
// `pkg run notes`, which polls its window every 30ms), typing a shell command
// got silently corrupted - "pkg remove notes" arrived at the shell as
// "pkg remoes", an unrecognized subcommand, swallowing most of "remove" and
// all of "notes".
//
// Two real fixes landed from digging into this (see work.md):
//   1. Every scheduler context switch unconditionally did a synchronous,
//      interrupts-disabled serial_println! in
//      src/scheduler/mod.rs::resume_task. Gated behind an off-by-default
//      `sched-trace` Cargo feature - confirmed via A/B testing (feature on
//      vs off) to be the dominant contributor.
//   2. The shell's input loop (src/shell/mod.rs::shell_entry) only drained
//      one queued keystroke per scheduler turn even though
//      `yield_current_kernel_task` offers this loop's `hlt` up for
//      preemption on every timer tick regardless of pending input - changed
//      to drain everything queued per turn.
//
// What's NOT fully closed: a control run (typing the same text with no
// background task running at all - zero corruption) proves a background
// task's own wake cycle is the trigger. Even with both fixes above, this
// exact scenario (notes polling every 30ms, "pkg remove notes" typed via
// 45ms-spaced synthetic keystrokes) still deterministically loses one
// character ('v' or "ve" from "remove") on every run. Root cause: the PS/2
// 8042 controller has a single-byte output register - if a second scancode
// arrives before the CPU reads the first (i.e. while interrupts are
// disabled for a scheduler context-switch decision), the first is
// permanently overwritten at the hardware level, unrecoverable in software.
// Fully closing this needs either a system-wide interrupt-latency audit
// across the scheduler/syscall path or a more robust input-delivery design
// - a bigger undertaking than this pass, so it's tracked as a known open
// finding rather than silently declared fixed. This script documents both:
// it should NOT time out or see catastrophic corruption (the original,
// now-fixed symptom), but is expected to still fail its last two checks
// until that follow-up lands.
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
const serialLog = path.join(repo, "target", "keyboard-input-integrity-verify-serial.log");
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

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`appliance disk image not found: ${diskImage} - run scripts/make-appliance.ps1 first`);

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for keyboard input integrity verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) { monitor.write(`${cmd}\n`); await sleep(waitMs); }
const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon",
  "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe", ",": "comma",
}));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

try {
  let start = 0;
  await waitForSerial("FerrumOS:~$", 45, start);
  check("boot reaches shell prompt", true);

  // Make sure notes is installed regardless of what a prior run of this
  // same script (which removes it further down) left on the persistent
  // appliance disk image.
  const beforeInstall = serialText().length;
  await sendText("pkg install notes");
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, beforeInstall);
  check("notes is installed", true);

  // Launch notes in the background - same trigger as the audit finding.
  // `pkg run` is enough to get its 30ms poll loop actively running in ring 3.
  const beforeRun = serialText().length;
  await sendText("pkg run notes");
  await sendKey("ret");
  await waitForSerial("launched notes as pid", 10, beforeRun);
  check("notes launched in the background", true);
  await sleep(500); // let its poll loop get going

  // Now type the exact command that previously got corrupted while notes
  // was actively polling in the background.
  const beforeRemove = serialText().length;
  await sendText("pkg remove notes");
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, beforeRemove);
  const removeOutput = serialText().slice(beforeRemove);
  check(
    "'pkg remove notes' typed while notes polls in the background arrives intact",
    removeOutput.includes("removed notes"),
    removeOutput.includes("removed notes") ? "" : `got: ${JSON.stringify(removeOutput.slice(0, 300))}`
  );
  check(
    "no 'unknown subcommand' corruption (the original symptom)",
    !/unknown subcommand/.test(removeOutput)
  );

  const full = serialText().slice(start);
  check("no userspace fault or page fault panic", !/terminating|General Protection|Page Fault/.test(full));
} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log("\n" + results.join("\n"));
