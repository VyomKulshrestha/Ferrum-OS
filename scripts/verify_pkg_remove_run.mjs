// ============================================================================
// FerrumOS - `pkg remove` vs. plain `run` Verification
// ============================================================================
// work.md finding 2.2: after `pkg run <name>` successfully launches a
// package (registering it in `userspace`'s dynamic program table via
// `register_dynamic_program`, so it can go through the same
// `enter_registered` ring-3 dispatch path as a compiled-in program),
// `pkg remove <name>` only ever cleared ferrumpkg's own install registry -
// it never touched that dynamic table. `pkg run <name>` re-checks
// ferrumpkg's registry so it correctly refused a removed package, but the
// plain `run <name>` shell command (`crate::userspace::launch`) dispatches
// straight off the dynamic table and kept launching a "removed" package
// forever. This verifies `unregister_dynamic_program` (called from
// `cmd_pkg`'s "remove" branch) actually closes that gap.
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
const serialLog = path.join(repo, "target", "pkg-remove-run-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
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

console.log("[test] starting QEMU for pkg-remove-vs-run verification...");
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

async function mon(cmd, waitMs = 150) { monitor.write(`${cmd}\n`); await sleep(waitMs); }
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus" }));
// Once `notes` is running (after `pkg run`), it round-robins for CPU
// turns alongside the shell (D13's shell/agent coexistence fix), so
// keystrokes typed afterward land less reliably than at a plain idle
// prompt - a too-fast 45ms gap here previously dropped a keystroke and
// mangled "pkg remove notes" into "pkg remo notes".
async function sendKey(k) { await mon(`sendkey ${k}`, 90); }
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
  let start = serialText().length;
  await waitForSerial("FerrumOS:~$", 60, start);
  check("boot reaches shell prompt", true);

  // heliox-disk.img persists across runs of this script - force a clean
  // "not installed" baseline regardless of what an earlier run left behind.
  start = serialText().length;
  await runCommand("pkg remove notes", start);

  start = serialText().length;
  await runCommand("pkg install notes", start);
  let out = serialText().slice(start);
  check("pkg install succeeds", /installed notes/.test(out), out.trim());

  // Successfully launch it via `pkg run` - this is what registers "notes"
  // in userspace's dynamic program table (register_dynamic_program), the
  // exact precondition the original bug needed and the earlier
  // verify_pkg_manager.mjs run never actually exercised before removing.
  start = serialText().length;
  await sendText("pkg run notes");
  await sendKey("ret");
  await waitForSerial("[notes] alive in ring 3", 15, start);
  check("pkg run launches notes and registers it as a dynamic program", true);

  // D13's shell/agent coexistence fix means `pkg run`'s ring-3 dispatch no
  // longer abandons the shell prompt - confirm it's still there before
  // continuing.
  await waitForSerial("FerrumOS:~$", 10, start);
  check("shell prompt is still usable after pkg run", true);
  await sleep(500);

  start = serialText().length;
  await runCommand("pkg remove notes", start);
  out = serialText().slice(start);
  check("pkg remove succeeds", /removed notes/.test(out), out.trim());

  // The actual bug: plain `run <name>` dispatches off the dynamic program
  // table directly and used to keep launching a removed package forever.
  start = serialText().length;
  await runCommand("run notes", start);
  out = serialText().slice(start);
  check(
    "plain `run` refuses a package after `pkg remove` (was the bug: it kept launching)",
    /not found|no such|not installed/i.test(out) && !/launched/i.test(out),
    out.trim()
  );
  check("removed package's run command did not actually start a second instance", !/\[notes\] alive in ring 3/.test(serialText().slice(start)), out.trim());

  start = serialText().length;
  await runCommand("whoami", start);
  out = serialText().slice(start);
  check("shell remains responsive after all pkg/run commands", out.includes("root") || out.includes("uid="));

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
