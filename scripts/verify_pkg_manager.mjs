// ============================================================================
// FerrumOS - Package Manager (ferrumpkg) Verification
// ============================================================================
// Boots the real appliance disk image (target/heliox-disk.img, staged by
// scripts/make-appliance.ps1 with a "notes" package under
// /pkgs-available/notes/ - never embedded in the kernel binary, see
// build.rs) and drives the plain kernel shell's `pkg` command directly -
// no `ring3 init` needed, since the scheduler is already live by the time
// the shell prompt appears (only `init`'s own userspace supervisor process
// needs that command).
//
// Asserts the full real lifecycle: available-but-not-installed can't be
// run, install genuinely persists in the registry, install lets it run
// (spawns real ring-3 code that was never in the kernel image), and
// remove genuinely revokes the ability to run it again - not just cosmetic
// bookkeeping.
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

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45491);
const serialLog = path.join(repo, "target", "pkg-manager-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`appliance disk image not found: ${diskImage} - run scripts/make-appliance.ps1 first`);

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
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-2000)}`);
}

const qemuArgs = [
  "-m", "512M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];

let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU with the real appliance disk image...");
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

async function mon(cmd, waitMs = 150) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus" }));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
// Waits for the shell prompt to reappear after the command, rather than a
// fixed sleep, so the caller's subsequent serialText().slice(start) is
// guaranteed to already contain the command's full output (echo + result
// + new prompt) instead of racing the serial log's flush.
async function runCommand(cmd, start) {
  await sendText(cmd);
  await sendKey("ret");
  await waitForSerial("FerrumOS:~$", 10, start);
  await sleep(100);
}

try {
  let start = serialText().length;
  await waitForSerial("FerrumOS:~$", 60, start);
  check("boot reaches shell prompt", true);

  // heliox-disk.img is a persistent file on the host, not reset between
  // boots (same reason verify_real_model.mjs removes a leftover
  // config.json first) - a `pkg install notes` from an earlier run of
  // this script would otherwise still be registered. Force a clean
  // "not installed" baseline regardless of what ran before; the result
  // is intentionally not asserted on since either outcome (was installed
  // / wasn't) is fine here.
  start = serialText().length;
  await runCommand("pkg remove notes", start);

  // 1. The package is on disk (staged by make-appliance.ps1) but not yet
  // installed - `pkg list` should surface it as available, not installed.
  start = serialText().length;
  await runCommand("pkg list", start);
  let out = serialText().slice(start);
  check("pkg list shows notes as available before install", /notes.*\[available\]/.test(out), out.trim());

  // 2. Running an available-but-uninstalled package must be refused - the
  // whole point of ferrumpkg's install gate (src/pkg/mod.rs, sys_exec's
  // check in src/syscall/process.rs) is that the bytes existing on disk
  // isn't sufficient permission to execute them.
  start = serialText().length;
  await runCommand("pkg run notes", start);
  out = serialText().slice(start);
  check("pkg run refuses an uninstalled package", /not installed/.test(out), out.trim());
  check("uninstalled package did not actually start", !/\[notes\] alive in ring 3/.test(out), out.trim());

  // 3. Install, then confirm it now reports installed.
  start = serialText().length;
  await runCommand("pkg install notes", start);
  out = serialText().slice(start);
  check("pkg install succeeds", /installed notes/.test(out), out.trim());

  start = serialText().length;
  await runCommand("pkg list", start);
  out = serialText().slice(start);
  check("pkg list shows notes as installed after install", /notes.*\[installed\]/.test(out), out.trim());

  // 4. Remove, then confirm the ability to run it is genuinely revoked -
  // not just a UI label change. Done *before* the final successful run
  // below, deliberately: once that run actually enters ring 3, this
  // long-running GUI app (and init/heliox-daemon, both already alive)
  // rotate the CPU amongst themselves via the scheduler's normal
  // round-robin - none of them ever exit, so there's no guarantee the
  // plain kernel shell's own prompt becomes interactive again afterward.
  // Every check that needs the shell prompt back runs before that point.
  start = serialText().length;
  await runCommand("pkg remove notes", start);
  out = serialText().slice(start);
  check("pkg remove succeeds", /removed notes/.test(out), out.trim());

  start = serialText().length;
  await runCommand("pkg run notes", start);
  out = serialText().slice(start);
  check("pkg run refuses notes again after remove", /not installed/.test(out), out.trim());
  check("removed package did not start", !/\[notes\] alive in ring 3/.test(out), out.trim());

  // 5. Reinstall and actually run it - real ring-3 code that was never
  // part of the kernel binary (see build.rs's comment on the notes
  // crate). This is the last interactive step in this scenario.
  start = serialText().length;
  await runCommand("pkg install notes", start);
  out = serialText().slice(start);
  check("pkg install succeeds again", /installed notes/.test(out), out.trim());

  start = serialText().length;
  await sendText("pkg run notes");
  await sendKey("ret");
  await waitForSerial("[notes] alive in ring 3", 15, start);
  await waitForSerial("window created id=", 10, start);
  check("installed package actually runs in ring 3", true);

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
