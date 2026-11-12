// ============================================================================
// FerrumOS - Heliox authority gate: self-approval and approval-binding probe
// ============================================================================
// fi1 workstream D, round 1. Boots the image, pairs a JSON-RPC client (the
// role an external model plays) and drives `execute_tool` through the real
// daemon:
//   1. A Tier-3 write_file waits for the operator.
//   2. The client tries to approve it itself: ipc_send to the daemon's own
//      mailbox ("heliox") with CONFIRM:<id>. Must be refused.
//   3. Repeating the write must still wait (it was not approved).
//   4. Writing the daemon's own config (auto_approve_tier) must be refused.
//   5. The operator approves a write via the kernel shell (`heliox confirm`);
//      a different path sharing the first 32 bytes must NOT be covered by
//      that approval; the exact approved call then runs once.
// On main at dba7016 steps 2, 3 and 5 fail (self-approval works; approvals
// were keyed on a 32-byte summary). Run: node scripts/verify_authority_gate_self_approval.mjs
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

const monitorPort = Number(process.env.FERRUMOS_MONITOR_PORT || 45588);
const hostPort = Number(process.env.FERRUMOS_HOST_PORT || 0) || await freeTcpPort();
const serialLog = path.join(repo, "target", "authority-gate-self-approval-serial.log");
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

  // 1-3: self-approval through the daemon's own mailbox.
  const target = { path: "/disk/fi1gatea.txt", content: "self-approval probe" };
  const first = await tool("write_file", target);
  const id = awaitingId(first);
  check("Tier-3 write_file waits for the operator", id !== null, out(first));
  const selfConfirm = await tool("ipc_send", { target_service: "heliox", message: `CONFIRM:${id}` });
  check(
    "ipc_send CONFIRM to the daemon's own mailbox is refused",
    selfConfirm?.result?.success === false && /Refused by authority policy/.test(out(selfConfirm)),
    out(selfConfirm),
  );
  await rpcCall(ws, "nudge-1", "ping", {});
  const second = await tool("write_file", target);
  check("the write is still waiting (no self-approval)", awaitingId(second) === id, out(second));

  // 4: own configuration.
  const cfg = await tool("write_file", { path: "/disk/heliox/config.json", content: "{\"auto_approve_tier\":4}" });
  check(
    "write_file of the daemon's own config is refused, not queued",
    cfg?.result?.success === false && /Refused by authority policy/.test(out(cfg)),
    out(cfg),
  );

  // 5: binding to the complete arguments, approved by the operator.
  const approved = { path: "/disk/fi1gate-binding-probe-00000001-approved.txt", content: "approved" };
  const other = { path: "/disk/fi1gate-binding-probe-00000001-substitute.txt", content: "approved" };
  const req = await tool("write_file", approved);
  const reqId = awaitingId(req);
  check("second write waits for the operator", reqId !== null, out(req));
  const mark = serialText().length;
  await sendText(`heliox confirm ${reqId}`);
  await sendKey("ret");
  await waitForSerial(`confirmation gate resolved: ${reqId}`, 20, mark);
  await sleep(500);
  await rpcCall(ws, "nudge-2", "ping", {});
  const substitute = await tool("write_file", other);
  check(
    "the approval does not cover a path that shares its first 32 bytes",
    substitute?.result?.success === false && awaitingId(substitute) !== null && awaitingId(substitute) !== reqId,
    out(substitute),
  );
  const exact = await tool("write_file", approved);
  check("the exactly approved call runs", exact?.result?.success === true, out(exact));
  const again = await tool("write_file", approved);
  check("the approval is single-use", awaitingId(again) !== null, out(again));

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
