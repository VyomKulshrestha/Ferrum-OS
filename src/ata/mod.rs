// ============================================================================
// FerrumOS - ATA PIO Disk Driver
// ============================================================================
// Bare-metal ATA/IDE driver using Programmed I/O (PIO) mode.
// Supports primary and secondary IDE channels, master and slave drives.
//
// I/O Ports:
//   Primary:   data=0x1F0 .. status=0x1F7, control=0x3F6
//   Secondary: data=0x170 .. status=0x177, control=0x376
//
// Commands used:
//   IDENTIFY (0xEC) — discover drive geometry and capabilities
//   READ SECTORS (0x20) — PIO sector read (LBA28)
//   WRITE SECTORS (0x30) — PIO sector write (LBA28)
//   FLUSH CACHE (0xE7) — commit write-back cache to media
//
// The driver is polling-based: it busy-waits on the BSY/DRQ status bits
// rather than sleeping on IRQ 14/15. This is the standard approach for
// PIO transfers in hobby OS kernels and avoids async complexity.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use spin::Mutex;
use x86_64::instructions::port::{Port, PortReadOnly, PortWriteOnly};

// ============================================================================
// Constants
// ============================================================================

/// ATA status register bits
const STATUS_BSY: u8 = 0x80;   // Drive is busy
#[allow(dead_code)]
const STATUS_DRDY: u8 = 0x40;  // Drive is ready
const STATUS_DRQ: u8 = 0x08;   // Data request — ready to transfer
const STATUS_ERR: u8 = 0x01;   // Error occurred
const STATUS_DF: u8 = 0x20;    // Drive fault

/// ATA command bytes
const CMD_IDENTIFY: u8 = 0xEC;
const CMD_READ_SECTORS: u8 = 0x20;
const CMD_WRITE_SECTORS: u8 = 0x30;
const CMD_FLUSH_CACHE: u8 = 0xE7;

/// Sector size in bytes
pub const SECTOR_SIZE: usize = 512;

/// Maximum number of sectors per PIO transfer (LBA28)
const MAX_SECTORS_PER_TRANSFER: u16 = 256;

/// Timeout: maximum iterations to wait for BSY to clear
const BSY_TIMEOUT: u32 = 100_000;

// ============================================================================
// Types
// ============================================================================

/// Identifies which IDE channel a drive is on.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AtaBus {
    Primary,
    Secondary,
}

impl AtaBus {
    pub fn name(&self) -> &'static str {
        match self {
            AtaBus::Primary => "primary",
            AtaBus::Secondary => "secondary",
        }
    }
}

/// Information about a detected ATA drive.
#[derive(Debug, Clone)]
pub struct AtaDrive {
    pub bus: AtaBus,
    pub drive: u8,        // 0 = master, 1 = slave
    pub present: bool,
    pub model: String,
    pub serial: String,
    pub sectors: u64,     // Total addressable sectors
    pub size_mb: u64,     // Approximate size in MiB
    pub lba48: bool,      // True if drive supports LBA48
}

/// Per-channel I/O port set and drive state.
struct AtaChannel {
    data: Port<u16>,
    _error: PortReadOnly<u8>,
    sector_count: Port<u8>,
    lba_lo: Port<u8>,
    lba_mid: Port<u8>,
    lba_hi: Port<u8>,
    drive_head: Port<u8>,
    status: PortReadOnly<u8>,
    command: PortWriteOnly<u8>,
    control: Port<u8>,
    drives: [Option<AtaDrive>; 2],
    bus: AtaBus,
}

/// Top-level controller holding both channels.
struct AtaController {
    primary: AtaChannel,
    secondary: AtaChannel,
}

// ============================================================================
// Global State
// ============================================================================

static ATA: Mutex<Option<AtaController>> = Mutex::new(None);

// ============================================================================
// Channel Implementation
// ============================================================================

impl AtaChannel {
    /// Create a new ATA channel from base I/O port addresses.
    fn new(base: u16, control: u16, bus: AtaBus) -> Self {
        Self {
            data: Port::new(base),
            _error: PortReadOnly::new(base + 1),
            sector_count: Port::new(base + 2),
            lba_lo: Port::new(base + 3),
            lba_mid: Port::new(base + 4),
            lba_hi: Port::new(base + 5),
            drive_head: Port::new(base + 6),
            status: PortReadOnly::new(base + 7),
            command: PortWriteOnly::new(base + 7),
            control: Port::new(control),
            drives: [None, None],
            bus,
        }
    }

    /// Read the status register.
    unsafe fn read_status(&mut self) -> u8 {
        self.status.read()
    }

    /// Read the alternate status register (does not clear IRQ).
    unsafe fn read_alt_status(&mut self) -> u8 {
        self.control.read()
    }

    /// 400ns delay by reading the alternate status register 4 times.
    /// Each I/O port read takes ~100ns on x86.
    unsafe fn io_delay(&mut self) {
        for _ in 0..4 {
            let _ = self.read_alt_status();
        }
    }

    /// Wait for BSY to clear. Returns the final status byte or an error.
    unsafe fn wait_not_busy(&mut self) -> Result<u8, String> {
        for _ in 0..BSY_TIMEOUT {
            let status = self.read_status();
            if status & STATUS_BSY == 0 {
                return Ok(status);
            }
        }
        Err(String::from("ATA timeout: BSY did not clear"))
    }

    /// Wait for DRQ to assert (data ready). BSY must already be clear.
    unsafe fn wait_drq(&mut self) -> Result<u8, String> {
        for _ in 0..BSY_TIMEOUT {
            let status = self.read_status();
            if status & STATUS_BSY != 0 {
                continue;
            }
            if status & STATUS_ERR != 0 || status & STATUS_DF != 0 {
                return Err(String::from("ATA error during transfer"));
            }
            if status & STATUS_DRQ != 0 {
                return Ok(status);
            }
        }
        Err(String::from("ATA timeout: DRQ not set"))
    }

    /// Software reset the channel.
    unsafe fn software_reset(&mut self) {
        // Set SRST bit
        self.control.write(0x04);
        self.io_delay();
        // Clear SRST bit, disable IRQ (nIEN=1)
        self.control.write(0x02);
        self.io_delay();
        // Wait for BSY to clear after reset
        let _ = self.wait_not_busy();
    }

    /// Select a drive on this channel: 0=master, 1=slave.
    unsafe fn select_drive(&mut self, drive: u8) {
        let sel = if drive == 0 { 0xA0 } else { 0xB0 };
        self.drive_head.write(sel);
        self.io_delay();
    }

    /// Send the IDENTIFY command and read the 256-word response.
    /// Returns None if no drive is present.
    unsafe fn identify(&mut self, drive_num: u8) -> Option<AtaDrive> {
        // Select the drive
        self.select_drive(drive_num);

        // Clear sector count and LBA registers
        self.sector_count.write(0);
        self.lba_lo.write(0);
        self.lba_mid.write(0);
        self.lba_hi.write(0);

        // Send IDENTIFY
        self.command.write(CMD_IDENTIFY);
        self.io_delay();

        // Check if drive exists — if status is 0, no drive
        let status = self.read_status();
        if status == 0 {
            return None;
        }

        // Wait for BSY to clear
        if self.wait_not_busy().is_err() {
            return None;
        }

        // Check if this is an ATAPI or SATA device (not plain ATA)
        let lba_mid = self.lba_mid.read();
        let lba_hi = self.lba_hi.read();
        if lba_mid != 0 || lba_hi != 0 {
            // Not an ATA disk (could be ATAPI CD-ROM, SATA, etc.)
            return None;
        }

        // Wait for DRQ
        if self.wait_drq().is_err() {
            return None;
        }

        // Read 256 words of IDENTIFY data
        let mut identify_data = [0u16; 256];
        for word in identify_data.iter_mut() {
            *word = self.data.read();
        }

        // Parse model string (words 27-46, big-endian byte pairs)
        let model = Self::parse_ata_string(&identify_data[27..47]);

        // Parse serial string (words 10-19, big-endian byte pairs)
        let serial = Self::parse_ata_string(&identify_data[10..20]);

        // Determine sector count
        // Check for LBA48 support (bit 10 of word 83)
        let lba48 = (identify_data[83] & (1 << 10)) != 0;
        let sectors = if lba48 {
            // LBA48: words 100-103 contain 64-bit sector count
            (identify_data[100] as u64)
                | ((identify_data[101] as u64) << 16)
                | ((identify_data[102] as u64) << 32)
                | ((identify_data[103] as u64) << 48)
        } else {
            // LBA28: words 60-61 contain 28-bit sector count
            (identify_data[60] as u64) | ((identify_data[61] as u64) << 16)
        };

        let size_mb = (sectors * SECTOR_SIZE as u64) / (1024 * 1024);

        Some(AtaDrive {
            bus: self.bus,
            drive: drive_num,
            present: true,
            model,
            serial,
            sectors,
            size_mb,
            lba48,
        })
    }

    /// Parse an ATA identification string from word pairs.
    /// ATA strings have swapped byte pairs and trailing spaces.
    fn parse_ata_string(words: &[u16]) -> String {
        let mut bytes = Vec::with_capacity(words.len() * 2);
        for &word in words {
            bytes.push((word >> 8) as u8);   // High byte first
            bytes.push((word & 0xFF) as u8); // Low byte second
        }
        // Convert to string, trim trailing spaces
        let s = core::str::from_utf8(&bytes).unwrap_or("").trim();
        String::from(s)
    }

    /// Read sectors using LBA28 PIO.
    ///
    /// # Arguments
    /// * `drive_num` - 0 for master, 1 for slave
    /// * `lba` - Starting Logical Block Address
    /// * `count` - Number of sectors to read (1-256; 0 means 256)
    /// * `buf` - Buffer to fill; must be at least `count * 512` bytes
    unsafe fn read_sectors(
        &mut self,
        drive_num: u8,
        lba: u64,
        count: u16,
        buf: &mut [u8],
    ) -> Result<(), String> {
        if count == 0 || count > MAX_SECTORS_PER_TRANSFER {
            return Err(String::from("ATA: invalid sector count"));
        }
        let needed = count as usize * SECTOR_SIZE;
        if buf.len() < needed {
            return Err(String::from("ATA: buffer too small"));
        }
        if lba > 0x0FFF_FFFF {
            return Err(String::from("ATA: LBA28 overflow (max 0x0FFFFFFF)"));
        }

        // Wait for drive to be ready
        self.wait_not_busy()?;

        // Select drive and set LBA bits 24-27
        let drive_sel = if drive_num == 0 { 0xE0 } else { 0xF0 };
        self.drive_head
            .write(drive_sel | ((lba >> 24) as u8 & 0x0F));

        // Write sector count and LBA
        let sc = if count == 256 { 0u8 } else { count as u8 };
        self.sector_count.write(sc);
        self.lba_lo.write(lba as u8);
        self.lba_mid.write((lba >> 8) as u8);
        self.lba_hi.write((lba >> 16) as u8);

        // Send READ SECTORS command
        self.command.write(CMD_READ_SECTORS);

        // Read each sector
        let mut offset = 0;
        for _ in 0..count {
            self.wait_drq()?;
            for _ in 0..256 {
                let word = self.data.read();
                buf[offset] = word as u8;
                buf[offset + 1] = (word >> 8) as u8;
                offset += 2;
            }
        }

        Ok(())
    }

    /// Write sectors using LBA28 PIO.
    ///
    /// # Arguments
    /// * `drive_num` - 0 for master, 1 for slave
    /// * `lba` - Starting Logical Block Address
    /// * `count` - Number of sectors to write (1-256)
    /// * `buf` - Data to write; must be at least `count * 512` bytes
    unsafe fn write_sectors(
        &mut self,
        drive_num: u8,
        lba: u64,
        count: u16,
        buf: &[u8],
    ) -> Result<(), String> {
        if count == 0 || count > MAX_SECTORS_PER_TRANSFER {
            return Err(String::from("ATA: invalid sector count"));
        }
        let needed = count as usize * SECTOR_SIZE;
        if buf.len() < needed {
            return Err(String::from("ATA: buffer too small"));
        }
        if lba > 0x0FFF_FFFF {
            return Err(String::from("ATA: LBA28 overflow (max 0x0FFFFFFF)"));
        }

        // Wait for drive to be ready
        self.wait_not_busy()?;

        // Select drive and set LBA bits 24-27
        let drive_sel = if drive_num == 0 { 0xE0 } else { 0xF0 };
        self.drive_head
            .write(drive_sel | ((lba >> 24) as u8 & 0x0F));

        // Write sector count and LBA
        let sc = if count == 256 { 0u8 } else { count as u8 };
        self.sector_count.write(sc);
        self.lba_lo.write(lba as u8);
        self.lba_mid.write((lba >> 8) as u8);
        self.lba_hi.write((lba >> 16) as u8);

        // Send WRITE SECTORS command
        self.command.write(CMD_WRITE_SECTORS);

        // Write each sector
        let mut offset = 0;
        for _ in 0..count {
            self.wait_drq()?;
            for _ in 0..256 {
                let word = (buf[offset] as u16) | ((buf[offset + 1] as u16) << 8);
                self.data.write(word);
                offset += 2;
            }
        }

        // Flush the write cache
        self.command.write(CMD_FLUSH_CACHE);
        self.wait_not_busy()?;

        let status = self.read_status();
        if status & STATUS_ERR != 0 {
            return Err(String::from("ATA: write error"));
        }

        Ok(())
    }

    /// Send FLUSH CACHE command.
    unsafe fn flush_cache(&mut self, drive_num: u8) -> Result<(), String> {
        self.select_drive(drive_num);
        self.wait_not_busy()?;
        self.command.write(CMD_FLUSH_CACHE);
        self.wait_not_busy()?;
        let status = self.read_status();
        if status & STATUS_ERR != 0 {
            return Err(String::from("ATA: flush error"));
        }
        Ok(())
    }

    /// Probe both master and slave drives on this channel.
    unsafe fn probe(&mut self) {
        self.software_reset();
        self.drives[0] = self.identify(0);
        self.drives[1] = self.identify(1);
    }
}

// ============================================================================
// Public API
// ============================================================================

/// Initialize the ATA subsystem: probe all channels and drives.
pub fn init() {
    let mut primary = AtaChannel::new(0x1F0, 0x3F6, AtaBus::Primary);
    let mut secondary = AtaChannel::new(0x170, 0x376, AtaBus::Secondary);

    unsafe {
        primary.probe();
        secondary.probe();
    }

    // Register discovered drives in the device registry
    register_drives(&primary);
    register_drives(&secondary);

    // Print discovery results to serial
    let mut found = 0u32;
    for drive in primary.drives.iter().chain(secondary.drives.iter()) {
        if let Some(d) = drive {
            crate::serial_println!(
                "[ata] {}.{}: {} — {} sectors ({} MiB) [LBA48={}]",
                d.bus.name(),
                if d.drive == 0 { "master" } else { "slave" },
                d.model,
                d.sectors,
                d.size_mb,
                d.lba48,
            );
            found += 1;
        }
    }
    if found == 0 {
        crate::serial_println!("[ata] no drives detected");
    }

    *ATA.lock() = Some(AtaController { primary, secondary });
}

/// Register discovered ATA drives in the device registry.
fn register_drives(channel: &AtaChannel) {
    for drive in &channel.drives {
        if let Some(d) = drive {
            let name = alloc::format!(
                "ata.{}.{}",
                d.bus.name(),
                if d.drive == 0 { "master" } else { "slave" }
            );
            crate::devices::register_device(
                &name,
                crate::devices::DeviceClass::Storage,
                crate::devices::DeviceState::Online,
                "ata-pio",
                "block:rw",
            );
        }
    }
}

/// Return information about all detected drives.
pub fn list_drives() -> Vec<AtaDrive> {
    let lock = ATA.lock();
    let mut result = Vec::new();
    if let Some(ref ctl) = *lock {
        for drive in ctl.primary.drives.iter().chain(ctl.secondary.drives.iter()) {
            if let Some(d) = drive {
                result.push(d.clone());
            }
        }
    }
    result
}

/// Check if a primary master drive is present.
pub fn has_primary_master() -> bool {
    let lock = ATA.lock();
    if let Some(ref ctl) = *lock {
        ctl.primary.drives[0].is_some()
    } else {
        false
    }
}

/// Get the primary master drive info (if present).
pub fn primary_master_info() -> Option<AtaDrive> {
    let lock = ATA.lock();
    if let Some(ref ctl) = *lock {
        ctl.primary.drives[0].clone()
    } else {
        None
    }
}

/// Read sectors from an ATA drive.
///
/// # Arguments
/// * `bus` - Which IDE channel
/// * `drive` - 0 for master, 1 for slave
/// * `lba` - Starting sector (LBA28)
/// * `count` - Number of sectors to read (1-256)
/// * `buf` - Output buffer (must be at least `count * 512` bytes)
pub fn read_sectors(
    bus: AtaBus,
    drive: u8,
    lba: u64,
    count: u16,
    buf: &mut [u8],
) -> Result<(), String> {
    let mut lock = ATA.lock();
    let ctl = lock
        .as_mut()
        .ok_or_else(|| String::from("ATA not initialized"))?;
    let channel = match bus {
        AtaBus::Primary => &mut ctl.primary,
        AtaBus::Secondary => &mut ctl.secondary,
    };
    if channel.drives[drive as usize].is_none() {
        return Err(String::from("ATA: no drive at that position"));
    }
    unsafe { channel.read_sectors(drive, lba, count, buf) }
}

/// Write sectors to an ATA drive.
///
/// # Arguments
/// * `bus` - Which IDE channel
/// * `drive` - 0 for master, 1 for slave
/// * `lba` - Starting sector (LBA28)
/// * `count` - Number of sectors to write (1-256)
/// * `buf` - Data to write (must be at least `count * 512` bytes)
pub fn write_sectors(
    bus: AtaBus,
    drive: u8,
    lba: u64,
    count: u16,
    buf: &[u8],
) -> Result<(), String> {
    let mut lock = ATA.lock();
    let ctl = lock
        .as_mut()
        .ok_or_else(|| String::from("ATA not initialized"))?;
    let channel = match bus {
        AtaBus::Primary => &mut ctl.primary,
        AtaBus::Secondary => &mut ctl.secondary,
    };
    if channel.drives[drive as usize].is_none() {
        return Err(String::from("ATA: no drive at that position"));
    }
    unsafe { channel.write_sectors(drive, lba, count, buf) }
}

/// Flush the write cache of an ATA drive.
pub fn flush(bus: AtaBus, drive: u8) -> Result<(), String> {
    let mut lock = ATA.lock();
    let ctl = lock
        .as_mut()
        .ok_or_else(|| String::from("ATA not initialized"))?;
    let channel = match bus {
        AtaBus::Primary => &mut ctl.primary,
        AtaBus::Secondary => &mut ctl.secondary,
    };
    if channel.drives[drive as usize].is_none() {
        return Err(String::from("ATA: no drive at that position"));
    }
    unsafe { channel.flush_cache(drive) }
}
