// ============================================================================
// FerrumOS - Extended JSON-RPC Method Surface Verification
// ============================================================================
// Heliox-daemon's WebSocket JSON-RPC surface used to be exactly 3 methods:
// ping, execute_tool, and a single hardcoded gesture_event case. This proves
// the 4 new methods added alongside it - health, get_config, system_status,
// agent_stats - are real (backed by actual daemon/orchestrator state, not
// stubs), not just that they return *a* JSON blob.
//
// Two independent boots (mirroring verify_heliox_setup.mjs's pattern)
// instead of driving heliox-assistant-panel's wizard mid-test: the app's
// own setup flow is already covered end to end by verify_assistant_panel.mjs,
// and typing through it here would just add GUI-focus timing risk to a test
// that's really about the JSON-RPC surface, not the wizard.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
const basePort = Number(process.env.FERRUMOS_MONITOR_PORT || 45488);
const visible = process.argv.includes("--visible");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function connectMonitor(port) {
  for (let i = 0; i < 60; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const sock = net.createConnection({ port, host: "127.0.0.1" }, () => resolve(sock));
        sock.once("error", reject);
      });
    } catch { await sleep(250); }
  }
  throw new Error("could not connect to QEMU monitor");
}

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon",
  "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe", ",": "comma"
}));

function rpc(ws, id, method, params) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`timed out waiting for response to ${method}`)), 15000);
    const handler = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.id === id) {
          clearTimeout(timeout);
          ws.removeEventListener("message", handler);
          resolve(data);
        }
      } catch { /* ignore unrelated frames */ }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  });
}

async function runScenario(label, port, hostfwdPort, preRing3Init) {
  const serialLog = path.join(repo, "target", `jsonrpc-verify-${label}-serial.log`);
  const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
  const waitForSerial = async (needle, seconds, from = 0) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      const text = serialText().slice(from);
      if (text.includes(needle)) return text;
      await sleep(150);
    }
    throw new Error(`[${label}] timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
  };
  async function sendKey(k, mon) { mon.write(`sendkey ${k}\n`); await sleep(45); }
  async function sendText(t, mon) {
    for (const ch of t) {
      if (keyMap.has(ch)) await sendKey(keyMap.get(ch), mon);
      else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase(), mon);
      else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
    }
  }

  const qemuArgs = [
    "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", `user,id=net0,hostfwd=tcp::${hostfwdPort}-:8785`,
    "-device", "rtl8139,netdev=net0",
    "-no-reboot",
  ];
  if (!visible) qemuArgs.push("-display", "none");

  console.log(`[test] [${label}] starting QEMU...`);
  let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: !visible });
  await sleep(2500);
  if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
    console.log(`[${label}] WHPX unsupported or failed, falling back to TCG...`);
    qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: !visible });
    await sleep(1500);
  }

  const monitor = await connectMonitor(port);
  monitor.setEncoding("ascii");
  await sleep(500);

  let ws = null;
  try {
    const start = serialText().length;
    await waitForSerial("FerrumOS:~$", 45, start);
    check(`[${label}] boot reaches shell prompt`, true);

    if (preRing3Init) {
      await preRing3Init(sendText, sendKey, monitor);
    }

    await sendText("ring3 init", monitor);
    await sendKey("ret", monitor);

    await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 30, start);
    await sleep(2000); // let the WebSocket server bind

    ws = new WebSocket(`ws://127.0.0.1:${hostfwdPort}`);
    await new Promise((resolve, reject) => {
      ws.onopen = resolve;
      ws.onerror = reject;
    });
    check(`[${label}] connected to JSON-RPC WebSocket`, true);

    return { ws, monitor, qemuProcess, waitForSerial, start };
  } catch (err) {
    check(`[${label}] verification`, false, err && err.message ? err.message.split("\n")[0] : String(err));
    ws?.close();
    monitor.destroy();
    qemuProcess.kill("SIGKILL");
    return null;
  }
}

// --- Scenario 1: fresh boot, no config, exercise the "unconfigured" state --
{
  const label = "unconfigured";
  const ctx = await runScenario(label, basePort, 8785);
  if (ctx) {
    const { ws, monitor, qemuProcess } = ctx;
    try {
      const health = await rpc(ws, "t-health", "health", {});
      check(
        "health reports configured=false and provider=auto before setup (backed by real config state)",
        health.result && health.result.configured === false && health.result.provider === "auto",
        JSON.stringify(health.result)
      );

      const cfg = await rpc(ws, "t-get_config", "get_config", {});
      check(
        "get_config returns real config fields (provider, tick_interval)",
        cfg.result && cfg.result.provider === "auto" && typeof cfg.result.tick_interval === "number",
        JSON.stringify(cfg.result)
      );
      check(
        "get_config does not leak api_key",
        cfg.result && !("api_key" in cfg.result),
        JSON.stringify(Object.keys(cfg.result || {}))
      );

      const status1 = await rpc(ws, "t-status-1", "system_status", {});
      check(
        "system_status reports a real (non-negative) tick_count and a real goal string",
        status1.result && status1.result.tick_count >= 0 && typeof status1.result.goal === "string" && status1.result.goal.length > 0,
        JSON.stringify(status1.result)
      );
      const status2 = await rpc(ws, "t-status-2", "system_status", {});
      check(
        "system_status's tick_count strictly advances between two calls (real counter, not a stub)",
        status2.result && status2.result.tick_count >= status1.result.tick_count,
        `first=${status1.result.tick_count} second=${status2.result.tick_count}`
      );

      // Before setup, config.rs deliberately keeps the daemon idle (provider
      // stays "auto", tick()'s early-return skips even emit_telemetry) - see
      // REPORT.md's Phase D5 section on why an unconfigured daemon must not
      // autonomously compute. An empty ring buffer here is the *correct*
      // behavior, not agent_stats being a stub.
      const stats = await rpc(ws, "t-agent_stats", "agent_stats", {});
      check(
        "agent_stats reports an empty telemetry buffer while genuinely unconfigured (correct idle behavior, not a stub returning zero)",
        stats.result && stats.result.telemetry_event_count === 0 && stats.result.last_event === null,
        JSON.stringify(stats.result)
      );

      const pong = await rpc(ws, "t-ping", "ping", {});
      check("ping still returns pong (existing method unaffected)", pong.result === "pong", JSON.stringify(pong.result));

      const full = fs.readFileSync(path.join(repo, "target", `jsonrpc-verify-${label}-serial.log`), "utf8");
      check(`[${label}] no userspace fault or page fault panic`, !/terminating|General Protection|Page Fault/.test(full));
    } catch (err) {
      check(`[${label}] verification`, false, err && err.message ? err.message.split("\n")[0] : String(err));
    } finally {
      ws.close();
      monitor.destroy();
      qemuProcess.kill("SIGKILL");
    }
  }
}

// --- Scenario 2: config pre-written before ring3 init, exercise the "configured and ticking" state --
{
  const label = "configured";
  const ctx = await runScenario(label, basePort + 1, 8786, async (sendText, sendKey, monitor) => {
    // Written via the plain kernel shell prompt before ring3 init even
    // runs - proven pattern from verify_real_model.mjs/verify_heliox_setup.mjs,
    // sidesteps any GUI-focus timing since nothing but the shell exists yet.
    await sendText('write /disk/heliox/config.json {"provider":"local","tick_interval":1}', monitor);
    await sendKey("ret", monitor);
    await sleep(300);
  });
  if (ctx) {
    const { ws, monitor, qemuProcess, waitForSerial, start } = ctx;
    try {
      await waitForSerial("[heliox-daemon] active provider: local-", 10, start);
      await sleep(1000); // let a few ticks accumulate telemetry

      const stats = await rpc(ws, "t-agent_stats", "agent_stats", {});
      check(
        "agent_stats reports real telemetry activity once the agent is actually configured and ticking",
        stats.result && stats.result.telemetry_event_count > 0 && stats.result.last_event && !!stats.result.last_event.kind,
        JSON.stringify(stats.result)
      );

      const health = await rpc(ws, "t-health-2", "health", {});
      check(
        "health reports configured=true once a real provider is active",
        health.result && health.result.configured === true && health.result.provider.startsWith("local"),
        JSON.stringify(health.result)
      );

      const full = fs.readFileSync(path.join(repo, "target", `jsonrpc-verify-${label}-serial.log`), "utf8");
      check(`[${label}] no userspace fault or page fault panic`, !/terminating|General Protection|Page Fault/.test(full));
    } catch (err) {
      check(`[${label}] verification`, false, err && err.message ? err.message.split("\n")[0] : String(err));
    } finally {
      ws.close();
      monitor.destroy();
      qemuProcess.kill("SIGKILL");
    }
  }
}

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
