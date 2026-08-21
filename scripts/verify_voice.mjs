// ============================================================================
// FerrumOS - heliox-daemon End-to-End Voice & STT Loop verification
// ============================================================================
// Boots the kernel in QEMU with audio devices, runs a mock Whisper STT server
// on free host ports, writes a custom config to /disk/heliox/config.json with
// vad_threshold=0 to force silent capture, and asserts that:
//   1. the daemon starts up and detects voice activity,
//   2. records 3 seconds and POSTs to mock Whisper STT,
//   3. the capture blocks only the calling task while init keeps scheduling,
//   4. the transcript enters voice-event handling and triggers a safe action,
//   5. the action reaches a capability-gated syscall without bypassing the
//      normal world-model, permission-tier, or confirmation pipeline,
//   6. receiving "heliox voice event" updates the goal via IPC.
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";
import { assertPaired, rpcCall, waitForPairingToken } from "./lib/heliox_pairing.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const port = Number(process.env.FERRUMOS_MONITOR_PORT || await freeTcpPort());
const sttPort = Number(process.env.FERRUMOS_STT_PORT || await freeTcpPort());
const providerPort = Number(process.env.FERRUMOS_PROVIDER_PORT || await freeTcpPort());
const hostPort = Number(process.env.FERRUMOS_HOST_PORT || await freeTcpPort());
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
let providerRequestReceived = false;
let voiceProviderRequestReceived = false;
let safeVoiceActionReturned = false;
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

const mockProvider = http.createServer((req, res) => {
  if (req.url === "/api/generate" && req.method === "POST") {
    providerRequestReceived = true;
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const body = Buffer.concat(chunks).toString("utf8");
      const isCapturedVoiceGoal = body.includes("list the files");
      voiceProviderRequestReceived ||= isCapturedVoiceGoal;
      const action = !isCapturedVoiceGoal
        ? null
        : !safeVoiceActionReturned
          ? {
              tool: "report_status",
              args: { status: "voice-capture-ok" },
            }
          : {
              tool: "write_file",
              args: { path: "/tmp/voice-confirmation-boundary", content: "blocked" },
            };
      if (isCapturedVoiceGoal && !safeVoiceActionReturned) {
        safeVoiceActionReturned = true;
      }
      const response = JSON.stringify({
        response: action === null
          ? "No action for the queued shell-only test event."
          : JSON.stringify(action),
      });
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(response).toString(),
      });
      res.end(response);
    });
  } else {
    res.writeHead(404);
    res.end();
  }
});

await new Promise((resolve) => {
  mockServer.listen(sttPort, "127.0.0.1", () => {
    console.log(`[mock server] STT listening on port ${sttPort}`);
    resolve();
  });
});
await new Promise((resolve) => {
  mockProvider.listen(providerPort, "127.0.0.1", () => {
    console.log(`[mock provider] listening on port ${providerPort}`);
    resolve();
  });
});

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", `user,id=net0,hostfwd=tcp:127.0.0.1:${hostPort}-:8785`,
  "-device", "rtl8139,netdev=net0",
  "-audiodev", "none,id=hda0,timer-period=10000,in.fixed-settings=on,in.frequency=48000,in.channels=2,in.format=s16",
  "-device", "intel-hda",
  "-device", "hda-duplex,audiodev=hda0",
  "-no-reboot",
];
if (!visible) qemuArgs.push("-display", "none");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let qemuProcess = spawn(
  qemu,
  ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs],
  { windowsHide: !visible },
);
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: !visible });
  await sleep(1500);
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

async function sendKey(k) { await mon(`sendkey ${k} 20`, 45); }
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
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // 2. Write custom config.json to enable STT loop and set vad_threshold to 0
  await sendText(`write /disk/heliox/config.json {"provider":"ollama","model_name":"voice-test","api_host":"10.0.2.2","api_port":${providerPort},"api_path":"/api/generate","tick_interval":1,"auto_approve_tier":1,"stt_host":"10.0.2.2","stt_port":${sttPort},"vad_threshold":0}`);
  await sendKey("ret");
  await sleep(600);

  // 3. Queue a voice event before entering ring-3 (as the shell is replaced on entry)
  await sendText("heliox voice event hello world");
  await sendKey("ret");
  await sleep(600);

  // 4. Start init supervisor
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 30, start);
  const ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
  const pairingToken = await waitForPairingToken(serialText);
  assertPaired(await rpcCall(ws, "pair-voice", "pair", {
    token: pairingToken,
    control_mode: "cooperative",
  }));
  check("external model remains paired while ambient hearing is enabled", true);

  // Step 1: Daemon spawns and registers voice activity due to vad_threshold=0
  await waitForSerial("[heliox-daemon] voice activity detected, recording command...", 30, start);
  check("daemon starts and detects voice activity (VAD=0)", true);
  const captureStart = serialText().indexOf(
    "[heliox-daemon] voice activity detected, recording command...",
    start,
  );

  // Step 2: Daemon records 3 seconds of audio and POSTs to Whisper mock endpoint
  await waitForSerial("[heliox-daemon] voice transcript: hey heliox list the files", 30, start);
  check("daemon receives mock STT transcript", true);
  check("mock server received the binary audio payload", requestReceived);
  check("mock server received expected size (>=500KB)", receivedBodyLength >= 500000); // 3 seconds * 192KB/s = 576KB

  const transcriptOffset = serialText().indexOf(
    "[heliox-daemon] voice transcript: hey heliox list the files",
    captureStart,
  );
  const captureWindow = serialText().slice(captureStart, transcriptOffset);
  const heartbeats = (captureWindow.match(/\[init\] heartbeat/g) || []).length;
  check(
    `independent init task kept scheduling during 3s capture (heartbeats=${heartbeats})`,
    heartbeats >= 2,
  );

  // Step 3: Daemon sets goal from ambient VAD transcription
  await waitForSerial("[heliox-daemon] new goal set: list the files", 30, start);
  check("daemon extracts and sets new goal from transcript", true);

  await waitForSerial("[heliox-daemon] voice event accepted: list the files", 30, start);
  check("captured transcript enters Heliox voice-event handling", true);
  const voiceEventOffset = serialText().indexOf(
    "[heliox-daemon] voice event accepted: list the files",
    transcriptOffset,
  );

  await waitForSerial(
    "[AUDIT] UserAudit: HELIOX_STATUS:voice-capture-ok",
    30,
    voiceEventOffset,
  );
  check("voice-triggered Tier-1 report_status reaches capability-gated audit syscall", true);
  check("mock provider received the voice-driven planning request", providerRequestReceived);
  check("provider request contains the captured voice goal", voiceProviderRequestReceived);
  const safeActionOffset = serialText().indexOf(
    "[AUDIT] UserAudit: HELIOX_STATUS:voice-capture-ok",
    voiceEventOffset,
  );

  await waitForSerial(
    "[heliox-daemon] tool write_file awaiting operator confirmation",
    30,
    safeActionOffset,
  );
  check("higher-tier follow-up remains behind explicit operator confirmation", true);

  // Step 4: Verify the queued voice event updated the goal via IPC
  await waitForSerial("New goal set via IPC: hello world", 30, start);
  check("queued shell command voice event updates goal on the daemon via IPC", true);

  const pong = await rpcCall(ws, "voice-ping", "ping", {});
  check("bridge remains responsive after the full audio/STT cycle", pong.result === "pong");
  ws.close();

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
  mockProvider.close();
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
