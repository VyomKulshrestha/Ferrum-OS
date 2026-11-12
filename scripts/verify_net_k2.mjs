// fi1 kernel round 2: the guest's network receive path under crafted frames.
//
// QEMU's RTL8139 is attached to a host UDP socket (`-netdev dgram`), so this
// script is the whole Ethernet segment: every datagram it sends is one frame
// the guest's driver receives, and every frame the guest sends arrives here.
// Nothing leaves 127.0.0.1. The script answers the guest's ARP for 10.0.2.2,
// and while the kernel self-test `net-listen` polls the interface (listening
// on TCP 7781) it sends:
//   1. ICMP echo requests (the guest must answer: alive before the corpus);
//   2. a corpus of malformed Ethernet/ARP/IPv4/ICMP/UDP/TCP frames;
//   3. oversized frames (9000 and 60000 bytes): QEMU's RTL8139 writes a frame
//      of any size into an empty receive ring, linearly past its end;
//   4. echo requests again (alive after);
//   5. a SYN it never completes, then after 5 s a SYN from another port: the
//      listener must have returned to LISTEN and answer the second SYN.
//
//   node scripts/verify_net_k2.mjs
import dgram from "node:dgram";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell_k2.mjs";
import { freeTcpPort } from "./lib/free_port.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const field = (text, name) => (text.match(new RegExp(`\\b${name}=([^\\s]+)`)) || [])[1];

const GUEST_MAC = Buffer.from([0x52, 0x54, 0x00, 0x12, 0x34, 0x56]);
const PEER_MAC = Buffer.from([0x52, 0x54, 0x00, 0xaa, 0xbb, 0xcc]);
const GUEST_IP = Buffer.from([10, 0, 2, 15]);
const PEER_IP = Buffer.from([10, 0, 2, 2]);
const LISTEN_PORT = 7781;

// ---- frame building ---------------------------------------------------------
function csum(buf) {
  let sum = 0;
  for (let i = 0; i + 1 < buf.length; i += 2) sum += buf.readUInt16BE(i);
  if (buf.length % 2) sum += buf[buf.length - 1] << 8;
  while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
  return (~sum) & 0xffff;
}
const eth = (type, payload, dst = GUEST_MAC) => {
  const h = Buffer.alloc(14);
  dst.copy(h, 0); PEER_MAC.copy(h, 6); h.writeUInt16BE(type, 12);
  return Buffer.concat([h, payload]);
};
function ipv4(proto, payload, { ihl = 5, totalLength, flagsFrag = 0, badChecksum = false, src = PEER_IP } = {}) {
  const h = Buffer.alloc(ihl * 4 >= 20 ? ihl * 4 : 20);
  h[0] = 0x40 | (ihl & 0xf); h[1] = 0;
  h.writeUInt16BE(totalLength ?? h.length + payload.length, 2);
  h.writeUInt16BE(0x1234, 4); h.writeUInt16BE(flagsFrag, 6);
  h[8] = 64; h[9] = proto;
  src.copy(h, 12); GUEST_IP.copy(h, 16);
  h.writeUInt16BE(0, 10);
  const c = csum(h.subarray(0, Math.max(20, Math.min(h.length, (ihl & 0xf) * 4))));
  h.writeUInt16BE(badChecksum ? c ^ 0xffff : c, 10);
  return Buffer.concat([h, payload]);
}
function icmpEcho(id, seq, data = Buffer.from("fi1-k2-ping")) {
  const b = Buffer.alloc(8 + data.length);
  b[0] = 8; b.writeUInt16BE(id, 4); b.writeUInt16BE(seq, 6); data.copy(b, 8);
  b.writeUInt16BE(csum(b), 2);
  return b;
}
function tcp(srcPort, dstPort, flags, { seq = 1000, ack = 0, dataOffset = 5, options = Buffer.alloc(0), payload = Buffer.alloc(0), window = 8192 } = {}) {
  const hl = 20 + options.length;
  const b = Buffer.alloc(hl + payload.length);
  b.writeUInt16BE(srcPort, 0); b.writeUInt16BE(dstPort, 2);
  b.writeUInt32BE(seq >>> 0, 4); b.writeUInt32BE(ack >>> 0, 8);
  b[12] = (dataOffset & 0xf) << 4; b[13] = flags; b.writeUInt16BE(window, 14);
  options.copy(b, 20); payload.copy(b, hl);
  const pseudo = Buffer.alloc(12);
  PEER_IP.copy(pseudo, 0); GUEST_IP.copy(pseudo, 4); pseudo[9] = 6; pseudo.writeUInt16BE(b.length, 10);
  b.writeUInt16BE(csum(Buffer.concat([pseudo, b])), 16);
  return b;
}
function udp(srcPort, dstPort, payload, lengthField) {
  const b = Buffer.alloc(8 + payload.length);
  b.writeUInt16BE(srcPort, 0); b.writeUInt16BE(dstPort, 2);
  b.writeUInt16BE(lengthField ?? b.length, 4); payload.copy(b, 8);
  return b;
}
function arp(op, { hlen = 6, plen = 4, targetMac = GUEST_MAC, targetIp = GUEST_IP } = {}) {
  const b = Buffer.alloc(28);
  b.writeUInt16BE(1, 0); b.writeUInt16BE(0x0800, 2); b[4] = hlen; b[5] = plen; b.writeUInt16BE(op, 6);
  PEER_MAC.copy(b, 8); PEER_IP.copy(b, 14); targetMac.copy(b, 18); targetIp.copy(b, 24);
  return b;
}
const SYN = 0x02, RST = 0x04, ACK = 0x10;

// ---- the Ethernet segment ---------------------------------------------------
const hostPort = await freeTcpPort();
const qemuPort = await freeTcpPort();
const sock = dgram.createSocket("udp4");
await new Promise((resolve) => sock.bind(hostPort, "127.0.0.1", resolve));
let qemuAddr = null;
const seen = { echoReplies: new Set(), synAcks: [], rsts: [], arps: 0, frames: 0 };
sock.on("message", (msg, rinfo) => {
  qemuAddr = rinfo;
  seen.frames++;
  if (msg.length < 14) return;
  const type = msg.readUInt16BE(12);
  if (type === 0x0806 && msg.length >= 42 && msg.readUInt16BE(20) === 1) {
    seen.arps++;
    const reply = Buffer.alloc(28);
    reply.writeUInt16BE(1, 0); reply.writeUInt16BE(0x0800, 2); reply[4] = 6; reply[5] = 4; reply.writeUInt16BE(2, 6);
    PEER_MAC.copy(reply, 8); msg.copy(reply, 14, 38, 42); msg.copy(reply, 18, 22, 28); msg.copy(reply, 24, 28, 32);
    send(eth(0x0806, reply, msg.subarray(6, 12)));
    return;
  }
  if (type !== 0x0800) return;
  const ip = msg.subarray(14);
  const ihl = (ip[0] & 0xf) * 4;
  const proto = ip[9];
  const l4 = ip.subarray(ihl);
  if (proto === 1 && l4[0] === 0) seen.echoReplies.add(l4.readUInt16BE(6));
  if (proto === 6 && l4.readUInt16BE(0) === LISTEN_PORT) {
    const flags = l4[13];
    const dst = l4.readUInt16BE(2);
    if ((flags & (SYN | ACK)) === (SYN | ACK)) seen.synAcks.push(dst);
    if (flags & RST) seen.rsts.push(dst);
  }
});
function send(frame) {
  sock.send(frame, qemuPort, "127.0.0.1");
}
async function pingUntilReply(firstSeq, tries, waitMs = 400) {
  for (let i = 0; i < tries; i++) {
    const seq = firstSeq + i;
    send(eth(0x0800, ipv4(1, icmpEcho(0x4b32, seq))));
    await sleep(waitMs);
    if ([...seen.echoReplies].some((s) => s >= firstSeq && s < firstSeq + tries)) return true;
  }
  return false;
}

const netArgs = [
  "-netdev", `dgram,id=net0,local.type=inet,local.host=127.0.0.1,local.port=${qemuPort},remote.type=inet,remote.host=127.0.0.1,remote.port=${hostPort}`,
  "-device", "rtl8139,netdev=net0",
];

let shell;
try {
  shell = await bootShell(repo, "net-k2-serial.log", { netArgs });
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);
  const from = shell.serial().length;
  await shell.type("test-syscall net-listen");
  await shell.key("ret");
  await shell.waitFor("selftest net-listen: listening port=7781", 30, from);

  // 1. alive before
  check("the guest answers ICMP echo before the corpus", await pingUntilReply(1, 8), `arp_requests=${seen.arps}`);

  // 2. malformed corpus
  const corpus = [
    ["runt Ethernet frame", Buffer.alloc(10, 0xff)],
    ["Ethernet header only", eth(0x0800, Buffer.alloc(0))],
    ["ARP with hlen 255", eth(0x0806, arp(1, { hlen: 255 }))],
    ["ARP truncated", eth(0x0806, arp(1).subarray(0, 9))],
    ["IPv4 IHL 2", eth(0x0800, ipv4(1, icmpEcho(1, 900), { ihl: 2 }))],
    ["IPv4 IHL 15 in a short frame", eth(0x0800, ipv4(1, Buffer.alloc(4), { ihl: 15 }).subarray(0, 30))],
    ["IPv4 total length beyond the frame", eth(0x0800, ipv4(1, icmpEcho(1, 901), { totalLength: 1400 }))],
    ["IPv4 total length below the header", eth(0x0800, ipv4(1, icmpEcho(1, 902), { totalLength: 8 }))],
    ["IPv4 bad header checksum", eth(0x0800, ipv4(1, icmpEcho(1, 903), { badChecksum: true }))],
    ["IPv4 first fragment (MF)", eth(0x0800, ipv4(1, icmpEcho(1, 904), { flagsFrag: 0x2000 }))],
    ["IPv4 fragment at offset 8184", eth(0x0800, ipv4(17, udp(1, 2, Buffer.alloc(16)), { flagsFrag: 0x1fff }))],
    ["IPv4 version 6 nibble", eth(0x0800, Buffer.concat([Buffer.from([0x65]), ipv4(1, icmpEcho(1, 905)).subarray(1)]))],
    ["IPv4 broadcast source", eth(0x0800, ipv4(1, icmpEcho(1, 906), { src: Buffer.from([255, 255, 255, 255]) }))],
    ["ICMP truncated to 3 bytes", eth(0x0800, ipv4(1, Buffer.from([8, 0, 0])))],
    ["UDP length 65535", eth(0x0800, ipv4(17, udp(1000, 53, Buffer.alloc(8), 65535)))],
    ["UDP length 3", eth(0x0800, ipv4(17, udp(1000, 53, Buffer.alloc(8), 3)))],
    ["TCP data offset 15 in a short segment", eth(0x0800, ipv4(6, tcp(40100, LISTEN_PORT, SYN, { dataOffset: 15 })))],
    ["TCP data offset 2", eth(0x0800, ipv4(6, tcp(40101, LISTEN_PORT, SYN, { dataOffset: 2 })))],
    ["TCP MSS option length 0", eth(0x0800, ipv4(6, tcp(40102, 9, SYN, { dataOffset: 6, options: Buffer.from([2, 0, 0, 0]) })))],
    ["TCP option length 40 past the header", eth(0x0800, ipv4(6, tcp(40103, 9, SYN, { dataOffset: 6, options: Buffer.from([3, 40, 1, 0]) })))],
    ["TCP window scale 255", eth(0x0800, ipv4(6, tcp(40104, 9, SYN, { dataOffset: 6, options: Buffer.from([3, 3, 255, 0]) })))],
    ["TCP SYN+FIN+RST+URG to the listener", eth(0x0800, ipv4(6, tcp(40105, 9, 0x2f)))],
    ["TCP ACK with no connection, seq 0xffffffff", eth(0x0800, ipv4(6, tcp(40106, 9, ACK, { seq: 0xffffffff, ack: 0xffffffff })))],
  ];
  for (const [, frame] of corpus) { send(frame); await sleep(30); }
  check(`a corpus of ${corpus.length} malformed frames was sent`, true);

  // 3. oversized frames
  const big = (n) => eth(0x0800, ipv4(17, udp(1000, 9, Buffer.alloc(n - 14 - 20 - 8, 0x41)), { totalLength: 1500 }));
  for (const n of [9000, 60000, 1600, 60000]) {
    send(eth(0x0800, ipv4(1, icmpEcho(0x4b32, 5000 + n % 97)))); // small frame first, to move the ring
    await sleep(40);
    send(big(n));
    await sleep(60);
  }

  // 4. alive after
  check("the guest still answers ICMP echo after the corpus and oversized frames", await pingUntilReply(100, 10));

  // 5. half-open handshake
  seen.synAcks.length = 0; seen.rsts.length = 0;
  send(eth(0x0800, ipv4(6, tcp(40001, LISTEN_PORT, SYN, { seq: 11111 }))));
  await sleep(1500);
  check("the listener answers a SYN", seen.synAcks.includes(40001), `syn_acks=${JSON.stringify(seen.synAcks)}`);
  await sleep(4500);
  send(eth(0x0800, ipv4(6, tcp(40002, LISTEN_PORT, SYN, { seq: 22222 }))));
  await sleep(2000);
  check("after a handshake left half-open for 5 s, the listener accepts a new client",
    seen.synAcks.includes(40002), `syn_acks=${JSON.stringify(seen.synAcks)} rsts=${JSON.stringify(seen.rsts)}`);
  // Do not complete it; reset it from the client side.
  send(eth(0x0800, ipv4(6, tcp(40002, LISTEN_PORT, RST, { seq: 22223 }))));

  const out = await shell.waitFor(/selftest net-listen: half_open_resets=.*\n/, 40, from);
  const summary = (out.match(/selftest net-listen: half_open_resets=.*/) || [""])[0];
  const maxLen = Number(field(summary, "rx_max_delivered_len"));
  check("no frame longer than 1518 bytes reached the network stack", Number.isFinite(maxLen) && maxLen <= 1518, summary);
  check("the driver dropped the oversized frames", Number(field(summary, "rx_dropped_oversize")) >= 1);
  check("the half-open listener was reset by the kernel", Number(field(summary, "half_open_resets")) >= 1);
  await shell.waitFor(/half_open_resets=[^\n]*\n[\s\S]*FerrumOS:~\$/, 30, from);
  const echo = await shell.command("echo k2-alive");
  check("the shell still runs commands afterwards", /k2-alive/.test(echo));
  check("no kernel panic or fault", !/panicked at|PAGE FAULT|Page Fault|General Protection|DOUBLE FAULT|EXCEPTION/.test(shell.serial()));
  console.log(`INFO\tframes_from_guest=${seen.frames} arp_requests=${seen.arps} echo_replies=${seen.echoReplies.size}`);
} catch (error) {
  check("verification", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
  sock.close();
}
report("Network receive-path verification (round 2)", results);
