// ============================================================================
// FerrumOS - Synthetic Camera & Gesture Verification
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45465);
const serialLog = path.join(repo, "target", "camera-verify-serial.log");
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

const qemuArgs = [
  "-m", "2048M",
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

console.log("[test] starting QEMU...");
// Without an explicit accelerator, QEMU falls back to plain (unaccelerated)
// TCG at whatever default memory/speed it happens to pick - heliox-daemon's
// ELF alone needs to map ~16,385 pages for its ~64MB heap arena
// (src/process/mod.rs's map_user_range), and this reliably took long enough
// under unaccelerated/under-provisioned QEMU to blow through every timeout
// in this script, every run - not because anything was actually hung.
let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("[test] WHPX unsupported or failed, falling back to TCG...");
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

const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon" }));
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

function makeFrame(text) {
  const payload = Buffer.from(text, "utf8");
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81;
    header[1] = len;
  } else if (len <= 65535) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }
  return Buffer.concat([header, payload]);
}

function parseFrame(buffer) {
  if (buffer.length < 2) return null;
  const opcode = buffer[0] & 0x0f;
  const lenByte = buffer[1] & 0x7f;
  let headerLen = 2;
  let payloadLen = lenByte;
  if (lenByte === 126) {
    if (buffer.length < 4) return null;
    payloadLen = buffer.readUInt16BE(2);
    headerLen = 4;
  } else if (lenByte === 127) {
    if (buffer.length < 10) return null;
    payloadLen = Number(buffer.readBigUInt64BE(2));
    headerLen = 10;
  }
  if (buffer.length < headerLen + payloadLen) return null;
  const payload = buffer.slice(headerLen, headerLen + payloadLen);
  const rest = buffer.slice(headerLen + payloadLen);
  return { opcode, payload, rest };
}

try {
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Wait for the camera online log from kernel
  await waitForSerial("[camera] device online (synthetic)", 45, 0);
  check("kernel detects and registers synthetic camera", true);

  // Wait for the daemon to start and initialize its socket
  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 45, start);
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 45, start);
  await waitForSerial("[heliox-daemon] camera device detected, enabling gesture pipeline", 45, start);
  check("daemon starts, detects camera, and initializes pipeline", true);

  // Wait for initial gesture processing log
  await waitForSerial("[heliox-daemon] gesture: OpenPalm", 45, start);
  await waitForSerial("[heliox-daemon] gesture OpenPalm -> direct: resume agent", 45, start);
  check("gesture OpenPalm detected and direct action triggered", true);

  // Connect via WebSocket
  console.log("[test] connecting to guest daemon WebSocket server...");
  const client = net.createConnection({ port: 8785, host: "127.0.0.1" });
  
  let handshakeDone = false;
  let serverResponseData = Buffer.alloc(0);
  const responses = [];

  await new Promise((resolve, reject) => {
    client.on("connect", () => {
      client.write(
        "GET / HTTP/1.1\r\n" +
        "Host: 127.0.0.1:8785\r\n" +
        "Upgrade: websocket\r\n" +
        "Connection: Upgrade\r\n" +
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n" +
        "Sec-WebSocket-Version: 13\r\n\r\n"
      );
    });

    client.on("data", (data) => {
      serverResponseData = Buffer.concat([serverResponseData, data]);
      
      if (!handshakeDone) {
        const idx = serverResponseData.indexOf("\r\n\r\n");
        if (idx !== -1) {
          const header = serverResponseData.slice(0, idx).toString();
          if (header.includes("101 Switching Protocols")) {
            handshakeDone = true;
            serverResponseData = serverResponseData.slice(idx + 4);
            resolve();
          } else {
            reject(new Error("Upgrade rejected: " + header));
          }
        }
      } else {
        let parsed;
        while ((parsed = parseFrame(serverResponseData)) !== null) {
          const textMsg = parsed.payload.toString("utf8");
          try {
            responses.push(JSON.parse(textMsg));
          } catch (e) {
            console.error("[test] failed to parse response JSON:", textMsg, e);
          }
          serverResponseData = parsed.rest;
        }
      }
    });

    client.on("error", reject);
  });

  await waitForSerial("[heliox-daemon] bridge client connected, handshake successful!", 45, start);
  check("WebSocket bridge handshake successful", true);

  // Send ping request
  client.write(makeFrame(JSON.stringify({ method: "ping", id: 100 })));
  let deadline = Date.now() + 5000;
  while (responses.length < 1 && Date.now() < deadline) {
    await sleep(50);
  }
  check("received pong from daemon", responses.length >= 1 && responses[0].result === "pong" && responses[0].id === 100);

  // Query gesture_status tool
  client.write(makeFrame(JSON.stringify({
    method: "execute_tool",
    params: {
      tool: "gesture_status",
      args: {}
    },
    id: 101
  })));
  deadline = Date.now() + 5000;
  while (responses.length < 2 && Date.now() < deadline) {
    await sleep(50);
  }
  check("gesture_status tool execution succeeded", responses.length >= 2 && responses[1].id === 101 && responses[1].result && responses[1].result.success === true);
  check("gesture_status reported OpenPalm", responses.length >= 2 && responses[1].result.output.includes("OpenPalm"));

  // Query camera_capture tool
  client.write(makeFrame(JSON.stringify({
    method: "execute_tool",
    params: {
      tool: "camera_capture",
      args: {}
    },
    id: 102
  })));
  deadline = Date.now() + 5000;
  while (responses.length < 3 && Date.now() < deadline) {
    await sleep(50);
  }
  check("camera_capture tool execution succeeded", responses.length >= 3 && responses[2].id === 102 && responses[2].result && responses[2].result.success === true);
  check("camera_capture reported OpenPalm", responses.length >= 3 && responses[2].result.output.includes("OpenPalm"));

  // Close connection
  client.end();
  await sleep(500);

  // Check no userspace fault/panic occurred
  const full = serialText().slice(start);
  check("no userspace fault/panic during camera test",
    !/terminating|General Protection|Page Fault/.test(full));

} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
