// ============================================================================
// FerrumOS - Full Shell Command Audit
// ============================================================================
// Boots the appliance once and runs every shell command (from execute()'s
// match table in src/shell/commands.rs) in a sensible order, capturing the
// full serial log so each command's actual output/behavior can be reviewed.
// A missing prompt, corrupted command echo, or unknown command is a failure;
// the audit must not turn input loss into a false green result.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45495);
const serialLog = path.join(repo, "target", "audit-all-commands-serial.log");
const runDisk = path.join(repo, "target", "audit-all-commands-disk.img");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
fs.rmSync(runDisk, { force: true });
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

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(120);
  }
  return null; // audit script: never throw, just record a miss
}

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`appliance disk image not found: ${diskImage} - run scripts/make-appliance.ps1 first`);
fs.copyFileSync(diskImage, runDisk);

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[audit] starting QEMU...");
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
// This is a command-coverage audit, not a maximum-rate keyboard benchmark.
// Use a fast but human-plausible cadence so command results are not polluted
// by QEMU HMP/PS/2 saturation while background userspace is starting.
async function sendKey(k, waitMs = 180) { await mon(`sendkey ${k} 50`, waitMs); }
async function sendText(t, waitMs = 180) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch), waitMs);
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase(), waitMs);
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

const commandLog = [];
const requiredOutput = new Map([
  ["pkg remove notes", "removed notes"],
  ["spawn audit_task", "Spawned task 'audit_task'"],
  ["useradd audituser user", "created account 'audituser'"],
  ["login audituser", "logged in as audituser"],
  ["heliox neural", "heliox neural: usage"],
  ["heliox neural arm", "heliox neural: arm requested"],
  ["heliox neural disarm", "heliox neural: disarm requested"],
  ["ring3 init", "Dispatching ring-3 init"],
]);
async function runCmd(cmd, waitSeconds = 8) {
  const before = serialText().length;
  await sendText(cmd);
  if (!await waitForSerial(cmd, 2, before)) {
    console.log(`[audit] incomplete keyboard echo; clearing and retrying slowly: ${cmd}`);
    await sendKey("ctrl-u", 300);
    await sendText(cmd, 300);
    if (!await waitForSerial(cmd, 3, before)) {
      throw new Error(`keyboard input remained incomplete after retry: ${cmd}`);
    }
  }
  await sendKey("ret");
  const got = await waitForSerial("FerrumOS:~$", waitSeconds, before);
  const output = serialText().slice(before);
  commandLog.push({ cmd, promptReturned: !!got, output });
  console.log(`[audit] ran: ${cmd}  (prompt returned: ${!!got})`);
  if (/Unknown command:|(?:pkg|heliox): unknown subcommand/.test(output)) {
    throw new Error(`unexpected unknown command path while sending: ${cmd}`);
  }
  const expected = requiredOutput.get(cmd);
  if (expected && !output.includes(expected)) {
    throw new Error(`expected output missing after ${cmd}: ${expected}`);
  }
  if (!got) {
    throw new Error(`shell prompt did not return after: ${cmd}`);
  }
  await sleep(150);
  return output;
}

let fatalError = null;
try {
  if (!await waitForSerial("FerrumOS:~$", 45, 0)) {
    throw new Error("boot did not reach shell prompt");
  }
  console.log("[audit] boot reached shell prompt");

  // --- Informational / read-only commands first ---------------------------
  await runCmd("help");
  await runCmd("uname");
  await runCmd("whoami");
  await runCmd("uptime");
  await runCmd("mem");
  await runCmd("ps");
  await runCmd("devices");
  await runCmd("net");
  await runCmd("caps");
  await runCmd("services");
  await runCmd("ipc");
  await runCmd("clipboard status");
  await runCmd("clipboard set audit");
  await runCmd("clipboard get");
  await runCmd("clipboard clear");
  await runCmd("notify audit complete");
  await runCmd("notifications");
  await runCmd("notifications clear");
  await runCmd("notifications");
  await runCmd("syscalls");
  await runCmd("programs");
  await runCmd("users");
  await runCmd("mounts");
  await runCmd("log");
  await runCmd("scheduler");
  await runCmd("security");
  await runCmd("about");
  await runCmd("disk");
  await runCmd("accounts");
  await runCmd("elf");
  await runCmd("process");

  // --- Filesystem commands --------------------------------------------------
  await runCmd("ls /disk");
  await runCmd("mkdir /disk/audit_test_dir");
  await runCmd("touch /disk/audit_test_file.txt");
  await runCmd("write /disk/audit_test_file.txt hello_audit");
  await runCmd("cat /disk/audit_test_file.txt");
  await runCmd("stat /disk/audit_test_file.txt");
  await runCmd("sync");
  await runCmd("rm /disk/audit_test_file.txt");
  await runCmd("ls /disk");

  // --- echo / clear ----------------------------------------------------------
  await runCmd("echo audit test message");
  await runCmd("clear");

  // --- camera_gesture ----------------------------------------------------
  await runCmd("camera_gesture openpalm");
  await runCmd("camera_gesture none");
  await runCmd("camera_gesture bogus_gesture_name"); // expected error path

  // --- services with subcommands ------------------------------------------
  await runCmd("services start 1");
  await runCmd("services stop 1");

  // --- pkg -----------------------------------------------------------------
  await runCmd("pkg list");
  await runCmd("pkg install notes --confirm");
  await runCmd("pkg run notes", 10);
  await runCmd("pkg remove notes");

  // --- run -------------------------------------------------------------------
  await runCmd("run notes", 10);

  // --- spawn / kill ------------------------------------------------------
  await runCmd("spawn audit_task");
  await runCmd("ps"); // to see the spawned task's id
  await runCmd("kill 999"); // nonexistent id - error path

  // --- syscall / test-syscall ----------------------------------------------
  await runCmd("test-syscall yield");
  await runCmd("test-syscall sleep");
  await runCmd("test-syscall priority");
  await runCmd("test-syscall frame-recycle");
  await runCmd("syscall 2 0"); // pid=2 (init), syscall 0 = Yield

  // --- dashboard (has its own ESC-to-exit input loop, not the normal prompt loop) ---
  {
    const before = serialText().length;
    await sendText("dashboard");
    await sendKey("ret");
    await waitForSerial("[dashboard] launching system dashboard", 5, before);
    await sleep(800);
    await sendKey("esc");
    const got = await waitForSerial("FerrumOS:~$", 8, before);
    const output = serialText().slice(before);
    commandLog.push({ cmd: "dashboard", promptReturned: !!got, output });
    console.log(`[audit] ran: dashboard  (prompt returned: ${!!got})`);
    if (!output.replaceAll("\r", "").includes("dashboard\n") || !got) {
      throw new Error("dashboard command input or prompt return failed");
    }
  }

  // --- session / useradd / login (identity-changing - kept near the end) -----
  await runCmd("session guest");
  await runCmd("whoami");
  await runCmd("clipboard get");
  await runCmd("notify denied body");
  await runCmd("notifications");
  await runCmd("session root");
  await runCmd("useradd audituser user");
  await runCmd("login audituser");
  await runCmd("whoami");
  await runCmd("session root");

  // --- heliox / agent (informational only, no ring3 dispatch yet) -----------
  await runCmd("heliox status");
  await runCmd("heliox tiers");
  await runCmd("heliox neural");
  await runCmd("heliox neural arm");
  await runCmd("heliox neural disarm");
  await runCmd("agent status");

  // --- ring3 / desktop (start real background activity; test near the end so
  // it doesn't interfere with anything above, and confirm the shell/agent
  // coexistence fix - see REPORT.md D13 - by running a command AFTER it) -----
  const beforeRing3 = serialText().length;
  await runCmd("ring3 init", 15);
  // The shell prompt returns as soon as init is dispatched, before init has
  // spawned heliox-daemon. Do not turn daemon startup output into an input
  // race; post-ring3 command coverage begins once the daemon is actually live.
  if (!await waitForSerial("[heliox-daemon] loop tick complete, sleeping...", 45, beforeRing3)) {
    throw new Error("ring3 init did not start a live heliox-daemon");
  }
  await sleep(250);
  await runCmd("agent status");
  await runCmd("uptime");
  await runCmd("heliox status");

  console.log("\n[audit] all commands attempted, writing raw log...");
} catch (err) {
  fatalError = err;
  console.error("[audit] fatal error:", err && err.message ? err.message : String(err));
} finally {
  const summaryPath = path.join(repo, "target", "audit-all-commands-summary.json");
  fs.writeFileSync(summaryPath, JSON.stringify(commandLog, null, 2));
  console.log(`[audit] wrote per-command summary to ${summaryPath}`);
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
  await sleep(300);
  fs.rmSync(runDisk, { force: true });
}

if (fatalError) process.exitCode = 1;
