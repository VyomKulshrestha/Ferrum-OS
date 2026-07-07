// ============================================================================
// FerrumOS - Phase H1 Hardware Tier & Provider Verification
// ============================================================================
// Boots the kernel in QEMU under two different memory conditions,
// verifies the kernel detects the correct hardware tier, and verifies the
// userspace daemon selects the appropriate LLM provider.
// ============================================================================
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45470);
const serialLog = path.join(repo, "target", "tier-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

async function runScenario(memory, expectedTier, expectedProvider) {
  try { fs.unlinkSync(serialLog); } catch {}

  // We try launching with WHPX first
  const whpxArgs = [
    "-accel", "whpx,kernel-irqchip=off",
    "-cpu", "Haswell",
    "-m", memory,
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
    "-device", "rtl8139,netdev=net0",
    "-device", "intel-hda",
    "-device", "hda-duplex",
    "-no-reboot",
  ];
  if (!visible) whpxArgs.push("-display", "none");

  console.log(`Launching Scenario: ${memory} (Expected Tier: ${expectedTier})...`);
  let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });

  // Wait to see if it exits immediately (WHPX unsupported)
  await sleep(2500);
  if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
    console.log("WHPX unsupported or failed, falling back to TCG...");
    const tcgArgs = [
      "-accel", "tcg",
      "-cpu", "max",
      "-m", memory,
      "-drive", `format=raw,file=${image}`,
      "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
      "-serial", `file:${serialLog}`,
      "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
      "-device", "rtl8139,netdev=net0",
      "-device", "intel-hda",
      "-device", "hda-duplex",
      "-no-reboot",
    ];
    if (!visible) tcgArgs.push("-display", "none");
    qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
    await sleep(1500);
  }

  const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };

  const waitForSerial = async (needle, seconds) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      const text = serialText();
      if (text.includes(needle)) return text;
      await sleep(150);
    }
    throw new Error(`timed out waiting for "${needle}"`);
  };

  // Wait for boot and verify hardware detection logs
  await waitForSerial("Hardware detected:", 25);
  const bootLog = serialText();
  
  // Assert the hardware logs show the correct tier
  const tierRegex = new RegExp(`Tier:\\s*${expectedTier}`, "i");
  check(`Kernel detects ${expectedTier} tier for -m ${memory}`, tierRegex.test(bootLog), `Log: ${bootLog.split("\n").find(l => l.includes("Hardware detected"))}`);

  // Connect to monitor and start ring3 init to spawn daemon
  const monitor = await connectMonitor();
  monitor.setEncoding("ascii");
  await sleep(500);
  
  const mon = async (cmd) => {
    monitor.write(`${cmd}\n`);
    await sleep(120);
  };

  const keyMap = new Map(Object.entries({
    " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
    "{": "shift-bracket_left", "}": "shift-bracket_right", "\"": "shift-apostrophe", ",": "comma", ":": "shift-semicolon",
  }));
  const sendKey = async (k) => { await mon(`sendkey ${k}`); };
  const sendText = async (t) => {
    for (const ch of t) {
      if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
      else if (/^[a-z0-9]$/.test(ch)) await sendKey(ch);
      else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
    }
  };

  // Wait for prompt and boot into ring3
  await waitForSerial("FerrumOS:~$", 35);

  // heliox-daemon now stays idle (provider stuck at "auto", no tier
  // resolution) until a config.json actually exists on disk - a fresh,
  // totally unconfigured boot must NOT silently start autonomous inference
  // (see REPORT.md's Phase D5 section). This test is about hardware-tier
  // detection feeding provider selection, which only fires once the user
  // has chosen "auto" (or the wizard completes) - so pre-write that choice
  // via the shell before `ring3 init`, same pattern as
  // verify_jsonrpc_methods.mjs's "configured" scenario.
  await sendText('write /disk/heliox/config.json {"provider":"auto"}');
  await sendKey("ret");
  await sleep(300);

  await sendText("ring3 init");
  await sendKey("ret");

  // Wait for daemon startup and verify active provider log
  await waitForSerial("[heliox-daemon] active provider:", 35);
  const daemonLog = serialText();
  
  const providerRegex = new RegExp(`active provider:\\s*${expectedProvider}`, "i");
  check(`Daemon selects ${expectedProvider} provider for ${expectedTier} tier`, providerRegex.test(daemonLog), `Log: ${daemonLog.split("\n").find(l => l.includes("active provider"))}`);

  // Clean up
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
  await sleep(1500);
}

try {
  // Scenario 1: High Tier
  await runScenario("8192M", "high", "local-1.1B");

  // Scenario 2: Low Tier
  await runScenario("1536M", "low", "cloud");

} catch (err) {
  check("verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
}

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
