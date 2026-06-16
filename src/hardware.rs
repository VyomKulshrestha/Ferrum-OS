// ============================================================================
// FerrumOS — Hardware Identification and Tier Classification
// ============================================================================

use spin::Mutex;
use bootloader::BootInfo;
use core::arch::x86_64::{__cpuid, __cpuid_count};

#[derive(Debug, Clone, Copy)]
pub struct HardwareTierInfo {
    pub ram_mb: u64,
    pub sse: bool,
    pub avx: bool,
    pub avx2: bool,
    pub tier: &'static str,
}

pub static HARDWARE_TIER: Mutex<Option<HardwareTierInfo>> = Mutex::new(None);

pub fn init(boot_info: &'static BootInfo) {
    // 1. Calculate total RAM from memory map (summing all non-reserved regions)
    let total_bytes: u64 = boot_info.memory_map.iter()
        .filter(|r| r.region_type != bootloader::bootinfo::MemoryRegionType::Reserved)
        .map(|r| r.range.end_addr() - r.range.start_addr())
        .sum();
    let ram_mb = total_bytes / (1024 * 1024);

    // 2. Probe CPUID features
    // Check CPUID leaf 1 for SSE and AVX
    let cpuid_1 = __cpuid(1);
    let sse = (cpuid_1.edx & (1 << 25)) != 0;
    let avx = (cpuid_1.ecx & (1 << 28)) != 0;

    // Check maximum leaf supported
    let cpuid_0 = __cpuid(0);
    let max_leaf = cpuid_0.eax;

    let avx2 = if max_leaf >= 7 {
        let cpuid_7 = __cpuid_count(7, 0);
        (cpuid_7.ebx & (1 << 5)) != 0
    } else {
        false
    };

    // 3. Classify hardware tier
    // High: >= 6 GB RAM (6144 MB) + AVX2
    // Standard: >= 2 GB RAM (2048 MB) + AVX
    // Low: < 2 GB RAM or no AVX
    let tier = if ram_mb >= 6144 && avx2 {
        "high"
    } else if ram_mb >= 2048 && avx {
        "standard"
    } else {
        "low"
    };

    let info = HardwareTierInfo {
        ram_mb,
        sse,
        avx,
        avx2,
        tier,
    };

    *HARDWARE_TIER.lock() = Some(info);
}

pub fn get_info() -> Option<HardwareTierInfo> {
    *HARDWARE_TIER.lock()
}
