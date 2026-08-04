// Verify the capability-gated clipboard across the kernel shell and a real
// ring-3 Text Editor process. This covers the service, syscall ABI, PS/2
// Ctrl+V/Ctrl+C translation, SDK wrappers, and persistence after paste.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const serialLog = path.join(repo, "target", "clipboard-verify-serial.log");
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45518);
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
  "-accel", accel, "-cpu", cpu, "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
  "-serial", `file:${serialLog}`, "-vga", "std", "-display", "none", "-no-reboot",
];

let child = spawn(qemu, qemuArgs("whpx,kernel-irqchip=off", "Haswell"), { windowsHide: true });
await sleep(2500);
if (child.exitCode !== null) {
  child = spawn(qemu, qemuArgs("tcg", "max"), { windowsHide: true });
  await sleep(1500);
}

let monitor;
const results = [];
function check(name, ok) { results.push(`${ok ? "PASS" : "FAIL"}\t${name}`); }

try {
  monitor = await connectMonitor();
  monitor.setEncoding("ascii");
  async function mon(command, waitMs = 60) { monitor.write(`${command}\n`); await sleep(waitMs); }
  async function key(name) { await mon(`sendkey ${name} 20`, 55); }
  async function text(value) {
    for (const char of value) {
      if (char === " ") await key("spc");
      else if (char === "/") await key("slash");
      else if (char === "-") await key("minus");
      else if (char === ".") await key("dot");
      else await key(char.toLowerCase());
    }
  }
  async function command(value) { await text(value); await key("ret"); await sleep(300); }

  let cursorX = 512, cursorY = 384;
  async function click(x, y) {
    await mon(`mouse_move ${x - cursorX} ${y - cursorY}`, 120);
    cursorX = x; cursorY = y;
    await mon("mouse_button 1", 120);
    await mon("mouse_button 0", 250);
  }

  // Geometry mirrors desktop.rs at 1024x768 with eleven launcher entries.
  const dockX = Math.floor((1024 - 846) / 2), dockY = 718;
  const startX = dockX + 10 + 35, startY = dockY + 20;
  const launcherX = dockX + 10, launcherY = dockY - (16 + 11 * 28 + 8);
  async function launchTextEditor() {
    await click(startX, startY);
    await sleep(1500);
    await click(launcherX + 98, launcherY + 8 + 3 * 28 + 12);
    await sleep(1800);
  }

  await waitForSerial("FerrumOS:~$", 40);
  check("clipboard service initialized", serialText().includes("Shared clipboard service initialized"));

  let offset = serialText().length;
  await command("session guest");
  await command("clipboard get");
  const denied = await waitForSerial("permission denied: clipboard:read", 5, offset);
  check("guest session cannot read clipboard", denied.includes("permission denied: clipboard:read"));

  await command("session root");
  await command("write /disk/scratch.txt seed");
  offset = serialText().length;
  await command("clipboard set shared");
  const setLog = await waitForSerial("clipboard updated (generation 1)", 5, offset);
  check("shell writes bounded shared clipboard", setLog.includes("[clipboard] write pid=0 bytes=6 generation=1"));

  await command("ring3 init");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 35, offset);

  offset = serialText().length;
  await launchTextEditor();
  await waitForSerial("[text-editor] window created id=", 30, offset);
  await key("ctrl-v");
  const pasteLog = await waitForSerial("[text-editor] pasted clipboard bytes=6", 8, offset);
  check("ring-3 app reads shell-owned clipboard with Ctrl+V", pasteLog.includes("pasted clipboard bytes=6"));

  await key("esc");
  await waitForSerial("[text-editor] saved", 8, offset);
  // Close the 484px-wide app window, then prove a new process loads the paste.
  await click(150 + 484 - 12, 160);
  await sleep(600);
  offset = serialText().length;
  await launchTextEditor();
  const reload = await waitForSerial("[text-editor] window created id=", 30, offset);
  check("pasted content persists through Text Editor save", reload.includes("[text-editor] loaded: seedshared"));

  await key("ctrl-c");
  const copyLog = await waitForSerial("[text-editor] copied all to clipboard", 8, offset);
  check("ring-3 app writes clipboard with Ctrl+C", /\[clipboard\] write pid=[1-9][0-9]* bytes=10/.test(copyLog));
} catch (error) {
  results.push(`FAIL\tverifier completed\t${error.message}`);
} finally {
  if (monitor) monitor.destroy();
  child.kill();
}

console.log("\nClipboard verification:");
for (const result of results) console.log(result);
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exitCode = 1;
