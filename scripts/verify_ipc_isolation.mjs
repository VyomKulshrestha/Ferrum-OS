import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const serialLog = path.join(repo, "target", "ipc-isolation-serial.log");
const monitorPort = await freeTcpPort();
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);
fs.rmSync(serialLog, { force: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const qemuArgs = [
  "-m", "2048M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0",
  "-device", "rtl8139,netdev=net0",
  "-display", "none",
  "-no-reboot",
];

let qemuProcess = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs], { windowsHide: true });
await sleep(2500);
if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
  qemuProcess = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...qemuArgs], { windowsHide: true });
  await sleep(1500);
}

async function connectMonitor() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port: monitorPort }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch {
      await sleep(200);
    }
  }
  throw new Error("could not connect to QEMU monitor");
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");
async function mon(command, waitMs = 60) {
  monitor.write(`${command}\n`);
  await sleep(waitMs);
}
const keyMap = new Map(Object.entries({ " ": "spc", "/": "slash", "_": "shift-minus" }));
async function sendKey(key) { await mon(`sendkey ${key} 20`, 45); }
async function sendText(value) {
  for (const char of value) {
    if (keyMap.has(char)) await sendKey(keyMap.get(char));
    else if (/^[a-z0-9]$/i.test(char)) await sendKey(char.toLowerCase());
    else throw new Error(`no key mapping for ${JSON.stringify(char)}`);
  }
}
const serialText = () => {
  try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; }
};
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(120);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}\n${serialText().slice(-2500)}`);
}

const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? `\t${detail}` : ""}`);
try {
  await waitForSerial("FerrumOS:~$", 90);
  check("boot reaches shell", true);
  const start = serialText().length;
  await sendText("write /tmp/init_test 8");
  await sendKey("ret");
  await sleep(400);
  await sendText("ring3 init");
  await sendKey("ret");

  await waitForSerial("[ipc-test] cross-process mailbox isolation confirmed", 30, start);
  check("IPC-capable process cannot consume another process mailbox", true);
  await waitForSerial("[ipc-test] per-service backpressure preserves unrelated mailboxes", 30, start);
  check("stalled service cannot starve an unrelated mailbox", true);
  await waitForSerial("[ipc-test] all checks complete", 30, start);
  check("authorized process receives only its own seeded mailbox", true);
  await waitForSerial("FerrumOS:~$", 45, start);
  const log = serialText().slice(start);
  check("foreign receive is audited and denied", log.includes("IPC receive denied for mailbox owned by another process"));
  check("no kernel or userspace fault", !/Page Fault|General Protection|panicked at|terminating/.test(log));
} catch (error) {
  check("verification", false, error?.message?.split("\n")[0] || String(error));
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log(results.join("\n"));
const failed = results.filter((line) => line.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
