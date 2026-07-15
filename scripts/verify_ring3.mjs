// ============================================================================
// FerrumOS - ring-3 syscall verification
// ============================================================================
// Boots the kernel in QEMU, drives `ring3 init` from the shell, and asserts
// that the real init binary:
//   1. enters ring 3 and successfully makes an `int 0x80` syscall (SYS_WRITE),
//   2. queries its pid (SYS_GETPID),
//   3. sleeps/yields cooperatively (SYS_SLEEP / SYS_YIELD),
//   4. exits cleanly (SYS_EXIT) and returns control to the kernel shell.
//
// If the DPL-3 syscall gate were missing, step 1 would #GP and the kernel
// would print "terminating" instead of the init banner — so the presence of
// the init banner on serial is itself the proof the gate works.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45459);
const serialLog = path.join(repo, "target", "ring3-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// This script predates the WHPX-acceleration + TCG-fallback pattern every
// other verify_*.mjs script uses - it used to spawn QEMU with no `-accel`
// flag at all, which defaults to QEMU's plain interpreted TCG and made the
// kernel's now-much-larger boot sequence (heliox-daemon's real model,
// world-model MLPs, etc. - all far bigger than when this script was
// written) take well over a minute to reach the shell prompt, timing out
// this script's original 30s boot budget. The kernel was never actually
// hung - confirmed by waiting 120s against unaccelerated QEMU directly, at
// which point it did reach the prompt. Accelerating this the same way
// every other test does is the fix, not a longer timeout on slow emulation.
const qemuArgs = [
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
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
let monitorBuffer = "";
monitor.on("data", (d) => { monitorBuffer += d; });
await sleep(500);

async function mon(cmd, waitMs = 60) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}

const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus" }));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/.test(ch)) await sendKey(ch);
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
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

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

try {
  await waitForSerial("FerrumOS:~$", 45);
  check("boot reaches shell prompt", true);

  const start = serialText().length;
  await sendText("write /tmp/init_test 1");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: ring-3 syscall works (the banner only prints if int 0x80 from
  // ring 3 entered the kernel rather than #GP-ing).
  await waitForSerial("[init] userspace is alive in ring 3", 12, start);
  check("ring-3 SYS_WRITE reaches kernel (DPL-3 gate works)", true);

  // Step 2: SYS_GETPID round-tripped (init reports a valid pid).
  const afterAlive = serialText();
  check("SYS_GETPID round-trips", afterAlive.includes("[init] obtained pid from kernel via SYS_GETPID"));

  // Step 3 + 4: sleep/yield loop completes and init exits cleanly.
  await waitForSerial("[init] supervision complete, exiting cleanly", 15, start);
  check("SYS_SLEEP/SYS_YIELD supervision loop ran", true);

  // Step 5: kernel reaps the process and returns to a fresh shell.
  //
  // This used to wait for `[kernel] user process N exited (code N)` -
  // `kernel_return_entry`'s reap-and-report trampoline (src/scheduler/mod.rs).
  // That trampoline is D13-era legacy: before the shell became a genuine,
  // always-in-the-run-queue-when-idle kernel task, it was the *only* way
  // control ever returned to the shell after a ring-3 dispatch, so it fired
  // on every exit. Post-D13, `schedule_next()` normally finds and resumes
  // the shell directly the moment it's Ready, without ever reaching this
  // trampoline (see its own doc comment) - so this line now only fires on
  // the rare edge case of the shell not yet having reached its own first
  // safepoint. Waiting on it unconditionally made this check flaky/stale.
  //
  // `sys_exit`'s own audit log line (src/interrupts/mod.rs), by contrast,
  // fires unconditionally and immediately on every clean exit regardless of
  // which reap path handles the cleanup afterward - the reliable signal.
  await waitForSerial("[AUDIT] ProcessKilled: user process exited via sys_exit", 10, start);
  const exited = serialText().slice(start);
  check("kernel reports clean exit via sys_exit", /ProcessKilled: user process exited via sys_exit/.test(exited));
  await waitForSerial("FerrumOS:~$", 8, start + 1);
  check("shell prompt returns after init exit", true);

  // Negative control: there must be NO fault/termination from init.
  const full = serialText().slice(start);
  check("no userspace fault during init run",
    !/terminating|General Protection|Page Fault/.test(full));
} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
