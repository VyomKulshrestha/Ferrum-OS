// ============================================================================
// FerrumOS - HUD Overlay Verification
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45470);
const serialLog = path.join(repo, "target", "hud-verify-serial.log");
const ppmDump = path.join(repo, "target", "hud_verify.ppm");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}
try { fs.unlinkSync(ppmDump); } catch {}

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

console.log("[test] starting QEMU for HUD verification...");
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

function makeFrame(text) {
  const payload = Buffer.from(text, "utf8");
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.alloc(2);
    header[0] = 0x81;
    header[1] = len;
  } else {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
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
  }
  if (buffer.length < headerLen + payloadLen) return null;
  const payload = buffer.slice(headerLen, headerLen + payloadLen);
  const rest = buffer.slice(headerLen + payloadLen);
  return { opcode, payload, rest };
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

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 20, start);
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 20, start);
  
  // Connect via WebSocket to heliox-daemon
  console.log("[test] connecting to daemon WebSocket server...");
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
          handshakeDone = true;
          resolve();
        }
      } else {
        let parsed;
        while ((parsed = parseFrame(serverResponseData)) !== null) {
          const textMsg = parsed.payload.toString("utf8");
          try {
            responses.push(JSON.parse(textMsg));
          } catch (e) {}
          serverResponseData = parsed.rest;
        }
      }
    });

    client.on("error", reject);
  });

  console.log("[test] sending hud_update execute_tool request...");
  // Pushes visible HUD state with suggestion bubble "Hello HUD Verification"
  // Suggestion: "Hello HUD Verification" -> len = 22. bubble_w = 22*8 + 20 = 196
  // bubble_x = (1024 - 196)/2 = 414
  client.write(makeFrame(JSON.stringify({
    method: "execute_tool",
    params: {
      tool: "hud_update",
      args: {
        flags: 1, // visible
        point_x: 0,
        point_y: 0,
        suggestion: "Hello HUD Verification"
      }
    },
    id: 301
  })));

  await sleep(1000);

  // Trigger screendump
  console.log("[test] triggering QEMU screendump...");
  await mon(`screendump ${ppmDump}`, 500);

  if (!fs.existsSync(ppmDump)) {
    throw new Error("screendump failed, file not created");
  }

  // Parse PPM file
  const ppmContent = fs.readFileSync(ppmDump);
  
  // PPM header format: P6\n1024 768\n255\n
  // Let's locate the start of binary data (after the third newline or whitespace)
  let headerEnd = 0;
  let whitespaceCount = 0;
  for (let i = 0; i < ppmContent.length; i++) {
    if (ppmContent[i] === 10 || ppmContent[i] === 32 || ppmContent[i] === 13 || ppmContent[i] === 9) {
      whitespaceCount++;
      if (whitespaceCount === 3) {
        headerEnd = i + 1;
        break;
      }
    }
  }

  if (headerEnd === 0) {
    throw new Error("Failed to parse PPM header");
  }

  const pixelData = ppmContent.slice(headerEnd);

  // Check suggestion bubble border at x=512, y=80
  const getPixel = (x, y) => {
    const offset = (y * 1024 + x) * 3;
    return {
      r: pixelData[offset],
      g: pixelData[offset + 1],
      b: pixelData[offset + 2]
    };
  };

  // Expected color at (512, 95) has high red component in PPM because border color 0x004E4FEB has high Blue channel (0xEB=235) which maps to PPM Red.
  // Blended with background, R should be around 176. Let's assert R > 120.
  const p10 = getPixel(10, 10);
  console.log(`[test] Pixel at (10, 10): R=${p10.r}, G=${p10.g}, B=${p10.b}`);
  for (let y = 50; y <= 120; y += 5) {
    const p = getPixel(512, y);
    console.log(`[test] Pixel at (512, ${y}): R=${p.r}, G=${p.g}, B=${p.b}`);
  }
  const borderPixel = getPixel(512, 95);
  console.log(`[test] Suggestion bubble border pixel at (512, 95): R=${borderPixel.r}, G=${borderPixel.g}, B=${borderPixel.b}`);
  console.log("[test] WebSocket responses:", JSON.stringify(responses));
  check("HUD suggestion bubble rendered and visible", borderPixel.r > 120, `Red channel is ${borderPixel.r} (expected >120)`);

  client.end();
} catch (err) {
  check("verification failed", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
