#!/usr/bin/env node
import assert from "node:assert/strict";
import http from "node:http";
import { parseProviderResponse, requestBatch, validateArguments, validateBatch } from "./prefetch_world_model_responses.mjs";

const tasks = [
  { id: "one", step: 0, goal: "read config", expected_tool: "read_file" },
  { id: "two", step: 0, goal: "move pointer", expected_tool: "mouse_move" },
];
const modelOutput = {
  responses: [
    { id: "one", step: 0, tool: "read_file", args: { path: "/disk/heliox/config.json" } },
    { id: "two", step: 0, tool: "mouse_move", args: { dx: 3, dy: -2 } },
  ],
};
const parsed = parseProviderResponse("ollama", { message: { content: JSON.stringify(modelOutput) } });
assert.deepEqual(validateBatch(tasks, parsed), modelOutput.responses.map(({ tool, args }) => ({ tool, args })));
assert.throws(
  () => validateBatch(tasks, [{ ...modelOutput.responses[0], tool: "delete_file" }, modelOutput.responses[1]]),
  /expected read_file/,
);
assert.deepEqual(
  validateBatch(
    [{ id: "later", step: 2, goal: "read", expected_tool: "read_file" }],
    [{ id: "later", step: 0, tool: "read_file", args: { path: "/disk/a" } }],
  ),
  [{ tool: "read_file", args: { path: "/disk/a" } }],
);
assert.throws(() => validateArguments("write_file", { path: "/disk/a" }), /missing required field content/);
assert.throws(
  () => validateArguments("local_inference", { prompt: "test", max_tokens: 128 }),
  /integer from 1 to 64/,
);

const server = http.createServer((request, response) => {
  let body = "";
  request.on("data", (chunk) => (body += chunk));
  request.on("end", () => {
    const payload = JSON.parse(body);
    assert.equal(payload.stream, false);
    assert.equal(payload.think, false);
    const transport = JSON.stringify({ message: { content: JSON.stringify(modelOutput) } });
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(transport);
  });
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
try {
  const result = await requestBatch(tasks, {
    provider: "ollama",
    url: `http://127.0.0.1:${server.address().port}/api/chat`,
    model: "mock-local",
    apiKey: "",
    temperature: 0,
    seed: 42,
    timeoutMs: 5_000,
    allowToolMismatch: false,
  });
  assert.equal(result.calls.length, 2);
  assert.equal(result.calls[1].tool, "mouse_move");
} finally {
  server.close();
}

console.log("PASS\tprefetch parses strict batched JSON responses");
console.log("PASS\tprefetch rejects target-tool mismatches");
console.log("PASS\tprefetch rejects missing, empty, or out-of-range arguments");
console.log("PASS\tsingle-item retries tolerate harmless local-model step resets");
console.log("PASS\tprefetch works through an Ollama-compatible HTTP endpoint");
console.log("5/5 checks passed");
