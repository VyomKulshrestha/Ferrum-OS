// ============================================================================
// FerrumOS - Block Device Abstraction
// ============================================================================
// Trait-based abstraction over raw sector I/O. Filesystem implementations
// program against this trait so they are decoupled from the specific disk
// driver (ATA PIO today, virtio-blk or NVMe tomorrow).
// ============================================================================

extern crate alloc;

use alloc::string::String;
use crate::ata::{AtaBus, SECTOR_SIZE};

/// A block device that can read and write fixed-size sectors.
pub trait BlockDevice: Send + Sync {
    /// Read a single sector at the given LBA into `buf`.
    /// `buf` must be at least `sector_size()` bytes.
    fn read_sector(&self, lba: u64, buf: &mut [u8]) -> Result<(), String>;

    /// Write a single sector at the given LBA from `buf`.
    /// `buf` must be at least `sector_size()` bytes.
    fn write_sector(&self, lba: u64, buf: &[u8]) -> Result<(), String>;

    /// Sector size in bytes (typically 512).
    fn sector_size(&self) -> usize;

    /// Total number of sectors on this device.
    fn sector_count(&self) -> u64;

    /// Flush any pending writes to stable storage.
    fn flush(&self) -> Result<(), String>;
}

/// ATA-backed block device wrapping the ATA PIO driver.
pub struct AtaBlockDevice {
    pub bus: AtaBus,
    pub drive: u8,
    pub sectors: u64,
}

impl AtaBlockDevice {
    /// Create a new ATA block device from drive info.
    pub fn new(bus: AtaBus, drive: u8, sectors: u64) -> Self {
        Self { bus, drive, sectors }
    }

    /// Create from primary master if present.
    pub fn from_primary_master() -> Option<Self> {
        let info = crate::ata::primary_master_info()?;
        Some(Self::new(info.bus, info.drive, info.sectors))
    }
}

impl BlockDevice for AtaBlockDevice {
    fn read_sector(&self, lba: u64, buf: &mut [u8]) -> Result<(), String> {
        if buf.len() < SECTOR_SIZE {
            return Err(String::from("buffer too small for sector read"));
        }
        crate::ata::read_sectors(self.bus, self.drive, lba, 1, buf)
    }

    fn write_sector(&self, lba: u64, buf: &[u8]) -> Result<(), String> {
        if buf.len() < SECTOR_SIZE {
            return Err(String::from("buffer too small for sector write"));
        }
        crate::ata::write_sectors(self.bus, self.drive, lba, 1, buf)
    }

    fn sector_size(&self) -> usize {
        SECTOR_SIZE
    }

    fn sector_count(&self) -> u64 {
        self.sectors
    }

    fn flush(&self) -> Result<(), String> {
        crate::ata::flush(self.bus, self.drive)
    }
}
