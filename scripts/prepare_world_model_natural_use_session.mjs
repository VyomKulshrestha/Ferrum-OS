// Launch one visible, disposable FerrumOS natural-use session. Keyboard and
// pointer input are intentionally left to Windows Computer Use.
import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { freeTcpPort } from "./lib/free_port.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const valueAfter = (name) => {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : null;
};
const session = Number(valueAfter("--session"));
const runtimePath = path.resolve(repo, valueAfter("--runtime") || `target/world-model-natural-use-session-${session}-runtime.json`);
const transitionPath = path.resolve(repo, valueAfter("--transition") || "target/world-model-v3-work/world_model_jepa_v3_candidate.bin");
if (!Number.isInteger(session) || session < 1 || session > 3) throw new Error("--session must be 1, 2 or 3");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const sourceDisk = path.join(repo, "target", "heliox-disk.img");
const runDisk = path.join(repo, "target", `world-model-natural-use-session-${session}.img`);
const serialLog = path.join(repo, "target", `world-model-natural-use-session-${session}.log`);
const monitorPort = await freeTcpPort();
let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu)) qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
for (const required of [image, sourceDisk, transitionPath]) if (!fs.existsSync(required)) throw new Error(`missing ${required}`);
fs.copyFileSync(sourceDisk, runDisk);
fs.rmSync(serialLog, { force: true });

const relativeRunDisk = path.relative(repo, runDisk).replaceAll("\\", "/");
const relativeTransition = path.relative(repo, transitionPath).replaceAll("\\", "/");
const relativeReadme = "docs/research/world_model_natural_use_readme_v1.txt";
for (const command of [
  "unlink /heliox/config.json",
  "mkdir /tmp",
  `write ${relativeReadme} /README.txt`,
  "unlink /heliox/world/model_learned.bin",
  `write ${relativeTransition} /heliox/world/model_learned.bin`,
]) {
  const prepared = spawnSync("wsl", ["debugfs", "-w", "-R", command, relativeRunDisk], { cwd: repo, encoding: "utf8" });
  if (prepared.status !== 0) throw new Error(`disk preparation failed: ${prepared.stderr || prepared.stdout}`);
}

const args = [
  "-name", `FerrumOS Natural Use Session ${session}`,
  "-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", "-m", "4096M",
  "-drive", `format=raw,file=${image}`,
  "-drive", `format=raw,file=${runDisk},if=ide,index=1`,
  "-serial", `file:${serialLog}`,
  "-netdev", "user,id=net0", "-device", "rtl8139,netdev=net0",
  "-monitor", `tcp:127.0.0.1:${monitorPort},server,nowait`,
  "-display", "gtk,zoom-to-fit=on", "-no-reboot",
];
const child = spawn(qemu, args, { detached: true, windowsHide: false, stdio: "ignore" });
child.unref();
const runtime = {
  schema_version: 1,
  session,
  pid: child.pid,
  monitor_port: monitorPort,
  qemu,
  image: path.relative(repo, image).replaceAll("\\", "/"),
  source_disk: path.relative(repo, sourceDisk).replaceAll("\\", "/"),
  source_disk_sha256_before: digest(sourceDisk),
  run_disk: path.relative(repo, runDisk).replaceAll("\\", "/"),
  serial_log: path.relative(repo, serialLog).replaceAll("\\", "/"),
  transition: path.relative(repo, transitionPath).replaceAll("\\", "/"),
  transition_sha256: digest(transitionPath),
  input_boundary: "Windows Computer Use against the visible QEMU window",
  setup_mode: "ring3 init; full desktop loop; assistant first-run wizard: local then tiny",
  setup_commands: ["ring3 init", "desktop"],
  effective_tick_interval: 100,
  intent_boundary: "deterministic common-OS intent adapter; every tool call remains capability and world-model gated",
};
fs.writeFileSync(runtimePath, JSON.stringify(runtime, null, 2) + "\n");
const controller = spawn(
  "pythonw.exe",
  [path.join(repo, "scripts", "natural_use_keyboard_controller.py"), "--runtime", runtimePath],
  { detached: true, windowsHide: false, stdio: "ignore" },
);
controller.unref();
runtime.controller_pid = controller.pid;
fs.writeFileSync(runtimePath, JSON.stringify(runtime, null, 2) + "\n");
console.log(JSON.stringify({
  runtime: runtimePath,
  pid: child.pid,
  controller_pid: controller.pid,
  window_title: `FerrumOS Natural Use Session ${session}`,
}, null, 2));
