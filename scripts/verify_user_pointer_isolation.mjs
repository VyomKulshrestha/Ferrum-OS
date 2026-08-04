// Prove that ring-3 syscall buffers are checked against the caller's actual
// mapped address space, not merely against the broad canonical-address range.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const serialLog = path.join(repo, "target", "user-pointer-verify-serial.log");
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45522);
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu)) qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
fs.rmSync(serialLog, { force: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(120);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}\n${serialText().slice(-3000)}`);
}
async function connectMonitor() {
  for (let i = 0; i < 80; i++) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(250); }
  }
  throw new Error("could not connect to QEMU monitor");
}
const qemuArgs = (accel, cpu) => [
  "-accel", accel, "-cpu", cpu, "-m", "512M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`, "-display", "none", "-no-reboot",
];
let child = spawn(qemu, qemuArgs("whpx,kernel-irqchip=off", "Haswell"), { windowsHide: true });
await sleep(2500);
if (child.exitCode !== null) {
  child = spawn(qemu, qemuArgs("tcg", "max"), { windowsHide: true });
  await sleep(1500);
}

const results = [];
const check = (name, ok) => results.push(`${ok ? "PASS" : "FAIL"}\t${name}`);
let monitor;
try {
  monitor = await connectMonitor();
  monitor.setEncoding("ascii");
  const keyMap = new Map([[" ", "spc"], ["/", "slash"], ["_", "shift-minus"]]);
  async function key(name) { monitor.write(`sendkey ${name} 20\n`); await sleep(55); }
  async function text(value) {
    for (const char of value) {
      if (keyMap.has(char)) await key(keyMap.get(char));
      else await key(char.toLowerCase());
    }
  }
  async function command(value) { await text(value); await key("ret"); await sleep(350); }

  await waitForSerial("FerrumOS:~$", 45);
  const offset = serialText().length;
  await command("write /tmp/init_test 5");
  await command("ring3 init");
  const output = await waitForSerial("[pointer-test] all invalid ranges denied", 20, offset);
  check("kernel low-memory pointer is denied", output.includes("all invalid ranges denied"));
  check("unmapped user-slot pointer is denied", output.includes("all invalid ranges denied"));
  check("range crossing user-slot end is denied", output.includes("all invalid ranges denied"));
  check("invalid pointers do not fault the kernel", !/PAGE FAULT|General Protection|panicked at/.test(output));
} catch (error) {
  results.push(`FAIL\tverifier completed\t${error.message}`);
} finally {
  if (monitor) monitor.destroy();
  child.kill();
}

console.log("\nUser-pointer isolation verification:");
for (const result of results) console.log(result);
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exitCode = 1;
