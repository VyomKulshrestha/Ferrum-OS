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
const qemu = process.env.QEMU || "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45459);
const serialLog = path.join(repo, "target", "ring3-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");

const qemuProcess = spawn(qemu, qemuArgs, { windowsHide: !visible });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
  await waitForSerial("FerrumOS:~$", 30);
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

  // Step 5: kernel reaps the process and returns to a fresh shell. Wait for
  // the specific reap line ("...exited (code N)") rather than the generic
  // "user process" substring, which also appears in the earlier audit line.
  await waitForSerial("exited (code", 10, start);
  const exited = serialText().slice(start);
  check("kernel reports clean exit + reaps", /user process \d+ exited \(code \d+\)/.test(exited),
    (exited.match(/\[kernel\].*exited[^\n]*/) || [""])[0].trim());
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
