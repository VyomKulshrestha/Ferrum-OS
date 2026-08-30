#!/usr/bin/env node
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}
const iterations = Math.max(20, Math.min(2000, Number(arg("--iterations", "100"))));
const outPath = path.resolve(arg("--json-out", path.join(repo, "target", "world_model_runtime_benchmark.json")));
const transitionArgument = arg("--transition", "");
const transition = transitionArgument ? path.resolve(transitionArgument) : null;
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const sourceDisk = path.join(repo, "target", "heliox-disk.img");
const runId = `${process.pid}-${Date.now()}`;
const runDisk = path.join(repo, "target", `world-model-benchmark-${runId}-disk.img`);
const serialLog = path.join(repo, "target", `world-model-benchmark-${runId}-serial.log`);
const monitorPort = await freeTcpPort();
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
for (const required of [image, sourceDisk, qemu, ...(transition ? [transition] : [])]) {
  if (!fs.existsSync(required)) throw new Error(`required file not found: ${required}`);
}
const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const sourceDiskSha256 = digest(sourceDisk);
fs.copyFileSync(sourceDisk, runDisk);
if (transition) {
  const relativeRunDisk = path.relative(repo, runDisk).replaceAll("\\", "/");
  const relativeTransition = path.relative(repo, transition).replaceAll("\\", "/");
  for (const command of [
    "unlink /heliox/world/model_learned.bin",
    `write ${relativeTransition} /heliox/world/model_learned.bin`,
  ]) {
    const prepared = spawnSync("wsl", ["debugfs", "-w", "-R", command, relativeRunDisk], {
      cwd: repo, encoding: "utf8",
    });
    if (prepared.status !== 0) throw new Error(`candidate shadow disk preparation failed: ${prepared.stderr || prepared.stdout}`);
  }
}
fs.rmSync(serialLog, { force: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}\n${serialText().slice(-3000)}`);
}
async function connectMonitor() {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port: monitorPort }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(200); }
  }
  throw new Error("could not connect to QEMU monitor");
}

const qemuArgs = [
  "-m", "512M", "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
  "-serial", `file:${serialLog}`, "-netdev", "user,id=net0",
  "-device", "rtl8139,netdev=net0", "-no-reboot", "-display", "none",
];
let accelerator = "whpx";
let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: true });
await sleep(2500);
if (qemuProcess.exitCode !== null) {
  accelerator = "tcg";
  qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: true });
  await sleep(1500);
}
const monitor = await connectMonitor();
monitor.setEncoding("ascii");
async function mon(command, waitMs = 120) {
  monitor.write(`${command}\n`);
  await sleep(waitMs);
}
const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
}));
async function sendText(text) {
  for (const character of text) {
    const key = keyMap.get(character) || (/^[a-z0-9]$/i.test(character) ? character.toLowerCase() : null);
    if (!key) throw new Error(`no key mapping for ${JSON.stringify(character)}`);
    await mon(`sendkey ${key} 20`, 35);
  }
}
async function runCommand(command) {
  const start = serialText().length;
  await sendText(command);
  await mon("sendkey ret 20", 60);
  await waitForSerial("FerrumOS:~$", 15, start);
}

try {
  await waitForSerial("FerrumOS:~$", 60);
  await runCommand(`write /tmp/world_model_benchmark ${iterations}`);
  const start = serialText().length;
  await sendText("ring3 init");
  await mon("sendkey ret 20", 60);
  await waitForSerial("[world-model-benchmark-memory-v1]", 180, start);
  const text = serialText();
  assert.doesNotMatch(text, /KERNEL PANIC|panicked at|userspace fault|page fault/i);
  const pattern = /\[world-model-benchmark-v3\] horizon=(\d+) iterations=(\d+) batch_ticks=(\d+) mean_us=(\d+) median_us=(\d+) p95_us=(\d+) p99_us=(\d+) max_us=(\d+) median_cycles=(\d+) p95_cycles=(\d+) p99_cycles=(\d+) max_cycles=(\d+) blocked=(\d+)/g;
  const horizons = [];
  let match;
  while ((match = pattern.exec(text)) !== null) {
    horizons.push({
      horizon: Number(match[1]), iterations: Number(match[2]), batch_ticks: Number(match[3]),
      mean_microseconds: Number(match[4]), median_microseconds: Number(match[5]),
      p95_microseconds: Number(match[6]), p99_microseconds: Number(match[7]), max_microseconds: Number(match[8]),
      median_cycles: Number(match[9]), p95_cycles: Number(match[10]), p99_cycles: Number(match[11]),
      max_cycles: Number(match[12]), blocked_previews: Number(match[13]),
    });
  }
  assert.deepEqual(horizons.map((row) => row.horizon), [1, 2, 3, 4, 5]);
  assert.ok(horizons.every((row) => row.iterations === iterations));
  assert.ok(horizons.every((row) => row.median_cycles > 0 && row.p95_cycles >= row.median_cycles));
  assert.ok(horizons.every((row) => row.p99_cycles >= row.p95_cycles && row.max_cycles >= row.p99_cycles));
  assert.ok(horizons.every((row) => row.p95_microseconds >= row.median_microseconds
    && row.p99_microseconds >= row.p95_microseconds && row.max_microseconds >= row.p99_microseconds));
  const memoryMatch = text.match(/\[world-model-benchmark-memory-v1\] heap_before=(\d+) heap_after=(\d+) heap_delta=(\d+) encoder_file_bytes=(\d+) transition_file_bytes=(\d+) runtime_parameters=(\d+) encoder_loaded=([01]) transition_loaded=([01])/);
  assert.ok(memoryMatch, "missing memory benchmark marker");
  const loadMatch = text.match(/\[world-model-load-v1\] cycles=(\d+) ticks=(\d+) encoder_loaded=([01]) transition_loaded=([01])/);
  assert.ok(loadMatch, "missing model-load benchmark marker");
  const memory = {
    heap_before_bytes: Number(memoryMatch[1]), heap_after_bytes: Number(memoryMatch[2]),
    heap_growth_bytes: Number(memoryMatch[3]), encoder_file_bytes: Number(memoryMatch[4]),
    transition_file_bytes: Number(memoryMatch[5]), runtime_parameters: Number(memoryMatch[6]),
    encoder_loaded: memoryMatch[7] === "1", transition_loaded: memoryMatch[8] === "1",
  };
  assert.ok(memory.encoder_loaded && memory.transition_loaded);
  const loadCycles = Number(loadMatch[1]);
  const modelLoad = {
    cycles: loadCycles,
    pit_ticks: Number(loadMatch[2]),
    pit_elapsed_microseconds: Number(loadMatch[2]) * 1000,
    encoder_loaded: loadMatch[3] === "1",
    transition_loaded: loadMatch[4] === "1",
  };
  assert.ok(modelLoad.cycles > 0 && modelLoad.encoder_loaded && modelLoad.transition_loaded);
  const report = {
    schema_version: 2,
    protocol: "in-guest-world-model-runtime-benchmark-v3",
    accelerator, ram_mb: 512, iterations_per_horizon: iterations, warmup_previews: 64,
    scope: "ring-3 Heliox capture + encoder + transition + safety predicate preview; authority disabled and no action dispatch",
    authority_disabled: true,
    transition: {
      role: transition ? "research candidate injected into disposable run-disk copy" : "packaged runtime artifact",
      path: transition ? path.relative(repo, transition).replaceAll("\\", "/") : "target/heliox-disk.img:/heliox/world/model_learned.bin",
      sha256: transition ? digest(transition) : null,
    },
    packaged_source_disk: {
      sha256_before: sourceDiskSha256,
      sha256_after: digest(sourceDisk),
      unchanged: sourceDiskSha256 === digest(sourceDisk),
    },
    horizons, memory, model_load: modelLoad,
    serial_sha256: crypto.createHash("sha256").update(text).digest("hex"),
    limitations: [
      "Mean and percentile time use the guest 1 kHz PIT; percentile resolution is therefore 1 ms. Raw TSC cycles are retained without converting virtualized TSC to wall time.",
      "A 64-preview H=5 warmup runs before the measured horizons to remove first-use cache and paging bias.",
      "Preview latency excludes tool execution, provider latency, and operator confirmation.",
      "Concurrent request behavior is evaluated separately.",
    ],
  };
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`);
  assert.ok(report.packaged_source_disk.unchanged);
  console.log(`PASS\tmeasured H=1..5 in the real ring-3 gate (${iterations} previews each)`);
  console.log("PASS\tguest PIT mean/median/p95/p99 time and raw TSC cycle distributions recorded");
  console.log("PASS\tmodel load time, load state, and heap growth recorded without a guest fault");
  console.log(`3/3 checks passed\n${outPath}`);
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
  await sleep(300);
  fs.rmSync(runDisk, { force: true });
  fs.rmSync(serialLog, { force: true });
}
