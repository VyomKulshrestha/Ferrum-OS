// ============================================================================
// FerrumOS - Phase H4 Appliance & TLS Fallback Verification
// ============================================================================
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(scriptDir, "..");
const image = path.join(repo, "target", "x86_64-unknown-none", "debug", "bootimage-ferrumos.bin");
const diskImage = path.join(repo, "target", "heliox-disk.img");

let qemu = process.env.QEMU || "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
if (!fs.existsSync(qemu) && fs.existsSync("C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe")) {
  qemu = "C:\\Program Files\\GNS3\\qemu-3.1.0\\qemu-system-x86_64.exe";
}

const port = Number(process.env.FERRUMOS_MONITOR_PORT || 45480);
const serialLog = path.join(repo, "target", "appliance-verify-serial.log");
const visible = process.argv.includes("--visible");

if (!fs.existsSync(image)) throw new Error(`boot image not found: ${image}`);
if (!fs.existsSync(diskImage)) throw new Error(`model disk image not found: ${diskImage}`);
if (!fs.existsSync(qemu)) throw new Error(`qemu not found: ${qemu}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connectMonitor() {
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

const results = [];
function check(name, ok, detail = "") {
  results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
  return ok;
}

const serialText = () => { try { return fs.readFileSync(serialLog, "utf8"); } catch { return ""; } };

async function waitForSerial(needle, seconds, from = 0) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const text = serialText().slice(from);
    if (text.includes(needle)) return text;
    await sleep(150);
  }
  throw new Error(`timed out waiting for "${needle}"\nRecent serial:\n${serialText().slice(-1000)}`);
}

async function runScenario(memory, useDisk, setupFn, verifyFn) {
  try { fs.unlinkSync(serialLog); } catch {}

  const qemuArgs = [
    "-m", memory,
    "-drive", `format=raw,file=${image}`,
    "-monitor", `tcp:127.0.0.1:${port},server,nowait`,
    "-serial", `file:${serialLog}`,
    "-netdev", "user,id=net0,hostfwd=tcp::8785-:8785",
    "-device", "rtl8139,netdev=net0",
    "-device", "intel-hda",
    "-device", "hda-duplex",
    "-rtc", "base=utc",
    "-no-reboot",
  ];

  if (useDisk) {
    qemuArgs.push("-drive", `format=raw,file=${diskImage},if=ide,index=1`);
  }

  // Use WHPX acceleration if possible, fallback to TCG
  let whpxArgs = ["-accel", "whpx,kernel-irqchip=off", "-cpu", "Haswell", ...qemuArgs];
  if (!visible) whpxArgs.push("-display", "none");

  console.log(`\nLaunching Scenario with memory ${memory}...`);
  let qemuProcess = spawn(qemu, whpxArgs, { windowsHide: !visible });

  await sleep(2500);
  if (qemuProcess.exitCode !== null && qemuProcess.exitCode !== 0) {
    console.log("WHPX failed, falling back to TCG...");
    let tcgArgs = ["-accel", "tcg", "-cpu", "max", ...qemuArgs];
    if (!visible) tcgArgs.push("-display", "none");
    qemuProcess = spawn(qemu, tcgArgs, { windowsHide: !visible });
    await sleep(1500);
  }

  const monitor = await connectMonitor();
  monitor.setEncoding("ascii");
  await sleep(500);

  const mon = async (cmd) => {
    monitor.write(`${cmd}\n`);
    await sleep(150);
  };

  const keyMap = new Map(Object.entries({
    " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus",
    ":": "shift-semicolon", "{": "shift-bracket_left", "}": "shift-bracket_right",
    "\"": "shift-apostrophe", ",": "comma"
  }));

  const sendKey = async (k) => { await mon(`sendkey ${k}`); };
  const sendText = async (t) => {
    for (const ch of t) {
      if (keyMap.has(ch)) await sendKey(keyMap.get(ch));
      else if (/^[a-z0-9]$/i.test(ch)) {
        if (ch === ch.toUpperCase() && !/^[0-9]$/.test(ch)) {
          await sendKey(`shift-${ch.toLowerCase()}`);
        } else {
          await sendKey(ch.toLowerCase());
        }
      } else {
        throw new Error(`no key mapping for ${JSON.stringify(ch)}`);
      }
    }
  };

  try {
    const start = serialText().length;
    await waitForSerial("FerrumOS:~$", 45, start);

    if (setupFn) {
      await setupFn(sendText, sendKey);
    }

    // Spawn daemon
    await sendText("ring3 init");
    await sendKey("ret");

    if (verifyFn) {
      await verifyFn(start);
    }
  } finally {
    monitor.destroy();
    qemuProcess.kill("SIGKILL");
    await sleep(1500);
  }
}

// ---- Main Execution ----

let mockHttpsServer;
let httpsRequestReceived = false;

try {
  // 1. Setup Host Mock HTTPS Server
  const options = {
    key: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.key")),
    cert: fs.readFileSync(path.join(repo, "userland", "heliox-daemon", "certs", "test_server.pem"))
  };

  mockHttpsServer = https.createServer(options, (req, res) => {
    console.log(`[mock HTTPS server] received request: ${req.method} ${req.url}`);
    let body = "";
    req.on("data", chunk => body += chunk);
    req.on("end", () => {
      console.log(`[mock HTTPS server] body: ${body}`);
      httpsRequestReceived = true;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ response: "Hello from mock TLS cloud!" }));
    });
  });

  mockHttpsServer.on("connection", (socket) => {
    console.log(`[mock HTTPS server] TCP Connection established from ${socket.remoteAddress}:${socket.remotePort}`);
  });

  mockHttpsServer.on("secureConnection", (tlsSocket) => {
    console.log(`[mock HTTPS server] Secure TLS connection established`);
  });

  mockHttpsServer.on("tlsClientError", (err, tlsSocket) => {
    console.log(`[mock HTTPS server] TLS Client Error: ${err.message}`);
  });

  await new Promise((resolve) => {
    mockHttpsServer.listen(8443, "0.0.0.0", () => {
      console.log("[mock HTTPS server] listening on port 8443");
      resolve();
    });
  });

  // Scenario 1: High Tier (Local SLM Inference)
  // High specs: 2048MB memory, Ext2 primary slave mounted at /disk, loads model
  await runScenario("2048M", true, async (sendText, sendKey) => {
    // Write config to VFS config.json
    console.log("Writing config.json for local provider to VFS...");
    const configStr = '{"provider":"auto","api_host":"localhost","tick_interval":1}';
    await sendText("rm /disk/heliox/config.json");
    await sendKey("ret");
    await sleep(200);
    await sendText(`write /disk/heliox/config.json ${configStr}`);
    await sendKey("ret");
    await sleep(500);
  }, async (start) => {
    const serialOutput = await waitForSerial("[heliox-daemon] active provider: local-", 25, start);
    const hasLocalProvider = serialOutput.includes("local-1.1B") || serialOutput.includes("local-15M");
    check("High/Standard Tier active provider is local-1.1B or local-15M", hasLocalProvider);

    await waitForSerial("[heliox-daemon] loaded model from /disk/heliox/models/stories15M-q8.bin", 20, start);
    check("High Tier successfully loaded model from primary slave disk", true);

    await waitForSerial("stories15M-q8.bin", 10, start); // Should list or verify model name
    check("High Tier model loads stories15M-q8.bin successfully", true);
  });

  // Scenario 2: Low Tier (Secure TLS 1.3 Cloud Fallback)
  // Low specs: 1024MB memory, VFS config.json points to host mock HTTPS server
  await runScenario("1024M", true, async (sendText, sendKey) => {
    // Write config to VFS config.json
    console.log("Writing config.json to VFS...");
    const configStr = '{"provider":"cloud","api_host":"10.0.2.2","api_port":8443,"api_path":"/","model_name":"mock","api_key":"key","tick_interval":1}';
    await sendText("rm /disk/heliox/config.json");
    await sendKey("ret");
    await sleep(200);
    await sendText(`write /disk/heliox/config.json ${configStr}`);
    await sendKey("ret");
    await sleep(500);
  }, async (start) => {
    await waitForSerial("[heliox-daemon] active provider: cloud", 25, start);
    check("Low Tier active provider is cloud", true);

    await waitForSerial("[heliox-daemon] [ ERROR ] TLS Handshake failed", 20, start).then(() => {
      throw new Error("TLS handshake failed in daemon logs!");
    }).catch((e) => {
      if (e.message.includes("timed out")) {
        // Did not fail, check if we received response
        check("TLS Handshake completed without error log", true);
      } else {
        check("TLS Handshake completed without error log", false, e.message);
      }
    });

    await waitForSerial("Response received", 20, start);
    check("Low Tier received LLM query response from host mock HTTPS server", true);
    check("Host mock HTTPS server registered a secure request", httpsRequestReceived);
  });

} catch (err) {
  check("Appliance Verification", false, err && err.message ? err.message.split("\n")[0] : String(err));
} finally {
  if (mockHttpsServer) {
    mockHttpsServer.close();
  }
}

console.log("\n=================== VERIFICATION RESULTS ===================");
console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
