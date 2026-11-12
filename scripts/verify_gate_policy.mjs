// ============================================================================
// FerrumOS - fi2 gate policy (workstream P), end to end
// ============================================================================
// Boots the image, runs the fi2 kernel self-tests (shell-only hook directory,
// the audit ring's per-source share with its runtime negative control, the
// focus-bound key injection, the service-registry query), then starts the
// daemon with a config.json that does not parse and drives the gate through a
// paired JSON-RPC client: tier 0 after the broken config (Q3), network sends
// outside the allowlist and poll_input asking (Q1), approval only of the
// request shown last plus `heliox pending` and `heliox deny` (Q2), an approved
// agent write that still cannot plant a hook trigger (Q4), service names in
// the notice (Q5), typed text bound to the focused window (Q-J2c) and the
// refused delete of /disk/heliox (Q-J2d).
// Run: node scripts/verify_gate_policy.mjs   (FERRUMOS_BOOT_SECONDS raises the
// first-prompt budget on a loaded host.)
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
const bootSeconds = Number(process.env.FERRUMOS_BOOT_SECONDS || 90);

const monitorPort = await freeTcpPort();
const hostPort = await freeTcpPort();
const serialLog = path.join(repo, "target", "gate-policy-serial.log");
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
  throw new Error(`timed out waiting for "${needle}"\n${serialText().slice(-1500)}`);
}

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + String(detail).slice(0, 300) : ""}`);
  return ok;
}
const field = (text, name) => (text.match(new RegExp(`${name}=([^\\s]+)`)) || [])[1];

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
const KEYS = { " ": "spc", "/": "slash", ":": "shift-semicolon", ".": "dot", "-": "minus", "_": "shift-minus" };
async function sendKey(k) { monitor.write(`sendkey ${k} 20\n`); await sleep(45); }
async function sendText(t) {
  for (const ch of t) {
    if (KEYS[ch]) await sendKey(KEYS[ch]);
    else if (/^[a-z0-9]$/.test(ch)) await sendKey(ch);
    else if (/^[A-Z]$/.test(ch)) await sendKey(`shift-${ch.toLowerCase()}`);
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}
/// Types a shell command as the operator (physical keys) and returns the
/// serial output after it, once `needle` appears.
async function operator(cmd, needle, seconds = 20) {
  const mark = serialText().length;
  await sendText(cmd);
  await sendKey("ret");
  if (needle) await waitForSerial(needle, seconds, mark);
  else await sleep(1500);
  return serialText().slice(mark);
}

let ws = null;
let rpcId = 0;
const tool = (name, args) => rpcCall(ws, `j-${++rpcId}`, "execute_tool", { tool: name, args });
const out = (r) => String(r?.result?.output ?? JSON.stringify(r));
const awaitingId = (r) => {
  const m = /Awaiting confirmation \(id=(\d+)\)/.exec(out(r));
  return m ? Number(m[1]) : null;
};
async function nudge() {
  await sleep(1500);
  await rpcCall(ws, `nudge-${++rpcId}`, "ping", {});
  await sleep(500);
}


try {
  await waitForSerial("FerrumOS:~$", bootSeconds);
  check("boot reaches shell prompt", true);

  // ---- kernel self-tests -------------------------------------------------
  let o = await operator("test-syscall hook-dir", "removed=").catch((e) => String(e.message || e).split("\n")[0]);
  check("Q4 kernel: /tmp/heliox-hooks exists at boot and every spelling inside it is shell-only",
    field(o, "exists") === "true" && field(o, "covered") === "true" && field(o, "not_covered") === "true",
    (o.match(/selftest hook-dir: .*/) || [""])[0]);
  check("Q4 kernel: the kernel shell can still create and remove a trigger there",
    field(o, "shell_can_write") === "true" && field(o, "removed") === "true");

  o = await operator("test-syscall audit-quota", "dropped=", 60).catch((e) => String(e.message || e).split("\n")[0]);
  check("Q6 kernel: a flood of 300 entries from one source leaves another source's 10 unflushed entries in place",
    field(o, "victim_kept") === "10/10", (o.match(/selftest audit-quota: .*/) || [""])[0]);
  check("Q6 kernel: the flooder holds at most its share and the ring stays within 256",
    field(o, "flooder_within_share") === "true" && field(o, "within_ring") === "true");
  o = await operator("test-syscall audit-quota-off", "dropped=", 60).catch((e) => String(e.message || e).split("\n")[0]);
  check("Q6 negative control: with the quota switched off the same flood pushes the victim's entries out",
    field(o, "victim_kept") === "0/10", (o.match(/selftest audit-quota-off: .*/) || [""])[0]);

  o = await operator("test-syscall focus-target", "none_reported=").catch((e) => String(e.message || e).split("\n")[0]);
  check("Q-J2c kernel: FocusTarget names the focused window; a key bound to it is delivered, marked",
    field(o, "target_ok") === "true" && field(o, "delivered") === "true",
    (o.match(/selftest focus-target: .*/) || [""])[0]);
  check("Q-J2c kernel: a key bound to another window is refused; one whose window loses focus is dropped",
    field(o, "refused_other") === "true" && field(o, "dropped_later") === "true"
      && field(o, "not_delivered") === "true" && field(o, "none_reported") === "true");

  o = await operator("test-syscall service-query", "json_array=").catch((e) => String(e.message || e).split("\n")[0]);
  check("Q5 kernel: SystemQuery type 5 names every registered service",
    Number(field(o, "services")) > 0 && field(o, "all_named") === "true" && field(o, "json_array") === "true",
    (o.match(/selftest service-query: .*/) || [""])[0]);

  // ---- Q3: a configuration that exists and does not parse ----------------
  await operator("write /disk/heliox/config.json notjson", "Written to /disk/heliox/config.json");
  await operator("ring3 init", "[heliox-daemon] sent HELIOX_READY IPC announce", 60);
  check("Q3: a config.json that does not parse is reported once on the console with tier 0",
    serialText().includes("[heliox-daemon] /disk/heliox/config.json exists but cannot be used (not valid JSON): running with auto_approve_tier 0 until it is fixed"));
  await sleep(2000);
  ws = new WebSocket(`ws://127.0.0.1:${hostPort}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  assertPaired(await rpcCall(ws, "pair", "pair", { token: await waitForPairingToken(serialText) }));
  check("paired JSON-RPC client", true);
  let r = await tool("read_file", { path: "/etc/hostname" });
  check("Q3: at tier 0 even a tier-1 read waits for the operator (before fi2 it ran at tier 2)", awaitingId(r) !== null, out(r));

  // ---- Q1: network sends outside the allowlist, and poll_input -----------
  try {
    let mark = serialText().length;
    r = await tool("http_get", { host: "attacker.example", port: 80, path: "/c" });
    const httpId = awaitingId(r);
    check("Q1: http_get to a host outside the allowlist waits for the operator", httpId !== null, out(r));
    await waitForSerial(`confirmation ${httpId} requested: http_get (Modify)`, 10, mark);
    check("Q1: the notice is tier 3 and names the host",
      serialText().slice(mark).includes("[reaches host \"attacker.example\", not on the network allowlist]"));
    r = await tool("poll_input", {});
    check("Q1: poll_input waits for the operator", awaitingId(r) !== null, out(r));
  } catch (err) {
    check("Q1 section", false, err && err.message ? err.message.split("\n")[0] : String(err));
  }

  // ---- Q2: approval by the last notice; heliox pending and deny -----------
  try {
    const a = { path: "/tmp/fi2q2a", content: "approved after a second look" };
    const ra = await tool("write_file", a);
    const aId = awaitingId(ra);
    const rb = await tool("write_file", { path: "/tmp/fi2q2b", content: "buries the first notice ".repeat(60) });
    const bId = awaitingId(rb);
    check("Q2: two writes wait for the operator", aId !== null && bId !== null, `${out(ra)} | ${out(rb)}`);
    let seen = await operator(`heliox confirm ${aId}`, `confirmation gate resolved: ${aId}`);
    await nudge();
    seen = serialText();
    check("Q2: a CONFIRM for a request that was not shown last approves nothing and prints it again",
      seen.includes(`[heliox-daemon] confirmation ${aId} was not the request shown last`)
        && seen.lastIndexOf(`confirmation ${aId} requested: write_file`) > seen.lastIndexOf(`confirmation ${bId} requested: write_file`));
    await operator(`heliox confirm ${aId}`, `confirmation gate resolved: ${aId}`);
    await nudge();
    r = await tool("write_file", a);
    check("Q2: the second CONFIRM, right after the request was shown again, approves it", r?.result?.success === true, out(r));
    let mark = serialText().length;
    await operator("heliox pending", "asked the daemon to show every pending request");
    await nudge();
    check("Q2: heliox pending prints the full text of every pending request",
      serialText().slice(mark).includes("pending confirmation request(s)")
        && serialText().slice(mark).includes(`confirmation ${bId} requested: write_file`));
    await operator(`heliox deny ${bId}`, `confirmation gate denied: ${bId}`);
    await nudge();
    r = await tool("write_file", { path: "/tmp/fi2q2b", content: "buries the first notice ".repeat(60) });
    check("Q2: heliox deny denies it", /denied by operator/.test(out(r)), out(r));
  } catch (err) {
    check("Q2 section", false, err && err.message ? err.message.split("\n")[0] : String(err));
  }

  // ---- Q4: the agent cannot plant a startup-hook trigger ------------------
  try {
    const plant = { path: "/tmp/heliox-hooks/net_test", content: "10.0.2.2:8080/x" };
    r = await tool("write_file", plant);
    const pid = awaitingId(r);
    await operator(`heliox confirm ${pid}`, `confirmation gate resolved: ${pid}`);
    await nudge();
    const mark = serialText().length;
    r = await tool("write_file", plant);
    await sleep(500);
    check("Q4: even an approved agent write cannot create a hook trigger (the kernel refuses ring 3)",
      pid !== null && r?.result?.success !== true
        && serialText().slice(mark).includes("write to a shell-only path denied: /tmp/heliox-hooks/net_test"), out(r));
  } catch (err) {
    check("Q4 section", false, err && err.message ? err.message.split("\n")[0] : String(err));
  }

  // ---- Q5: service calls name the service --------------------------------
  try {
    const mark = serialText().length;
    r = await tool("service_stop", { service_id: 1 });
    const sid = awaitingId(r);
    await waitForSerial(`confirmation ${sid} requested: service_stop`, 10, mark);
    const line = (serialText().slice(mark).match(new RegExp(`confirmation ${sid} requested: service_stop.*`)) || [""])[0];
    check("Q5: the service_stop notice names the service", /\[stops service 1 "[^"]+"\]/.test(line), line);
  } catch (err) {
    check("Q5 section", false, err && err.message ? err.message.split("\n")[0] : String(err));
  }

  // ---- Q-J2c: typed text is bound to the focused window ------------------
  try {
    const mark = serialText().length;
    r = await tool("keyboard_type", { text: "fi2" });
    const kid = awaitingId(r);
    await waitForSerial(`confirmation ${kid} requested: keyboard_type (Destructive)`, 10, mark);
    const line = (serialText().slice(mark).match(new RegExp(`confirmation ${kid} requested: keyboard_type.*`)) || [""])[0];
    check("Q-J2c: the keyboard_type notice names the window that will receive the text", /\[types into /.test(line), line);
    await operator(`heliox confirm ${kid}`, `confirmation gate resolved: ${kid}`);
    await nudge();
    r = await tool("keyboard_type", { text: "fi2" });
    // The keys go only to the window named in the notice (with no focused
    // window, nowhere).
    check("Q-J2c: an approved keyboard_type types into the window it was bound to, or nothing",
      /keyboard focus left the approved window after 0 characters/.test(out(r)) || r?.result?.success === true, out(r));
  } catch (err) {
    check("Q-J2c section", false, err && err.message ? err.message.split("\n")[0] : String(err));
  }

  // ---- Q-J2d: a directory holding the configuration cannot be deleted -----
  r = await tool("delete_file", { path: "/disk/heliox" });
  check("Q-J2d: delete_file of /disk/heliox is refused before any request",
    /may not delete its own authority configuration/.test(out(r)) && awaitingId(r) === null, out(r));

  check("no kernel panic or fault", !/panicked at|PAGE FAULT|Page Fault|General Protection|DOUBLE FAULT/.test(serialText()));
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
