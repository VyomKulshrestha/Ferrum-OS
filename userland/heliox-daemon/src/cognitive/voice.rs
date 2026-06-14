// ============================================================================
// Heliox-Daemon - Voice Module
// ============================================================================
// Provides audio recording, voice activity detection, and future STT
// integration via kernel audio syscalls.
//
// The agent uses this module to:
//   - Record audio from the virtual microphone
//   - Detect voice activity (energy-based)
//   - Save recordings to the Ext2 disk
//   - Forward audio for speech-to-text (when STT service is available)
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::vec;
use alloc::format;

// Syscall numbers (must match kernel src/syscall/mod.rs)
const SYS_RECORD_AUDIO: u64 = 24;
const SYS_PLAY_AUDIO: u64 = 23;
const SYS_SET_VOLUME: u64 = 25;
const SYS_WRITE_FILE: u64 = 16;

// ============================================================================
// Audio Buffer
// ============================================================================

/// Raw PCM audio buffer captured from the kernel audio subsystem.
pub struct AudioBuffer {
    /// Raw PCM data (48kHz, 16-bit signed LE, stereo)
    pub data: Vec<u8>,
    /// Sample rate in Hz
    pub sample_rate: u32,
    /// Bits per sample
    pub bits: u8,
    /// Number of channels
    pub channels: u8,
    /// Duration in milliseconds
    pub duration_ms: u32,
}

impl AudioBuffer {
    /// Calculate the number of samples (per channel) in this buffer.
    pub fn sample_count(&self) -> usize {
        let bytes_per_sample = (self.bits as usize / 8) * self.channels as usize;
        if bytes_per_sample == 0 {
            return 0;
        }
        self.data.len() / bytes_per_sample
    }

    /// Calculate the RMS (root mean square) amplitude of the audio.
    /// Returns a value in the range [0, 32767] for 16-bit audio.
    pub fn rms_amplitude(&self) -> u32 {
        if self.data.len() < 2 || self.bits != 16 {
            return 0;
        }

        let mut sum_sq: u64 = 0;
        let mut count: u64 = 0;

        // Iterate over 16-bit signed LE samples
        let mut i = 0;
        while i + 1 < self.data.len() {
            let sample = i16::from_le_bytes([self.data[i], self.data[i + 1]]);
            sum_sq += (sample as i64 * sample as i64) as u64;
            count += 1;
            i += 2;
        }

        if count == 0 {
            return 0;
        }

        // Integer square root approximation of mean square
        let mean_sq = sum_sq / count;
        isqrt(mean_sq) as u32
    }

    /// Calculate the zero-crossing rate (ZCR) of the audio.
    /// Returns the total number of zero-crossings in the buffer.
    pub fn zero_crossing_rate(&self) -> u32 {
        if self.data.len() < 4 || self.bits != 16 {
            return 0;
        }

        let mut crossings: u32 = 0;
        let mut last_sample: i16 = 0;
        let mut initialized = false;

        // Iterate over 16-bit signed LE samples
        let mut i = 0;
        while i + 1 < self.data.len() {
            let sample = i16::from_le_bytes([self.data[i], self.data[i + 1]]);
            if initialized {
                if (sample >= 0 && last_sample < 0) || (sample < 0 && last_sample >= 0) {
                    crossings += 1;
                }
            } else {
                initialized = true;
            }
            last_sample = sample;
            i += 2;
        }

        crossings
    }
}

/// Integer square root using Newton's method.
fn isqrt(n: u64) -> u64 {
    if n == 0 {
        return 0;
    }
    let mut x = n;
    let mut y = (x + 1) / 2;
    while y < x {
        x = y;
        y = (x + n / x) / 2;
    }
    x
}

// ============================================================================
// Recording
// ============================================================================

/// Record audio from the virtual microphone for the given duration.
///
/// Returns an `AudioBuffer` containing raw PCM data (48kHz, 16-bit, stereo).
pub fn record_audio(duration_ms: u32) -> Result<AudioBuffer, &'static str> {
    if duration_ms == 0 || duration_ms > 30_000 {
        return Err("Duration must be 1-30000 ms");
    }

    // Calculate buffer size: 48000 Hz * 2 bytes * 2 channels = 192000 bytes/sec
    let bytes_per_sec: u32 = 48000 * 2 * 2;
    let buf_size = ((bytes_per_sec as u64 * duration_ms as u64) / 1000) as usize;
    let mut buf = vec![0u8; buf_size];

    let bytes_recorded = unsafe {
        crate::syscall4(
            SYS_RECORD_AUDIO,
            buf.as_mut_ptr() as u64,
            buf_size as u64,
            duration_ms as u64,
            0,
        )
    };

    if bytes_recorded == 0 || bytes_recorded > buf_size as u64 {
        return Err("Recording failed or returned invalid size");
    }

    buf.truncate(bytes_recorded as usize);

    Ok(AudioBuffer {
        data: buf,
        sample_rate: 48000,
        bits: 16,
        channels: 2,
        duration_ms,
    })
}

/// Play raw PCM audio data through the virtual speaker.
pub fn play_audio(data: &[u8]) -> Result<(), &'static str> {
    if data.is_empty() {
        return Err("No audio data to play");
    }

    let result = unsafe {
        crate::syscall4(
            SYS_PLAY_AUDIO,
            data.as_ptr() as u64,
            data.len() as u64,
            0,
            0,
        )
    };

    if result == 0 {
        Ok(())
    } else {
        Err("Playback failed")
    }
}

/// Set the audio output volume (0 = mute, 127 = max).
pub fn set_volume(level: u8) {
    let clamped = if level > 127 { 127 } else { level };
    unsafe {
        crate::syscall4(SYS_SET_VOLUME, clamped as u64, 0, 0, 0);
    }
}

// ============================================================================
// Voice Activity Detection (VAD)
// ============================================================================

/// Energy threshold for voice activity detection.
/// 16-bit audio has a range of [0, 32767]; typical background noise
/// in QEMU is near-zero, so even a low threshold works.
const VAD_RMS_THRESHOLD: u32 = 500;

/// Minimum duration of voice activity to be considered speech (in ms).
const VAD_MIN_DURATION_MS: u32 = 200;

/// Detect whether the given audio buffer contains voice activity.
///
/// Uses simple energy-based detection: if the RMS amplitude exceeds
/// `threshold` for at least `VAD_MIN_DURATION_MS`, returns true.
/// A threshold of 0 forces voice activity detection to succeed instantly (for tests).
pub fn detect_voice_activity(buf: &AudioBuffer, threshold: u32) -> bool {
    if threshold == 0 {
        return true;
    }
    if buf.data.len() < 4 || buf.bits != 16 {
        return false;
    }

    let rms = buf.rms_amplitude();
    let _zcr = buf.zero_crossing_rate();
    // Simple: if overall RMS exceeds threshold and duration is sufficient
    rms > threshold && buf.duration_ms >= VAD_MIN_DURATION_MS
}

// ============================================================================
// Save / Transcribe
// ============================================================================

/// Save a recording to the Ext2 disk as a raw PCM file.
pub fn save_recording(buf: &AudioBuffer, path: &str) -> Result<(), &'static str> {
    if buf.data.is_empty() {
        return Err("Empty audio buffer");
    }

    let path_bytes = path.as_bytes();
    let result = unsafe {
        crate::syscall4(
            SYS_WRITE_FILE,
            path_bytes.as_ptr() as u64,
            path_bytes.len() as u64,
            buf.data.as_ptr() as u64,
            buf.data.len() as u64,
        )
    };

    if result == 0 {
        Ok(())
    } else {
        Err("Failed to write audio file")
    }
}

/// Transcribe audio to text using a speech-to-text service.
///
/// Sends the raw PCM via HTTP POST and returns the transcript text.
pub fn transcribe(buf: &AudioBuffer, host: &str, port: u16) -> Result<String, &'static str> {
    if host == "unconfigured" {
        return Err("STT host is unconfigured");
    }

    let response = crate::network::http_post_binary(
        host,
        port,
        "/v1/audio/transcriptions",
        &buf.data,
        "audio/l16; rate=48000; channels=2",
        "",
    )?;

    if response.status_code != 200 {
        return Err("STT server returned non-200 status");
    }

    // Parse the JSON response to extract the text
    let parsed = crate::cognitive::json::parse(&response.body)
        .map_err(|_| "Failed to parse STT response JSON")?;
    
    let text_val = parsed.get("text").ok_or("STT response does not contain 'text' field")?;
    let text_str = text_val.as_str().ok_or("STT response 'text' field is not a string")?;
    
    Ok(String::from(text_str))
}

/// Generate a short notification beep (440Hz sine wave, 200ms).
/// Returns raw PCM data suitable for `play_audio()`.
pub fn generate_beep() -> Vec<u8> {
    let sample_rate: u32 = 48000;
    let duration_ms: u32 = 200;
    let frequency: u32 = 440;
    let num_samples = (sample_rate * duration_ms / 1000) as usize;
    let mut buf = Vec::with_capacity(num_samples * 4); // 16-bit stereo = 4 bytes/sample

    // Simple square wave approximation (no floating point needed)
    let samples_per_period = sample_rate / frequency;
    let half_period = samples_per_period / 2;

    for i in 0..num_samples {
        let sample_in_period = (i as u32) % samples_per_period;
        let value: i16 = if sample_in_period < half_period {
            8000 // positive half
        } else {
            -8000 // negative half
        };

        let bytes = value.to_le_bytes();
        // Left channel
        buf.push(bytes[0]);
        buf.push(bytes[1]);
        // Right channel (same)
        buf.push(bytes[0]);
        buf.push(bytes[1]);
    }

    buf
}
