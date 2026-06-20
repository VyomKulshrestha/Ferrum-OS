// ============================================================================
// FerrumOS — Hardware RDRAND-backed CSPRNG
// ============================================================================

use core::arch::x86_64::__cpuid;

/// Probe CPUID to check if RDRAND is supported by the processor.
pub fn is_rdrand_supported() -> bool {
    let cpuid_result = unsafe { __cpuid(1) };
    (cpuid_result.ecx & (1 << 30)) != 0
}

/// Fill the buffer with cryptographically secure random bytes from hardware RDRAND.
/// Returns an error if RDRAND is unsupported or fails to generate entropy.
pub fn get_random(buf: &mut [u8]) -> Result<(), &'static str> {
    if !is_rdrand_supported() {
        return Err("RDRAND not supported by CPU");
    }

    let mut chunks = buf.chunks_exact_mut(8);
    for chunk in &mut chunks {
        let mut val: u64 = 0;
        let mut success: u8 = 0;
        for _ in 0..10 {
            unsafe {
                core::arch::asm!(
                    "rdrand {0}",
                    "setc {1}",
                    out(reg) val,
                    out(reg_byte) success,
                );
            }
            if success != 0 {
                break;
            }
        }
        if success == 0 {
            return Err("RDRAND hardware failure after retries");
        }
        chunk.copy_from_slice(&val.to_ne_bytes());
    }

    let remainder = chunks.into_remainder();
    if !remainder.is_empty() {
        let mut val: u64 = 0;
        let mut success: u8 = 0;
        for _ in 0..10 {
            unsafe {
                core::arch::asm!(
                    "rdrand {0}",
                    "setc {1}",
                    out(reg) val,
                    out(reg_byte) success,
                );
            }
            if success != 0 {
                break;
            }
        }
        if success == 0 {
            return Err("RDRAND hardware failure after retries");
        }
        let bytes = val.to_ne_bytes();
        remainder.copy_from_slice(&bytes[..remainder.len()]);
    }

    Ok(())
}
