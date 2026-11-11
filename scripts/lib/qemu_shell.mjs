// Boot the FerrumOS image in QEMU and drive the kernel shell over the monitor
// (sendkey) while reading the serial log. Shared by the fi1 kernel harnesses.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { freeTcpPort } from "./free_port.mjs";

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const KEYS = new Map(Object.entries({
  " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon", "=": "equal",
}));

export async function bootShell(repo, logName, { bootSeconds = Number(process.env.FERRUMOS_BOOT_SECONDS || 240) } = {}) {
  const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
  const serialLog = path.join(repo, "target", logName);
  let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
  if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
    qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
  }
  if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
  fs.rmSync(serialLog, { force: true });
  const port = await freeTcpPort();
  const args = (accel, cpu) => [
    "-accel", accel, "-cpu", cpu, "-m", "4096M",
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", "user,id=net0", "-device", "rtl8139,netdev=net0",
    "-device", "intel-hda", "-device", "hda-duplex",
    "-display", "none", "-no-reboot",
  ];
  const started = Date.now();
  let child = spawn(qemu, args("whpx,kernel-irqchip=off", "Haswell"), { windowsHide: true });
  await sleep(2500);
  if (child.exitCode !== null) {
    child = spawn(qemu, args("tcg", "max"), { windowsHide: true });
    await sleep(1500);
  }
  let monitor = null;
  for (let i = 0; i < 80 && !monitor; i++) {
    try {
      monitor = await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(250); }
  }
  if (!monitor) { child.kill("SIGKILL"); throw new Error("could not connect to QEMU monitor"); }
  monitor.setEncoding("ascii");

  const serial = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
  async function waitFor(needle, seconds, from = 0) {
    const deadline = Date.now() + seconds * 1000;
    while (Date.now() < deadline) {
      const text = serial().slice(from);
      if (typeof needle === "string" ? text.includes(needle) : needle.test(text)) return text;
      if (child.exitCode !== null) throw new Error(`QEMU exited (code ${child.exitCode}) while waiting for ${needle}`);
      await sleep(100);
    }
    throw new Error(`timed out waiting for ${needle}\n${serial().slice(-1500)}`);
  }
  async function key(name) { monitor.write(`sendkey ${name} 20\n`); await sleep(45); }
  async function type(text) {
    for (const ch of text) {
      if (KEYS.has(ch)) await key(KEYS.get(ch));
      else if (/^[a-z0-9]$/i.test(ch)) await key(ch.toLowerCase());
      else throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
    }
  }
  // Type a command and return the serial output it produced, up to the next
  // prompt. Ring-3 apps print on serial too, so the slice may contain their
  // lines as well.
  async function command(text, seconds = 30) {
    const from = serial().length;
    await type(text);
    await key("ret");
    const out = await waitFor(/\r?\n[^\n]*FerrumOS:~\$/, seconds, from + text.length);
    return out;
  }

  await waitFor("FerrumOS:~$", bootSeconds);
  const bootMs = Date.now() - started;
  return {
    bootMs, serial, waitFor, type, key, command,
    close() { try { monitor.destroy(); } catch {} child.kill("SIGKILL"); },
    get exited() { return child.exitCode !== null; },
  };
}

export function report(title, results) {
  console.log(`\n${title}:`);
  for (const line of results) console.log(line);
  const failed = results.filter((line) => line.startsWith("FAIL"));
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exitCode = failed.length ? 1 : 0;
}
