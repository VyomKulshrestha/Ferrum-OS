// ============================================================================
// FerrumOS - World Model Learned Transition Model Verification
// ============================================================================
// Confirms cognitive/world_model/learned.rs actually loads a trained MLP
// at boot when staged onto the appliance disk (scripts/train_world_model.py
// + make-appliance.ps1), and that the safety gate still correctly blocks
// a delete_file targeting the daemon's own config.json while running on
// the learned model instead of the Phase 1 rule table - proving
// `deletes_own_config` (a direct argument check, not a numeric
// prediction) stays correct regardless of which delta source is active.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import https from "node:https";
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

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45501);
const serialLog = path.join(repo, "target", "world-model-learned-verify-serial.log");
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

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
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

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
}

try { fs.unlinkSync(serialLog); } catch {}

let requestCount = 0;
const options = {
  key: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.key")),
  cert: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.pem")),
};
const mockServer = https.createServer(options, (req, res) => {
  requestCount++;
  const toolCall = requestCount <= 2
    ? { tool: "write_file", args: { path: `/disk/wm_learned_${requestCount}.txt`, content: "hello" } }
    : { tool: "delete_file", args: { path: "/disk/heliox/config.json" } };
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    const payload = JSON.stringify({ response: JSON.stringify(toolCall) });
    res.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) });
    res.end(payload);
  });
});
await new Promise((resolve) => mockServer.listen(8443, "0.0.0.0", resolve));

const qemuArgs = [
  "-m", "1024M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
  "-device", "rtl8139,netdev=net0",
  "-no-reboot",
];
let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("Starting QEMU with the real appliance disk image...");
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
  let start = serialText().length;
  await waitForSerial("FerrumOS:~$", 60, start);
  check("boot reaches shell prompt", true);

  start = serialText().length;
  await runCommand("rm /disk/heliox/config.json", start);
  const configStr = '{"provider":"cloud","api_host":"10.0.2.2","api_port":8443,"api_path":"/","model_name":"mock","api_key":"key","tick_interval":1,"auto_approve_tier":4}';
  await runCommand(`write /disk/heliox/config.json ${configStr}`, start);

  start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("[heliox-daemon] active provider: cloud", 25, start);
  const loadMsg = await waitForSerial("[world-model] loaded learned transition model", 15, start);
  check(
    "learned transition model loads from the staged weights file at boot",
    true,
    loadMsg.split("\n").find((l) => l.includes("loaded learned transition model")) || ""
  );

  const encoderMsg = await waitForSerial("[world-model] loaded learned encoder", 15, start);
  check(
    "learned encoder loads from the staged weights file at boot",
    true,
    encoderMsg.split("\n").find((l) => l.includes("loaded learned encoder")) || ""
  );

  // Even on the learned model, deletes_own_config is a direct argument
  // check (transition.rs), not a numeric prediction - must still block.
  const blockMsg = await waitForSerial("[world-model] BLOCKED tool 'delete_file'", 30, start);
  check(
    "safety gate still blocks delete_file targeting config.json while using the learned model",
    true,
    blockMsg.split("\n").reverse().find((l) => l.includes("BLOCKED tool 'delete_file'")) || ""
  );
  check(
    "block message reports the lookahead step count (Layer 6.2 wired in)",
    /lookahead_steps=\d+/.test(blockMsg)
  );

  const full = serialText();
  check("no userspace fault or page fault panic", !/terminating|General Protection|Page Fault/.test(full));
} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
  mockServer.close();
}

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
