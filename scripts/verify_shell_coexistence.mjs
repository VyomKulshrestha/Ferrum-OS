// ============================================================================
// FerrumOS - Shell/Agent Coexistence Verification
// ============================================================================
// Before this fix, `ring3 init` (and `pkg run`) permanently abandoned the
// interactive shell prompt one-way (`process::enter_registered` used to do
// the ring0->ring3 switch itself, never returning) - the exact same class of
// bug found and fixed for the desktop GUI loop (see model.md/REPORT.md D11),
// just for the plain shell instead. This proves the fix: the shell keeps
// accepting commands *after* dispatching heliox-daemon, and the daemon
// genuinely runs concurrently (not just a prompt that reappears cosmetically
// while the daemon never gets scheduled).
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45493);
const serialLog = path.join(repo, "target", "shell-coexistence-verify-serial.log");
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

console.log("[test] starting QEMU for shell/agent coexistence verification...");
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
async function runCommand(cmd, start) {
  await sendText(cmd);
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, start);
  await sleep(100);
}

try {
  let start = 0;
  await waitForSerial("FerrumOS:~$", 45, start);
  check("boot reaches shell prompt", true);

  // Configure a fast, deterministic local provider so heliox-daemon has
  // something real to log once it actually runs.
  start = serialText().length;
  await runCommand("rm /disk/heliox/config.json", start);
  const configStr = '{"provider":"auto","tick_interval":1}';
  await runCommand(`write /disk/heliox/config.json ${configStr}`, start);

  // Dispatch init/heliox-daemon. This used to abandon the shell prompt
  // one-way - the whole point of this test is that it no longer does.
  start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");
  await waitForSerial("Dispatching ring-3 init", 10, start);
  check("ring3 init dispatches the target process", true);

  const promptReappeared = await (async () => {
    try {
      await waitForSerial("FerrumOS:~$", 10, start);
      return true;
    } catch {
      return false;
    }
  })();
  check("the shell prompt reappears after ring3 init instead of being abandoned one-way", promptReappeared);

  // Prove the shell is still genuinely *interactive*, not just printing a
  // stale prompt: type a real command and confirm it's processed. Longer
  // wait here since heliox-daemon's own startup (network/TLS setup) may
  // still be mid-flight and briefly slow to yield back.
  const beforeUptime = serialText().length;
  await sendText("uptime");
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 30, beforeUptime);
  await sleep(100);
  const uptimeOutput = serialText().slice(beforeUptime);
  check(
    "the shell still processes a real command typed after ring3 init",
    /uptime|ticks/i.test(uptimeOutput),
    uptimeOutput.split("\n").find((l) => /uptime|ticks/i.test(l)) || ""
  );

  // Prove heliox-daemon is genuinely running concurrently, not just that
  // the prompt cosmetically reappeared while it sits registered but never
  // scheduled (the exact failure mode this fix targets).
  await waitForSerial("[heliox-daemon] active provider:", 15, start);
  check("heliox-daemon actually starts running while the shell is still usable", true);

  // Deliberately not waiting for a full daemon boot/tick-loop milestone
  // here (its `auto` provider resolves to the real 15M-parameter local
  // model, loaded lazily via on-demand paging - genuinely slow, and now
  // sharing the CPU fairly with `shell`/`init` for the first time ever,
  // which is real progress this fix intentionally trades for raw
  // single-task throughput, but makes a fixed short wait unreliable).
  // Instead, confirm actual interleaving directly from the log: both
  // tasks' RESUME_TASK lines present since the daemon started, not just
  // one that ran once and starved the other.
  await sleep(2000);
  const sinceStart = serialText().slice(start);
  const shellResumes = (sinceStart.match(/RESUME_TASK\] Resuming pid=\d+, name=shell/g) || []).length;
  const daemonResumes = (sinceStart.match(/RESUME_TASK\] Resuming pid=\d+, name=heliox-daemon/g) || []).length;
  check(
    "shell and heliox-daemon are both genuinely getting repeated CPU turns (real interleaving, not starvation)",
    shellResumes >= 2 && daemonResumes >= 2,
    `shell resumed ${shellResumes}x, heliox-daemon resumed ${daemonResumes}x`
  );

  // And the shell must still be responsive *right now*, with the daemon
  // actively mid-flight - proving ongoing, not just momentary, coexistence.
  // Longer wait than runCommand's default: the daemon's real model load is
  // still contending for CPU turns, so the round-trip for this one command
  // takes longer in wall-clock time than it would uncontended.
  const beforeWhoami = serialText().length;
  await sendText("whoami");
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 30, beforeWhoami);
  await sleep(100);
  const whoamiOutput = serialText().slice(beforeWhoami);
  check(
    "the shell remains responsive while the daemon is actively running",
    whoamiOutput.length > 0 && !/command not found/.test(whoamiOutput)
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
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
