// ============================================================================
// FerrumOS — CMOS Real Time Clock (RTC) Driver
// ============================================================================

use x86_64::instructions::port::Port;

/// Read a register from CMOS.
unsafe fn read_cmos_register(reg: u8) -> u8 {
    let mut port_70 = Port::new(0x70);
    let mut port_71 = Port::new(0x71);
    port_70.write(reg);
    port_71.read()
}

/// Check if CMOS update in progress flag is set.
fn get_update_in_progress_flag() -> bool {
    unsafe { read_cmos_register(0x0A) & 0x80 != 0 }
}

/// Helper to check if a year is a leap year.
fn is_leap_year(year: u64) -> bool {
    (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0)
}

/// Helper function to perform epoch calculation, separate for unit testing.
pub fn calculate_epoch(
    year: u8,
    month: u8,
    day: u8,
    hour: u8,
    minute: u8,
    second: u8,
    is_binary: bool,
    is_24h: bool,
) -> Option<u64> {
    let mut yr = year;
    let mut mo = month;
    let mut dy = day;
    let mut hr = hour;
    let mut min = minute;
    let mut sec = second;

    // Decode BCD if necessary
    if !is_binary {
        sec = (sec & 0x0F) + ((sec / 16) * 10);
        min = (min & 0x0F) + ((min / 16) * 10);
        hr = ((hr & 0x0F) + (((hr & 0x70) / 16) * 10)) | (hr & 0x80);
        dy = (dy & 0x0F) + ((dy / 16) * 10);
        mo = (mo & 0x0F) + ((mo / 16) * 10);
        yr = (yr & 0x0F) + ((yr / 16) * 10);
    }

    // Decode 12-hour format if necessary
    if !is_24h {
        let is_pm = (hr & 0x80) != 0;
        hr &= 0x7F;
        if is_pm {
            if hr < 12 {
                hr += 12;
            }
        } else if hr == 12 {
            hr = 0;
        }
    }

    if mo < 1 || mo > 12 || dy < 1 || dy > 31 || hr > 23 || min > 59 || sec > 59 {
        return None;
    }

    let full_year = if yr < 70 {
        2000 + yr as u64
    } else {
        1900 + yr as u64
    };

    let mut days_since_epoch = 0u64;
    for y in 1970..full_year {
        days_since_epoch += if is_leap_year(y) { 366 } else { 365 };
    }

    let months = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    for m in 0..(mo as usize - 1) {
        if m == 1 && is_leap_year(full_year) {
            days_since_epoch += 29;
        } else {
            days_since_epoch += months[m];
        }
    }
    days_since_epoch += dy as u64 - 1;

    let seconds = days_since_epoch * 86400 
        + hr as u64 * 3600 
        + min as u64 * 60 
        + sec as u64;

    Some(seconds)
}

/// Read the calendar clock from the CMOS RTC.
/// Returns the Unix epoch seconds, or None if the read timed out or failed.
pub fn read_rtc_time() -> Option<u64> {
    // Run unit assertions to verify correct calculations on first call
    static UNIT_TEST_PASSED: spin::Once = spin::Once::new();
    UNIT_TEST_PASSED.call_once(|| {
        // Assert June 19, 2026 12:00:00 UTC (BCD format: yr=26h, mo=06h, dy=19h, hr=12h, min=00h, sec=00h)
        // In BCD: 26 = 0x26 = 38 decimal. 19 = 0x19 = 25 decimal.
        let val = calculate_epoch(0x26, 0x06, 0x19, 0x12, 0x00, 0x00, false, true);
        assert_eq!(val, Some(1781856000));
    });

    // Wait until CMOS is not updating
    let mut retries = 0;
    while get_update_in_progress_flag() {
        retries += 1;
        if retries > 10000 {
            return None;
        }
    }

    // Read date-time registers
    let second = unsafe { read_cmos_register(0x00) };
    let minute = unsafe { read_cmos_register(0x02) };
    let hour = unsafe { read_cmos_register(0x04) };
    let day = unsafe { read_cmos_register(0x07) };
    let month = unsafe { read_cmos_register(0x08) };
    let year = unsafe { read_cmos_register(0x09) };
    let register_b = unsafe { read_cmos_register(0x0B) };

    let is_binary = (register_b & 0x04) != 0;
    let is_24h = (register_b & 0x02) != 0;

    calculate_epoch(year, month, day, hour, minute, second, is_binary, is_24h)
}
