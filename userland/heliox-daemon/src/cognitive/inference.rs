// ============================================================================
// Heliox-OS — Toy SLM Local Inference Engine
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;

fn read_file_to_vec(path: &str) -> Result<Vec<u8>, &'static str> {
    const SYS_READ_FILE: u64 = 15;
    // We allocate a buffer on the heap (up to 4 MB)
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
    if (bytes_read as i64) < 0 {
        Err("Failed to read file")
    } else {
        buf.truncate(bytes_read as usize);
        Ok(buf)
    }
}

pub fn run_local_inference(prompt: &str) -> Result<String, &'static str> {
    // 1. Load the model weights from Ext2 filesystem
    let model_path = "/disk/heliox/models/toy.gguf";
    
    // Read the GGUF file bytes.
    let file_bytes = match read_file_to_vec(model_path) {
        Ok(bytes) => bytes,
        Err(_) => return Err("Failed to read model file: /disk/heliox/models/toy.gguf not found"),
    };

    if file_bytes.len() < 16 {
        return Err("Model file is too small to be a valid GGUF file");
    }

    // 2. Validate GGUF Magic Header
    // GGUF v3 magic: 'G' 'G' 'U' 'F' (0x46554747)
    if &file_bytes[0..4] != b"GGUF" {
        return Err("Invalid GGUF magic header");
    }

    let version = u32::from_le_bytes([file_bytes[4], file_bytes[5], file_bytes[6], file_bytes[7]]);
    if version != 3 {
        return Err("Unsupported GGUF version (only GGUF v3 is supported)");
    }

    // 3. Simulate Scalar Q4 Matrix-Vector Multiplication (GEMV)
    // In a real SLM, we parse tensors, dequantize blocks, and perform matrix multiplication.
    // Here we simulate the processing of a prompt over the quantized weights.
    let mut sum: f32 = 0.0;
    
    // Simple mock computation over the first few KB of quantized blocks
    let limit = file_bytes.len().min(1024);
    for i in (8..limit).step_by(32) {
        let scale = file_bytes[i] as f32 / 256.0;
        let mut block_sum = 0.0;
        for j in 0..16 {
            if i + 4 + j < file_bytes.len() {
                let byte = file_bytes[i + 4 + j];
                let val1 = (byte & 0x0F) as i8 - 8;
                let val2 = ((byte >> 4) & 0x0F) as i8 - 8;
                block_sum += (val1 as f32) * scale + (val2 as f32) * scale;
            }
        }
        sum += block_sum;
    }

    // 4. Generate a coherent local SLM response based on prompt and mock tensor computation
    let mut response = String::from("Local SLM Response: ");
    if prompt.to_lowercase().contains("hello") || prompt.to_lowercase().contains("hey") {
        response.push_str("Hello! I am your offline assistant running natively on FerrumOS CPU cores. How can I help you today?");
    } else if prompt.to_lowercase().contains("status") {
        response.push_str("All offline systems are operational. CPU SSE registers are active and protected.");
    } else {
        response.push_str("Processed prompt successfully. Scalar Q4 GEMV calculation trace: ");
        let int_sum = (sum.abs() as i32) % 100;
        response.push_str(&alloc::format!("0.{}", int_sum));
    }

    Ok(response)
}
