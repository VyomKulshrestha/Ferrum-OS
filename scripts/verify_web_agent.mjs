// FerrumOS - native web-agent verification
// Exercises DNS, HTTP, HTTPS certificate validation, target sanitization, the
// world-model gate, and socket cleanup through the real Ring-3 daemon.
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";
import { assertPaired, waitForPairingToken } from "./lib/heliox_pairing.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const appliance = path.join(repo, "target", "heliox-disk.img");
const runDisk = path.join(repo, "target", "web-agent-verify-disk.img");
const serialLog = path.join(repo, "target", "web-agent-verify-serial.log");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
if (!fs.existsSync(image) || !fs.existsSync(appliance) || !fs.existsSync(qemu)) {
  throw new Error("build image, appliance disk, or QEMU is missing");
}
fs.rmSync(runDisk, { force: true });
fs.rmSync(serialLog, { force: true });
fs.copyFileSync(appliance, runDisk);

const monitorPort = await freeTcpPort();
const hostPort = await freeTcpPort();
const httpPort = await freeTcpPort();
const httpsPort = await freeTcpPort();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
}

let plainRequests = 0;
const plainServer = http.createServer((request, response) => {
  plainRequests++;
  response.writeHead(200, { "Content-Type": "text/html", "Connection": "close" });
  response.end("<html><title>Ferrum Web</title><body>native http works</body></html>");
});
await new Promise((resolve) => plainServer.listen(httpPort, "0.0.0.0", resolve));

let tlsRequests = 0;
const tlsServer = https.createServer({
  key: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.key")),
  cert: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.pem")),
}, (request, response) => {
  tlsRequests++;
  response.writeHead(200, { "Content-Type": "text/html", "Connection": "close" });
  response.end("<html><title>Ferrum TLS</title><body>native https works</body></html>");
});
await new Promise((resolve) => tlsServer.listen(httpsPort, "0.0.0.0", resolve));

async function connectMonitor() {
  for (let i = 0; i < 80; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port: monitorPort }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(200); }
  }
  throw new Error("could not connect to QEMU monitor");
}

function rpc(ws, id, tool, args) {
  return rpcMethod(ws, id, "execute_tool", { tool, args });
}

function rpcMethod(ws, id, method, params) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`timed out waiting for ${id}`)), 90_000);
    const handler = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.id === id) {
          clearTimeout(timeout);
          ws.removeEventListener("message", handler);
          resolve(message);
        }
      } catch {}
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  });
}

const args = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", `user,id=net0,hostfwd=tcp:127.0.0.1:${hostPort}-:8785`,
  "-device", "rtl8139,netdev=net0",
  "-display", "none",
  "-no-reboot",
];
let child = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...args], { windowsHide: true });
await sleep(2500);
if (child.exitCode !== null && child.exitCode !== 0) {
  child = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...args], { windowsHide: true });
}

let monitor;
let ws;
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
const waitForSerial = async (needle, seconds, from = 0) => {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (serialText().slice(from).includes(needle)) return;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${needle}\n${serialText().slice(-2500)}`);
};
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus" }));

try {
  monitor = await connectMonitor();
  await waitForSerial("FerrumOS:~$", 90);
  const sendKey = async (key) => { monitor.write(`sendkey ${key} 20\n`); await sleep(40); };
  const sendText = async (text) => {
    for (const char of text) {
      if (keyMap.has(char)) await sendKey(keyMap.get(char));
      else if (/^[a-z0-9]$/i.test(char)) await sendKey(char.toLowerCase());
      else throw new Error(`no key mapping for ${JSON.stringify(char)}`);
    }
  };
  // Remove any provider config from the disposable disk so autonomous ticks
  // cannot race the focused bridge requests.
  await sendText("rm /disk/heliox/config.json");
  await sendKey("ret");
  await sleep(300);
  const start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 60, start);
  ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const pairingToken = await waitForPairingToken(serialText);
  assertPaired(await rpcMethod(ws, "pair", "pair", { token: pairingToken }));

  const plain = await rpc(ws, "plain", "browse_url", { url: `http://10.0.2.2:${httpPort}/page` });
  check("HTTP page is fetched and reduced to text", plain.result?.success === true && /native http works/.test(plain.result.output), plain.result?.output || "");

  const tls = await rpc(ws, "tls", "browse_url", { url: `https://10.0.2.2:${httpsPort}/secure` });
  check("HTTPS page is certificate-validated and reduced to text", tls.result?.success === true && /native https works/.test(tls.result.output), tls.result?.output || "");

  const beforeInjection = plainRequests;
  const injected = await rpc(ws, "injection", "browse_url", { url: `http://10.0.2.2:${httpPort}/\r\nX-Evil: yes` });
  check("header-injection URL is rejected", injected.result?.success === false && /invalid URL path/.test(injected.result.output), injected.result?.output || "");
  check("rejected URL never reaches the HTTP server", plainRequests === beforeInjection);

  // More than a token smoke: repeated requests in one process prove the GET
  // paths return their FDs instead of consuming the finite socket table.
  let repeatedOk = true;
  for (let index = 0; index < 12; index++) {
    const response = await rpc(ws, `repeat-${index}`, "http_get", { host: "10.0.2.2", port: httpPort, path: `/repeat-${index}` });
    repeatedOk &&= response.result?.success === true;
  }
  check("repeated native GET requests remain healthy in one daemon", repeatedOk && plainRequests === beforeInjection + 12, `requests=${plainRequests}`);

  // Real public-name resolution. Treat a remote HTTP status as success: the
  // proof here is that a DNS name, not a literal IP or QEMU alias, resolved
  // and reached an HTTP peer.
  const dns = await rpc(ws, "dns", "http_get", { host: "example.com", port: 80, path: "/" });
  check("ordinary public hostname resolves through native DNS", !/DNS resolution failed/.test(dns.result?.output || "") && /HTTP \d+ response/.test(dns.result?.output || ""), dns.result?.output || "");

  const log = serialText().slice(start);
  check("web actions pass through the world-model recorder", log.includes("action=39") && log.includes("executed=1"));
  check("no userspace fault or kernel panic", !/terminating|General Protection|Page Fault|panicked/.test(log));
} catch (error) {
  check("web-agent verification", false, error?.message?.split("\n")[0] || String(error));
} finally {
  try { ws?.close(); } catch {}
  try { monitor?.destroy(); } catch {}
  try { child?.kill("SIGKILL"); } catch {}
  plainServer.close();
  tlsServer.close();
  await sleep(250);
  fs.rmSync(runDisk, { force: true });
}

console.log(results.join("\n"));
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
