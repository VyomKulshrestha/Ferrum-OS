// FerrumOS ferrumpkg trust-boundary verification.
// Boots disposable copies of the real appliance image after independently
// tampering with (1) the detached signature and (2) the signed ELF payload.
// Both must be rejected by `pkg verify` and `pkg install` inside the guest.
import { spawn, execFileSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const appliance = path.join(repo, "target", "heliox-disk.img");
const notesElf = path.join(repo, "userland", "notes", "target", "x86_64-unknown-none", "release", "notes");
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}

for (const required of [image, appliance, notesElf, qemu]) {
  if (!fs.existsSync(required)) throw new Error(`required file not found: ${required}`);
}

const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function debugfs(imagePath, command) {
  const relativeImage = path.relative(repo, imagePath).replaceAll("\\", "/");
  execFileSync("wsl", ["debugfs", "-w", "-R", command, relativeImage], { cwd: repo, stdio: "pipe" });
}

function prepareTamperedDisk(kind, index) {
  const disk = path.join(repo, "target", `pkg-trust-${kind}-${index}.img`);
  fs.copyFileSync(appliance, disk);
  if (kind === "signature") {
    const badSig = path.join(repo, "target", `pkg-trust-bad-${index}.sig`);
    fs.writeFileSync(badSig, `${"00".repeat(64)}\n`, "ascii");
    debugfs(disk, "rm /pkgs-available/notes/manifest.sig");
    debugfs(disk, `write target/${path.basename(badSig)} /pkgs-available/notes/manifest.sig`);
    fs.rmSync(badSig, { force: true });
  } else {
    const badElf = path.join(repo, "target", `pkg-trust-bad-${index}.elf`);
    const bytes = fs.readFileSync(notesElf);
    bytes[Math.min(512, bytes.length - 1)] ^= 0x01;
    fs.writeFileSync(badElf, bytes);
    debugfs(disk, "rm /pkgs-available/notes/bin");
    debugfs(disk, `write target/${path.basename(badElf)} /pkgs-available/notes/bin`);
    fs.rmSync(badElf, { force: true });
  }
  return disk;
}

async function connectMonitor(port) {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection({ host: "127.0.0.1", port }, () => resolve(socket));
        socket.once("error", reject);
      });
    } catch { await sleep(200); }
  }
  throw new Error("could not connect to QEMU monitor");
}

async function runScenario(kind, index) {
  const disk = prepareTamperedDisk(kind, index);
  const port = 45520 + index;
  const serialLog = path.join(repo, "target", `pkg-trust-${kind}.log`);
  fs.rmSync(serialLog, { force: true });
  const common = [
    "-m", "512M",
    "-drive", `format=raw,file=${image}`,
    "-drive", `format=raw,file=${disk},if=ide,index=1`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-display", "none",
    "-no-reboot",
  ];
  let proc = spawn(qemu, ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...common], { windowsHide: true });
  await sleep(2500);
  if (proc.exitCode !== null && proc.exitCode !== 0) {
    proc = spawn(qemu, ["-accel", "tcg", "-cpu", "max", ...common], { windowsHide: true });
    await sleep(1500);
  }
  let monitor;
  try {
    monitor = await connectMonitor(port);
    monitor.setEncoding("ascii");
    const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };
    const waitFor = async (needle, seconds, from = 0) => {
      const deadline = Date.now() + seconds * 1000;
      while (Date.now() < deadline) {
        if (serialText().slice(from).includes(needle)) return;
        await sleep(120);
      }
      throw new Error(`timed out waiting for ${needle}`);
    };
    const mon = async (command, waitMs = 70) => { monitor.write(`${command}\n`); await sleep(waitMs); };
    const send = async (text) => {
      for (const ch of text) await mon(`sendkey ${ch === " " ? "spc" : ch} 20`);
      await mon("sendkey ret 20", 120);
    };

    await waitFor("FerrumOS:~$", 60);
    const verifyStart = serialText().length;
    await send("pkg verify notes");
    await waitFor("FerrumOS:~$", 10, verifyStart);
    let output = serialText().slice(verifyStart);
    const expected = kind === "signature" ? "manifest signature verification failed" : "binary SHA-256 does not match signed manifest";
    check(`${kind} tampering is rejected by pkg verify`, output.includes(expected), output.trim());

    const installStart = serialText().length;
    await send("pkg install notes");
    await waitFor("FerrumOS:~$", 10, installStart);
    output = serialText().slice(installStart);
    check(`${kind} tampering cannot be installed`, output.includes("package verification failed") && output.includes(expected), output.trim());
    check(`${kind} scenario has no kernel/page fault`, !/General Protection|Page Fault|panicked at/.test(serialText()));
  } finally {
    if (monitor) monitor.destroy();
    proc.kill("SIGKILL");
    if (proc.exitCode === null) {
      await Promise.race([
        new Promise((resolve) => proc.once("exit", resolve)),
        sleep(2000),
      ]);
    }
    for (let attempt = 0; attempt < 10; attempt++) {
      try {
        fs.rmSync(disk, { force: true });
        break;
      } catch (error) {
        if (attempt === 9) throw error;
        await sleep(200);
      }
    }
  }
}

try {
  await runScenario("signature", 0);
  await runScenario("binary", 1);
} catch (error) {
  check("verification", false, error?.message || String(error));
}

console.log("\n" + results.join("\n"));
const failed = results.filter((line) => line.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
