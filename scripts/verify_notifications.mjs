// End-to-end notification service verification: capability denial, shell
// post/list, ring-3 Notification Center read/clear, and Text Editor posting.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const serialLog = path.join(repo, "target", "notifications-verify-serial.log");
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45519);
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
  const launcherX = dockX + 15, launcherY = dockY - (16 + 10 * 28 + 8);
  async function launch(index) {
    await click(startX, startY);
    await sleep(1500);
    await click(launcherX + 98, launcherY + 8 + index * 28 + 12);
    await sleep(1800);
  }

  await waitForSerial("FerrumOS:~$", 40);
  check("notification service initialized", serialText().includes("Desktop notification service initialized"));
  let offset = serialText().length;
  await command("session guest");
  await command("notify denied body");
  const denied = await waitForSerial("permission denied: notification:post", 5, offset);
  check("guest cannot post notifications", denied.includes("permission denied: notification:post"));

  await command("session root");
  offset = serialText().length;
  await command("notify Backup complete");
  await command("notifications");
  const shellLog = await waitForSerial("[1] backup - complete (pid 0)", 5, offset);
  check("shell posts and lists notification history", shellLog.includes("notification posted (id 1)"));

  await command("ring3 init");
  await waitForSerial("[heliox-daemon] sent HELIOX_READY IPC announce", 35, offset);
  offset = serialText().length;
  await launch(9);
  const centerLog = await waitForSerial("[notification-center] loaded count=1", 30, offset);
  check("Notification Center reads broker history in ring 3", centerLog.includes("loaded count=1"));

  // Clear button: app canvas starts at (152,172), clear rect center=(406,18).
  await click(558, 190);
  await waitForSerial("[notification-center] cleared all", 8, offset);
  check("Notification Center clears broker history", true);

  // Close center, launch Text Editor, and save to exercise app-originated post.
  await click(150 + 464 - 12, 160);
  await sleep(500);
  offset = serialText().length;
  await launch(3);
  await waitForSerial("[text-editor] window created id=", 30, offset);
  await key("esc");
  const postLog = await waitForSerial("title=File saved", 8, offset);
  check("Text Editor posts save notification", /\[notification\] posted id=2 pid=[1-9][0-9]* title=File saved/.test(postLog));

  await click(150 + 484 - 12, 160);
  await sleep(500);
  offset = serialText().length;
  await launch(9);
  const reload = await waitForSerial("[notification-center] loaded count=1", 30, offset);
  check("Notification Center sees app-originated notification", reload.includes("loaded count=1"));
} catch (error) {
  results.push(`FAIL\tverifier completed\t${error.message}`);
} finally {
  if (monitor) monitor.destroy();
  child.kill();
}

console.log("\nNotification verification:");
for (const result of results) console.log(result);
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exitCode = 1;
