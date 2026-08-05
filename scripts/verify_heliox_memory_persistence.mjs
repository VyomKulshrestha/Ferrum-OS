// FerrumOS - Heliox durable memory verification
// Proves explicit context is saved through the canonical world-model path,
// survives a full guest reboot, is restored automatically, and is queryable.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const appliance = path.join(repo, "target", "heliox-disk.img");
const runDisk = path.join(repo, "target", "memory-persistence-verify-disk.img");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(appliance)) throw new Error(`appliance disk not found: ${appliance}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);

fs.rmSync(runDisk, { force: true });
fs.copyFileSync(appliance, runDisk);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
  ":": "shift-semicolon", "{": "shift-bracket_left", "}": "shift-bracket_right",
  "\"": "shift-apostrophe", ",": "comma",
}));

async function connectMonitor(port) {
  for (let i = 0; i < 80; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(200); }
  }
  throw new Error("could not connect to QEMU monitor");
}

function rpc(ws, id, method, params) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`timed out waiting for ${method}`)), 60_000);
    const handler = (event) => {
      try {
        const response = JSON.parse(event.data);
        if (response.id === id) {
          clearTimeout(timeout);
          ws.removeEventListener("message", handler);
          resolve(response);
        }
      } catch { /* ignore unrelated frames */ }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  });
}

async function boot(label, configure) {
  const monitorPort = await freeTcpPort();
  const hostPort = await freeTcpPort();
  const serialLog = path.join(repo, "target", `memory-persistence-${label}-serial.log`);
  fs.rmSync(serialLog, { force: true });
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
  const monitor = await connectMonitor(monitorPort);
  const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
  const waitForSerial = async (needle, seconds, from = 0) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      if (serialText().slice(from).includes(needle)) return serialText().slice(from);
      await sleep(150);
    }
    throw new Error(`[${label}] timed out waiting for ${needle}\n${serialText().slice(-2500)}`);
  };
  const sendKey = async (key) => { monitor.write(`sendkey ${key} 20\n`); await sleep(40); };
  const sendText = async (text) => {
    for (const char of text) {
      if (keyMap.has(char)) await sendKey(keyMap.get(char));
      else if (/^[a-z0-9]$/i.test(char)) await sendKey(char.toLowerCase());
      else throw new Error(`no key mapping for ${JSON.stringify(char)}`);
    }
  };

  await waitForSerial("FerrumOS:~$", 90);
  if (configure) {
    await sendText('write /disk/heliox/config.json {"provider":"auto","auto_approve_tier":3,"tick_interval":1000}');
    await sendKey("ret");
    await waitForSerial("FerrumOS:~$", 15, serialText().length - 64);
  }
  const start = serialText().length;
  await sendText("ring3 init");
  await sendKey("ret");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 60, start);
  const ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  return { child, monitor, ws, serialText, waitForSerial, start };
}

let first;
let second;
try {
  first = await boot("write", true);
  const saved = await rpc(first.ws, "save", "execute_tool", {
    tool: "save_memory",
    args: {
      id: "release-memory-proof",
      category: "preference",
      content: "Remember cobalt window layout for the release acceptance proof",
    },
  });
  check("save_memory executes through the public world-model path", saved.result?.success === true, JSON.stringify(saved));
  check("save_memory reports a durable document", /documents\)/.test(saved.result?.output || ""), saved.result?.output || "");
  const before = await rpc(first.ws, "before", "execute_tool", {
    tool: "query_memory", args: { query: "cobalt window layout", top_k: 3 },
  });
  check("new context is queryable before reboot", /cobalt window layout/.test(before.result?.output || ""));
  check("memory action emitted a world-model dataset row", first.serialText().slice(first.start).includes("[world-model-dataset-v2]"));
  first.ws.close();
  first.monitor.destroy();
  first.child.kill("SIGKILL");
  await sleep(750);

  second = await boot("restore", false);
  const restoredLog = await second.waitForSerial("[heliox-daemon] restored", 20, second.start);
  check("daemon automatically restores durable memory at boot", /restored \d+ durable memories/.test(restoredLog));
  const after = await rpc(second.ws, "after", "execute_tool", {
    tool: "query_memory", args: { query: "cobalt window layout", top_k: 3 },
  });
  check("context remains queryable after full guest reboot", /cobalt window layout/.test(after.result?.output || ""), after.result?.output || "");
  check("no userspace fault or kernel panic", !/terminating|General Protection|Page Fault|panicked/.test(second.serialText().slice(second.start)));
} catch (error) {
  check("memory persistence verification", false, error?.message?.split("\n")[0] || String(error));
} finally {
  for (const context of [first, second]) {
    try { context?.ws?.close(); } catch {}
    try { context?.monitor?.destroy(); } catch {}
    try { context?.child?.kill("SIGKILL"); } catch {}
  }
  await sleep(250);
  fs.rmSync(runDisk, { force: true });
}

console.log(results.join("\n"));
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
