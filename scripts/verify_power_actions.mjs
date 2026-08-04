// FerrumOS Power Menu Verification
// Boots a fresh disposable image for each destructive action, opens the
// desktop's Power menu with real PS/2 pointer input, and proves that Restart
// and Shut down reach the hardware action and terminate QEMU cleanly.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceImage = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function serialText(log) { try { return fs.readFileSync(log, "utf8"); } catch { return ""; } }

async function waitForSerial(log, needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (serialText(log).slice(from).includes(needle)) return;
    await sleep(120);
  }
  throw new Error(`timed out waiting for ${JSON.stringify(needle)}: ${serialText(log).slice(-1500)}`);
}

async function connectMonitor(port) {
  for (let attempt = 0; attempt < 80; attempt++) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch {
      await sleep(200);
    }
  }
  throw new Error("could not connect to QEMU monitor");
}

const keyMap = new Map(Object.entries({ " ": "spc", "-": "minus" }));

async function runAction({ name, entryIndex, marker, port }) {
  const runImage = path.join(repo, "target", `power-${name}-disk.bin`);
  const log = path.join(repo, "target", `power-${name}-serial.log`);
  fs.rmSync(runImage, { force: true });
  fs.rmSync(log, { force: true });
  fs.copyFileSync(sourceImage, runImage);

  let child;
  let monitor;
  try {
    child = spawn(qemu, [
      "-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", "-m", "4096M",
      "-drive", `format=raw,file=${runImage}`,
      "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
      "-serial", `file:${log}`, "-display", "none", "-vga", "std", "-no-reboot",
    ], { windowsHide: true });
    monitor = await connectMonitor(port);
    const mon = async (command, waitMs = 60) => {
      monitor.write(`${command}\n`);
      await sleep(waitMs);
    };
    const sendKey = async (key) => mon(`sendkey ${key} 20`, 45);
    const sendText = async (text) => {
      for (const character of text) {
        if (keyMap.has(character)) await sendKey(keyMap.get(character));
        else if (/^[a-z0-9]$/i.test(character)) await sendKey(character.toLowerCase());
        else throw new Error(`unsupported key ${JSON.stringify(character)}`);
      }
    };

    await waitForSerial(log, "FerrumOS:~$", 40);
    const bootOffset = serialText(log).length;
    await sendText("ring3 init");
    await sendKey("ret");
    await waitForSerial(log, "[heliox-daemon] sent HELIOX_READY IPC announce", 35, bootOffset);
    await sleep(4000);

    // Cursor begins at (512,384). Taskbar Power center is (814,738).
    await mon("mouse_move 100 100", 80);
    await mon("mouse_move 100 100", 80);
    await mon("mouse_move 100 100", 80);
    await mon("mouse_move 2 54", 80);
    await mon("mouse_button 1", 120);
    await mon("mouse_button 0", 250);

    // Popup entry centers: x=754; y=574 + index*28. Cursor is (814,738).
    const targetX = 754;
    const targetY = 574 + entryIndex * 28;
    await mon(`mouse_move ${targetX - 814} ${targetY - 738}`, 100);
    const actionOffset = serialText(log).length;
    await mon("mouse_button 1", 100);
    await mon("mouse_button 0", 100);
    await waitForSerial(log, marker, 8, actionOffset);

    const deadline = Date.now() + 8000;
    while (child.exitCode === null && Date.now() < deadline) await sleep(100);
    if (child.exitCode === null) throw new Error(`${name} reached ACPI path but QEMU stayed running`);
    return `PASS\tPower menu ${name} reaches hardware action and exits QEMU`;
  } finally {
    if (monitor) monitor.destroy();
    if (child && child.exitCode === null) child.kill("SIGKILL");
    await sleep(200);
    fs.rmSync(runImage, { force: true });
  }
}

const results = [];
for (const action of [
  { name: "restart", entryIndex: 2, marker: "Initiating reboot...", port: 45489 },
  { name: "shutdown", entryIndex: 3, marker: "Initiating ACPI shutdown...", port: 45490 },
]) {
  try {
    results.push(await runAction(action));
  } catch (error) {
    results.push(`FAIL\tPower menu ${action.name}\t${error.message.split("\n")[0]}`);
  }
}

console.log(results.join("\n"));
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
