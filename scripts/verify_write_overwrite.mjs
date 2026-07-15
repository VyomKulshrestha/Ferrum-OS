// ============================================================================
// FerrumOS - `write` Overwrite Verification
// ============================================================================
// work.md finding 2.1: `write <file> <text>` refused outright if the target
// already existed ("write: file already exists"), rather than overwriting it -
// every verify script that predates this fix had to `rm` a file first just in
// case it already existed. This verifies `cmd_write` -> `fs::create_file` ->
// `Ext2Fs::create_file` now overwrites an existing regular file's content in
// place, still creates brand-new files as before, and still refuses to clobber
// a directory.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45498);
const serialLog = path.join(repo, "target", "write-overwrite-verify-serial.log");
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

console.log("[test] starting QEMU for write-overwrite verification...");
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
}));
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
  await waitForSerial("FerrumOS:~$", 15, start);
  await sleep(100);
  return serialText().slice(start);
}

try {
  await waitForSerial("FerrumOS:~$", 45, 0);
  check("boot reaches shell prompt", true);

  // Clean slate - ignore errors, these may not exist yet.
  await runCommand("rm /disk/write_overwrite_test.txt");
  await runCommand("rm /disk/write_overwrite_new.txt");
  await runCommand("rm /disk/write_overwrite_dir");

  // 1. Create the file, then write it once - baseline create-path still works.
  await runCommand("touch /disk/write_overwrite_test.txt");
  const firstWrite = await runCommand("write /disk/write_overwrite_test.txt hello_first");
  check("first write on a freshly-touched file succeeds", !/already exists|error/i.test(firstWrite));

  const firstCat = await runCommand("cat /disk/write_overwrite_test.txt");
  check("cat shows the first write's content", firstCat.includes("hello_first"));

  // 2. Write again over the same, already-populated file - this is the bug:
  // it used to fail with "write: file already exists" and leave the old
  // (or empty) content in place.
  const secondWrite = await runCommand("write /disk/write_overwrite_test.txt hello_second");
  check("second write overwriting an existing file does not error", !/already exists|error/i.test(secondWrite), secondWrite.trim());

  const secondCat = await runCommand("cat /disk/write_overwrite_test.txt");
  check("cat shows the new content after overwrite", secondCat.includes("hello_second"));
  check("cat no longer shows the stale first write", !secondCat.includes("hello_first"));

  // 3. write straight to a brand-new path with no prior touch - the plain
  // create path must still work unchanged.
  const newFileWrite = await runCommand("write /disk/write_overwrite_new.txt brand_new_file");
  check("write to a brand-new path still creates it", !/already exists|error/i.test(newFileWrite));
  const newFileCat = await runCommand("cat /disk/write_overwrite_new.txt");
  check("cat shows the brand-new file's content", newFileCat.includes("brand_new_file"));

  // 4. A third overwrite with shorter content, to exercise the old-block
  // freeing path shrinking the file, not just replacing it same-size.
  const thirdWrite = await runCommand("write /disk/write_overwrite_test.txt hi");
  check("third write (shrinking content) does not error", !/already exists|error/i.test(thirdWrite));
  const thirdCat = await runCommand("cat /disk/write_overwrite_test.txt");
  check("cat shows the shrunk content exactly", thirdCat.includes("hi") && !thirdCat.includes("hello_second"));

  // 5. write must still refuse to clobber a directory.
  await runCommand("mkdir /disk/write_overwrite_dir");
  const dirWrite = await runCommand("write /disk/write_overwrite_dir nope");
  check("write onto an existing directory still refuses", /error|not a regular file|is a directory/i.test(dirWrite), dirWrite.trim());

  // Final sanity: shell still responsive, no crash anywhere in the run.
  const whoami = await runCommand("whoami");
  check("shell remains responsive after all writes", whoami.includes("root") || whoami.includes("uid="));

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
