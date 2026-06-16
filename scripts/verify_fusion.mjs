// ============================================================================
// FerrumOS - Multimodal Fusion Verification
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const qemu = process.env.QEMU || "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45475);
const serialLog = path.join(repo, "target", "fusion-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

// Start Mock STT Server
let requestReceived = false;
const mockServer = http.createServer((req, res) => {
  if (req.url === "/v1/audio/transcriptions" && req.method === "POST") {
    requestReceived = true;
    let chunks = [];
    req.on("data", chunk => chunks.push(chunk));
    req.on("end", () => {
      const jsonResponse = JSON.stringify({ text: "hey heliox open this" });
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(jsonResponse).toString()
      });
      res.end(jsonResponse);
    });
  } else {
    res.writeHead(404);
    res.end();
  }
});

await new Promise((resolve) => {
  mockServer.listen(8786, "127.0.0.1", () => {
    console.log("[mock server] STT listening on port 8786");
    resolve();
  });
});

const qemuArgs = [
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
  "-device", "rtl8139,netdev=net0",
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");

console.log("[test] starting QEMU for fusion verification...");
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

async function mon(cmd, waitMs = 150) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}

const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon", "\"": "shift-apostrophe", "{": "shift-bracket_left", "}": "shift-bracket_right", ",": "comma" }));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
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
  await waitForSerial("FerrumOS:~$", 35);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Set the synthetic camera gesture to pointing
  await sendText("camera_gesture pointing");
  await sendKey("ret");
  await sleep(600);

  // Write configuration for daemon
  await sendText("write /disk/heliox/config.json {\"api_host\":\"host\",\"stt_host\":\"10.0.2.2\",\"stt_port\":8786,\"vad_threshold\":0}");
  await sendKey("ret");
  await sleep(600);

  // Start init supervisor which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: Daemon spawns and registers voice activity
  await waitForSerial("[heliox-daemon] voice activity detected, recording command...", 30, start);
  check("daemon starts and detects voice activity", true);

  // Step 2: Verify the pointing gesture was detected stable and registered
  await waitForSerial("[heliox-daemon] gesture: Pointing", 30, start);
  check("daemon CV pipeline registers stable Pointing gesture", true);

  // Step 3: Transcription received
  await waitForSerial("[heliox-daemon] voice transcript: hey heliox open this", 30, start);
  check("daemon receives transcribed voice command 'hey heliox open this'", true);

  // Step 4: Spatial intent resolved and prepended [FUSED]
  await waitForSerial("[heliox-daemon] spatial fusion resolved: open TERMINAL", 30, start);
  check("spatial intent resolved to TERMINAL window", true);

  await sleep(2000);

  // Verify no userspace page fault or panic
  const full = serialText().slice(start);
  check("no userspace fault/panic during fusion test",
    !/terminating|General Protection|Page Fault/.test(full));

} catch (err) {
  check("verification failed", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
  mockServer.close();
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
