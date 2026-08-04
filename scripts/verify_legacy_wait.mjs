// Verify syscall 13's legacy wait-any ABI blocks a real ring-3 parent until
// one of its children exits, then resumes it with that child's status.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const serialLog = path.join(repo, "target", "legacy-wait-verify-serial.log");
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45523);
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu)) qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
fs.rmSync(serialLog, { force: true });

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const output = serialText().slice(from);
    if (output.includes(needle)) return output;
    await sleep(120);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}\n${serialText().slice(-2500)}`);
}
async function connectMonitor() {
  for (let attempt = 0; attempt < 80; attempt++) {
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
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? `\t${detail}` : ""}`);
let monitor;
try {
  monitor = await connectMonitor();
  const keyMap = new Map([[" ", "spc"], ["/", "slash"], ["_", "shift-minus"]]);
  const key = async (name) => { monitor.write(`sendkey ${name} 20\n`); await sleep(55); };
  const text = async (value) => {
    for (const character of value) await key(keyMap.get(character) || character.toLowerCase());
  };
  const command = async (value) => { await text(value); await key("ret"); await sleep(350); };

  await waitForSerial("FerrumOS:~$", 45);
  const offset = serialText().length;
  await command("write /tmp/init_test 6");
  await command("ring3 init");
  const output = await waitForSerial("[wait-test] legacy wait resumed with status=", 25, offset);
  const spawnAt = output.indexOf("[wait-test] child pid=");
  const childExitAt = output.indexOf("[WAKE_PARENT] Waking parent");
  const resumedAt = output.indexOf("[wait-test] legacy wait resumed with status=");
  check("legacy wait-any spawns a real child", spawnAt >= 0);
  check("parent is woken by its child's exit", childExitAt > spawnAt);
  check("wait returns only after the child exit wakeup", resumedAt > childExitAt);
  check("wait path does not fault the kernel", !/Page Fault|General Protection|panicked at/.test(output));
} catch (error) {
  results.push(`FAIL\tverifier completed\t${error.message.split("\n")[0]}`);
} finally {
  if (monitor) monitor.destroy();
  child.kill();
}

console.log("\nLegacy wait verification:");
for (const result of results) console.log(result);
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exitCode = 1;
