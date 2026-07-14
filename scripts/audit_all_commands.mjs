// ============================================================================
// FerrumOS - Full Shell Command Audit
// ============================================================================
// Boots the appliance once and runs every shell command (from execute()'s
// match table in src/shell/commands.rs) in a sensible order, capturing the
// full serial log so each command's actual output/behavior can be reviewed
// afterward. This is a SURVEY, not a verify script: it doesn't assert
// pass/fail per command, it just records what happened so problems can be
// written up in work.md before any fix is attempted.
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
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

const commandLog = [];
async function runCmd(cmd, waitSeconds = 8) {
  const before = serialText().length;
  await sendText(cmd);
  await sendKey("ret");
  const got = await waitForSerial("FerrumOS:~$", waitSeconds, before);
  const output = serialText().slice(before);
  commandLog.push({ cmd, promptReturned: !!got, output });
  console.log(`[audit] ran: ${cmd}  (prompt returned: ${!!got})`);
  await sleep(150);
  return output;
}

try {
  await waitForSerial("FerrumOS:~$", 45, 0);
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
  await runCmd("pkg install notes");
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
  }

  // --- session / useradd / login (identity-changing - kept near the end) -----
  await runCmd("session guest");
  await runCmd("whoami");
  await runCmd("session root");
  await runCmd("useradd audituser user");
  await runCmd("login audituser");
  await runCmd("whoami");

  // --- heliox / agent (informational only, no ring3 dispatch yet) -----------
  await runCmd("heliox status");
  await runCmd("heliox tiers");
  await runCmd("agent status");

  // --- ring3 / desktop (start real background activity; test near the end so
  // it doesn't interfere with anything above, and confirm the shell/agent
  // coexistence fix - see REPORT.md D13 - by running a command AFTER it) -----
  await runCmd("ring3 init", 15);
  await runCmd("agent status");
  await runCmd("uptime");
  await runCmd("heliox status");

  console.log("\n[audit] all commands attempted, writing raw log...");
} catch (err) {
  console.error("[audit] fatal error:", err && err.message ? err.message : String(err));
} finally {
  const summaryPath = path.join(repo, "target", "audit-all-commands-summary.json");
  fs.writeFileSync(summaryPath, JSON.stringify(commandLog, null, 2));
  console.log(`[audit] wrote per-command summary to ${summaryPath}`);
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}
