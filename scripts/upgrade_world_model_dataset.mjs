// Upgrades the known 9,700-row wide-bucket synthetic corpus described in
// model.md to the hybrid schema without fabricating any state targets. The
// before/after embeddings stay byte-for-byte identical; only the deterministic
// ToolCall arguments originally used by synthetic_action(i) are reconstructed
// so their canonical feature vector can be attached. Every reconstructed tool
// id is checked against the recorded id and the script fails closed on drift.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}
const input = path.resolve(arg("--input", path.join(repo, "target", "world_model_dataset.jsonl")));
const output = path.resolve(arg("--out", path.join(repo, "target", "world_model_dataset_hybrid.jsonl")));
const appendFiles = [];
for (let i = 0; i < process.argv.length; i++) {
  if (process.argv[i] === "--append" && process.argv[i + 1]) appendFiles.push(path.resolve(process.argv[++i]));
}
const ramMb = Number(arg("--ram", "512"));

const toolIds = {
  read_file: 7, net_connect: 13, write_file: 17, create_directory: 18,
  save_memory: 19, service_start: 23, service_stop: 24, exec_process: 25,
  delete_file: 26, play_audio: 34, keyboard_type: 36, mouse_click: 37,
  mouse_move: 38,
};

function syntheticAction(i) {
  if (i > 0 && i % 47 === 0) {
    return { tool: "delete_file", args: { path: "/disk/heliox/config.json" } };
  }
  const variant = Math.floor(i / 13);
  switch (i % 13) {
    case 0: {
      const contentLength = 16 + (variant % 16) * 256;
      let content;
      if (variant % 2 === 0) {
        content = "x".repeat(contentLength);
      } else {
        content = `sample data ${i} `;
        while (content.length < contentLength) content += "more data ";
      }
      return { tool: "write_file", args: { path: `/disk/wm_data_${i}.txt`, content } };
    }
    case 1: return { tool: "create_directory", args: { path: `/disk/wm_dir_${i % 16}` } };
    case 2: return { tool: "delete_file", args: { path: `/disk/wm_data_${Math.max(0, i - 2)}.txt` } };
    case 3: return {
      tool: "exec_process",
      args: { path: variant % 3 === 2 ? `/disk/wm_missing_${i % 16}` : "/disk/pkgs-available/notes/bin" },
    };
    case 4: return { tool: "service_start", args: { service_id: (variant % 8) + 1 } };
    case 5: return { tool: "service_stop", args: { service_id: (variant % 8) + 1 } };
    case 6: return {
      tool: "net_connect",
      args: { host: "10.0.2.2", port: [9, 25, 53, 80, 143, 443, 3000, 8785][variant % 8] },
    };
    case 7: return { tool: "save_memory", args: {} };
    case 8: return { tool: "play_audio", args: {} };
    case 9: return {
      tool: "keyboard_type",
      args: { text: ["x", "hello", "The quick brown fox", "1234567890", "a", "testing 123", "FerrumOS", "!@#$%^&*()"][variant % 8] },
    };
    case 10: return { tool: "mouse_click", args: { button: variant % 3 } };
    case 11: {
      const [dx, dy] = [[1, 1], [-5, 3], [10, -10], [-1, -1], [50, 0], [0, -50], [-20, 20], [100, 100]][variant % 8];
      return { tool: "mouse_move", args: { dx, dy } };
    }
    default: return {
      tool: "read_file",
      args: { path: variant % 3 === 2 ? "/disk/wm_missing_read.txt" : "/disk/heliox/config.json" },
    };
  }
}

function ratio(value, max) { return Math.max(0, Math.min(1, value / max)); }
function hash(value) {
  let result = 2166136261;
  for (const byte of Buffer.from(value)) result = Math.imul(result ^ byte, 16777619) >>> 0;
  return result / 0xffffffff;
}
function signed(value) { return (Math.max(-10000, Math.min(10000, value)) / 10000 + 1) * 0.5; }

function features(action) {
  const entries = Object.entries(action.args);
  const out = new Array(16).fill(0);
  out[0] = ratio(entries.length, 8);
  let totalStringBytes = 0;
  let stringCount = 0;
  const numbers = [];
  for (const [key, value] of entries) {
    if (typeof value === "string") {
      const length = Buffer.byteLength(value);
      stringCount++;
      totalStringBytes += length;
      if (key === "content") out[2] = ratio(length, 4096);
      else if (key === "path") {
        out[3] = ratio(length, 256);
        out[4] = hash(value);
        out[10] = value.includes("/disk/heliox/config.json") ? 1 : 0;
        out[11] = value.startsWith("/disk/heliox") ? 1 : 0;
        out[12] = value.startsWith("/disk/") ? 1 : 0;
        const lower = value.toLowerCase();
        out[13] = lower.includes("missing") || lower.includes("nonexistent") ? 1 : 0;
      } else if (["text", "query", "goal"].includes(key)) out[5] = ratio(length, 1024);
      else if (key === "host") out[6] = hash(value);
    } else if (typeof value === "number") {
      numbers.push(value);
      if (key === "port") out[7] = ratio(value, 65535);
    }
  }
  out[1] = ratio(totalStringBytes, 4096);
  out[8] = signed(numbers[0] || 0);
  out[9] = signed(numbers[1] || 0);
  out[14] = ratio(stringCount, 8);
  out[15] = ratio(numbers.length, 8);
  return out;
}

const rows = fs.readFileSync(input, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
const upgraded = rows.map((row, index) => {
  const action = syntheticAction(index);
  const expected = toolIds[action.tool];
  if (row.action !== expected) {
    throw new Error(`generator drift at row ${index}: recorded action=${row.action}, reconstructed ${action.tool}=${expected}`);
  }
  return {
    source: "synthetic-recovered-arguments",
    episode_id: `synthetic-${ramMb}m-${Math.floor(index / 13)}`,
    step: index % 13,
    ram_mb: ramMb,
    schema_version: 2,
    ...row,
    executed: !(action.tool === "delete_file"
      && action.args.path === "/disk/heliox/config.json"),
    action_features: features(action),
  };
});

for (const file of appendFiles) {
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    if (line.trim()) upgraded.push(JSON.parse(line));
  }
}

fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, `${upgraded.map((row) => JSON.stringify(row)).join("\n")}\n`);
console.log(`wrote ${upgraded.length} hybrid-schema transitions to ${output}`);
