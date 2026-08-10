// ============================================================================
// FerrumOS - heliox-daemon WebSocket Bridge Verification
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";
import { waitForPairingToken } from "./lib/heliox_pairing.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const diskImage = path.join(repo, "target", "heliox-disk.img");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45460);
const hostPort = Number(process.env.FERRUMOS_HOST_PORT || await freeTcpPort());
const serialLog = path.join(repo, "target", "bridge-verify-serial.log");
const runDisk = path.join(repo, "target", "bridge-verify-disk.img");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
fs.rmSync(runDisk, { force: true });
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
try { fs.unlinkSync(serialLog); } catch {}

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", `user,id=net0,hostfwd=tcp:127.0.0.1:${hostPort}-:8785`,
  "-device", "rtl8139,netdev=net0",
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];
if (fs.existsSync(diskImage)) {
  // Never mutate the packaged appliance. This test deliberately removes its
  // provider config below so autonomous ticks cannot starve a bridge request.
  fs.copyFileSync(diskImage, runDisk);
  qemuArgs.push("-drive", `format=raw,file=${runDisk},if=ide,index=1`);
}
if (!visible) qemuArgs.push("-display", "none");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Without an explicit accelerator, QEMU falls back to plain (unaccelerated)
// TCG at whatever default memory/speed it happens to pick - on the old
// GNS3-bundled QEMU 3.1.0 this reliably takes long enough to load
// heliox-daemon's ~64MB heap arena (see src/process/mod.rs's map_user_range)
// that it blew straight through every timeout in this script, every run.
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
async function sendKey(k) { await mon(`sendkey ${k} 20`, 45); }
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
  // Generous boot budget: heliox-daemon's ELF alone needs to map ~16,385
  // pages for its ~64MB heap arena (src/process/mod.rs's map_user_range),
  // and how long that actually takes varies with host load - a tight
  // timeout here was blowing up intermittently even on a correctly
  // functioning kernel, not because anything was hung (confirmed directly:
  // waiting longer always got there).
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell prompt", true);

  if (fs.existsSync(runDisk)) {
    const configStart = serialText().length;
    await sendText("rm /disk/heliox/config.json");
    await sendKey("ret");
    await waitForSerial("FerrumOS:~$", 15, configStart);
  }

  const start = serialText().length;

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Wait for the daemon to start and initialize its socket
  await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 45, start);
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 45, start);
  check("daemon starts and enters loop", true);

  // Connect via WebSocket
  console.log("[test] connecting to guest daemon WebSocket server...");
  const client = net.createConnection({ port: hostPort, host: "127.0.0.1" });
  
  let handshakeDone = false;
  let serverResponseData = Buffer.alloc(0);
  const responses = [];

  await new Promise((resolve, reject) => {
    client.on("connect", () => {
      console.log("[test] connected at TCP level. Sending HTTP Upgrade...");
      client.write(
        "GET / HTTP/1.1\r\n" +
        `Host: 127.0.0.1:${hostPort}\r\n` +
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

  // Privileged methods must fail closed before pairing.
  client.write(makeFrame(JSON.stringify({
    method: "execute_tool", params: { tool: "yield_cpu", args: {} }, id: 101,
  })));
  deadline = Date.now() + 5000;
  while (responses.length < 2 && Date.now() < deadline) await sleep(50);
  check(
    "unpaired client cannot invoke privileged tools",
    responses[1]?.id === 101 && responses[1]?.error?.code === -32003,
  );

  client.write(makeFrame(JSON.stringify({
    method: "pair", params: { token: "00000000000000000000000000000000" }, id: 102,
  })));
  deadline = Date.now() + 5000;
  while (responses.length < 3 && Date.now() < deadline) await sleep(50);
  check(
    "incorrect pairing token is rejected",
    responses[2]?.id === 102 && responses[2]?.error?.code === -32003,
  );

  const pairingToken = await waitForPairingToken(serialText);
  client.write(makeFrame(JSON.stringify({
    method: "pair", params: { token: pairingToken }, id: 103,
  })));
  deadline = Date.now() + 5000;
  while (responses.length < 4 && Date.now() < deadline) await sleep(50);
  check(
    "physical-console pairing token authorizes this connection",
    responses[3]?.id === 103 && responses[3]?.result?.authorized === true,
  );

  const previewStart = serialText().length;
  client.write(makeFrame(JSON.stringify({
    method: "world_model_preview",
    params: { tool: "delete_file", args: { path: "/disk/heliox/config.json" } },
    id: 104,
  })));
  deadline = Date.now() + 5000;
  while (responses.length < 5 && Date.now() < deadline) await sleep(50);
  check(
    "world model previews and rejects a protected action without executing it",
    responses[4]?.result?.allowed === false
      && responses[4]?.result?.risk >= 0.7
      && /Read the current config/.test(responses[4]?.result?.suggestion || "")
      && !serialText().slice(previewStart).includes("[world-model-dataset-v2]"),
  );

  client.write(makeFrame(JSON.stringify({ method: "does_not_exist", id: 105 })));
  deadline = Date.now() + 5000;
  while (responses.length < 6 && Date.now() < deadline) await sleep(50);
  check("unknown JSON-RPC method returns -32601", responses[5]?.error?.code === -32601);

  client.write(makeFrame(JSON.stringify({ method: "execute_tool", params: {}, id: 106 })));
  deadline = Date.now() + 5000;
  while (responses.length < 7 && Date.now() < deadline) await sleep(50);
  check("invalid tool parameters return -32602", responses[6]?.error?.code === -32602);

  client.write(makeFrame("{"));
  deadline = Date.now() + 5000;
  while (responses.length < 8 && Date.now() < deadline) await sleep(50);
  check("malformed JSON returns a parse error", responses[7]?.error?.code === -32700);

  // Send execute_tool request
  console.log("[test] sending execute_tool...");
  const executeStart = serialText().length;
  client.write(makeFrame(JSON.stringify({
    method: "execute_tool",
    params: {
      tool: "yield_cpu",
      args: {}
    },
    id: 107
  })));

  // Wait for execute_tool response
  // The world-model path captures two live snapshots around execution. Allow
  // the same slow-TCG/host-load variance as the boot waits.
  deadline = Date.now() + 60000;
  while (responses.length < 9 && Date.now() < deadline) {
    await sleep(50);
  }

  check("received execute_tool response from daemon", responses.length >= 9 && responses[8].id === 107);
  check("execute_tool result was successful", responses.length >= 9 && responses[8].result && responses[8].result.success === true);
  const executeLog = await waitForSerial("[world-model-dataset-v2]", 15, executeStart);
  check(
    "public execute_tool passes through the world-model recorder",
    executeLog.includes("action=2")
      && executeLog.includes("success=1")
      && executeLog.includes("executed=1"),
  );

  async function executeTool(id, tool, args, expectedResponses = responses.length + 1) {
    client.write(makeFrame(JSON.stringify({ method: "execute_tool", params: { tool, args }, id })));
    const toolDeadline = Date.now() + 60000;
    while (responses.length < expectedResponses && Date.now() < toolDeadline) await sleep(50);
    return responses.find((response) => response.id === id);
  }

  async function rpcMethod(id, method, params, timeoutMs = 60000) {
    const expectedResponses = responses.length + 1;
    client.write(makeFrame(JSON.stringify({ method, params, id })));
    const rpcDeadline = Date.now() + timeoutMs;
    while (responses.length < expectedResponses && Date.now() < rpcDeadline) await sleep(50);
    return responses.find((response) => response.id === id);
  }

  const auditStart = serialText().length;
  const auditResponse = await executeTool(120, "audit_write", { message: "bridge audit event" });
  check("audit_write appends the caller-provided event", auditResponse?.result?.success === true);
  await waitForSerial("[AUDIT] UserAudit: bridge audit event", 15, auditStart);
  check("audit_write reaches the kernel audit trail", true);

  const statusStart = serialText().length;
  const statusResponse = await executeTool(121, "report_status", { status: "bridge-ready" });
  check("report_status succeeds through the audit syscall", statusResponse?.result?.success === true);
  await waitForSerial("HELIOX_STATUS:bridge-ready", 15, statusStart);
  check("report_status records the supplied status", true);

  const ipcResponse = await executeTool(122, "ipc_send", {
    target_service: "heliox",
    message: "STATUS:bridge-ipc",
  });
  check(
    "ipc_send uses the service mailbox ABI and returns a message id",
    ipcResponse?.result?.success === true && /message_id=[1-9]/.test(ipcResponse?.result?.output || ""),
  );

  const capabilityResponse = await executeTool(123, "capability_check", { capability_id: 1 });
  check(
    "capability_check reports held authority without inverting success",
    capabilityResponse?.result?.success === true && /held=true/.test(capabilityResponse?.result?.output || ""),
  );

  const sleepStart = Date.now();
  const sleepResponse = await executeTool(124, "sleep", { ms: 25 });
  check(
    "sleep uses the scheduler blocking syscall",
    sleepResponse?.result?.success === true && Date.now() - sleepStart >= 20,
  );

  const physicalBefore = await rpcMethod(125, "physical_status", {});
  check(
    "physical runtime and embedded transition model are available in the booted daemon",
    physicalBefore?.result?.schema_version === 1
      && physicalBefore?.result?.available === true
      && physicalBefore?.result?.mode === "simulator"
      && physicalBefore?.result?.learned_gate === "shadow_only"
      && physicalBefore?.result?.physical_model_loaded === true
      && physicalBefore?.result?.os_jepa_reused === false
      && physicalBefore?.result?.completed_simulations === 0,
    JSON.stringify(physicalBefore?.result),
  );

  const unconfirmedPhysical = await rpcMethod(126, "physical_maintenance_demo", {});
  check(
    "physical maintenance simulation requires explicit per-request confirmation",
    unconfirmedPhysical?.error?.code === -32602
      && /confirm_simulation=true/.test(unconfirmedPhysical?.error?.message || ""),
  );

  const physicalDemo = await rpcMethod(
    127,
    "physical_maintenance_demo",
    { confirm_simulation: true },
  );
  check(
    "physical maintenance vertical completes through the booted Heliox service",
    physicalDemo?.result?.simulation_only === true
      && physicalDemo?.result?.job_completed === true
      && physicalDemo?.result?.tasks === 5
      && physicalDemo?.result?.approval_enforced === true,
    JSON.stringify(physicalDemo?.result),
  );
  check(
    "physical safety and delivery evidence survives the JSON-RPC boundary",
    physicalDemo?.result?.unsafe_motion_blocked === true
      && physicalDemo?.result?.safe_motion_delivered === true
      && physicalDemo?.result?.policy_revision === 1
      && Number.isInteger(physicalDemo?.result?.shadow_risk_permille)
      && physicalDemo?.result?.task_successes === 5
      && physicalDemo?.result?.safety_interventions >= 1
      && physicalDemo?.result?.twin_events >= 1,
    JSON.stringify(physicalDemo?.result),
  );

  const physicalAfter = await rpcMethod(128, "physical_status", {});
  check(
    "physical service state advances only after a confirmed successful run",
    physicalAfter?.result?.completed_simulations === 1
      && physicalAfter?.result?.last_job_completed === true,
    JSON.stringify(physicalAfter?.result),
  );

  // Send gesture_event request
  console.log("[test] sending gesture_event...");
  const gestureStart = serialText().length;
  const gestureExpectedResponses = responses.length + 1;
  client.write(makeFrame(JSON.stringify({
    method: "gesture_event",
    params: {
      gesture: "circle_clockwise"
    },
    id: 108
  })));

  // Wait for gesture response
  deadline = Date.now() + 5000;
  while (responses.length < gestureExpectedResponses && Date.now() < deadline) {
    await sleep(50);
  }

  const gestureResponse = responses.find((response) => response.id === 108);

  check(
    "received capability-gated gesture response from daemon",
    gestureResponse?.result
      && gestureResponse.result.success === false
      && /Awaiting confirmation/.test(gestureResponse.result.output || ""),
  );

  // Gesture-originated OS effects must use exactly the same world-model and
  // confirmation path as provider/public tool calls; no direct injected key.
  const gestureLog = await waitForSerial(
    "gesture circle_clockwise mapped through gated keyboard_type",
    30,
    gestureStart,
  );
  check("daemon routes gesture input through the canonical dispatcher", true);
  check(
    "gesture key injection remains pending without operator approval",
    gestureLog.includes("Awaiting confirmation"),
  );
  const gestureDataset = await waitForSerial("[world-model-dataset-v2]", 30, gestureStart);
  check(
    "gesture-originated keyboard action is recorded but not executed",
    gestureDataset.includes("action=36") && gestureDataset.includes("executed=0"),
  );

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
  await sleep(300);
  fs.rmSync(runDisk, { force: true });
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
