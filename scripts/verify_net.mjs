// ============================================================================
// FerrumOS - heliox-daemon Ring-3 network verification
// ============================================================================
// Boots the kernel in QEMU with network cards, runs a mock HTTP server on host
// port 8080, writes a network test trigger `/tmp/net_test`, and asserts that
// the daemon successfully makes the HTTP GET request and receives the response.
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
const serialLog = path.join(repo, "target", "net-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

// 1. Start Host-Side Mock HTTP Server
let requestReceived = false;
const mockServer = http.createServer((req, res) => {
  console.log(`[mock server] received request: ${req.method} ${req.url}`);
  if (req.url === "/test" && req.method === "GET") {
    requestReceived = true;
    res.writeHead(200, {
      "Content-Type": "text/plain",
      "Content-Length": "6"
    });
    res.end("net_ok");
  } else {
    res.writeHead(404);
    res.end();
  }
});

await new Promise((resolve) => {
  mockServer.listen(8080, "127.0.0.1", () => {
    console.log("[mock server] listening on port 8080");
    resolve();
  });
});

const qemuArgs = [
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
  "-device", "rtl8139,netdev=net0",
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

try {
  await waitForSerial("FerrumOS:~$", 30);
  check("boot reaches shell prompt", true);

  const start = serialText().length;
  // Write the network trigger file
  await sendText("write /tmp/net_test 10.0.2.2:8080/test");
  await sendKey("ret");
  await sleep(400);

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Step 1: daemon starts and detects network test trigger
  await waitForSerial("[heliox-daemon] running network test GET to 10.0.2.2:8080/test", 20, start);
  check("daemon starts and registers network test trigger", true);

  // Step 2: daemon performs GET request and logs success
  await waitForSerial("[heliox-daemon] net_test response status: 200, body: net_ok", 20, start);
  check("daemon successfully performs HTTP GET and gets 'net_ok' response", true);
  check("mock server received the request", requestReceived);

  // Step 3: verify no page fault/panic occurred
  const full = serialText().slice(start);
  check("no userspace fault/panic during network test",
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
