// ============================================================================
// FerrumOS - heliox-daemon WebSocket Bridge Verification
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const qemu = process.env.QEMU || "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45460);
const serialLog = path.join(repo, "target", "bridge-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

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
  await waitForSerial("FerrumOS:~$", 30);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Wait for the daemon to start and initialize its socket
  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 20, start);
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 20, start);
  check("daemon starts and enters loop", true);

  // Connect via WebSocket
  console.log("[test] connecting to guest daemon WebSocket server...");
  const client = net.createConnection({ port: 8785, host: "127.0.0.1" });
  
  let handshakeDone = false;
  let serverResponseData = Buffer.alloc(0);
  const responses = [];

  await new Promise((resolve, reject) => {
    client.on("connect", () => {
      console.log("[test] connected at TCP level. Sending HTTP Upgrade...");
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
            console.log("[test] WebSocket handshake successful!");
            handshakeDone = true;
            serverResponseData = serverResponseData.slice(idx + 4);
            resolve();
          } else {
            reject(new Error("Upgrade rejected: " + header));
          }
        }
      } else {
        // Parse frames
        let parsed;
        while ((parsed = parseFrame(serverResponseData)) !== null) {
          const textMsg = parsed.payload.toString("utf8");
          console.log(`[test] received WS frame payload: ${textMsg}`);
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

  await waitForSerial("[heliox-daemon] bridge client connected, handshake successful!", 15, start);
  check("guest logs successful handshake connection", true);

  // Send ping request
  console.log("[test] sending ping...");
  client.write(makeFrame(JSON.stringify({ method: "ping", id: 100 })));
  
  // Wait for pong response
  let deadline = Date.now() + 5000;
  while (responses.length < 1 && Date.now() < deadline) {
    await sleep(50);
  }
  
  check("received pong from daemon", responses.length >= 1 && responses[0].result === "pong" && responses[0].id === 100);

  // Send execute_tool request
  console.log("[test] sending execute_tool...");
  client.write(makeFrame(JSON.stringify({
    method: "execute_tool",
    params: {
      tool: "yield_cpu",
      args: {}
    },
    id: 101
  })));

  // Wait for execute_tool response
  deadline = Date.now() + 5000;
  while (responses.length < 2 && Date.now() < deadline) {
    await sleep(50);
  }

  check("received execute_tool response from daemon", responses.length >= 2 && responses[1].id === 101);
  check("execute_tool result was successful", responses.length >= 2 && responses[1].result && responses[1].result.success === true);

  // Send gesture_event request
  console.log("[test] sending gesture_event...");
  client.write(makeFrame(JSON.stringify({
    method: "gesture_event",
    params: {
      gesture: "circle_clockwise"
    },
    id: 102
  })));

  // Wait for gesture response
  deadline = Date.now() + 5000;
  while (responses.length < 3 && Date.now() < deadline) {
    await sleep(50);
  }

  check("received gesture response from daemon", responses.length >= 3 && responses[2].id === 102 && responses[2].result === "ok");

  // Wait for the guest to log the gesture event mapping
  await waitForSerial("[heliox-daemon] gesture circle_clockwise mapped: injecting 'g'", 15, start);
  check("daemon mapped gesture and logged key injection", true);

  // Close connection
  client.end();
  await sleep(500);

  // Check no userspace fault/panic occurred
  const full = serialText().slice(start);
  check("no userspace fault/panic during bridge test",
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
