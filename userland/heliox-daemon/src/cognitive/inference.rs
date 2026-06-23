// ============================================================================
// Heliox-OS — Toy SLM Local Inference Engine
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::format;

const SYS_READ_FILE: u64 = 15;
const SYS_WRITE: u64 = 34;
const FD_CONSOLE: u64 = 1;
const SYS_YIELD: u64 = 0;

#[derive(Clone, Copy, Debug)]
pub struct Config {
    pub dim: usize,
    pub hidden_dim: usize,
    pub n_layers: usize,
    pub n_heads: usize,
    pub n_kv_heads: usize,
    pub vocab_size: usize,
    pub seq_len: usize,
}

pub struct QuantizedTensor {
    pub q: *const i8,
    pub s: *const f32,
}

pub struct TransformerWeights {
    pub rms_att_weight: *const f32,
    pub rms_ffn_weight: *const f32,
    pub rms_final_weight: *const f32,
    pub q_tokens: QuantizedTensor,
    pub token_embedding_table: Vec<f32>,
    pub wq: Vec<QuantizedTensor>,
    pub wk: Vec<QuantizedTensor>,
    pub wv: Vec<QuantizedTensor>,
    pub wo: Vec<QuantizedTensor>,
    pub w1: Vec<QuantizedTensor>,
    pub w2: Vec<QuantizedTensor>,
    pub w3: Vec<QuantizedTensor>,
    pub wcls: QuantizedTensor,
}

pub struct QuantizedBuffer {
    pub q: Vec<i8>,
    pub s: Vec<f32>,
}

impl QuantizedBuffer {
    pub fn new(size: usize, gs: usize) -> Self {
        Self {
            q: alloc::vec![0i8; size],
            s: alloc::vec![0.0f32; size / gs],
        }
    }

    pub fn as_tensor(&self) -> QuantizedTensor {
        QuantizedTensor {
            q: self.q.as_ptr(),
            s: self.s.as_ptr(),
        }
    }
}

pub struct RunState {
    pub x: Vec<f32>,
    pub xb: Vec<f32>,
    pub xb2: Vec<f32>,
    pub hb: Vec<f32>,
    pub hb2: Vec<f32>,
    pub xq: QuantizedBuffer,
    pub hq: QuantizedBuffer,
    pub q: Vec<f32>,
    pub k: Vec<f32>,
    pub v: Vec<f32>,
    pub att: Vec<f32>,
    pub logits: Vec<f32>,
    pub key_cache: Vec<f32>,
    pub value_cache: Vec<f32>,
}

impl RunState {
    pub fn new(p: &Config, gs: usize) -> Self {
        let kv_dim = (p.dim * p.n_kv_heads) / p.n_heads;
        Self {
            x: alloc::vec![0.0f32; p.dim],
            xb: alloc::vec![0.0f32; p.dim],
            xb2: alloc::vec![0.0f32; p.dim],
            hb: alloc::vec![0.0f32; p.hidden_dim],
            hb2: alloc::vec![0.0f32; p.hidden_dim],
            xq: QuantizedBuffer::new(p.dim, gs),
            hq: QuantizedBuffer::new(p.hidden_dim, gs),
            q: alloc::vec![0.0f32; p.dim],
            k: alloc::vec![0.0f32; kv_dim],
            v: alloc::vec![0.0f32; kv_dim],
            att: alloc::vec![0.0f32; p.n_heads * p.seq_len],
            logits: alloc::vec![0.0f32; p.vocab_size],
            key_cache: alloc::vec![0.0f32; p.n_layers * p.seq_len * kv_dim],
            value_cache: alloc::vec![0.0f32; p.n_layers * p.seq_len * kv_dim],
        }
    }
}

pub struct Tokenizer {
    pub vocab: Vec<Vec<u8>>,
    pub vocab_scores: Vec<f32>,
    pub max_token_length: usize,
    pub vocab_size: usize,
    pub sorted_vocab: Vec<(Vec<u8>, usize)>,
}

fn read_file_to_vec(path: &str) -> Result<Vec<u8>, &'static str> {
    let mut buf = alloc::vec![0u8; 4 * 1024 * 1024];
    let bytes_read = unsafe {
        crate::syscall4(
            SYS_READ_FILE,
            path.as_ptr() as u64,
            path.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    let msg = format!("[daemon-read] read {} res: {}\n", path, bytes_read as i64);
    unsafe {
        crate::syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
    }
    if (bytes_read as i64) < 0 {
        Err("Failed to read file")
    } else {
        buf.truncate(bytes_read as usize);
        Ok(buf)
    }
}

impl Tokenizer {
    pub fn load(path: &str, vocab_size: usize) -> Result<Self, &'static str> {
        let bytes = read_file_to_vec(path)?;
        if bytes.len() < 4 {
            return Err("Tokenizer file is too small");
        }
        let mut offset = 0;
        let max_token_length = i32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]) as usize;
        offset += 4;

        let mut vocab = Vec::with_capacity(vocab_size);
        let mut vocab_scores = Vec::with_capacity(vocab_size);

        for _ in 0..vocab_size {
            if offset + 8 > bytes.len() {
                return Err("Unexpected EOF in tokenizer file");
            }
            let score = f32::from_le_bytes([
                bytes[offset],
                bytes[offset+1],
                bytes[offset+2],
                bytes[offset+3],
            ]);
            offset += 4;
            let len = i32::from_le_bytes([
                bytes[offset],
                bytes[offset+1],
                bytes[offset+2],
                bytes[offset+3],
            ]) as usize;
            offset += 4;

            if offset + len > bytes.len() {
                return Err("Unexpected EOF in tokenizer file (string bytes)");
            }
            let mut s_bytes = Vec::with_capacity(len);
            s_bytes.extend_from_slice(&bytes[offset..offset+len]);
            offset += len;

            vocab.push(s_bytes);
            vocab_scores.push(score);
        }

        let mut sorted_vocab = Vec::with_capacity(vocab_size);
        for (i, v) in vocab.iter().enumerate() {
            sorted_vocab.push((v.clone(), i));
        }
        sorted_vocab.sort_unstable_by(|a, b| a.0.cmp(&b.0));

        Ok(Self {
            vocab,
            vocab_scores,
            max_token_length,
            vocab_size,
            sorted_vocab,
        })
    }

    fn find_token(&self, bytes: &[u8]) -> Option<usize> {
        match self.sorted_vocab.binary_search_by(|probe| probe.0.as_slice().cmp(bytes)) {
            Ok(idx) => Some(self.sorted_vocab[idx].1),
            Err(_) => None,
        }
    }

    pub fn encode(&self, text: &str, bos: bool, eos: bool) -> Vec<usize> {
        let mut tokens = Vec::new();

        if bos {
            tokens.push(1); // BOS is 1
        }

        if !text.is_empty() {
            if let Some(dummy_idx) = self.find_token(b" ") {
                tokens.push(dummy_idx);
            }
        }

        let mut str_buffer = Vec::new();
        for ch in text.chars() {
            let mut char_buf = [0u8; 4];
            let char_str = ch.encode_utf8(&mut char_buf);
            
            if let Some(id) = self.find_token(char_str.as_bytes()) {
                tokens.push(id);
            } else {
                for &b in char_str.as_bytes() {
                    tokens.push(b as usize + 3);
                }
            }
        }

        loop {
            let mut best_score = -1e10f32;
            let mut best_id = None;
            let mut best_idx = None;

            if tokens.len() < 2 {
                break;
            }

            for i in 0..(tokens.len() - 1) {
                str_buffer.clear();
                str_buffer.extend_from_slice(&self.vocab[tokens[i]]);
                str_buffer.extend_from_slice(&self.vocab[tokens[i+1]]);

                if let Some(id) = self.find_token(&str_buffer) {
                    let score = self.vocab_scores[id];
                    if score > best_score {
                        best_score = score;
                        best_id = Some(id);
                        best_idx = Some(i);
                    }
                }
            }

            let (Some(idx), Some(id)) = (best_idx, best_id) else {
                break;
            };

            tokens[idx] = id;
            tokens.remove(idx + 1);
        }

        if eos {
            tokens.push(2); // EOS is 2
        }

        tokens
    }

    pub fn decode(&self, prev_token: usize, token: usize) -> &[u8] {
        let piece = &self.vocab[token];
        let mut res = piece.as_slice();
        if prev_token == 1 && res.first() == Some(&b' ') {
            res = &res[1..];
        }
        res
    }
}

fn decode_token_bytes(token_bytes: &[u8]) -> Vec<u8> {
    if token_bytes.len() == 6 && token_bytes.starts_with(b"<0x") && token_bytes.ends_with(b">") {
        let h1 = token_bytes[3];
        let h2 = token_bytes[4];
        let parse_hex = |h: u8| match h {
            b'0'..=b'9' => Some(h - b'0'),
            b'a'..=b'f' => Some(h - b'a' + 10),
            b'A'..=b'F' => Some(h - b'A' + 10),
            _ => None,
        };
        if let (Some(v1), Some(v2)) = (parse_hex(h1), parse_hex(h2)) {
            return alloc::vec![(v1 << 4) | v2];
        }
    }
    token_bytes.to_vec()
}

unsafe fn dequantize(qx: &QuantizedTensor, x: &mut [f32], n: usize, gs: usize) {
    for i in 0..n {
        let scale = *qx.s.add(i / gs);
        let q_val = *qx.q.add(i);
        x[i] = (q_val as f32) * scale;
    }
}

fn init_quantized_tensor(ptr: &mut *const u8, size: usize, gs: usize) -> QuantizedTensor {
    let q = *ptr as *const i8;
    *ptr = unsafe { ptr.add(size) };
    let s = *ptr as *const f32;
    *ptr = unsafe { ptr.add((size / gs) * 4) };
    QuantizedTensor { q, s }
}

fn init_quantized_tensors(ptr: &mut *const u8, n: usize, size_each: usize, gs: usize) -> Vec<QuantizedTensor> {
    let mut vec = Vec::with_capacity(n);
    for _ in 0..n {
        vec.push(init_quantized_tensor(ptr, size_each, gs));
    }
    vec
}

fn rmsnorm(o: &mut [f32], x: &[f32], weight: &[f32]) {
    let size = x.len();
    let mut ss = 0.0f32;
    for &val in x {
        ss += val * val;
    }
    ss /= size as f32;
    ss += 1e-5f32;
    ss = 1.0f32 / libm::sqrtf(ss);
    for j in 0..size {
        o[j] = weight[j] * (ss * x[j]);
    }
}

fn softmax(x: &mut [f32]) {
    if x.is_empty() {
        return;
    }
    let mut max_val = x[0];
    for &val in x.iter().skip(1) {
        if val > max_val {
            max_val = val;
        }
    }
    let mut sum = 0.0f32;
    for val in x.iter_mut() {
        *val = libm::expf(*val - max_val);
        sum += *val;
    }
    for val in x.iter_mut() {
        *val /= sum;
    }
}

fn quantize(qx: &mut QuantizedBuffer, x: &[f32], gs: usize) {
    let n = x.len();
    let num_groups = n / gs;
    let q_max = 127.0f32;
    
    for group in 0..num_groups {
        let mut wmax = 0.0f32;
        for i in 0..gs {
            let val = libm::fabsf(x[group * gs + i]);
            if val > wmax {
                wmax = val;
            }
        }
        
        let scale = wmax / q_max;
        qx.s[group] = scale;
        
        for i in 0..gs {
            let val = x[group * gs + i];
            let quant_val = if scale > 0.0 {
                libm::roundf(val / scale)
            } else {
                0.0
            };
            let clamped = if quant_val < -128.0 {
                -128
            } else if quant_val > 127.0 {
                127
            } else {
                quant_val as i8
            };
            qx.q[group * gs + i] = clamped;
        }
    }
}

pub fn detect_sse41() -> bool {
    let ecx: u32;
    unsafe {
        core::arch::asm!(
            "push rbx",
            "mov eax, 1",
            "cpuid",
            "pop rbx",
            out("eax") _,
            out("ecx") ecx,
            out("edx") _,
        );
    }
    // SSE4.1 is bit 19 of ECX
    (ecx & (1 << 19)) != 0
}

#[inline(always)]
unsafe fn dot_product_avx2(mut px: *const i8, mut pw: *const i8, mut gs: usize) -> i32 {
    let mut result: i32 = 0;
    core::arch::asm!(
        "vpxor ymm0, ymm0, ymm0",
        "2:",
        "vmovdqu xmm1, [{px}]",
        "vmovdqu xmm2, [{pw}]",
        "vpmovsxbw ymm1, xmm1",
        "vpmovsxbw ymm2, xmm2",
        "vpmaddwd ymm1, ymm1, ymm2",
        "vpaddd ymm0, ymm0, ymm1",
        "add {px}, 16",
        "add {pw}, 16",
        "sub {gs}, 16",
        "jnz 2b",
        
        "vextracti128 xmm1, ymm0, 1",
        "vpaddd xmm0, xmm0, xmm1",
        "vpshufd xmm1, xmm0, 0x4e",
        "vpaddd xmm0, xmm0, xmm1",
        "vpshufd xmm1, xmm0, 0xb1",
        "vpaddd xmm0, xmm0, xmm1",
        "vmovd {result:e}, xmm0",
        
        px = inout(reg) px => _,
        pw = inout(reg) pw => _,
        gs = inout(reg) gs => _,
        result = out(reg) result,
        out("ymm0") _,
        out("ymm1") _,
        out("ymm2") _,
        options(readonly, nostack)
    );
    result
}

#[inline(always)]
unsafe fn dot_product_sse41(mut px: *const i8, mut pw: *const i8, mut gs: usize) -> i32 {
    let mut result: i32 = 0;
    core::arch::asm!(
        "pxor xmm0, xmm0",
        "2:",
        "pmovsxbw xmm1, [{px}]",
        "pmovsxbw xmm2, [{pw}]",
        "pmaddwd xmm1, xmm2",
        "paddd xmm0, xmm1",
        "add {px}, 8",
        "add {pw}, 8",
        "sub {gs}, 8",
        "jnz 2b",
        
        "pshufd xmm1, xmm0, 0x4e",
        "paddd xmm0, xmm1",
        "pshufd xmm1, xmm0, 0xb1",
        "paddd xmm0, xmm1",
        "movd {result:e}, xmm0",
        
        px = inout(reg) px => _,
        pw = inout(reg) pw => _,
        gs = inout(reg) gs => _,
        result = out(reg) result,
        out("xmm0") _,
        out("xmm1") _,
        out("xmm2") _,
        options(readonly, nostack)
    );
    result
}

fn matmul(xout: &mut [f32], x: &QuantizedTensor, w: &QuantizedTensor, n: usize, d: usize, gs: usize, avx2_supported: bool) {
    if avx2_supported {
        unsafe {
            matmul_avx2(xout, x, w, n, d, gs);
        }
    } else if detect_sse41() {
        unsafe {
            matmul_sse41(xout, x, w, n, d, gs);
        }
    } else {
        matmul_scalar(xout, x, w, n, d, gs);
    }
}

fn matmul_scalar(xout: &mut [f32], x: &QuantizedTensor, w: &QuantizedTensor, n: usize, d: usize, gs: usize) {
    for i in 0..d {
        let mut val = 0.0f32;
        let row_offset = i * n;
        for j in (0..n).step_by(gs) {
            let mut ival = 0i32;
            for k in 0..gs {
                unsafe {
                    ival += (*x.q.add(j + k) as i32) * (*w.q.add(row_offset + j + k) as i32);
                }
            }
            unsafe {
                val += (ival as f32) * (*w.s.add((row_offset + j) / gs)) * (*x.s.add(j / gs));
            }
        }
        xout[i] = val;
    }
}

unsafe fn matmul_avx2(xout: &mut [f32], x: &QuantizedTensor, w: &QuantizedTensor, n: usize, d: usize, gs: usize) {
    for i in 0..d {
        let mut val = 0.0f32;
        let row_offset = i * n;
        
        for j in (0..n).step_by(gs) {
            let px = x.q.add(j);
            let pw = w.q.add(row_offset + j);
            let ival = dot_product_avx2(px, pw, gs);
            val += (ival as f32) * (*w.s.add((row_offset + j) / gs)) * (*x.s.add(j / gs));
        }
        xout[i] = val;
    }
}

unsafe fn matmul_sse41(xout: &mut [f32], x: &QuantizedTensor, w: &QuantizedTensor, n: usize, d: usize, gs: usize) {
    for i in 0..d {
        let mut val = 0.0f32;
        let row_offset = i * n;
        
        for j in (0..n).step_by(gs) {
            let px = x.q.add(j);
            let pw = w.q.add(row_offset + j);
            let ival = dot_product_sse41(px, pw, gs);
            val += (ival as f32) * (*w.s.add((row_offset + j) / gs)) * (*x.s.add(j / gs));
        }
        xout[i] = val;
    }
}

fn forward(w: &TransformerWeights, s: &mut RunState, token: usize, pos: usize, p: &Config, gs: usize, avx2_supported: bool) {
    let dim = p.dim;
    let kv_dim = (p.dim * p.n_kv_heads) / p.n_heads;
    let kv_mul = p.n_heads / p.n_kv_heads;
    let hidden_dim = p.hidden_dim;
    let head_size = dim / p.n_heads;
    let seq_len = p.seq_len;

    // copy token embedding
    let token_offset = token * dim;
    s.x.copy_from_slice(&w.token_embedding_table[token_offset..token_offset + dim]);

    for l in 0..p.n_layers {
        // attention rmsnorm
        unsafe {
            let rms_att_ptr = w.rms_att_weight.add(l * dim);
            let rms_att_slice = core::slice::from_raw_parts(rms_att_ptr, dim);
            rmsnorm(&mut s.xb, &s.x, rms_att_slice);
        }

        // qkv projections
        quantize(&mut s.xq, &s.xb, gs);
        let xq_tensor = s.xq.as_tensor();
        matmul(&mut s.q, &xq_tensor, &w.wq[l], dim, dim, gs, avx2_supported);
        matmul(&mut s.k, &xq_tensor, &w.wk[l], dim, kv_dim, gs, avx2_supported);
        matmul(&mut s.v, &xq_tensor, &w.wv[l], dim, kv_dim, gs, avx2_supported);

        // RoPE encoding
        for i in (0..dim).step_by(2) {
            let head_dim = i % head_size;
            let freq = 1.0f32 / libm::powf(10000.0f32, (head_dim as f32) / (head_size as f32));
            let val = (pos as f32) * freq;
            let fcr = libm::cosf(val);
            let fci = libm::sinf(val);
            
            let rotn = if i < kv_dim { 2 } else { 1 };
            for v_idx in 0..rotn {
                let vec = if v_idx == 0 { &mut s.q } else { &mut s.k };
                let v0 = vec[i];
                let v1 = vec[i + 1];
                vec[i]     = v0 * fcr - v1 * fci;
                vec[i + 1] = v0 * fci + v1 * fcr;
            }
        }

        // save key, value to cache
        let kv_offset = l * seq_len * kv_dim + pos * kv_dim;
        s.key_cache[kv_offset..kv_offset + kv_dim].copy_from_slice(&s.k[..kv_dim]);
        s.value_cache[kv_offset..kv_offset + kv_dim].copy_from_slice(&s.v[..kv_dim]);

        // multi-head attention
        for h in 0..p.n_heads {
            let q_head = &s.q[h * head_size .. (h + 1) * head_size];
            let att_offset = h * seq_len;
            
            for t in 0..=pos {
                let k_cache_offset = l * seq_len * kv_dim + t * kv_dim + (h / kv_mul) * head_size;
                let k_head = &s.key_cache[k_cache_offset .. k_cache_offset + head_size];
                
                let mut score = 0.0f32;
                for i in 0..head_size {
                    score += q_head[i] * k_head[i];
                }
                score /= libm::sqrtf(head_size as f32);
                s.att[att_offset + t] = score;
            }
            
            softmax(&mut s.att[att_offset .. att_offset + pos + 1]);
            
            let xb_head = &mut s.xb[h * head_size .. (h + 1) * head_size];
            xb_head.fill(0.0);
            for t in 0..=pos {
                let v_cache_offset = l * seq_len * kv_dim + t * kv_dim + (h / kv_mul) * head_size;
                let v_head = &s.value_cache[v_cache_offset .. v_cache_offset + head_size];
                let a = s.att[att_offset + t];
                for i in 0..head_size {
                    xb_head[i] += a * v_head[i];
                }
            }
        }

        // final projection
        quantize(&mut s.xq, &s.xb, gs);
        let xq_tensor = s.xq.as_tensor();
        matmul(&mut s.xb2, &xq_tensor, &w.wo[l], dim, dim, gs, avx2_supported);

        // residual connection
        for i in 0..dim {
            s.x[i] += s.xb2[i];
        }

        // FFN rmsnorm
        unsafe {
            let rms_ffn_ptr = w.rms_ffn_weight.add(l * dim);
            let rms_ffn_slice = core::slice::from_raw_parts(rms_ffn_ptr, dim);
            rmsnorm(&mut s.xb, &s.x, rms_ffn_slice);
        }

        // FFN matmuls
        quantize(&mut s.xq, &s.xb, gs);
        let xq_tensor = s.xq.as_tensor();
        matmul(&mut s.hb, &xq_tensor, &w.w1[l], dim, hidden_dim, gs, avx2_supported);
        matmul(&mut s.hb2, &xq_tensor, &w.w3[l], dim, hidden_dim, gs, avx2_supported);

        // SwiGLU non-linearity
        for i in 0..hidden_dim {
            let mut val = s.hb[i];
            val *= 1.0f32 / (1.0f32 + libm::expf(-val));
            val *= s.hb2[i];
            s.hb[i] = val;
        }

        // FFN output projection
        quantize(&mut s.hq, &s.hb, gs);
        let hq_tensor = s.hq.as_tensor();
        matmul(&mut s.xb, &hq_tensor, &w.w2[l], hidden_dim, dim, gs, avx2_supported);

        // residual connection
        for i in 0..dim {
            s.x[i] += s.xb[i];
        }
    }

    // final rmsnorm
    let mut x_final = alloc::vec![0.0f32; dim];
    unsafe {
        let rms_final_slice = core::slice::from_raw_parts(w.rms_final_weight, dim);
        rmsnorm(&mut x_final, &s.x, rms_final_slice);
    }

    // final classification to logits
    quantize(&mut s.xq, &x_final, gs);
    let xq_tensor = s.xq.as_tensor();
    matmul(&mut s.logits, &xq_tensor, &w.wcls, dim, p.vocab_size, gs, avx2_supported);
}

fn sample_argmax(logits: &[f32]) -> usize {
    let mut max_i = 0;
    let mut max_p = logits[0];
    for i in 1..logits.len() {
        if logits[i] > max_p {
            max_i = i;
            max_p = logits[i];
        }
    }
    max_i
}

pub fn run_local_inference(prompt: &str) -> Result<String, &'static str> {
    // 1. Detect if AVX2 is supported
    let avx2_supported = crate::cognitive::inference::detect_avx2();

    // 2. Read the model checkpoint header using SYS_READ_FILE
    let model_path = "/disk/heliox/models/stories15M-q8.bin";
    
    // Read only first 256 bytes for config header
    let mut header_buf = alloc::vec![0u8; 256];
    let bytes_read = unsafe {
        crate::syscall4(
            SYS_READ_FILE,
            model_path.as_ptr() as u64,
            model_path.len() as u64,
            header_buf.as_mut_ptr() as u64,
            header_buf.len() as u64,
        )
    };
    if (bytes_read as i64) < 256 {
        return Err("Failed to read model config header or file too small");
    }

    let magic = u32::from_le_bytes([header_buf[0], header_buf[1], header_buf[2], header_buf[3]]);
    if magic != 0x616b3432 {
        return Err("Invalid model magic number");
    }
    let version = i32::from_le_bytes([header_buf[4], header_buf[5], header_buf[6], header_buf[7]]);
    if version != 2 {
        return Err("Unsupported model version (requires v2)");
    }

    // Config parameters
    let dim = i32::from_le_bytes([header_buf[8], header_buf[9], header_buf[10], header_buf[11]]) as usize;
    let hidden_dim = i32::from_le_bytes([header_buf[12], header_buf[13], header_buf[14], header_buf[15]]) as usize;
    let n_layers = i32::from_le_bytes([header_buf[16], header_buf[17], header_buf[18], header_buf[19]]) as usize;
    let n_heads = i32::from_le_bytes([header_buf[20], header_buf[21], header_buf[22], header_buf[23]]) as usize;
    let n_kv_heads = i32::from_le_bytes([header_buf[24], header_buf[25], header_buf[26], header_buf[27]]) as usize;
    let vocab_size = i32::from_le_bytes([header_buf[28], header_buf[29], header_buf[30], header_buf[31]]) as usize;
    let seq_len = i32::from_le_bytes([header_buf[32], header_buf[33], header_buf[34], header_buf[35]]) as usize;
    let shared_classifier = header_buf[36];
    let group_size = i32::from_le_bytes([header_buf[37], header_buf[38], header_buf[39], header_buf[40]]) as usize;

    let config = Config {
        dim,
        hidden_dim,
        n_layers,
        n_heads,
        n_kv_heads,
        vocab_size,
        seq_len,
    };

    let gs = group_size;

    // Calculate exact weights size to memory-map
    let head_size = dim / n_heads;
    let kv_dim = (dim * n_kv_heads) / n_heads;

    let mut weight_size = 0;
    // float RMSNorms
    weight_size += n_layers * dim * 4; // rms_att_weight
    weight_size += n_layers * dim * 4; // rms_ffn_weight
    weight_size += dim * 4;            // rms_final_weight

    // quantized embedding tensor
    weight_size += vocab_size * dim; // q_tokens quantized
    weight_size += (vocab_size * dim / gs) * 4; // scales

    // wq, wk, wv, wo
    weight_size += n_layers * (dim * (n_heads * head_size) + (dim * (n_heads * head_size) / gs) * 4);
    weight_size += n_layers * (dim * (n_kv_heads * head_size) + (dim * (n_kv_heads * head_size) / gs) * 4);
    weight_size += n_layers * (dim * (n_kv_heads * head_size) + (dim * (n_kv_heads * head_size) / gs) * 4);
    weight_size += n_layers * ((n_heads * head_size) * dim + ((n_heads * head_size) * dim / gs) * 4);

    // w1, w2, w3
    weight_size += n_layers * (dim * hidden_dim + (dim * hidden_dim / gs) * 4);
    weight_size += n_layers * (hidden_dim * dim + (hidden_dim * dim / gs) * 4);
    weight_size += n_layers * (dim * hidden_dim + (dim * hidden_dim / gs) * 4);

    // classifier
    if shared_classifier == 0 {
        weight_size += dim * vocab_size + (dim * vocab_size / gs) * 4;
    }

    let total_file_size = 256 + weight_size;

    // 3. mmap the model file using SYS_MMAP
    const SYS_MMAP: u64 = 41;
    let vaddr = unsafe {
        crate::syscall4(
            SYS_MMAP,
            model_path.as_ptr() as u64,
            model_path.len() as u64,
            total_file_size as u64,
            0,
        )
    };

    if (vaddr as i64) < 0 {
        return Err("Failed to memory-map model weights file");
    }

    let loaded_msg = alloc::format!("[heliox-daemon] loaded model from {}\n", model_path);
    unsafe {
        crate::syscall3(
            SYS_WRITE,
            FD_CONSOLE,
            loaded_msg.as_ptr() as u64,
            loaded_msg.len() as u64,
        );
    }

    // Skip the 256-byte header
    let mut ptr = unsafe { (vaddr as *const u8).add(256) };

    // rmsNorms (read-only floats)
    let rms_att_weight = ptr as *const f32;
    ptr = unsafe { ptr.add(n_layers * dim * 4) };

    let rms_ffn_weight = ptr as *const f32;
    ptr = unsafe { ptr.add(n_layers * dim * 4) };

    let rms_final_weight = ptr as *const f32;
    ptr = unsafe { ptr.add(dim * 4) };

    // q_tokens quantized embedding
    let q_tokens = init_quantized_tensor(&mut ptr, vocab_size * dim, gs);

    // dequantize embedding table to float array
    let mut token_embedding_table = alloc::vec![0.0f32; vocab_size * dim];
    unsafe {
        dequantize(&q_tokens, &mut token_embedding_table, vocab_size * dim, gs);
    }

    // wq, wk, wv, wo
    let wq = init_quantized_tensors(&mut ptr, n_layers, dim * dim, gs);
    let wk = init_quantized_tensors(&mut ptr, n_layers, dim * kv_dim, gs);
    let wv = init_quantized_tensors(&mut ptr, n_layers, dim * kv_dim, gs);
    let wo = init_quantized_tensors(&mut ptr, n_layers, dim * dim, gs);

    // w1, w2, w3
    let w1 = init_quantized_tensors(&mut ptr, n_layers, dim * hidden_dim, gs);
    let w2 = init_quantized_tensors(&mut ptr, n_layers, hidden_dim * dim, gs);
    let w3 = init_quantized_tensors(&mut ptr, n_layers, dim * hidden_dim, gs);

    // classifier
    let wcls = if shared_classifier != 0 {
        QuantizedTensor { q: q_tokens.q, s: q_tokens.s }
    } else {
        init_quantized_tensor(&mut ptr, dim * vocab_size, gs)
    };

    let weights = TransformerWeights {
        rms_att_weight,
        rms_ffn_weight,
        rms_final_weight,
        q_tokens,
        token_embedding_table,
        wq,
        wk,
        wv,
        wo,
        w1,
        w2,
        w3,
        wcls,
    };

    // Load Tokenizer
    let tokenizer_path = "/disk/heliox/tokenizer.bin";
    let tokenizer = Tokenizer::load(tokenizer_path, vocab_size)?;

    // Allocate RunState
    let mut state = RunState::new(&config, gs);

    // Encode Prompt
    let prompt_tokens = tokenizer.encode(prompt, true, false);
    if prompt_tokens.is_empty() {
        return Err("Empty prompt tokens");
    }

    // Generate output
    let mut output_str = String::new();
    let mut token = prompt_tokens[0];
    let mut pos = 0;
    
    // Process prompt tokens
    for &t in prompt_tokens.iter().skip(1) {
        forward(&weights, &mut state, token, pos, &config, gs, avx2_supported);
        token = t;
        pos += 1;
        unsafe { crate::syscall3(SYS_YIELD, 0, 0, 0); }
    }

    let mut prev_token = token;
    // Generate text
    while pos < seq_len {
        forward(&weights, &mut state, token, pos, &config, gs, avx2_supported);
        
        let next_token = sample_argmax(&state.logits);
        if next_token == 2 {
            break; // EOS
        }

        let piece = tokenizer.decode(prev_token, next_token);
        let decoded = decode_token_bytes(piece);
        if let Ok(s) = core::str::from_utf8(&decoded) {
            output_str.push_str(s);
        }

        prev_token = token;
        token = next_token;
        pos += 1;
        unsafe { crate::syscall3(SYS_YIELD, 0, 0, 0); }
    }

    Ok(output_str)
}

pub fn detect_avx2() -> bool {
    let mut buf = [0u8; 512];
    let bytes_written = unsafe {
        crate::syscall4(
            29, // SYS_SYSTEM_QUERY
            0,  // query_type = system_info
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
            0,
        )
    };
    if bytes_written > 0 && (bytes_written as usize) <= buf.len() {
        if let Ok(text) = core::str::from_utf8(&buf[..bytes_written as usize]) {
            if let Some(idx) = text.find("\"avx2\":") {
                let rest = &text[idx + "\"avx2\":".len()..];
                if rest.starts_with("true") {
                    return true;
                }
            }
        }
    }
    false
}
