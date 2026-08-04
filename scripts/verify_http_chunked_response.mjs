#!/usr/bin/env node
// A real ring-3 provider round trip whose mock HTTP/1.1 server deliberately
// uses Transfer-Encoding: chunked. This framing is common in hosted APIs and
// previously leaked chunk-size lines into the JSON parser.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const corpus = path.join(repo, "target", "http-chunked-corpus.jsonl");
const dataset = path.join(repo, "target", "http-chunked-dataset.jsonl");
const traces = path.join(repo, "target", "http-chunked-traces.jsonl");
fs.writeFileSync(corpus, `${JSON.stringify({
  id: "http-chunked",
  prompt: "Yield the CPU after decoding a chunked provider response.",
  expected_tool: "yield_cpu",
  max_steps: 1,
  responses: [{ tool: "yield_cpu", args: {} }],
})}\n`);

const result = spawnSync(process.execPath, [
  path.join(repo, "scripts", "collect_world_model_hybrid.mjs"),
  "--corpus", corpus,
  "--out", dataset,
  "--traces", traces,
  "--ram", "512",
  "--max-scenarios", "1",
  "--scenarios-per-boot", "1",
  "--accel", "auto",
  "--chunked-responses",
], { cwd: repo, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
assert.equal(result.status, 0, "chunked-response collection must succeed");

const rows = fs.readFileSync(dataset, "utf8").split(/\r?\n/).filter(Boolean).map(JSON.parse);
assert.equal(rows.length, 1);
assert.equal(rows[0].actual_tool, "yield_cpu");
assert.equal(rows[0].executed, true);
const traceText = fs.readFileSync(traces, "utf8");
assert.doesNotMatch(traceText, /LLM query failed|parse|malformed|"failed":true/i);

console.log("PASS\tchunked provider JSON is decoded before tool parsing");
console.log("PASS\tdecoded tool executes and emits one transition");
console.log("2/2 checks passed");
