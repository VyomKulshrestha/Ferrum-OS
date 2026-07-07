// ============================================================================
// FerrumOS - Real Local Model Verification
// ============================================================================
// Boots the *real* packaged appliance (target/heliox-disk.img, built by
// scripts/make-appliance.ps1 from the real stories15M-q8.bin checkpoint in
// appliance/models/ - NOT the synthetic fixture verify_inference.mjs uses
// for its deterministic byte-exact assertion) and confirms local_inference
// produces actual coherent-looking English, not the old synthetic
// "pqrstuvwxyz{|}~" placeholder pattern.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const diskImage = path.join(repo, "target", "heliox-disk.img");

let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45486);
const serialLog = path.join(repo, "target", "real-model-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`appliance disk image not found: ${diskImage} - run scripts/make-appliance.ps1 first`);

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

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

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-2000)}`);
}

const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${diskImage},if=ide,index=1`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
  "-device", "rtl8139,netdev=net0",
  "-device", "intel-hda",
  "-device", "hda-duplex",
  "-no-reboot",
];

let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU with the real appliance disk image...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX failed, falling back to TCG...");
  let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 150) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}
const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon",
  "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe", ",": "comma"
}));
async function sendKey(k) { await mon(`sendkey ${k}`, 45); }
async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

try {
  const start = serialText().length;
  await waitForSerial("FerrumOS:~$", 90, start);
  check("boot reaches shell prompt", true);

  // Explicit "local" provider (this phase's setup-wizard fast path) rather
  // than relying on tier auto-detection, so this test is unambiguous about
  // what it's exercising. tick_interval is deliberately huge (not the
  // default 100) to suppress the orchestrator's autonomous "think" cycle
  // entirely - it calls run_local_inference on its own schedule with a
  // multi-KB system prompt, which would otherwise compete with (and its
  // console-logged output could be mistaken for) this test's explicit
  // execute_tool/local_inference call.
  // heliox-disk.img is a persistent file on the host, not reset between
  // boots - a config.json written by an earlier run of this script (or any
  // other test) survives on it. `write` refuses to overwrite an existing
  // file, so remove any leftover config first (ignoring the error if there
  // isn't one) to guarantee this run's config actually takes effect.
  await sendText("rm /disk/heliox/config.json");
  await sendKey("ret");
  await sleep(300);

  const configStr = '{"provider":"local","tick_interval":999999999}';
  await sendText(`write /disk/heliox/config.json ${configStr}`);
  await sendKey("ret");
  await sleep(400);

  await sendText("ring3 init");
  await sendKey("ret");

  // The real model is loaded lazily on the first inference request, not at
  // boot - with the autonomous think-cycle suppressed (tick_interval above),
  // nothing calls run_local_inference until this test's own WS request does
  // below. Waiting for "loaded model" before that request is sent would just
  // time out.
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 45, start);

  await sleep(2000); // let the WebSocket server bind

  console.log("[test] connecting to daemon WebSocket, requesting local_inference...");
  const ws = new WebSocket("ws://127.0.0.1:8785");
  let response = null;
  let wsError = null;

  ws.onopen = () => {
    ws.send(JSON.stringify({
      jsonrpc: "2.0",
      id: "real-model-test",
      method: "execute_tool",
      params: { tool: "local_inference", args: { prompt: "Once upon a time" } },
    }));
  };
  ws.onerror = (err) => { wsError = err; };
  ws.onmessage = (event) => {
    console.log("[test] WS message:", event.data);
    try {
      const data = JSON.parse(event.data);
      if (data.id === "real-model-test") response = data.result;
    } catch { /* ignore parse errors from unrelated frames */ }
  };

  // The real model is loaded lazily on the first inference request (not at
  // HELIOX_READY) and mmap's its ~16MB checkpoint page-by-page from the
  // disk image - on this debug kernel build under QEMU's emulated IDE that
  // first-load disk I/O can outlast a client's TCP patience even though the
  // daemon is making steady progress (see the fault_in() readahead fix in
  // src/process/mod.rs). So the console log line the daemon always emits
  // right after generating (independent of whether the WS response makes it
  // back) is the authoritative signal; a live WS round trip is a bonus,
  // best-effort check layered on top, not the pass/fail gate.
  await waitForSerial("[heliox-daemon] loaded model from /disk/heliox/models/stories15M-q8.bin", 60, start);
  check("daemon loaded the real stories15M-q8.bin checkpoint", true);

  let output = null;
  try {
    const genLog = await waitForSerial("[heliox-daemon] local_inference output: ", 240, start);
    // The daemon escapes embedded newlines (\n -> \\n) so a multi-paragraph
    // story stays on one console line; undo that to compare against the
    // WS response, which JSON already decoded back to real newlines.
    const line = genLog.split("[heliox-daemon] local_inference output: ")[1].split("\n")[0];
    output = line.replace(/\\n/g, "\n");
    console.log(`[test] local_inference output (via console log): ${JSON.stringify(output)}`);
  } catch (err) {
    throw new Error(`model never finished generating: ${err.message.split("\n")[0]}`);
  }
  check("local_inference actually ran and produced output", output !== null && output.length > 0);

  const wsDeadline = Date.now() + 10_000;
  while (Date.now() < wsDeadline && !response && !wsError) {
    await sleep(200);
  }
  if (response) {
    console.log(`[test] bonus: live WebSocket response also arrived: ${JSON.stringify(response.output)}`);
    check("bonus: live WebSocket response matches the console-logged output", response.output === output);
  } else {
    console.log("[test] bonus WS round trip did not complete within the connection's patience (see comment above) - not fatal, console log above is authoritative");
  }

  // The synthetic test fixture always emits ascending-ASCII gibberish like
  // "pqrstuvwxyz{|}~" (see the H3 "Known Limitation" this phase closes).
  // Assert the output is NOT that pattern...
  check("output is not the synthetic gibberish pattern", !/^[a-z]{5}[a-z{|}~]*$/.test(output.trim()) || !output.includes("pqrst"));

  // ...and does contain real, recognizable English words a trained
  // TinyStories-style model would actually produce, rather than just
  // checking it merely differs from the old placeholder.
  const commonWords = [" the ", " a ", " and ", " was ", " to ", " once ", " little ", " day "];
  const padded = ` ${output.toLowerCase()} `;
  const foundWords = commonWords.filter((w) => padded.includes(w));
  check(
    "output contains real English words (proves a real trained model, not gibberish)",
    foundWords.length > 0,
    `found: ${JSON.stringify(foundWords)} in output: ${JSON.stringify(output)}`
  );

  const full = serialText().slice(start);
  check("no userspace fault or page fault panic", !/terminating|General Protection|Page Fault/.test(full));

} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
