// ============================================================================
// FerrumOS - Provider-Independent Hybrid World-Model Collector
// ============================================================================
// Feeds task episodes through Heliox's real provider-backed ReAct path, then
// joins each raw provider response with the real FerrumOS before/action/after
// transition rows emitted by the daemon. The provider is a data-source detail;
// it is retained as audit metadata and never becomes a world-model feature.
//
// Corpus JSONL:
//   {"id":"file-1","prompt":"write ...","max_steps":2}
// For deterministic/offline replay tests, add:
//   {"responses":[{"tool":"write_file","args":{...}}, ...]}
//
// Live OpenAI-compatible bridge:
//   WM_PROVIDER_URL=https://.../v1/chat/completions
//   WM_PROVIDER_KEY=...
//   WM_PROVIDER_MODEL=...
//
// Usage:
//   node scripts/collect_world_model_hybrid.mjs --corpus target/corpus.jsonl
//   node scripts/collect_world_model_hybrid.mjs --corpus ... --ram 512,2048,8192 --resume
// ============================================================================

import { spawn } from "node:child_process";
import fs from "node:fs";
import https from "node:https";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");

function arg(name, fallback = undefined) {
  const i = process.argv.indexOf(name);
  if (i < 0) return fallback;
  const value = process.argv[i + 1];
  if (!value || value.startsWith("--")) return fallback;
  return value;
}

const corpusPath = path.resolve(arg("--corpus", path.join(repo, "scripts", "fixtures", "world_model_hybrid_smoke.jsonl")));
const outPath = path.resolve(arg("--out", path.join(repo, "target", "world_model_hybrid_dataset.jsonl")));
const tracePath = path.resolve(arg("--traces", path.join(repo, "target", "world_model_hybrid_traces.jsonl")));
const ramProfiles = String(arg("--ram", process.env.WM_RAM_MB || "512"))
  .split(",")
  .map((value) => Number(value.trim()))
  .filter((value) => Number.isFinite(value) && value >= 256);
const maxScenarios = Number(arg("--max-scenarios", "0"));
const scenariosPerBoot = Math.max(1, Number(arg("--scenarios-per-boot", "250")));
const resume = process.argv.includes("--resume");
const visible = process.argv.includes("--visible");
const providerUrl = process.env.WM_PROVIDER_URL || "";
const providerKey = process.env.WM_PROVIDER_KEY || "";
const providerModel = process.env.WM_PROVIDER_MODEL || "";
const providerLabel = process.env.WM_PROVIDER_LABEL || (providerUrl ? "openai-compatible" : "replay");
const toolNames = [
  "ipc_send", "audit_write", "yield_cpu", "camera_capture", "gesture_status",
  "report_status", "capability_check", "read_file", "read_dir", "query_memory",
  "get_config", "system_info", "list_processes", "net_connect", "net_send",
  "net_recv", "http_get", "write_file", "create_directory", "save_memory",
  "load_memory", "set_goal", "sleep", "service_start", "service_stop",
  "exec_process", "delete_file", "local_inference", "trigger_kernel_upgrade",
  "hud_update", "hit_test", "read_screen", "add_subtask", "record_audio",
  "play_audio", "set_volume", "keyboard_type", "mouse_click", "mouse_move",
  "browse_url", "poll_input",
];

const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const applianceDisk = path.join(repo, "target", "heliox-disk.img");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}

for (const required of [corpusPath, image, applianceDisk, qemu]) {
  if (!fs.existsSync(required)) throw new Error(`required file not found: ${required}`);
}
if (ramProfiles.length === 0) throw new Error("no valid --ram profiles");

const corpus = fs.readFileSync(corpusPath, "utf8")
  .split(/\r?\n/)
  .filter((line) => line.trim())
  .map((line, index) => {
    const row = JSON.parse(line);
    return {
      id: String(row.id || `scenario-${index}`),
      prompt: String(row.prompt || ""),
      expected_tool: row.expected_tool || null,
      max_steps: Math.max(1, Number(row.max_steps || 1)),
      responses: Array.isArray(row.responses)
        ? row.responses
        : row.response !== undefined ? [row.response] : [],
      tags: Array.isArray(row.tags) ? row.tags : [],
    };
  })
  .filter((row) => row.prompt);

if (!providerUrl && corpus.some((row) => row.responses.length === 0)) {
  throw new Error("corpus contains live scenarios but WM_PROVIDER_URL is not set");
}

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.mkdirSync(path.dirname(tracePath), { recursive: true });
if (!resume) {
  fs.rmSync(outPath, { force: true });
  fs.rmSync(tracePath, { force: true });
}

const completed = new Set();
const observedTools = new Set();
let expectedToolMismatches = 0;
let failedEpisodes = 0;
if (resume && fs.existsSync(tracePath)) {
  for (const line of fs.readFileSync(tracePath, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const row = JSON.parse(line);
      if (row.completed && row.episode_id) completed.add(row.episode_id);
    } catch { /* retain valid prior lines and continue */ }
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const appendJson = (file, value) => fs.appendFileSync(file, `${JSON.stringify(value)}\n`);

function hexToFloats(hex) {
  const result = [];
  for (let i = 0; i < hex.length; i += 8) {
    const bits = Number.parseInt(hex.slice(i, i + 8), 16);
    const buffer = new ArrayBuffer(4);
    const view = new DataView(buffer);
    view.setUint32(0, bits, false);
    result.push(view.getFloat32(0, false));
  }
  return result;
}

function parseTransitionRows(text) {
  const regex = /\[world-model-dataset-v2\] tick=(\d+) action=(\d+) reward=([\-0-9.]+) success=([01])(?: executed=([01]))? risk=([\-0-9.]+) features=([0-9a-f]+) before=([0-9a-f]+) after=([0-9a-f]+)/g;
  const rows = [];
  let match;
  while ((match = regex.exec(text)) !== null) {
    rows.push({
      schema_version: 2,
      tick: Number(match[1]),
      action: Number(match[2]),
      reward: Number(match[3]),
      success: match[4] === "1",
      executed: match[5] === undefined ? true : match[5] === "1",
      risk: Number(match[6]),
      action_features: hexToFloats(match[7]),
      before: hexToFloats(match[8]),
      after: hexToFloats(match[9]),
    });
  }
  return rows;
}

function normalizeReplayResponse(value) {
  if (value && typeof value === "object") {
    if (value.choices || value.response !== undefined) return JSON.stringify(value);
    if (value.tool) return JSON.stringify({ response: JSON.stringify(value) });
  }
  const text = String(value ?? "");
  try {
    const parsed = JSON.parse(text);
    if (parsed.choices || parsed.response !== undefined) return text;
  } catch { /* plain model content */ }
  return JSON.stringify({ response: text });
}

let activeScenario = null;
let activeStep = 0;
let latestExchange = null;

const bridgeOptions = {
  key: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.key")),
  cert: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.pem")),
};
const bridgePort = Number(arg("--bridge-port", await freeTcpPort()));
const bridge = https.createServer(bridgeOptions, (req, res) => {
  let requestBody = "";
  req.on("data", (chunk) => (requestBody += chunk));
  req.on("end", async () => {
    try {
      if (!activeScenario) throw new Error("provider request arrived without an active scenario");
      let responseBody;
      if (activeScenario.responses.length > 0) {
        const replay = activeScenario.responses[Math.min(activeStep, activeScenario.responses.length - 1)];
        responseBody = normalizeReplayResponse(replay);
      } else {
        const payload = JSON.parse(requestBody);
        if (providerModel) payload.model = providerModel;
        const headers = { "Content-Type": "application/json" };
        if (providerKey) headers.Authorization = `Bearer ${providerKey}`;
        const upstream = await fetch(providerUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });
        responseBody = await upstream.text();
        if (!upstream.ok) {
          throw new Error(`provider returned HTTP ${upstream.status}: ${responseBody.slice(0, 500)}`);
        }
      }
      latestExchange = {
        request: JSON.parse(requestBody),
        raw_response: responseBody,
      };
      res.writeHead(200, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(responseBody),
      });
      res.end(responseBody);
    } catch (error) {
      const body = JSON.stringify({ error: String(error?.message || error) });
      res.writeHead(500, {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
      });
      res.end(body);
    }
  });
});
await new Promise((resolve) => bridge.listen(bridgePort, "0.0.0.0", resolve));

function rpc(ws, id, method, params, timeoutMs = 300_000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`timed out waiting for ${method}`)), timeoutMs);
    const handler = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.id === id) {
          clearTimeout(timeout);
          ws.removeEventListener("message", handler);
          if (data.error) reject(new Error(data.error.message || JSON.stringify(data.error)));
          else resolve(data.result);
        }
      } catch { /* ignore unrelated frames */ }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  });
}

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
  "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe",
  ",": "comma", ":": "shift-semicolon",
}));

async function collectProfile(ramMb, selected, chunkIndex) {
  const monitorPort = await freeTcpPort();
  const wsPort = await freeTcpPort();
  const chunkLabel = String(chunkIndex).padStart(4, "0");
  const serialLog = path.join(repo, "target", `world-model-hybrid-${ramMb}m-${chunkLabel}-serial.log`);
  const runDisk = path.join(repo, "target", `world-model-hybrid-${ramMb}m-${chunkLabel}-disk.img`);
  fs.rmSync(serialLog, { force: true });
  fs.copyFileSync(applianceDisk, runDisk);
  const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
  const waitForSerial = async (needle, seconds, from = 0) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      const text = serialText().slice(from);
      if (text.includes(needle)) return text;
      await sleep(150);
    }
    throw new Error(`timed out waiting for "${needle}"\n${serialText().slice(-2500)}`);
  };
  const qemuArgs = [
    "-m", `${ramMb}M`,
    "-drive", `format=raw,file=${image}`,
    "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
    "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", `user,id=net0,hostfwd=tcp::${wsPort}-:8785`,
    "-device", "rtl8139,netdev=net0",
    "-no-reboot",
  ];
  if (!visible) qemuArgs.push("-display", "none");

  console.log(`[hybrid] booting ${ramMb} MB profile chunk ${chunkIndex + 1} (${selected.length} scenarios)`);
  const requestedAccel = arg("--accel", "auto");
  let activeAccel = requestedAccel === "tcg" ? "tcg" : "whpx";
  const launch = (accel) => spawn(
    qemu,
    accel === "tcg"
      ? ["-accel", "tcg", "-cpu", "max", ...qemuArgs]
      : ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs],
    { windowsHide: !visible },
  );
  const connectMonitorSocket = async () => {
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
  };
  let qemuProcess = launch(activeAccel);
  await sleep(activeAccel === "tcg" ? 1500 : 2500);
  if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0 && requestedAccel === "auto") {
    activeAccel = "tcg";
    qemuProcess = launch(activeAccel);
    await sleep(1500);
  }
  let monitor;
  let ws;
  try {
    monitor = await connectMonitorSocket();
    try {
      await waitForSerial("FerrumOS:~$", activeAccel === "tcg" ? 90 : 60);
    } catch (error) {
      if (activeAccel !== "whpx" || requestedAccel !== "auto") throw error;
      console.warn(`[hybrid] ${ramMb} MB WHPX boot was silent; retrying with TCG`);
      monitor.destroy();
      qemuProcess.kill("SIGKILL");
      await sleep(1000);
      fs.rmSync(serialLog, { force: true });
      activeAccel = "tcg";
      qemuProcess = launch(activeAccel);
      await sleep(1500);
      monitor = await connectMonitorSocket();
      await waitForSerial("FerrumOS:~$", 120);
    }
    monitor.setEncoding("ascii");
    const mon = async (command, delay = 100) => { monitor.write(`${command}\n`); await sleep(delay); };
    const sendKey = async (key) => mon(`sendkey ${key} 20`, 45);
    const sendText = async (text) => {
      for (const character of text) {
        if (keyMap.has(character)) await sendKey(keyMap.get(character));
        else if (/^[a-z0-9]$/i.test(character)) await sendKey(character.toLowerCase());
        else throw new Error(`no QEMU key mapping for ${JSON.stringify(character)}`);
      }
    };
    const runCommand = async (command) => {
      const start = serialText().length;
      await sendText(command);
      await sendKey("ret");
      await waitForSerial("FerrumOS:~$", 15, start);
    };

    await runCommand("rm /disk/heliox/config.json");
    const config = `{"provider":"cloud","api_host":"10.0.2.2","api_port":${bridgePort},"api_path":"/","model_name":"bridge","api_key":"bridge","tick_interval":999999999,"auto_approve_tier":4}`;
    await runCommand(`write /disk/heliox/config.json ${config}`);
    const bootStart = serialText().length;
    await sendText("ring3 init");
    await sendKey("ret");
    await waitForSerial(
      "[heliox-daemon] sent HELIOX_READY IPC announce",
      activeAccel === "tcg" ? 150 : 90,
      bootStart,
    );
    await sleep(1000);

    ws = new WebSocket(`ws://127.0.0.1:${wsPort}`);
    await new Promise((resolve, reject) => {
      ws.onopen = resolve;
      ws.onerror = reject;
    });

    let consecutiveEpisodeFailures = 0;
    for (let scenarioIndex = 0; scenarioIndex < selected.length; scenarioIndex++) {
      const scenario = selected[scenarioIndex];
      const episodeId = `${scenario.id}-${ramMb}m`;
      if (completed.has(episodeId)) continue;
      activeScenario = scenario;
      let episodeTransitions = 0;
      let episodeFailed = false;

      for (let step = 0; step < scenario.max_steps; step++) {
        activeStep = step;
        latestExchange = null;
        const serialStart = serialText().length;
        try {
          const result = await rpc(ws, `${episodeId}-${step}`, "agent_step", { goal: scenario.prompt });
          const newSerial = serialText().slice(serialStart);
          const transitions = parseTransitionRows(newSerial);
          if ((result.actions || []).length > 0 && transitions.length === 0) {
            throw new Error("agent returned actions without an emitted world-model transition");
          }
          const rawResponse = latestExchange?.raw_response || "";
          for (let index = 0; index < transitions.length; index++) {
            const actualTool = result.actions?.[index]?.tool
              || toolNames[transitions[index].action]
              || null;
            const expectedToolMatch = !scenario.expected_tool || actualTool === scenario.expected_tool;
            if (actualTool) observedTools.add(actualTool);
            if (!expectedToolMatch) expectedToolMismatches++;
            appendJson(outPath, {
              source: "hybrid",
              episode_id: episodeId,
              step,
              transition_in_step: index,
              ram_mb: ramMb,
              provider: providerLabel,
              provider_model: providerModel || null,
              prompt: scenario.prompt,
              expected_tool: scenario.expected_tool,
              actual_tool: actualTool,
              expected_tool_match: expectedToolMatch,
              tags: scenario.tags,
              model_response: rawResponse,
              ...transitions[index],
            });
          }
          episodeTransitions += transitions.length;
          appendJson(tracePath, {
            episode_id: episodeId,
            step,
            ram_mb: ramMb,
            provider: providerLabel,
            prompt: scenario.prompt,
            expected_tool: scenario.expected_tool,
            raw_response: rawResponse,
            actions: result.actions || [],
            expected_tool_match: !scenario.expected_tool
              || (result.actions || []).some((action) => action.tool === scenario.expected_tool),
            transition_count: transitions.length,
            completed: false,
          });
          if (!result.actions || result.actions.length === 0) break;
        } catch (error) {
          episodeFailed = true;
          appendJson(tracePath, {
            episode_id: episodeId,
            step,
            ram_mb: ramMb,
            provider: providerLabel,
            prompt: scenario.prompt,
            error: String(error?.message || error),
            completed: false,
          });
          break;
        }
      }
      appendJson(tracePath, {
        episode_id: episodeId,
        ram_mb: ramMb,
        provider: providerLabel,
        transition_count: episodeTransitions,
        failed: episodeFailed,
        completed: !episodeFailed,
      });
      if (!episodeFailed) {
        completed.add(episodeId);
        consecutiveEpisodeFailures = 0;
      } else {
        failedEpisodes++;
        consecutiveEpisodeFailures++;
      }
      console.log(`[hybrid] ${episodeId}: ${episodeTransitions} transitions${episodeFailed ? " (failed)" : ""}`);
      if (consecutiveEpisodeFailures >= 3) {
        throw new Error("three consecutive episodes failed; stopping this chunk for safe resume");
      }
    }
  } finally {
    activeScenario = null;
    ws?.close();
    monitor?.destroy();
    qemuProcess.kill("SIGKILL");
    await sleep(300);
    fs.rmSync(runDisk, { force: true });
  }
}

let exitCode = 0;
try {
  const selectedCorpus = maxScenarios > 0 ? corpus.slice(0, maxScenarios) : corpus;
  for (const ramMb of ramProfiles) {
    for (let offset = 0, chunkIndex = 0; offset < selectedCorpus.length; offset += scenariosPerBoot, chunkIndex++) {
      const chunk = selectedCorpus.slice(offset, offset + scenariosPerBoot);
      const remaining = chunk.filter((scenario) => !completed.has(`${scenario.id}-${ramMb}m`));
      if (remaining.length === 0) {
        console.log(`[hybrid] skipping completed ${ramMb} MB chunk ${chunkIndex + 1}`);
        continue;
      }
      await collectProfile(ramMb, remaining, chunkIndex);
    }
  }
} catch (error) {
  console.error(`[hybrid] collection failed: ${error?.stack || error}`);
  exitCode = 1;
} finally {
  bridge.close();
}

console.log(
  `[hybrid] observed ${observedTools.size}/${toolNames.length} canonical actions; `
  + `${expectedToolMismatches} transition(s) differed from the scenario's expected tool; `
  + `${failedEpisodes} episode(s) failed`,
);
if (failedEpisodes > 0 || expectedToolMismatches > 0) exitCode = 1;
process.exit(exitCode);
