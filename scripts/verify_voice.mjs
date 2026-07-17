// ============================================================================
// FerrumOS - heliox-daemon End-to-End Voice & STT Loop verification
// ============================================================================
// Boots the kernel in QEMU with audio devices, runs a mock Whisper STT server
// on host port 8786, writes a custom config to /disk/heliox/config.json with
// vad_threshold=0 to force silent capture, and asserts that:
//   1. the daemon starts up and detects voice activity,
//   2. records 3 seconds and POSTs to mock Whisper STT,
//   3. receives transcript and sets goal,
//   4. receiving "heliox voice event" updates the goal via IPC.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45460);
const serialLog = path.join(repo, "target", "voice-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

// 1. Start Host-Side Mock STT HTTP Server
let requestReceived = false;
let receivedBodyLength = 0;
const mockServer = http.createServer((req, res) => {
  console.log(`[mock server] received request: ${req.method} ${req.url}`);
  if (req.url === "/v1/audio/transcriptions" && req.method === "POST") {
    requestReceived = true;
    let chunks = [];
    req.on("data", chunk => chunks.push(chunk));
    req.on("end", () => {
      const body = Buffer.concat(chunks);
      receivedBodyLength = body.length;
      console.log(`[mock server] received binary body of length ${body.length}`);
      
      const jsonResponse = JSON.stringify({ text: "hey heliox list the files" });
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

// Map characters needed for writing config JSON
const keyMap = new Map(Object.entries({
  " ": "spc",
  ".": "dot",
  "-": "minus",
  "/": "slash",
  "_": "shift-minus",
  ":": "shift-semicolon",
  "{": "shift-bracket_left",
  "}": "shift-bracket_right",
  "\"": "shift-apostrophe",
  ",": "comma"
}));

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
  await waitForSerial("FerrumOS:~$", 30);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // 2. Write custom config.json to enable STT loop and set vad_threshold to 0
  await sendText("write /disk/heliox/config.json {\"api_host\":\"host\",\"stt_host\":\"10.0.2.2\",\"stt_port\":8786,\"vad_threshold\":0}");
  await sendKey("ret");
  await sleep(600);

  // 3. Queue a voice event before entering ring-3 (as the shell is replaced on entry)
  await sendText("heliox voice event hello world");
  await sendKey("ret");
  await sleep(600);

  // 4. Start init supervisor
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: Daemon spawns and registers voice activity due to vad_threshold=0
  await waitForSerial("[heliox-daemon] voice activity detected, recording command...", 30, start);
  check("daemon starts and detects voice activity (VAD=0)", true);

  // Step 2: Daemon records 3 seconds of audio and POSTs to Whisper mock endpoint
  await waitForSerial("[heliox-daemon] voice transcript: hey heliox list the files", 30, start);
  check("daemon receives mock STT transcript", true);
  check("mock server received the binary audio payload", requestReceived);
  check("mock server received expected size (>=500KB)", receivedBodyLength >= 500000); // 3 seconds * 192KB/s = 576KB

  // Step 3: Daemon sets goal from ambient VAD transcription
  await waitForSerial("[heliox-daemon] new goal set: list the files", 30, start);
  check("daemon extracts and sets new goal from transcript", true);

  // Step 4: Verify the queued voice event updated the goal via IPC
  await waitForSerial("New goal set via IPC: hello world", 30, start);
  check("queued shell command voice event updates goal on the daemon via IPC", true);

  // Step 5: Verify no userspace page fault or panic
  const full = serialText().slice(start);
  check("no userspace fault/panic during voice activity test",
    !/terminating|General Protection|Page Fault/.test(full));

} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
  mockServer.close();
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
