// ============================================================================
// FerrumOS - `touch`/`stat` Polish Verification
// ============================================================================
// work.md finding 2.7: two minor UX inconsistencies in the shell command
// audit.
//   1. `touch` gave no confirmation message on success, unlike `mkdir`
//      ("Directory created: ..."). Now prints "Created: <path>" to match.
//   2. `stat`'s displayed path dropped the mount prefix (typed
//      `/disk/foo.txt`, shown as `/foo.txt`) - `vfs::resolve` returns a path
//      relative to whatever mount owns it, and every `Filesystem::stat`
//      impl built its returned `path` from that stripped, relative path
//      rather than the one the caller actually typed. `fs::stat` now
//      overwrites the result with the real, full path queried.
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

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45509);
const serialLog = path.join(repo, "target", "touch-stat-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

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
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-2000)}`);
}

const qemuArgs = [
  "-m", "512M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for touch/stat verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX failed, falling back to TCG...");
  let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) { monitor.write(`${cmd}\n`); await sleep(waitMs); }
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus" }));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
async function runCommand(cmd) {
  const start = serialText().length;
  await sendText(cmd);
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, start);
  await sleep(100);
  return serialText().slice(start);
}

try {
  await waitForSerial("FerrumOS:~$", 45, 0);
  check("boot reaches shell prompt", true);

  await runCommand("rm /disk/touch_stat_test.txt");

  const touchOut = await runCommand("touch /disk/touch_stat_test.txt");
  check("touch prints a confirmation message like mkdir does", /Created: \/disk\/touch_stat_test\.txt/.test(touchOut), touchOut.trim());

  const statOut = await runCommand("stat /disk/touch_stat_test.txt");
  check(
    "stat reports the full path including the /disk mount prefix, not a stripped relative one",
    /Path:\s+\/disk\/touch_stat_test\.txt/.test(statOut) && !/Path:\s+\/touch_stat_test\.txt/.test(statOut),
    statOut.trim()
  );

  const full = serialText();
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
