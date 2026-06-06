// ============================================================================
// FerrumOS - Audio Subsystem
// ============================================================================
// Clean kernel-side audio API on top of the Intel HDA driver.
//
// Provides PCM audio playback, recording, volume control, and a built-in
// sine wave generator for testing. The HDA back-end is an internal module
// that abstracts the hardware (or provides soft-stubs when no codec is
// detected).
// ============================================================================

extern crate alloc;

use alloc::vec;
use alloc::vec::Vec;

// ---------------------------------------------------------------------------
// AudioFormat
// ---------------------------------------------------------------------------

/// Describes a PCM audio stream format.
#[derive(Debug, Clone, Copy)]
#[allow(dead_code)]
pub struct AudioFormat {
    pub sample_rate: u32,
    pub bits_per_sample: u8,
    pub channels: u8,
}

#[allow(dead_code)]
impl AudioFormat {
    /// CD-quality-ish default: 48 kHz, 16-bit, stereo.
    pub const PCM_48KHZ_16BIT_STEREO: Self = Self {
        sample_rate: 48000,
        bits_per_sample: 16,
        channels: 2,
    };

    /// Returns the raw byte throughput of this format.
    pub fn bytes_per_second(&self) -> u32 {
        self.sample_rate * (self.bits_per_sample as u32 / 8) * self.channels as u32
    }

    /// Bytes required to hold `duration_ms` milliseconds of audio.
    pub fn bytes_for_duration(&self, duration_ms: u32) -> usize {
        (self.bytes_per_second() as u64 * duration_ms as u64 / 1000) as usize
    }
}

// ---------------------------------------------------------------------------
// Internal HDA back-end — forwards to the real driver in crate::devices::hda
// ---------------------------------------------------------------------------

mod hda {
    /// Probe the PCI bus for an HDA controller and initialise it.
    pub fn init() {
        match crate::devices::hda::init() {
            Ok(()) => {}
            Err(e) => {
                crate::serial_println!("[audio] HDA init failed: {}", e);
            }
        }
    }

    /// Returns `true` when an HDA codec has been successfully initialised.
    pub fn is_available() -> bool {
        crate::devices::hda::is_available()
    }

    /// Submit a PCM buffer to the output DMA engine.
    pub fn play_buffer(data: &[u8]) -> Result<(), &'static str> {
        crate::devices::hda::play_buffer(data)
    }

    /// Start a capture DMA and fill `buf` with recorded PCM samples.
    pub fn record_buffer(buf: &mut [u8]) -> Result<usize, &'static str> {
        crate::devices::hda::record_buffer(buf)
    }

    /// Set the master output volume (0–127).
    pub fn set_volume(level: u8) {
        crate::devices::hda::set_volume(level);
    }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Initialise the audio subsystem.
///
/// Probes the HDA controller and registers the audio device with the
/// kernel device registry.
#[allow(dead_code)]
pub fn init() {
    hda::init();

    if hda::is_available() {
        crate::serial_println!("[audio] HDA controller initialised");

        // Update the device registry â€” replace the "planned" stub with
        // the real driver entry.
        crate::devices::register_device(
            "audio.hda",
            crate::devices::DeviceClass::Audio,
            crate::devices::DeviceState::Online,
            "intel-hda",
            "audio:pcm",
        );
    } else {
        crate::serial_println!("[audio] no HDA controller found");
    }
}

/// Play raw PCM data through the default output stream.
#[allow(dead_code)]
pub fn play(data: &[u8]) -> Result<(), &'static str> {
    hda::play_buffer(data)
}

/// Record `duration_ms` milliseconds of PCM audio from the default input.
///
/// Uses the default format (48 kHz / 16-bit / stereo) to calculate the
/// required buffer size.
#[allow(dead_code)]
pub fn record(duration_ms: u32) -> Result<Vec<u8>, &'static str> {
    let format = AudioFormat::PCM_48KHZ_16BIT_STEREO;
    let buf_size = format.bytes_for_duration(duration_ms);
    if buf_size == 0 {
        return Err("audio: zero-length recording requested");
    }

    let mut buf = vec![0u8; buf_size];
    let actual = hda::record_buffer(&mut buf)?;

    // Truncate to the number of bytes the driver actually captured.
    buf.truncate(actual);
    Ok(buf)
}

/// Set the master output volume (0â€“127).
#[allow(dead_code)]
pub fn set_volume(level: u8) {
    hda::set_volume(level);
}

/// Returns `true` when an audio device is available and initialised.
#[allow(dead_code)]
pub fn is_available() -> bool {
    hda::is_available()
}

// ---------------------------------------------------------------------------
// Sine-wave test-tone generator
// ---------------------------------------------------------------------------

/// 16-entry sine lookup table scaled to i16 range.
///
/// Values are `sin(2Ï€Â·k/16) * 32767` for k = 0..15, pre-computed so we
/// avoid any floating-point or `libm` dependency in the kernel.
const SINE_TABLE: [i16; 16] = [
    0,      12539,  23170,  30273,
    32767,  30273,  23170,  12539,
    0,     -12539, -23170, -30273,
   -32767, -30273, -23170, -12539,
];

/// Generate a PCM sine-wave test tone.
///
/// Output is 48 kHz, 16-bit signed LE, stereo â€” identical on both
/// channels. Uses the 16-sample lookup table with linear interpolation
/// between entries for reasonable spectral purity.
///
/// # Arguments
/// * `frequency_hz` â€” tone frequency in Hz (clamped to 1..24000).
/// * `duration_ms`  â€” tone length in milliseconds.
#[allow(dead_code)]
pub fn generate_sine_wave(frequency_hz: u32, duration_ms: u32) -> Vec<u8> {
    let format = AudioFormat::PCM_48KHZ_16BIT_STEREO;
    let total_samples = (format.sample_rate as u64 * duration_ms as u64 / 1000) as usize;
    let bytes_per_sample = (format.bits_per_sample as usize / 8) * format.channels as usize;

    let mut out = Vec::with_capacity(total_samples * bytes_per_sample);

    // Clamp frequency to the Nyquist limit.
    let freq = if frequency_hz == 0 {
        1u32
    } else if frequency_hz > format.sample_rate / 2 {
        format.sample_rate / 2
    } else {
        frequency_hz
    };

    // Fixed-point phase accumulator.
    // We represent one full period as `TABLE_LEN << 16` units so that
    // the fractional part gives us sub-entry precision for interpolation.
    const TABLE_LEN: u32 = 16;
    const FRAC_BITS: u32 = 16;
    let phase_step = (TABLE_LEN << FRAC_BITS) as u64 * freq as u64
        / format.sample_rate as u64;
    let phase_step = phase_step as u32;
    let phase_wrap = TABLE_LEN << FRAC_BITS;

    let mut phase: u32 = 0;

    for _ in 0..total_samples {
        // Integer and fractional table indices.
        let idx = (phase >> FRAC_BITS) as usize % TABLE_LEN as usize;
        let next_idx = (idx + 1) % TABLE_LEN as usize;
        let frac = (phase & 0xFFFF) as i32; // 0..65535

        // Linear interpolation between adjacent table entries.
        let a = SINE_TABLE[idx] as i32;
        let b = SINE_TABLE[next_idx] as i32;
        let sample = (a + ((b - a) * frac) / 65536) as i16;

        let le = sample.to_le_bytes();
        // Left channel
        out.push(le[0]);
        out.push(le[1]);
        // Right channel (identical)
        out.push(le[0]);
        out.push(le[1]);

        phase = phase.wrapping_add(phase_step);
        if phase >= phase_wrap {
            phase -= phase_wrap;
        }
    }

    out
}
