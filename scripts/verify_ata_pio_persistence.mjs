import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const sourceDisk = path.join(repo, "target", "heliox-disk.img");
const runDisk = path.join(repo, "target", "ata-pio-persistence-disk.img");
const basePort = Number(process.env.FERRUMOS_MONITOR_PORT || 45531);
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";

if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}
if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(sourceDisk)) throw new Error(`appliance disk not found: ${sourceDisk}`);

fs.rmSync(runDisk, { force: true });
fs.copyFileSync(sourceDisk, runDisk);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const keyMap = new Map(Object.entries({
  " ": "spc",
  ".": "dot",
  "-": "minus",
  "/": "slash",
  "_": "shift-minus",
}));
const results = [];

function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? `\t${detail}` : ""}`);
}

async function runPhase(name, port, commands) {
  const serialLog = path.join(repo, "target", `ata-pio-${name}-serial.log`);
  fs.rmSync(serialLog, { force: true });
  const commonArgs = [
    "-m", "2048M",
    "-drive", `format=raw,file=${image}`,
    "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-no-reboot",
    "-display", "none",
  ];
  let child = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...commonArgs], {
    windowsHide: true,
  });
  await sleep(2500);
  if (child.exitCode !== null && child.exitCode !== 0) {
    child = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...commonArgs], { windowsHide: true });
    await sleep(1500);
  }

  let monitor;
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
    throw new Error(`${name}: timed out waiting for ${JSON.stringify(needle)}`);
  }

  try {
    const connectDeadline = Date.now() + 15_000;
    while (!monitor && Date.now() < connectDeadline) {
      try {
        monitor = await new Promise((resolve, reject) => {
          const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
          socket.once("error", reject);
        });
      } catch {
        await sleep(200);
      }
    }
    if (!monitor) throw new Error(`${name}: could not connect to QEMU monitor`);
    monitor.setEncoding("ascii");
    await sleep(500);

    async function sendKey(key) {
      monitor.write(`sendkey ${key} 20\n`);
      await sleep(120);
    }
    async function sendText(text) {
      for (const char of text) {
        if (keyMap.has(char)) await sendKey(keyMap.get(char));
        else if (/^[a-z0-9]$/i.test(char)) await sendKey(char.toLowerCase());
        else throw new Error(`${name}: no key mapping for ${JSON.stringify(char)}`);
      }
    }
    async function runCommand(command, expected) {
      const start = serialText().length;
      await sendText(command);
      await sendKey("ret");
      const output = await waitForSerial("FerrumOS:~$", 20, start);
      if (!output.includes(expected)) {
        throw new Error(`${name}: ${command} did not emit ${JSON.stringify(expected)}`);
      }
      if (/ATA timeout|ATA: write error|ATA: flush error/.test(output)) {
        throw new Error(`${name}: ATA failure while running ${command}`);
      }
    }

    await waitForSerial("FerrumOS:~$", 45);
    for (const [command, expected] of commands) await runCommand(command, expected);
    const full = serialText();
    check(`${name} completes without ATA timeout or kernel fault`, !/ATA timeout|ATA: write error|ATA: flush error|Page Fault|General Protection/.test(full));
  } finally {
    if (monitor) monitor.destroy();
    child.kill("SIGKILL");
    await sleep(500);
  }
}

try {
  await runPhase("write", basePort, [
    ["mkdir /disk/ata_verify_dir", "Directory created: /disk/ata_verify_dir"],
    ["touch /disk/ata_verify_dir/state.txt", "Created: /disk/ata_verify_dir/state.txt"],
    ["write /disk/ata_verify_dir/state.txt ferrum_persisted", "Written to /disk/ata_verify_dir/state.txt"],
    ["cat /disk/ata_verify_dir/state.txt", "ferrum_persisted"],
    ["sync", "Filesystems synchronized successfully."],
  ]);
  await runPhase("reboot", basePort + 1, [
    ["mounts", "ata.primary.slave on /disk type ext2 (rw)"],
    ["cat /disk/ata_verify_dir/state.txt", "ferrum_persisted"],
    ["write /disk/ata_verify_dir/state.txt ferrum_after_reboot", "Written to /disk/ata_verify_dir/state.txt"],
    ["sync", "Filesystems synchronized successfully."],
    ["cat /disk/ata_verify_dir/state.txt", "ferrum_after_reboot"],
    ["rm /disk/ata_verify_dir/state.txt", "Removed: /disk/ata_verify_dir/state.txt"],
    ["rm /disk/ata_verify_dir", "Removed: /disk/ata_verify_dir"],
  ]);
  check("file content survives a cold QEMU restart", true);
} catch (error) {
  check("ATA persistence verification", false, error && error.message ? error.message : String(error));
}

console.log(results.join("\n"));
const failures = results.filter((result) => result.startsWith("FAIL\t"));
console.log(`${results.length - failures.length}/${results.length} checks passed`);
process.exit(failures.length ? 1 : 0);
