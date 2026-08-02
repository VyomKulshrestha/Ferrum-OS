// Verify PS/2 Alt+Tab reaches the compositor, raises the previous app, and is
// consumed before application input dispatch.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const serialLog = path.join(repo, "target", "task-switching-verify-serial.log");
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45520);
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
const check = (name, ok) => results.push(`${ok ? "PASS" : "FAIL"}\t${name}`);
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
  const dockX = Math.floor((1024 - 658) / 2), dockY = 718;
  const startX = dockX + 50, startY = dockY + 20;
  const launcherX = dockX + 15, launcherY = dockY - (16 + 11 * 28 + 8);
  async function launch(index) {
    await click(startX, startY);
    await sleep(1500);
    await click(launcherX + 98, launcherY + 8 + index * 28 + 12);
    await sleep(1800);
  }

  await waitForSerial("FerrumOS:~$", 40);
  await command("write /disk/scratch.txt base");
  let offset = serialText().length;
  await command("ring3 init");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 35, offset);

  await launch(3);
  await waitForSerial("[text-editor] window created id=", 30, offset);
  await launch(4);
  await waitForSerial("[calculator] window created id=", 30, offset);

  offset = serialText().length;
  await key("alt-tab");
  const toEditor = await waitForSerial("title=Text Editor", 8, offset);
  check("Alt+Tab raises the previous app", toEditor.includes("[desktop] alt-tab"));
  await key("z");
  await key("esc");
  await waitForSerial("[text-editor] saved", 8, offset);
  check("focused Text Editor receives ordinary keys after switch", true);

  offset = serialText().length;
  await key("alt-tab");
  const toCalculator = await waitForSerial("title=Calculator", 8, offset);
  check("second Alt+Tab returns to the prior foreground app", toCalculator.includes("[desktop] alt-tab"));

  await key("alt-tab");
  await waitForSerial("title=Text Editor", 8, offset);
  await click(150 + 484 - 12, 160);
  await sleep(500);
  offset = serialText().length;
  await launch(3);
  const reload = await waitForSerial("[text-editor] window created id=", 30, offset);
  check("Alt+Tab token never leaks into edited text", reload.includes("[text-editor] loaded: basez"));
  check("no userspace fault during switching", !reload.includes("USERSPACE FAULT") && !reload.includes("PAGE FAULT"));
} catch (error) {
  results.push(`FAIL\tverifier completed\t${error.message}`);
} finally {
  if (monitor) monitor.destroy();
  child.kill();
}

console.log("\nTask-switching verification:");
for (const result of results) console.log(result);
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exitCode = 1;
