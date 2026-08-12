// Exercise concurrent, read-only world-model previews over the real in-guest
// WebSocket JSON-RPC server.  Requests deliberately share one connection so
// response correlation, preview state isolation, and bridge framing are tested
// together without executing any proposed action.
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";
import { assertPaired, waitForPairingToken } from "./lib/heliox_pairing.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const sourceDisk = path.join(repo, "target", "heliox-disk.img");
const runId = `${process.pid}-${Date.now()}`;
const runDisk = path.join(repo, "target", `world-model-preview-concurrency-${runId}.img`);
const runDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "ferrumos-preview-concurrency-"));
const serialLog = path.join(runDirectory, "serial.log");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu)) qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const monitorPort = process.env.FERRUMOS_MONITOR_PORT
  ? Number(process.env.FERRUMOS_MONITOR_PORT)
  : await freeTcpPort();
const hostPort = await freeTcpPort();
const requestCount = Number(process.env.FERRUMOS_PREVIEW_REQUESTS || 96);
const outputIndex = process.argv.indexOf("--json-out");
const outputPath = outputIndex >= 0 ? path.resolve(repo, process.argv[outputIndex + 1]) : null;
if (!fs.existsSync(image) || !fs.existsSync(sourceDisk)) throw new Error("build the boot image and appliance disk first");
fs.copyFileSync(sourceDisk, runDisk);
// Keep the daemon unconfigured so the test exercises only the bridge and
// preview gate; no provider request or ambient action may race the batch.
const relativeRunDisk = path.relative(repo, runDisk).replaceAll("\\", "/");
const unlinkConfig = spawnSync("wsl", ["debugfs", "-w", "-R", "unlink /heliox/config.json", relativeRunDisk], {
  cwd: repo, encoding: "utf8",
});
if (unlinkConfig.status !== 0) throw new Error(`failed to prepare isolated appliance disk: ${unlinkConfig.stderr}`);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (serialText().includes(needle)) return;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}\n${serialText().slice(-3000)}`);
}
async function connectMonitor() {
  for (let i = 0; i < 80; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port: monitorPort }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(250); }
  }
  throw new Error("could not connect to QEMU monitor");
}
function rpcBatch(ws, requests) {
  return new Promise((resolve, reject) => {
    const pending = new Map(requests.map((request) => [request.id, request]));
    const responses = new Map();
    const timer = setTimeout(() => reject(new Error(`timed out with ${pending.size} responses missing`)), 30000);
    const handler = (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (!pending.has(message.id)) return;
      responses.set(message.id, message);
      pending.delete(message.id);
      if (pending.size === 0) {
        clearTimeout(timer);
        ws.removeEventListener("message", handler);
        resolve(responses);
      }
    };
    ws.addEventListener("message", handler);
    for (const request of requests) ws.send(JSON.stringify(request));
  });
}

const qemuArgs = [
  "-m", "4096M", "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", `user,id=net0,hostfwd=tcp::${hostPort}-:8785`,
  "-device", "rtl8139,netdev=net0", "-display", "none", "-no-reboot",
];
let accelerator = "whpx";
let child = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: true });
await sleep(2500);
if (child.exitCode !== null) {
  accelerator = "tcg";
  child = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: true });
}

let monitor;
let ws;
try {
  monitor = await connectMonitor();
  await waitForSerial("FerrumOS:~$", 45);
  monitor.write("sendkey r 20\nsendkey i 20\nsendkey n 20\nsendkey g 20\nsendkey 3 20\nsendkey spc 20\nsendkey i 20\nsendkey n 20\nsendkey i 20\nsendkey t 20\nsendkey ret 20\n");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 30);
  await waitForSerial("[world-model-load-v1]", 10);
  await sleep(1500);
  ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timed out opening preview WebSocket")), 20000);
    ws.onopen = () => { clearTimeout(timer); resolve(); };
    ws.onerror = (error) => { clearTimeout(timer); reject(error); };
  });

  const token = await waitForPairingToken(serialText);
  const paired = await rpcBatch(ws, [{
    jsonrpc: "2.0", id: "pair", method: "pair", params: { token, control_mode: "cooperative" },
  }]);
  assertPaired(paired.get("pair"));

  const cases = [
    { tool: "list_dir", args: { path: "/disk" } },
    { tool: "read_file", args: { path: "/disk/readme.txt" } },
    { tool: "write_file", args: { path: "/disk/tmp/preview.txt", content: "not executed" } },
    { tool: "delete_file", args: { path: "/disk/system/config.json" } },
    { tool: "shell", args: { command: "status" } },
    { tool: "hud_update", args: { suggestion: "x".repeat(256), confidence: 0.75 } },
  ];
  const requests = Array.from({ length: requestCount }, (_, index) => ({
    jsonrpc: "2.0", id: `preview-${index}`, method: "world_model_preview", params: cases[index % cases.length],
  }));
  const datasetBefore = (serialText().match(/\[world-model-dataset-v2\]/g) || []).length;
  const started = performance.now();
  const responses = await rpcBatch(ws, requests);
  const elapsedMs = performance.now() - started;
  const valid = requests.every(({ id }) => {
    const result = responses.get(id)?.result;
    return result && typeof result.allowed === "boolean" && Number.isFinite(result.risk)
      && Number.isInteger(result.lookahead_steps) && typeof result.reason === "string"
      && typeof result.suggestion === "string";
  });
  const stable = cases.every((_, caseIndex) => {
    const values = requests.filter((__, i) => i % cases.length === caseIndex)
      .map(({ id }) => JSON.stringify(responses.get(id)?.result));
    return new Set(values).size === 1;
  });
  await sleep(250);
  const log = serialText();
  const datasetAfter = (log.match(/\[world-model-dataset-v2\]/g) || []).length;
  if (responses.size !== requestCount) throw new Error(`received ${responses.size}/${requestCount} responses`);
  if (!valid) throw new Error("one or more responses failed the world_model_preview schema");
  if (!stable) throw new Error("identical concurrent previews produced different decisions");
  if (datasetAfter !== datasetBefore) throw new Error("read-only preview emitted an execution dataset event");
  if (!/\[world-model-load-v1\].*encoder_loaded=1 transition_loaded=1/.test(log)) throw new Error("learned world model was not loaded");
  if (/panicked at|Page Fault|General Protection Fault|terminating userspace task/i.test(log)) throw new Error("guest fault detected");
  if (outputPath) {
    const report = {
      schema_version: 1,
      protocol: "world-model-preview-concurrency-v1",
      accelerator,
      ram_mb: 4096,
      outstanding_requests: requestCount,
      action_classes: cases.length,
      responses_received: responses.size,
      batch_wall_milliseconds: Number(elapsedMs.toFixed(3)),
      identical_requests_deterministic: stable,
      execution_dataset_records_added: datasetAfter - datasetBefore,
      learned_encoder_loaded: true,
      learned_transition_loaded: true,
      guest_fault_free: true,
      serial_sha256: crypto.createHash("sha256").update(log).digest("hex"),
      limitation: "The single-threaded daemon serializes preview inference; concurrency here means multiple outstanding requests with response correlation, not parallel neural execution.",
    };
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + "\n");
  }
  console.log(`PASS concurrent preview responses correlated: ${responses.size}/${requestCount}`);
  console.log(`PASS identical previews deterministic across ${cases.length} action classes`);
  console.log("PASS previews did not execute actions or emit execution dataset records");
  console.log(`PASS guest remained fault-free (${elapsedMs.toFixed(1)} ms batch wall time)`);
} finally {
  try { ws?.close(); } catch {}
  try { monitor?.destroy(); } catch {}
  try { child?.kill("SIGKILL"); } catch {}
  await sleep(250);
  fs.rmSync(runDisk, { force: true });
  fs.rmSync(runDirectory, { recursive: true, force: true });
}
