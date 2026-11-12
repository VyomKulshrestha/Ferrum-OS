// usage: node probe.mjs <image.bin> <outlog> [--wait N] -- "cmd1" "cmd2" ...
// Boots a throwaway copy of the image (WHPX, 4096M, same devices as the harnesses),
// waits for the shell prompt, types each command, waits for the next prompt, writes serial to outlog.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
const [, , imageSrc, outlog, ...rest] = process.argv;
const sep = rest.indexOf("--");
const opts = rest.slice(0, sep < 0 ? 0 : sep);
const cmds = sep < 0 ? rest : rest.slice(sep + 1);
const perCmd = Number(opts[opts.indexOf("--wait") + 1] || 10);
const image = outlog + ".img";
fs.copyFileSync(imageSrc, image);
fs.rmSync(outlog, { force: true });
const port = 45900 + Math.floor(Math.random() * 90);
const qemu = "C:\\Program Files\\qemu\\qemu-system-x86_64.exe";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const serial = () => { try { return fs.readFileSync(outlog, "utf8"); } catch { return ""; } };
const args = (accel, cpu) => ["-accel", accel, "-cpu", cpu, "-m", "4096M", "-drive", `format=raw,file=${image}`,
  "-monitor", `tcp:127.0.0.1:${port},server,nowait`, "-serial", `file:${outlog}`,
  "-netdev", "user,id=net0", "-device", "rtl8139,netdev=net0", "-device", "intel-hda", "-device", "hda-duplex",
  "-display", "none", "-no-reboot"];
const t0 = Date.now();
let q = spawn(qemu, args("whpx,kernel-irqchip=off", "Haswell"), { windowsHide: true });
await sleep(2500);
if (q.exitCode !== null) { q = spawn(qemu, args("tcg", "max"), { windowsHide: true }); await sleep(1500); }
let mon;
for (let i = 0; i < 80 && !mon; i++) {
  try { mon = await new Promise((res, rej) => { const s = net.createConnection({ host: "127.0.0.1", port }, () => res(s)); s.once("error", rej); }); }
  catch { await sleep(250); }
}
const keyMap = new Map(Object.entries({ " ": "spc", ".": "dot", "-": "minus", "/": "slash", "_": "shift-minus", ":": "shift-semicolon", "=": "equal", ",": "comma" }));
async function key(k) { mon.write(`sendkey ${k} 20\n`); await sleep(45); }
async function text(t) { for (const c of t) { if (keyMap.has(c)) await key(keyMap.get(c)); else if (/[A-Z]/.test(c)) await key("shift-" + c.toLowerCase()); else await key(c); } }
let seenLen = 0; const timeline = [];
function stamp() { const t = serial(); if (t.length > seenLen) { const fresh = t.slice(seenLen).split(/\r?\n/).filter(l => l.trim()); for (const l of fresh) timeline.push(`${((Date.now() - t0) / 1000).toFixed(1)}	${l.slice(0, 100)}`); seenLen = t.length; } }
async function waitFor(needle, sec, from) {
  const d = Date.now() + sec * 1000;
  while (Date.now() < d) { stamp(); if (serial().slice(from).includes(needle)) return true; await sleep(100); }
  return false;
}
let status = "ok";
const c2stop = () => /mmap validation success/.test(serial());
try {
  if (!(await waitFor("FerrumOS:~$", Number(process.env.BOOT_WAIT||400), 0))) throw new Error("no prompt");
  console.log(`boot_ms ${Date.now() - t0}`);
  for (const c of cmds) {
    if (c.startsWith("@sleep ")) { const until = Date.now() + Number(c.slice(7)); while (Date.now() < until) { stamp(); if (c2stop()) break; await sleep(100); } continue; }
    const from = serial().length;
    await text(c); await key("ret");
    if (!(await waitFor("FerrumOS:~$", perCmd, from + c.length))) { console.log(`no prompt after: ${c}`); }
  }
} catch (e) { status = "error " + e.message; }
finally { mon?.destroy(); q.kill("SIGKILL"); for (let i = 0; i < 20; i++) { await sleep(500); try { fs.rmSync(image, { force: true }); break; } catch {} } }
console.log(status);
fs.writeFileSync(outlog + ".timeline", timeline.join(String.fromCharCode(10)));
