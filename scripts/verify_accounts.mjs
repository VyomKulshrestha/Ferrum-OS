// ============================================================================
// FerrumOS - Multi-User Accounts Verification
// ============================================================================
// Boots the real appliance disk image and drives the plain kernel shell's
// `useradd`/`login`/`whoami`/`accounts` commands directly (no `ring3 init`
// needed - these are pure kernel-context commands, same as `pkg`).
//
// Asserts the account system is real, not cosmetic: a new account
// persists in the registry, logging in as it actually swaps the shell's
// held capabilities (proven by a capability-gated command that succeeds
// as root but is denied as the new non-root account), and logging back
// in as root restores access.
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
const serialLog = path.join(repo, "target", "accounts-verify-serial.log");
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
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash" }));
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
  let start = serialText().length;
  await waitForSerial("FerrumOS:~$", 60, start);
  check("boot reaches shell prompt", true);

  start = serialText().length;
  await runCommand("whoami", start);
  let out = serialText().slice(start);
  check("default session is root", /root \(uid=0/.test(out), out.trim());

  // Capability-gated command that must succeed as root - the baseline
  // this test compares the non-root denial against.
  start = serialText().length;
  await runCommand("log", start);
  out = serialText().slice(start);
  check("root can read the audit log", !/permission denied/.test(out), out.trim());

  // heliox-disk.img persists across boots - a leftover account from an
  // earlier run of this script would make `useradd alice` fail on this
  // run. accounts.txt itself is small text (well under ext2's
  // create_file direct-block limit), so a plain `rm` is enough to reset
  // it cleanly, same reasoning as verify_real_model.mjs's config.json cleanup.
  start = serialText().length;
  await runCommand("rm /disk/accounts.txt", start);

  start = serialText().length;
  await runCommand("useradd alice user", start);
  out = serialText().slice(start);
  check("useradd creates a real account", /created account 'alice' \(uid=1000, profile=user/.test(out), out.trim());

  start = serialText().length;
  await runCommand("useradd alice user", start);
  out = serialText().slice(start);
  check("useradd refuses a duplicate username", /already exists/.test(out), out.trim());

  start = serialText().length;
  await runCommand("accounts", start);
  out = serialText().slice(start);
  check("accounts lists both root and alice", /root/.test(out) && /alice/.test(out), out.trim());

  start = serialText().length;
  await runCommand("login alice", start);
  out = serialText().slice(start);
  check("login switches the active session", /logged in as alice/.test(out), out.trim());

  start = serialText().length;
  await runCommand("whoami", start);
  out = serialText().slice(start);
  check("whoami reflects the logged-in account", /alice \(uid=1000, profile=user/.test(out), out.trim());

  // The real test: logging in as alice must actually change what the
  // shell can do, not just what it prints. alice's "user" profile
  // deliberately excludes cap:audit:read (src/accounts/mod.rs).
  start = serialText().length;
  await runCommand("log", start);
  out = serialText().slice(start);
  check("non-root account is denied a capability-gated command", /permission denied: audit:read/.test(out), out.trim());

  // Logging back in as root must restore full access - proves the
  // capability swap is live/bidirectional, not a one-way downgrade.
  start = serialText().length;
  await runCommand("login root", start);
  out = serialText().slice(start);
  check("login root restores the root session", /logged in as root/.test(out), out.trim());

  start = serialText().length;
  await runCommand("log", start);
  out = serialText().slice(start);
  check("root access is restored after logging back in", !/permission denied/.test(out), out.trim());

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
