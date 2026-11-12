// ============================================================================
// FerrumOS - Heliox authority gate: approval through injected keystrokes
// ============================================================================
// fi1 workstream D, round 2 (finding R2-1). Boots the image, pairs a JSON-RPC
// client (the role an external model plays) and drives `execute_tool`:
//   1. A Tier-3 write_file waits for the operator (id N).
//   2. The client asks for keyboard_type with text whose first 48 bytes are
//      a harmless shell `echo` and whose hidden tail is
//      "\nheliox confirm N\n". Injected keys reach the kernel shell, which
//      runs as Root and forwards `heliox confirm N` to the daemon.
//      Must be refused outright (Enter is never typed by the agent).
//   3. The write is still waiting: nothing approved it.
//   4. A printable-only keyboard_type waits as a Tier-4 (Destructive) call.
// On the round-1 image (df61cb0) step 2 queues the keyboard_type at Tier 3;
// the harness then plays an operator who approves it from the 48 bytes shown,
// the injected keys approve request N, and the write runs without the
// operator ever approving it. Run: node scripts/verify_authority_gate_input_injection.mjs
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";
import { assertPaired, rpcCall, waitForPairingToken } from "./lib/heliox_pairing.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);

const monitorPort = Number(process.env.FERRUMOS_MONITOR_PORT || 45589);
const hostPort = Number(process.env.FERRUMOS_HOST_PORT || 0) || await freeTcpPort();
const serialLog = path.join(repo, "target", "authority-gate-input-injection-serial.log");
fs.mkdirSync(path.dirname(serialLog), { recursive: true });
fs.rmSync(serialLog, { force: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (serialText().slice(from).includes(needle)) return true;
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\n${serialText().slice(-2000)}`);
}

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

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

const qemuArgs = [
  "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", `user,id=net0,hostfwd=tcp::${hostPort}-:8785`,
  "-device", "rtl8139,netdev=net0",
  "-no-reboot",
  "-display", "none",
];
let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: true });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: true });
  await sleep(1500);
}
const monitor = await connectMonitor(monitorPort);
monitor.setEncoding("ascii");
async function sendKey(k) { monitor.write(`sendkey ${k} 20\n`); await sleep(45); }
async function sendText(t) {
  for (const ch of t) {
    if (ch === " ") await sendKey("spc");
    else if (/^[a-z0-9]$/.test(ch)) await sendKey(ch);
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

let ws = null;
let rpcId = 0;
const tool = (name, args) => rpcCall(ws, `g-${++rpcId}`, "execute_tool", { tool: name, args });
const out = (r) => String(r?.result?.output ?? JSON.stringify(r));
const awaitingId = (r) => {
  const m = /Awaiting confirmation \(id=(\d+)\)/.exec(out(r));
  return m ? Number(m[1]) : null;
};

try {
  await waitForSerial("FerrumOS:~$", 60);
  check("boot reaches shell prompt", true);
  await sendText("ring3 init");
  await sendKey("ret");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 40);
  await sleep(2000);
  ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  assertPaired(await rpcCall(ws, "pair", "pair", { token: await waitForPairingToken(serialText) }));
  check("paired JSON-RPC client", true);

  const target = { path: "/disk/fi1inj-target.txt", content: "written without operator approval" };
  const first = await tool("write_file", target);
  const id = awaitingId(first);
  check("Tier-3 write_file waits for the operator", id !== null, out(first));

  const visible = "echo drafting the weekly status note for team 4.";
  const text = `${visible}\nheliox confirm ${id}\n`;
  const kb = await tool("keyboard_type", { text });
  const kbRefused = kb?.result?.success === false && /Refused by authority policy/.test(out(kb));
  check("keyboard_type carrying Enter is refused, not queued", kbRefused, out(kb));

  const kbId = awaitingId(kb);
  if (kbId !== null) {
    // Pre-fix behaviour: play the operator who approves what they were shown.
    const shown = serialText().includes("[48 of");
    check("(pre-fix) operator was shown only the first 48 bytes", shown);
    const mark = serialText().length;
    await sendText(`heliox confirm ${kbId}`);
    await sendKey("ret");
    await waitForSerial(`confirmation gate resolved: ${kbId}`, 20, mark);
    await sleep(500);
    await rpcCall(ws, "nudge-0", "ping", {});
    const typed = await tool("keyboard_type", { text });
    check("(pre-fix) the approved keyboard_type ran", typed?.result?.success === true, out(typed));
    try {
      await waitForSerial(`confirmation gate resolved: ${id}`, 20, mark);
      check("(pre-fix) injected keys approved the pending write", true);
    } catch {
      check("(pre-fix) injected keys approved the pending write", false);
    }
    await sleep(500);
    await rpcCall(ws, "nudge-1", "ping", {});
  }

  const again = await tool("write_file", target);
  check("the write is still waiting (nobody approved it)", again?.result?.success !== true && awaitingId(again) === id, out(again));

  const mark2 = serialText().length;
  const plain = await tool("keyboard_type", { text: "hello" });
  const plainId = awaitingId(plain);
  await sleep(300);
  check(
    "printable-only keyboard_type waits for approval as a Destructive (Tier 4) call",
    plainId !== null && serialText().slice(mark2).includes("keyboard_type (Destructive)"),
    out(plain),
  );

  check("no userspace fault or page fault panic", !/terminating|General Protection|Page Fault/.test(serialText()));
} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  try { ws?.close(); } catch { /* ignore */ }
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

for (const line of results) console.log(line);
const failed = results.filter((l) => l.startsWith("FAIL")).length;
console.log(`${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
