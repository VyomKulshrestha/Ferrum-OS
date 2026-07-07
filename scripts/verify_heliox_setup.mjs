// ============================================================================
// FerrumOS - Heliox Setup Wizard Verification
// ============================================================================
// Heliox is always the OS's native agent - it isn't a setup choice. What the
// first-run wizard actually decides is which brain powers it:
//   Local -> {tiny on-device model, or a local Ollama server}
//   Cloud -> {OpenAI, Claude, Gemini} + an API key
// This proves both branches actually reach a written config.json AND that
// the already-running daemon picks it up live (CONFIG_UPDATED IPC reload),
// not just that the file got written. Each branch gets its own fresh boot,
// since the Agent HUD only enters setup mode once at boot (when no config
// exists yet) - there's no in-session way to re-arm it.
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
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45485);
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

const keyMap = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon"
}));

async function runScenario(label, wizardSteps, expectPrefix) {
  const serialLog = path.join(repo, "target", `heliox-setup-verify-${label}-serial.log`);
  const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
  const waitForSerial = async (needle, seconds, from = 0) => {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      const text = serialText().slice(from);
      if (text.includes(needle)) return text;
      await sleep(120);
    }
    throw new Error(`[${label}] timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-3000)}`);
  };

  const whpxArgs = [
    "-accel", "whpx,kernel-irqchip=off",
    "-cpu", "Haswell",
    "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-vga", "std",
    "-no-reboot",
  ];
  if (!visible) whpxArgs.push("-display", "none");

  console.log(`[test] [${label}] starting QEMU...`);
  let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });
  await sleep(2500);
  if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
    console.log(`[${label}] WHPX unsupported or failed, falling back to TCG...`);
    const tcgArgs = [
      "-accel", "tcg",
      "-cpu", "max",
      "-m", "4096M",
      "-drive", `format=raw,file=${image}`,
      "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
      "-serial", `file:${serialLog}`,
      "-vga", "std",
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
  async function typeLine(text) {
    await sendText(text);
    await sendKey("ret");
    await sleep(250);
  }

  try {
    await waitForSerial("FerrumOS:~$", 35);
    check(`[${label}] boot reaches shell prompt`, true);

    const start = serialText().length;
    await sendText("ring3 init");
    await sendKey("ret");

    // Wait for the daemon's ambient loop to start pumping render/input
    // (see D1's investigation: keystrokes need this before compositor
    // ever drains them) before typing wizard responses.
    await waitForSerial("[heliox-daemon] userspace agent daemon is alive in ring 3", 15, start);
    await sleep(1500);

    const beforeWizard = serialText().length;
    for (const step of wizardSteps) {
      await typeLine(step);
    }
    await waitForSerial("[heliox-daemon] config reloaded via IPC, active provider:", 10, beforeWizard);
    const reloadLog = serialText().slice(beforeWizard);
    const match = reloadLog.match(/active provider: (\S+)/);
    check(
      `[${label}] resolves to the expected provider (${expectPrefix}...)`,
      !!match && match[1].startsWith(expectPrefix),
      match ? match[1] : "no match"
    );

    const full = serialText().slice(start);
    check(`[${label}] no userspace fault or page fault panic`, !/terminating|General Protection|Page Fault/.test(full));
  } catch (err) {
    check(`[${label}] verification`, false, err && err.message ? err.message.split("\n")[0] : String(err));
  } finally {
    monitor.destroy();
    qemuProcess.kill("SIGKILL");
  }
}

await runScenario("local-tiny", ["local", "tiny"], "local-");
await runScenario("cloud-claude", ["cloud", "claude", "sk-test-claude-key-123"], "claude");

console.log("\n" + results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
