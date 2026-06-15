// ============================================================================
// Heliox-Daemon - JARVIS Multimodal Fusion Engine
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::string::ToString;
use alloc::vec::Vec;
use spin::Mutex;

#[repr(C)]
#[derive(Debug, Clone, Copy)]
pub struct HudState {
    pub flags: u32,               // bit0 = visible, bit1 = listening, bit2 = pointing
    pub waveform: [u8; 64],       // audio waveform values (0..255)
    pub gesture_type: u8,         // stable gesture enum
    pub point_x: u16,             // target x (screen coords)
    pub point_y: u16,             // target y (screen coords)
    pub landmark_count: u8,       // number of landmarks
    pub landmarks: [[u16; 2]; 8],  // landmark coordinates
    pub suggestion_len: u8,       // suggestion text length
    pub suggestion: [u8; 128],    // suggestion text buffer
}

#[derive(Debug, Clone)]
pub struct ResolvedIntent {
    pub verb: String,
    pub target_label: String,
    pub sx: u32,
    pub sy: u32,
}

static GESTURE_HISTORY: Mutex<Vec<(u64, u16, u16)>> = Mutex::new(Vec::new());

pub fn get_uptime_ticks() -> u64 {
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
            if let Some(idx) = text.find("\"uptime_ticks\":") {
                let rest = &text[idx + "\"uptime_ticks\":".len()..];
                let end = rest.find(',').unwrap_or(rest.find('}').unwrap_or(rest.len()));
                let num_str = rest[..end].trim();
                if let Ok(ticks) = num_str.parse::<u64>() {
                    return ticks;
                }
            }
        }
    }
    0
}

pub fn note_gesture(ticks: u64, cam_x: u16, cam_y: u16) {
    let sx = (cam_x as u32 * 1024 / 320) as u16;
    let sy = (cam_y as u32 * 768 / 240) as u16;
    let mut history = GESTURE_HISTORY.lock();
    history.push((ticks, sx, sy));
    if history.len() > 16 {
        history.remove(0);
    }
}

pub fn resolve_spatial_intent(transcript: &str, current_ticks: u64) -> Option<ResolvedIntent> {
    let text_lower = transcript.to_lowercase();
    let has_deictic = text_lower.contains("this") || text_lower.contains("that") || text_lower.contains("here") || text_lower.contains(" it ");
    if !has_deictic {
        return None;
    }
    
    // Find the most recent Pointing gesture within 27 ticks (~1.5s at 18.2Hz)
    let history = GESTURE_HISTORY.lock();
    let mut best_gesture = None;
    for &(ticks, sx, sy) in history.iter().rev() {
        let diff = current_ticks.saturating_sub(ticks);
        if diff <= 27 {
            best_gesture = Some((sx, sy));
            break;
        }
    }
    
    let (sx, sy) = match best_gesture {
        Some(coords) => coords,
        None => return None,
    };
    
    // Call HitTest (40) gated by cap:hud:overlay
    let mut label_buf = [0u8; 64];
    let syscall_hit_test: u64 = 40;
    
    let window_id = unsafe {
        crate::syscall4(
            syscall_hit_test,
            sx as u64,
            sy as u64,
            label_buf.as_mut_ptr() as u64,
            label_buf.len() as u64,
        )
    };
    
    let mut label_len = 0;
    for &b in &label_buf {
        if b == 0 {
            break;
        }
        label_len += 1;
    }
    
    let target_label = if label_len > 0 {
        core::str::from_utf8(&label_buf[..label_len])
            .unwrap_or("desktop")
            .to_string()
    } else {
        String::from("desktop")
    };
    
    // Extract verb
    let mut verb = String::new();
    let words = transcript.split_whitespace();
    for w in words {
        let wl = w.to_lowercase();
        // Remove deictic markers
        if wl != "this" && wl != "that" && wl != "here" && wl != "the" && wl != "it" {
            if !verb.is_empty() {
                verb.push(' ');
            }
            verb.push_str(w);
        }
    }
    if verb.is_empty() {
        verb = String::from("act");
    }
    
    Some(ResolvedIntent {
        verb,
        target_label,
        sx: sx as u32,
        sy: sy as u32,
    })
}

pub fn push_hud_state(state: &HudState) -> Result<(), &'static str> {
    let syscall_hud_update: u64 = 39;
    let res = unsafe {
        crate::syscall3(
            syscall_hud_update,
            state as *const HudState as u64,
            core::mem::size_of::<HudState>() as u64,
            0,
        )
    };
    if (res as i64) < 0 {
        Err("Failed to update HUD state")
    } else {
        Ok(())
    }
}

pub fn downsample_to_waveform(buf: &crate::cognitive::voice::AudioBuffer) -> [u8; 64] {
    let mut wave = [0u8; 64];
    let data_len = buf.data.len();
    if data_len < 128 {
        return wave;
    }
    let samples_count = data_len / 2;
    let chunk_size = samples_count / 64;
    if chunk_size == 0 {
        return wave;
    }
    
    for i in 0..64 {
        let start = i * chunk_size;
        let mut sum_abs: u64 = 0;
        let mut count = 0;
        for j in 0..chunk_size {
            let offset = (start + j) * 2;
            if offset + 1 < data_len {
                let val = i16::from_le_bytes([buf.data[offset], buf.data[offset + 1]]) as i32;
                sum_abs += val.abs() as u64;
                count += 1;
            }
        }
        if count > 0 {
            let avg = sum_abs / count;
            wave[i] = ((avg * 255) / 32768).min(255) as u8;
        }
    }
    wave
}

pub fn idle_waveform(loop_count: u64) -> [u8; 64] {
    let mut wave = [0u8; 64];
    for i in 0..64 {
        let phase = (loop_count * 2 + i as u64) % 40;
        let val = if phase < 20 { phase } else { 40 - phase };
        wave[i] = (val * 2 + 5) as u8;
    }
    wave
}

