import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const fixturesDir = path.resolve(__dirname, '../userland/init/fixtures');
if (!fs.existsSync(fixturesDir)) {
    fs.mkdirSync(fixturesDir, { recursive: true });
}

const modelPath = path.join(fixturesDir, 'stories15M-q8.bin');
const tokenizerPath = path.join(fixturesDir, 'tokenizer.bin');

// Config parameters
const dim = 256;
const hidden_dim = 256;
const n_layers = 1;
const n_heads = 2;
const n_kv_heads = 2;
const vocab_size = 256;
const seq_len = 32;
const shared_classifier = 0; // Separate classifier to allow exact t+1 prediction
const group_size = 32;

console.log("Generating mock llama2.c model header...");

// Header is 256 bytes
const header = Buffer.alloc(256);
header.writeUInt32LE(0x616b3432, 0); // magic: "ak42"
header.writeInt32LE(2, 4);           // version: 2
header.writeInt32LE(dim, 8);
header.writeInt32LE(hidden_dim, 12);
header.writeInt32LE(n_layers, 16);
header.writeInt32LE(n_heads, 20);
header.writeInt32LE(n_kv_heads, 24);
header.writeInt32LE(vocab_size, 28);
header.writeInt32LE(seq_len, 32);
header.writeUInt8(shared_classifier, 36);
header.writeInt32LE(group_size, 37); // offset 37, 38, 39, 40

const weightsBuffers = [];

// Helper to write a float array
function writeFloats(arr) {
    const buf = Buffer.alloc(arr.length * 4);
    for (let i = 0; i < arr.length; i++) {
        buf.writeFloatLE(arr[i], i * 4);
    }
    weightsBuffers.push(buf);
}

// Helper to write a quantized tensor: values (int8) then scales (float)
function writeQuantizedTensor(values, scales) {
    const vBuf = Buffer.alloc(values.length);
    for (let i = 0; i < values.length; i++) {
        vBuf.writeInt8(values[i], i);
    }
    weightsBuffers.push(vBuf);
    writeFloats(scales);
}

// 1. rms_att_weight: n_layers * dim = 256 floats
writeFloats(new Array(n_layers * dim).fill(1.0));

// 2. rms_ffn_weight: n_layers * dim = 256 floats
writeFloats(new Array(n_layers * dim).fill(1.0));

// 3. rms_final_weight: dim = 256 floats
writeFloats(new Array(dim).fill(1.0));

// 4. q_tokens: vocab_size * dim = 256 * 256 elements
// For token t, set embedding element t to 127, others 0.
const q_tokens_vals = new Array(vocab_size * dim).fill(0);
const q_tokens_scales = new Array((vocab_size * dim) / group_size).fill(1.0);
for (let t = 0; t < vocab_size; t++) {
    q_tokens_vals[t * dim + t] = 127;
}
writeQuantizedTensor(q_tokens_vals, q_tokens_scales);

// 5. wq: n_layers * dim * dim = 1 * 256 * 256 elements
// Let's set all projection weights to 0 so they act as zero-deltas
writeQuantizedTensor(new Array(dim * dim).fill(0), new Array((dim * dim) / group_size).fill(1.0));

// 6. wk: n_layers * dim * dim = 256 * 256 elements
writeQuantizedTensor(new Array(dim * dim).fill(0), new Array((dim * dim) / group_size).fill(1.0));

// 7. wv: n_layers * dim * dim = 256 * 256 elements
writeQuantizedTensor(new Array(dim * dim).fill(0), new Array((dim * dim) / group_size).fill(1.0));

// 8. wo: n_layers * dim * dim = 256 * 256 elements
writeQuantizedTensor(new Array(dim * dim).fill(0), new Array((dim * dim) / group_size).fill(1.0));

// 9. w1: n_layers * dim * hidden_dim = 256 * 256 elements
writeQuantizedTensor(new Array(dim * hidden_dim).fill(0), new Array((dim * hidden_dim) / group_size).fill(1.0));

// 10. w2: n_layers * hidden_dim * dim = 256 * 256 elements
writeQuantizedTensor(new Array(hidden_dim * dim).fill(0), new Array((hidden_dim * dim) / group_size).fill(1.0));

// 11. w3: n_layers * dim * hidden_dim = 256 * 256 elements
writeQuantizedTensor(new Array(dim * hidden_dim).fill(0), new Array((dim * hidden_dim) / group_size).fill(1.0));

// 12. wcls: vocab_size * dim = 256 * 256 elements
// For token i, set element (i - 1 + 256) % 256 to 127
const wcls_vals = new Array(vocab_size * dim).fill(0);
const wcls_scales = new Array((vocab_size * dim) / group_size).fill(1.0);
for (let i = 0; i < vocab_size; i++) {
    const targetIdx = (i - 1 + 256) % 256;
    wcls_vals[i * dim + targetIdx] = 127;
}
writeQuantizedTensor(wcls_vals, wcls_scales);

// Concatenate everything and write
const modelBuffer = Buffer.concat([header, ...weightsBuffers]);
fs.writeFileSync(modelPath, modelBuffer);
console.log(`Generated mock model at ${modelPath} (size: ${modelBuffer.length} bytes)`);

// Generate tokenizer.bin
console.log("Generating mock tokenizer...");
const tokBuffers = [];

// max_token_length: i32 (4 bytes)
const tokHeader = Buffer.alloc(4);
tokHeader.writeInt32LE(1, 0);
tokBuffers.push(tokHeader);

for (let i = 0; i < vocab_size; i++) {
    // score: float (4 bytes)
    const scoreBuf = Buffer.alloc(4);
    scoreBuf.writeFloatLE(0.0, 0);
    tokBuffers.push(scoreBuf);

    // len: i32 (4 bytes)
    const lenBuf = Buffer.alloc(4);
    lenBuf.writeInt32LE(1, 0);
    tokBuffers.push(lenBuf);

    // bytes: 1 byte
    const byteBuf = Buffer.from([i]);
    tokBuffers.push(byteBuf);
}

const tokenizerBuffer = Buffer.concat(tokBuffers);
fs.writeFileSync(tokenizerPath, tokenizerBuffer);
console.log(`Generated mock tokenizer at ${tokenizerPath} (size: ${tokenizerBuffer.length} bytes)`);
