// ============================================================================
// FerrumOS - Non-blocking Audio Capture Verification (H5)
// ============================================================================
// Proves that SYS_RECORD_AUDIO no longer busy-spins in kernel context for the
// full recording duration. It boots the appliance image, triggers a ~1s HDA
// capture in heliox-daemon, and checks that:
//   1. Real DMA-captured bytes come back (n > 0).
//   2. The capture takes roughly as long as requested (elapsed_ticks is
//      consistent with ~1000ms at the PIT's configured rate - see
//      interrupts::PIT_TICK_MS - not near-zero).
//   3. init - an independent, concurrently-scheduled task - keeps printing
//      its heartbeat throughout the recording window, proving the syscall's
//      Blocked-retry design is not monopolizing the CPU.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45481);
const serialLog = path.join(repo, "target", "audio-verify-serial.log");
// Truncate any stale log from a previous run - QEMU's `-serial file:X` appends
// rather than truncates, and this script's own waitForSerial(needle, s, 0)
// checks start from byte 0, so a leftover log can produce a false-positive
// match (e.g. an old "FerrumOS:~$" prompt) before this run's QEMU has even
// booted, corrupting every offset computed afterward.
fs.rmSync(serialLog, { force: true });
const visible = process.argv.includes("--visible");

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function connectMonitor() {
  for (let i = 0; i < 60; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const sock = net.createConnection({ port, host: "127.0.0.1" }, () => resolve(sock));
        sock.once("error", reject);
      });
    } catch {
      await sleep(250);
    }
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
    await sleep(120);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
}

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon"
}));

// `-audiodev none,id=hda0` + `audiodev=hda0` on the hda-duplex device gives
// the emulated input stream a real (if silent) clocked PCM source. Without
// this, the codec's input line has nothing feeding it at all - the DMA
// position (LPIB) genuinely never advances, so every capture call
// legitimately reads back 0 bytes forever (not a kernel bug: there was
// nothing to record). The `bytes > 0` check only cares about byte *count*,
// not content, so silence is enough to prove the capture path itself works.
const audioArgs = ["-audiodev", "none,id=hda0"];
const hdaDuplexArgs = ["-device", "hda-duplex,audiodev=hda0"];

const whpxArgs = [
  "-accel", "whpx,kernel-irqchip=off",
  "-cpu", "Haswell",
  "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0,hostfwd=tcp::8786-:8785",
  "-device", "rtl8139,netdev=net0",
  ...audioArgs,
  "-device", "intel-hda",
  ...hdaDuplexArgs,
  "-no-reboot",
];
if (!visible) whpxArgs.push("-display", "none");

console.log("[test] starting QEMU for non-blocking audio capture verification...");
let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });

await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  console.log("WHPX unsupported or failed, falling back to TCG...");
  const tcgArgs = [
    "-accel", "tcg",
    "-cpu", "max",
    "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", "user,id=net0,hostfwd=tcp::8786-:8785",
    ...audioArgs,
    "-device", "intel-hda",
    ...hdaDuplexArgs,
    "-no-reboot",
  ];
  if (!visible) tcgArgs.push("-display", "none");
  qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
  await sleep(1500);
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
await sleep(500);

async function mon(cmd, waitMs = 60) {
  monitor.write(`${cmd}\n`);
  await sleep(waitMs);
}

async function sendKey(k) { await mon(`sendkey ${k}`, 45); }

async function sendText(t) {
  for (const ch of t) {
    if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
    else if (/^[a-z0-9]$/i.test(ch)) await sendKey(ch.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
  }
}

try {
  // Generous boot budget - real host-load variance (not a hang) has been
  // observed pushing boot well past a tight timeout; see work.md.
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell prompt", true);

  const start = serialText().length;

  // Write the audio test trigger file
  await sendText("write /tmp/audio_test 1");
  await sendKey("ret");
  await sleep(400);

  // Start init which spawns the daemon
  await sendText("ring3 init");
  await sendKey("ret");

  // Wait for the capture to start
  const startMarker = "[heliox-daemon] running audio capture test...";
  await waitForSerial(startMarker, 45, start);
  check("daemon started audio capture test", true);
  const captureStartOffset = serialText().indexOf(startMarker, start);

  // Wait for it to complete (should take ~1s of real DMA time, plus scheduling slack)
  const resultRe = /\[heliox-daemon\] audio capture result: bytes=(-?\d+) elapsed_ticks=(\d+)/;
  const afterStart = await waitForSerial("audio capture result:", 30, captureStartOffset);
  const m = afterStart.match(resultRe);
  check("found audio capture result line", !!m);

  let bytes = -1, elapsedTicks = -1;
  if (m) {
    bytes = parseInt(m[1], 10);
    elapsedTicks = parseInt(m[2], 10);
    console.log(`[test] capture result: bytes=${bytes} elapsed_ticks=${elapsedTicks}`);
  }

  check(`captured real, non-zero bytes (bytes=${bytes})`, bytes > 0);

  // PIT runs at 1000 Hz (see interrupts::PIT_TICK_MS); ~1000ms should be
  // roughly 1000 ticks. Allow a wide band to absorb scheduling jitter while
  // still ruling out an instant/fake return (elapsed_ticks near 0) or a
  // runaway hang.
  check(`elapsed ticks consistent with real ~1s DMA capture (elapsed_ticks=${elapsedTicks})`, elapsedTicks >= 300 && elapsedTicks <= 6000);

  await waitForSerial("audio capture test complete", 15, captureStartOffset);
  const completeOffset = serialText().indexOf("audio capture test complete", captureStartOffset);

  // Count init's heartbeats between capture start and completion - proof
  // that an independent concurrently-scheduled task kept running throughout
  // the recording window instead of the whole system freezing.
  const windowText = serialText().slice(captureStartOffset, completeOffset);
  const heartbeats = (windowText.match(/\[init\] heartbeat/g) || []).length;
  console.log(`[test] init heartbeats during capture window: ${heartbeats}`);
  check(`independent task (init) kept scheduling during capture (heartbeats=${heartbeats})`, heartbeats >= 2);

  // No faults/panics anywhere in the captured window
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
