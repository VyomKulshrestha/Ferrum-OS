// Exercise four simultaneous WebSocket transports against FerrumOS's bounded
// read-only world-model preview service. No request in this script may execute.
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
const protocolPath = path.join(repo, "docs", "research", "world_model_multiclient_contention_protocol_v1.json");
const protocol = JSON.parse(fs.readFileSync(protocolPath, "utf8"));
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const sourceDisk = path.join(repo, "target", "heliox-disk.img");
const outputIndex = process.argv.indexOf("--json-out");
const outputPath = outputIndex >= 0
  ? path.resolve(repo, process.argv[outputIndex + 1])
  : path.join(repo, "docs", "research", "world_model_multiclient_contention_result_v1.json");
const transitionIndex = process.argv.indexOf("--transition");
const transitionPath = transitionIndex >= 0 ? path.resolve(repo, process.argv[transitionIndex + 1]) : null;
const runId = `${process.pid}-${Date.now()}`;
const runDisk = path.join(repo, "target", `world-model-multiclient-${runId}.img`);
const runDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "ferrumos-multiclient-"));
const serialLog = path.join(runDirectory, "serial.log");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu)) qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const monitorPort = await freeTcpPort();
const hostPort = await freeTcpPort();
const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const sourceDiskSha256 = digest(sourceDisk);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
if (!fs.existsSync(image) || !fs.existsSync(sourceDisk)) throw new Error("build the boot image and appliance disk first");
if (transitionPath && !fs.existsSync(transitionPath)) throw new Error(`research transition not found: ${transitionPath}`);

fs.copyFileSync(sourceDisk, runDisk);
const relativeRunDisk = path.relative(repo, runDisk).replaceAll("\\", "/");
const unlinkConfig = spawnSync("wsl", ["debugfs", "-w", "-R", "unlink /heliox/config.json", relativeRunDisk], { cwd: repo, encoding: "utf8" });
if (unlinkConfig.status !== 0) throw new Error(`failed to prepare isolated appliance disk: ${unlinkConfig.stderr}`);
if (transitionPath) {
  const relativeTransition = path.relative(repo, transitionPath).replaceAll("\\", "/");
  for (const command of ["unlink /heliox/world/model_learned.bin", `write ${relativeTransition} /heliox/world/model_learned.bin`]) {
    const prepared = spawnSync("wsl", ["debugfs", "-w", "-R", command, relativeRunDisk], { cwd: repo, encoding: "utf8" });
    if (prepared.status !== 0) throw new Error(`failed to inject research transition: ${prepared.stderr || prepared.stdout}`);
  }
}

async function waitForSerial(needle, seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (serialText().includes(needle)) return;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}\n${serialText().slice(-4000)}`);
}

async function connectMonitor() {
  for (let index = 0; index < 80; index++) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port: monitorPort }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(250); }
  }
  throw new Error("could not connect to QEMU monitor");
}

async function openClient(agentIndex) {
  const ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timed out opening agent ${agentIndex}`)), 20000);
    ws.onopen = () => { clearTimeout(timer); resolve(); };
    ws.onerror = (error) => { clearTimeout(timer); reject(error); };
  });
  const pending = new Map();
  const unexpected = [];
  ws.addEventListener("message", (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    const waiter = pending.get(message.id);
    if (!waiter) {
      unexpected.push(message.id);
      return;
    }
    pending.delete(message.id);
    waiter.resolve({ message, latencyMs: performance.now() - waiter.started });
  });
  const call = (request, timeoutMs = 30000) => new Promise((resolve, reject) => {
    const started = performance.now();
    const timer = setTimeout(() => {
      pending.delete(request.id);
      reject(new Error(`agent ${agentIndex} timed out waiting for ${request.id}`));
    }, timeoutMs);
    pending.set(request.id, {
      started,
      resolve: (value) => { clearTimeout(timer); resolve(value); },
    });
    ws.send(JSON.stringify(request));
  });
  return { agentIndex, ws, call, unexpected };
}

const cases = [
  { tool: "read_dir", args: { path: "/disk" } },
  { tool: "read_file", args: { path: "/disk/readme.txt" } },
  { tool: "write_file", args: { path: "/disk/tmp/preview.txt", content: "not executed" } },
  { tool: "delete_file", args: { path: "/disk/system/config.json" } },
  { tool: "list_processes", args: {} },
  { tool: "hud_update", args: { suggestion: "status", confidence: 0.75 } },
  { tool: "exec_process", args: { path: "/bin/browser" } },
  { tool: "save_memory", args: { text: "preview only" } },
];
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
const clients = [];
try {
  monitor = await connectMonitor();
  await waitForSerial("FerrumOS:~$", 45);
  monitor.write("sendkey r 20\nsendkey i 20\nsendkey n 20\nsendkey g 20\nsendkey 3 20\nsendkey spc 20\nsendkey i 20\nsendkey n 20\nsendkey i 20\nsendkey t 20\nsendkey ret 20\n");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 30);
  await waitForSerial("[world-model-load-v1]", 10);
  const token = await waitForPairingToken(serialText);

  // Open sequentially so each guest listener replacement is observable, then
  // retain all four transports through a shared timed barrier.
  for (let agentIndex = 0; agentIndex < protocol.clients; agentIndex++) {
    const client = await openClient(agentIndex);
    clients.push(client);
    const paired = await client.call({
      jsonrpc: "2.0", id: `agent-${agentIndex}:pair`, method: "pair",
      params: { token, control_mode: "cooperative" },
    });
    assertPaired(paired.message);
    await sleep(100);
  }

  const unauthorizedExecution = await clients[1].call({
    jsonrpc: "2.0", id: "agent-1:authority-probe", method: "execute_tool",
    params: { tool: "write_file", args: { path: "/disk/tmp/must-not-exist", content: "denied" } },
  });
  if (unauthorizedExecution.message?.error?.code !== -32601) {
    throw new Error("preview-only client did not reject execution authority");
  }

  const datasetBefore = (serialText().match(/\[world-model-dataset-v2\]/g) || []).length;
  const started = performance.now();
  const work = [];
  for (const client of clients) {
    for (let index = 0; index < protocol.requests_per_client; index++) {
      const request = {
        jsonrpc: "2.0",
        id: `agent-${client.agentIndex}:preview-${index}`,
        method: "world_model_preview",
        params: cases[index % cases.length],
      };
      work.push(client.call(request).then((value) => ({ ...value, agentIndex: client.agentIndex, request })));
    }
  }
  const completed = await Promise.all(work);
  const batchWallMs = performance.now() - started;

  const perClient = clients.map((client) => {
    const rows = completed.filter((item) => item.agentIndex === client.agentIndex);
    const latencies = rows.map((item) => item.latencyMs).sort((a, b) => a - b);
    const percentile = (q) => latencies[Math.min(latencies.length - 1, Math.floor((latencies.length - 1) * q))];
    return {
      agent_index: client.agentIndex,
      responses: rows.length,
      median_latency_ms: Number(percentile(0.5).toFixed(3)),
      p95_latency_ms: Number(percentile(0.95).toFixed(3)),
      maximum_latency_ms: Number(latencies.at(-1).toFixed(3)),
      throughput_per_second: Number((rows.length / (Math.max(...latencies) / 1000)).toFixed(3)),
      unexpected_response_ids: [...client.unexpected],
    };
  });
  const throughputs = perClient.map((item) => item.throughput_per_second);
  const fairness = (throughputs.reduce((a, b) => a + b, 0) ** 2)
    / (throughputs.length * throughputs.reduce((sum, value) => sum + value * value, 0));
  const schemaValid = completed.every(({ message }) => {
    const result = message.result;
    return result && typeof result.allowed === "boolean" && Number.isFinite(result.risk)
      && Number.isInteger(result.lookahead_steps) && typeof result.reason === "string"
      && typeof result.suggestion === "string";
  });
  const deterministic = cases.every((_, caseIndex) => {
    const values = completed
      .filter(({ request }) => Number(request.id.split("-").at(-1)) % cases.length === caseIndex)
      .map(({ message }) => JSON.stringify(message.result));
    return new Set(values).size === 1;
  });

  // Disconnect a preview-only transport while the other three continue, then
  // reconnect and require a fresh pairing before a preview succeeds.
  clients[3].ws.close();
  await sleep(350);
  const survivorChecks = await Promise.all(clients.slice(0, 3).map((client) => client.call({
    jsonrpc: "2.0", id: `agent-${client.agentIndex}:survivor`, method: "world_model_preview", params: cases[client.agentIndex],
  })));
  const replacement = await openClient(3);
  const prePair = await replacement.call({
    jsonrpc: "2.0", id: "agent-3:prepair", method: "world_model_preview", params: cases[0],
  });
  const prePairRejected = prePair.message?.error?.code === -32003;
  const repairedPair = await replacement.call({
    jsonrpc: "2.0", id: "agent-3:repair", method: "pair", params: { token, control_mode: "cooperative" },
  });
  assertPaired(repairedPair.message);
  const replacementPreview = await replacement.call({
    jsonrpc: "2.0", id: "agent-3:replacement", method: "world_model_preview", params: cases[0],
  });
  replacement.ws.close();
  const disconnectIsolation = survivorChecks.every((item) => item.message?.result)
    && prePairRejected && Boolean(replacementPreview.message?.result);

  await sleep(300);
  const log = serialText();
  const datasetAfter = (log.match(/\[world-model-dataset-v2\]/g) || []).length;
  const sourceDiskAfter = digest(sourceDisk);
  const checks = {
    distinct_websocket_transports: clients.length === protocol.clients,
    all_timed_responses_received: completed.length === protocol.clients * protocol.requests_per_client,
    preview_schema_valid: schemaValid,
    no_cross_client_response_leakage: perClient.every((item) => item.unexpected_response_ids.length === 0),
    identical_requests_deterministic: deterministic,
    throughput_fairness: fairness >= 0.95,
    preview_only_execution_rejected: unauthorizedExecution.message?.error?.code === -32601,
    disconnect_isolation_and_repair: disconnectIsolation,
    no_execution_dataset_records: datasetAfter === datasetBefore,
    learned_model_loaded: /\[world-model-load-v1\].*encoder_loaded=1 transition_loaded=1/.test(log),
    guest_fault_free: !/panicked at|Page Fault|General Protection Fault|terminating userspace task/i.test(log),
    source_disk_unchanged: sourceDiskAfter === sourceDiskSha256,
  };
  const report = {
    schema_version: 1,
    protocol_id: protocol.protocol_id,
    protocol_sha256: digest(protocolPath),
    accelerator,
    ram_mb: 4096,
    clients: protocol.clients,
    requests_per_client: protocol.requests_per_client,
    timed_responses: completed.length,
    action_classes: cases.length,
    batch_wall_milliseconds: Number(batchWallMs.toFixed(3)),
    jain_throughput_fairness: Number(fairness.toFixed(6)),
    per_client: perClient,
    failure_probe: {
      surviving_clients_responded: survivorChecks.length,
      replacement_rejected_before_pair: prePairRejected,
      replacement_succeeded_after_pair: Boolean(replacementPreview.message?.result),
    },
    authority: {
      additional_clients_scope: "world_model_preview only",
      execution_probe_error_code: unauthorizedExecution.message?.error?.code,
      execution_dataset_records_added: datasetAfter - datasetBefore,
      physical_delivery_attempts: 0,
      physical_deliveries: 0,
    },
    transition: {
      role: transitionPath ? "research candidate injected into disposable run-disk copy" : "packaged runtime artifact",
      path: transitionPath ? path.relative(repo, transitionPath).replaceAll("\\", "/") : null,
      sha256: transitionPath ? digest(transitionPath) : null,
    },
    packaged_source_disk: { sha256_before: sourceDiskSha256, sha256_after: sourceDiskAfter, unchanged: sourceDiskAfter === sourceDiskSha256 },
    serial_sha256: crypto.createHash("sha256").update(log).digest("hex"),
    checks,
    acceptance_gates_passed: Object.values(checks).every(Boolean),
    promotion_eligible: false,
    claim_boundary: protocol.claim_boundary,
  };
  fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + "\n");
  if (!report.acceptance_gates_passed) throw new Error(`multiclient gates failed: ${JSON.stringify(checks)}`);
  console.log(`PASS ${completed.length}/${completed.length} responses across ${clients.length} WebSockets`);
  console.log(`PASS Jain throughput fairness ${fairness.toFixed(6)}`);
  console.log("PASS preview-only authority, disconnect isolation, and no-execution gates");
} finally {
  for (const client of clients) { try { client.ws.close(); } catch {} }
  try { monitor?.destroy(); } catch {}
  try { child?.kill("SIGKILL"); } catch {}
  await sleep(300);
  fs.rmSync(runDisk, { force: true });
  fs.rmSync(runDirectory, { recursive: true, force: true });
}
