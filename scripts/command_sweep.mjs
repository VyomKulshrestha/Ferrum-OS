import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(
  repo,
  "target",
  "x86_64-unknown-none",
  "debug",
  "bootimage-ferrumos.bin",
);
const defaultQemu =
  "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
const qemu = process.env.QEMU || defaultQemu;
const visible = process.argv.includes("--visible");
const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45457);
const serialLog = path.join(repo, "target", "command-test-serial.log");

if (!fs.existsSync(image)) {
  throw new Error(`boot image not found: ${image}`);
}

if (!fs.existsSync(qemu)) {
  throw new Error(`qemu not found: ${qemu}`);
}

try {
  fs.unlinkSync(serialLog);
} catch {
  // Log may not exist yet.
}

const qemuArgs = [
  "-drive",
  `format=raw,file=${image}`,
  "-device",
  "intel-hda",
  "-device",
  "hda-duplex",
  "-monitor",
  `tcp:127.0.0.1:${port},server,nowait`,
  "-serial",
  `file:${serialLog}`,
  "-no-reboot",
];

if (!visible) {
  qemuArgs.push("-display", "none");
}

const qemuProcess = spawn(qemu, qemuArgs, {
  windowsHide: !visible,
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function connectMonitor() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      return await new Promise((resolve, reject) => {
        const socket = net.createConnection(
          { host: "127.0.0.1", port },
          () => resolve(socket),
        );
        socket.once("error", reject);
      });
    } catch {
      await sleep(200);
    }
  }

  throw new Error("could not connect to QEMU monitor");
}

const monitor = await connectMonitor();
monitor.setEncoding("ascii");

let monitorBuffer = "";
monitor.on("data", (data) => {
  monitorBuffer += data;
});

await sleep(500);
monitorBuffer = "";

async function monitorCommand(command, waitMs = 60) {
  monitorBuffer = "";
  monitor.write(`${command}\n`);
  await sleep(waitMs);
  const output = monitorBuffer;
  monitorBuffer = "";
  return output;
}

const keyMap = new Map(
  Object.entries({
    " ": "spc",
    ".": "dot",
    "-": "minus",
    "/": "slash",
    "\\": "backslash",
    ";": "semicolon",
    "=": "equal",
    ",": "comma",
    "[": "bracket_left",
    "]": "bracket_right",
    "'": "apostrophe",
    "`": "grave_accent",
  }),
);

async function sendKey(key) {
  await monitorCommand(`sendkey ${key}`, 85);
}

async function sendText(text) {
  for (const char of text) {
    if (keyMap.has(char)) {
      await sendKey(keyMap.get(char));
    } else if (/^[a-z0-9]$/.test(char)) {
      await sendKey(char);
    } else {
      throw new Error(`no key mapping for ${JSON.stringify(char)}`);
    }
  }
}

function serialText() {
  try {
    return fs.readFileSync(serialLog, "utf8");
  } catch {
    return "";
  }
}

async function waitForSerial(needle, seconds = 25, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) {
      return text;
    }
    await sleep(120);
  }

  throw new Error(
    `timed out waiting for ${needle}\nRecent serial:\n${serialText().slice(-2000)}`,
  );
}

async function runCommand(command, expected) {
  const start = serialText().length;
  await sendText(command);
  await sendKey("ret");
  await waitForSerial(expected, 8, start);
}

/// Send a command, wait for the expected banner, and do NOT
/// expect a new shell prompt afterwards. Used for one-way
/// commands like `ring3 init` that iretq into user mode and
/// never return to the shell.
async function runOneWayCommand(command, expected) {
  const start = serialText().length;
  await sendText(command);
  await sendKey("ret");
  await waitForSerial(expected, 8, start);
}

const tests = [
  ["help", "FerrumOS Shell Commands:"],
  ["clear", "FerrumOS:~$"],
  ["echo hello ferrumos", "hello ferrumos"],
  ["ps", "PID  STATE"],
  ["mem", "Kernel Heap Memory:"],
  ["ls", "readme.txt"],
  ["cat readme.txt", "Welcome to FerrumOS"],
  ["stat readme.txt", "Type:     file"],
  ["mounts", "ramfs.root on / type ramfs"],
  ["mkdir testdir", "Directory created: testdir"],
  ["ls", "testdir"],
  ["touch note.txt", "FerrumOS:~$"],
  ["write note.txt ferrumosok", "Written to note.txt"],
  ["cat note.txt", "ferrumosok"],
  ["rm note.txt", "Removed: note.txt"],
  ["devices", "net.primary"],
  ["net", "127.0.0.0/8 via local dev lo"],
  ["net send hello", "loopback packet delivered"],
  ["caps", "cap:agent:control"],
  ["services", "runtime.agentd"],
  ["services stop 7", "service 7 stopped"],
  ["services start 7", "service 7 started"],
  ["services health", "Service Health:"],
  ["services restart 7", "service 7 restarted"],
  ["ipc", "IPC Broker:"],
  ["syscalls", "Syscall ABI:"],
  ["programs", "agent-bridge"],
  ["users", "init"],
  ["run agent-bridge", "launched agent-bridge as userspace pid 103"],
  ["users", "agent-bridge"],
  ["syscall 103 5 1", "syscall result: Ok value=1"],
  ["syscall 103 1", "syscall result: Ok value="],
  ["syscall 103 2", "syscall result: Ok value="],
  ["syscall 103 3 7", "syscall result: PermissionDenied value=0"],
  ["agent status", "Agent Runtime Boundary:"],
  ["agent start", "agentd started"],
  ["agent send ping", "agent command queued as IPC message"],
  ["agent status", "Last command:  ping"],
  ["heliox status", "Heliox-OS Integration Bridge:"],
  ["heliox services", "Heliox Runtime Service Slots:"],
  ["heliox methods", "Heliox JSON-RPC Methods"],
  ["heliox tiers", "Heliox Permission Tiers"],
  ["heliox actions", "Heliox Action Catalog"],
  ["heliox send ping", "heliox envelope dispatched: ping"],
  ["heliox notif status", "heliox notification prepared: status"],
  ["heliox voice start", "heliox voice listener started"],
  ["heliox voice event hello world", "voice_event envelope id="],
  ["heliox voice stop", "heliox voice listener stopped"],
  ["heliox screen on", "heliox screen vision enabled"],
  ["heliox screen context", "screen_context envelope id="],
  ["heliox screen off", "heliox screen vision disabled"],
  ["heliox persona add editor=helix", "persona rule recorded"],
  ["heliox confirm no-such-plan", "confirmation gate resolved: no-such-plan"],
  ["heliox execute open terminal", "heliox execute dispatched"],
  ["elf", "PT_LOAD segments:"],
  ["elf", "entry:      0x"],
  ["process", "Per-process Address Spaces"],
  ["process", "init-sample"],
  ["session guest", "session switched to guest"],
  ["heliox send ping", "permission denied: cap:heliox:bridge"],
  ["session root", "session switched to root"],
  ["log", "Recent Audit Log"],
  ["uptime", "Uptime:"],
  ["uname", "FerrumOS v0.1.0 x86_64"],
  ["whoami", "kernel (uid=0, gid=0)"],
  ["session guest", "session switched to guest"],
  ["whoami", "guest (uid=1000, gid=1000)"],
  ["cat readme.txt", "Welcome to FerrumOS"],
  ["write blocked.txt nope", "permission denied: fs:write:*"],
  ["net send denied", "permission denied: net:connect:*"],
  ["run init", "permission denied: process:spawn"],
  ["services stop 7", "permission denied: cap:service:register"],
  ["agent send denied", "permission denied: cap:agent:control"],
  ["log", "permission denied: audit:read"],
  ["session root", "session switched to root"],
  ["spawn worker1", "Spawned task 'worker1'"],
  ["kill 104", "Killed task 104"],
  ["security", "Security Status:"],
  ["about", "FerrumOS v0.1.0"],
  ["process", "Per-process Address Spaces (2):"],
  ["scheduler", "Scheduler State:"],
  ["test-syscall yield", "yield: ran=false"],
  ["test-syscall sleep", "sleep(2): ran=false"],
  ["test-syscall wait", "wait(-1): any_dead=true"],
  ["test-syscall priority", "priority System -> index 3"],
  ["ring3 init-sample", "Invalid Opcode"],
];

const results = [];

try {
  await waitForSerial("FerrumOS:~$", 25);
  for (const [command, expected] of tests.slice(0, -1)) {
    await runCommand(command, expected);
    results.push(`PASS\t${command}`);
  }
  const [ring3Command, ring3Expected] = tests[tests.length - 1];
  try {
    await runOneWayCommand(ring3Command, ring3Expected);
    results.push(`PASS\t${ring3Command} (one-way, kernel now in ring 3)`);
  } catch (err) {
    results.push(`FAIL\t${ring3Command}\t${err && err.message ? err.message : err}`);
  }
} finally {
  monitor.destroy();
  qemuProcess.kill("SIGKILL");
}

console.log(results.join("\n"));
