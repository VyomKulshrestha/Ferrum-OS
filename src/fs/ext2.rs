// ============================================================================
// FerrumOS - ext2 Filesystem Driver (Read-Write)
// ============================================================================
// Full read-write implementation of the ext2 filesystem.
// Supports Revision 0 and Revision 1, block sizes up to 4096 bytes,
// direct block pointers (up to 12 blocks), directory creation,
// file touch/creation, file deletion, and block/inode allocators.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::vec;
use core::mem::size_of;
use spin::Mutex;

use crate::fs::block::BlockDevice;
use crate::fs::vfs::Filesystem;
use crate::fs::{DirEntry, FsStat, FsUsage};

// ============================================================================
// Constants
// ============================================================================

pub const EXT2_MAGIC: u16 = 0xEF53;

// Inode mode constants (file types)
pub const S_IFMT: u16 = 0xF000;  // Type mask
pub const S_IFDIR: u16 = 0x4000; // Directory
pub const S_IFREG: u16 = 0x8000; // Regular file
pub const S_IFLNK: u16 = 0xA000; // Symbolic link

// Directory entry file types
pub const FT_UNKNOWN: u8 = 0;
pub const FT_REG_FILE: u8 = 1;
pub const FT_DIR: u8 = 2;
pub const FT_SYMLINK: u8 = 7;

// ============================================================================
// On-Disk Structures
// ============================================================================

#[repr(C, packed)]
#[derive(Clone, Copy, Debug)]
pub struct Superblock {
    pub inodes_count: u32,
    pub blocks_count: u32,
    pub r_blocks_count: u32,
    pub free_blocks_count: u32,
    pub free_inodes_count: u32,
    pub first_data_block: u32,
    pub log_block_size: u32,
    pub log_frag_size: u32,
    pub blocks_per_group: u32,
    pub frags_per_group: u32,
    pub inodes_per_group: u32,
    pub mtime: u32,
    pub wtime: u32,
    pub mnt_count: u16,
    pub max_mnt_count: u16,
    pub magic: u16,
    pub state: u16,
    pub errors: u16,
    pub minor_rev_level: u16,
    pub lastcheck: u32,
    pub checkinterval: u32,
    pub creator_os: u32,
    pub rev_level: u32,
    pub def_resuid: u16,
    pub def_resgid: u16,
    // Rev 1 fields:
    pub first_ino: u32,
    pub inode_size: u16,
    pub block_group_nr: u16,
    pub feature_compat: u32,
    pub feature_incompat: u32,
    pub feature_ro_compat: u32,
    pub uuid: [u8; 16],
    pub volume_name: [u8; 16],
    pub last_mounted: [u8; 64],
    pub algo_bitmap: u32,
    pub prealloc_blocks: u8,
    pub prealloc_dir_blocks: u8,
    pub alignment: u16,
    pub journal_uuid: [u8; 16],
    pub journal_inum: u32,
    pub journal_dev: u32,
    pub last_orphan: u32,
    pub hash_seed: [u32; 4],
    pub def_hash_version: u8,
    pub padding: [u8; 3],
    pub default_mount_options: u32,
    pub first_meta_bg: u32,
    pub unused_padding: [u8; 760],
}

#[repr(C, packed)]
#[derive(Clone, Copy, Debug)]
pub struct BlockGroupDescriptor {
    pub block_bitmap: u32,
    pub inode_bitmap: u32,
    pub inode_table: u32,
    pub free_blocks_count: u16,
    pub free_inodes_count: u16,
    pub used_dirs_count: u16,
    pub pad: u16,
    pub reserved: [u8; 12],
}

#[repr(C, packed)]
#[derive(Clone, Copy, Debug)]
pub struct Inode {
    pub mode: u16,
    pub uid: u16,
    pub size: u32,
    pub atime: u32,
    pub ctime: u32,
    pub mtime: u32,
    pub dtime: u32,
    pub gid: u16,
    pub links_count: u16,
    pub blocks: u32,
    pub flags: u32,
    pub osd1: u32,
    pub block: [u32; 15],
    pub generation: u32,
    pub file_acl: u32,
    pub dir_acl: u32,
    pub faddr: u32,
    pub osd2: [u8; 12],
}

#[repr(C, packed)]
#[derive(Clone, Copy, Debug)]
pub struct Ext2RawDirEntry {
    pub inode: u32,
    pub rec_len: u16,
    pub name_len: u8,
    pub file_type: u8,
}

// ============================================================================
// Directory Listing Abstraction
// ============================================================================

#[derive(Debug, Clone)]
pub struct Ext2DirEntry {
    pub inode: u32,
    pub file_type: u8,
    pub name: String,
}

// ============================================================================
// ext2 Filesystem State (Locked Inner Pattern)
// ============================================================================

pub struct Ext2FsInner<B: BlockDevice> {
    pub device: B,
    pub superblock: Superblock,
    pub group_descs: Vec<BlockGroupDescriptor>,
}

pub struct Ext2Fs<B: BlockDevice> {
    inner: Mutex<Ext2FsInner<B>>,
    pub block_size: u32,
    pub groups_count: u32,
}

// ============================================================================
// Internal Helpers
// ============================================================================

/// Safely copy bytes into a struct of type T, avoiding alignment requirements
unsafe fn from_bytes<T>(bytes: &[u8]) -> T {
    core::ptr::read_unaligned(bytes.as_ptr() as *const T)
}

/// Read block directly from block device using sector-based operations
fn read_raw_block(
    device: &dyn BlockDevice,
    block_size: u32,
    block: u32,
    buf: &mut [u8],
) -> Result<(), String> {
    let sector_size = device.sector_size();
    let sectors_per_block = (block_size as usize / sector_size) as u64;
    let start_lba = block as u64 * sectors_per_block;
    for i in 0..sectors_per_block {
        let offset = i as usize * sector_size;
        device.read_sector(start_lba + i, &mut buf[offset..offset + sector_size])?;
    }
    Ok(())
}

/// Write block directly to block device using sector-based operations
fn write_raw_block(
    device: &dyn BlockDevice,
    block_size: u32,
    block: u32,
    buf: &[u8],
) -> Result<(), String> {
    let sector_size = device.sector_size();
    let sectors_per_block = (block_size as usize / sector_size) as u64;
    let start_lba = block as u64 * sectors_per_block;
    for i in 0..sectors_per_block {
        let offset = i as usize * sector_size;
        device.write_sector(start_lba + i, &buf[offset..offset + sector_size])?;
    }
    Ok(())
}

/// Find the first free bit (0) in a bitmap buffer
fn find_free_bit(buf: &[u8]) -> Option<usize> {
    for (byte_idx, &byte) in buf.iter().enumerate() {
        if byte != 0xFF {
            for bit_idx in 0..8 {
                if (byte & (1 << bit_idx)) == 0 {
                    return Some(byte_idx * 8 + bit_idx);
                }
            }
        }
    }
    None
}

/// Set a specific bit in a bitmap buffer
fn set_bit(buf: &mut [u8], bit: usize, val: bool) {
    let byte_idx = bit / 8;
    let bit_idx = bit % 8;
    if val {
        buf[byte_idx] |= 1 << bit_idx;
    } else {
        buf[byte_idx] &= !(1 << bit_idx);
    }
}

// ============================================================================
// Implementation
// ============================================================================

impl<B: BlockDevice> Ext2Fs<B> {
    /// Mount an ext2 filesystem from a block device.
    pub fn mount(device: B) -> Result<Self, String> {
        let mut sb_buf = [0u8; 1024];
        device.read_sector(2, &mut sb_buf[0..512])?;
        device.read_sector(3, &mut sb_buf[512..1024])?;

        let superblock: Superblock = unsafe { from_bytes(&sb_buf) };
        let magic = superblock.magic;
        if magic != EXT2_MAGIC {
            return Err(alloc::format!("invalid ext2 magic: 0x{:X}", magic));
        }

        let block_size = 1024 << superblock.log_block_size;
        let inodes_per_group = superblock.inodes_per_group;
        if inodes_per_group == 0 {
            return Err(String::from("invalid inodes_per_group in superblock"));
        }

        let groups_count = (superblock.inodes_count + inodes_per_group - 1) / inodes_per_group;

        // Read block group descriptors
        let bgdt_block = superblock.first_data_block + 1;
        let bgdt_bytes_needed = groups_count as usize * size_of::<BlockGroupDescriptor>();
        let blocks_needed = (bgdt_bytes_needed + block_size as usize - 1) / block_size as usize;

        let mut bgdt_buf = Vec::new();
        bgdt_buf.resize(blocks_needed * block_size as usize, 0);

        for i in 0..blocks_needed {
            read_raw_block(
                &device,
                block_size,
                bgdt_block + i as u32,
                &mut bgdt_buf[i * block_size as usize..(i + 1) * block_size as usize],
            )?;
        }

        let mut group_descs = Vec::with_capacity(groups_count as usize);
        for g in 0..groups_count {
            let offset = g as usize * size_of::<BlockGroupDescriptor>();
            let desc: BlockGroupDescriptor = unsafe { from_bytes(&bgdt_buf[offset..offset + size_of::<BlockGroupDescriptor>()]) };
            group_descs.push(desc);
        }

        let inner = Ext2FsInner {
            device,
            superblock,
            group_descs,
        };

        Ok(Self {
            inner: Mutex::new(inner),
            block_size,
            groups_count,
        })
    }

    /// Create a sparse 64 MiB test file with exactly 3 blocks populated with known data:
    /// - Block 0 (offset 0)
    /// - Block 32768 (offset 32 MiB)
    /// - Block 65532 (offset 64 MiB - 4 KiB)
    pub fn create_test_mmap_file(&self, path: &str) -> Result<(), String> {
        let (parent_path, file_name) = split_path(path)?;
        let parent_inode_num = self.resolve_path(&parent_path)?;

        if self.resolve_path(path).is_ok() {
            return Ok(()); // already exists
        }

        let new_inode_num = self.alloc_inode()?;

        let blk0 = self.alloc_block()?;
        let blk32 = self.alloc_block()?;
        let blk64 = self.alloc_block()?;

        let mut b0 = vec![0u8; self.block_size as usize];
        let mut b32 = vec![0u8; self.block_size as usize];
        let mut b64 = vec![0u8; self.block_size as usize];
        b0[0..4].copy_from_slice(&[0x11, 0x22, 0x33, 0x44]);
        b32[0..4].copy_from_slice(&[0x55, 0x66, 0x77, 0x88]);
        b64[0..4].copy_from_slice(&[0xAA, 0xBB, 0xCC, 0xDD]);

        self.write_block(blk0, &b0)?;
        self.write_block(blk32, &b32)?;
        self.write_block(blk64, &b64)?;

        let mut inode = Inode {
            mode: S_IFREG | 0o644,
            uid: 0,
            size: 64 * 1024 * 1024, // 64 MiB
            atime: 0,
            ctime: 0,
            mtime: 0,
            dtime: 0,
            gid: 0,
            links_count: 1,
            blocks: (3 * self.block_size / 512) as u32,
            flags: 0,
            osd1: 0,
            block: [0; 15],
            generation: 0,
            file_acl: 0,
            dir_acl: 0,
            faddr: 0,
            osd2: [0; 12],
        };

        inode.block[0] = blk0;

        let dib = self.alloc_block()?;
        let mut dib_buf = vec![0u8; self.block_size as usize];
        inode.block[13] = dib;

        let sib1 = self.alloc_block()?;
        let mut sib1_buf = vec![0u8; self.block_size as usize];

        let sib2 = self.alloc_block()?;
        let mut sib2_buf = vec![0u8; self.block_size as usize];

        unsafe {
            let dib_ptr = dib_buf.as_mut_ptr() as *mut u32;
            let sib1_ptr = sib1_buf.as_mut_ptr() as *mut u32;
            let sib2_ptr = sib2_buf.as_mut_ptr() as *mut u32;

            core::ptr::write_unaligned(dib_ptr.add(126), sib1);
            core::ptr::write_unaligned(sib1_ptr.add(244), blk32);

            core::ptr::write_unaligned(dib_ptr.add(254), sib2);
            core::ptr::write_unaligned(sib2_ptr.add(240), blk64);
        }

        self.write_block(dib, &dib_buf)?;
        self.write_block(sib1, &sib1_buf)?;
        self.write_block(sib2, &sib2_buf)?;

        self.write_inode(new_inode_num, &inode)?;

        self.add_dir_entry(parent_inode_num, &file_name, new_inode_num, FT_REG_FILE)?;
        self.write_metadata()?;

        Ok(())
    }

    /// Read an ext2 block using the filesystem's block size.
    pub fn read_block(&self, block: u32, buf: &mut [u8]) -> Result<(), String> {
        let inner = self.inner.lock();
        read_raw_block(&inner.device, self.block_size, block, buf)
    }

    /// Write an ext2 block using the filesystem's block size.
    pub fn write_block(&self, block: u32, buf: &[u8]) -> Result<(), String> {
        let inner = self.inner.lock();
        write_raw_block(&inner.device, self.block_size, block, buf)
    }

    /// Read an Inode structure by its 1-indexed inode number.
    pub fn read_inode(&self, inode_num: u32) -> Result<Inode, String> {
        let inner = self.inner.lock();
        self.read_inode_inner(&inner, inode_num)
    }

    fn read_inode_inner(&self, inner: &Ext2FsInner<B>, inode_num: u32) -> Result<Inode, String> {
        if inode_num == 0 || inode_num > inner.superblock.inodes_count {
            return Err(alloc::format!("invalid inode number: {}", inode_num));
        }

        let inodes_per_group = inner.superblock.inodes_per_group;
        let group = (inode_num - 1) / inodes_per_group;
        let index = (inode_num - 1) % inodes_per_group;

        if group >= self.groups_count {
            return Err(alloc::format!("inode group out of bounds: {}", group));
        }

        let desc = &inner.group_descs[group as usize];
        let inode_size = if inner.superblock.rev_level >= 1 {
            inner.superblock.inode_size as usize
        } else {
            128
        };

        let byte_offset = index as usize * inode_size;
        let block_offset = (byte_offset / self.block_size as usize) as u32;
        let offset_in_block = byte_offset % self.block_size as usize;

        let target_block = desc.inode_table + block_offset;
        let mut block_buf = Vec::new();
        block_buf.resize(self.block_size as usize, 0);
        read_raw_block(&inner.device, self.block_size, target_block, &mut block_buf)?;

        let inode: Inode = unsafe { from_bytes(&block_buf[offset_in_block..offset_in_block + 128]) };
        Ok(inode)
    }

    /// Write an Inode structure to the disk.
    pub fn write_inode(&self, inode_num: u32, inode: &Inode) -> Result<(), String> {
        let inner = self.inner.lock();
        let block_size = self.block_size;
        let inodes_per_group = inner.superblock.inodes_per_group;

        let group = (inode_num - 1) / inodes_per_group;
        let index = (inode_num - 1) % inodes_per_group;

        let desc = &inner.group_descs[group as usize];
        let inode_size = if inner.superblock.rev_level >= 1 {
            inner.superblock.inode_size as usize
        } else {
            128
        };

        let byte_offset = index as usize * inode_size;
        let block_offset = (byte_offset / block_size as usize) as u32;
        let offset_in_block = byte_offset % block_size as usize;

        let target_block = desc.inode_table + block_offset;
        let mut block_buf = Vec::new();
        block_buf.resize(block_size as usize, 0);
        read_raw_block(&inner.device, block_size, target_block, &mut block_buf)?;

        unsafe {
            core::ptr::write_unaligned(
                block_buf.as_mut_ptr().add(offset_in_block) as *mut Inode,
                *inode,
            );
        }

        write_raw_block(&inner.device, block_size, target_block, &block_buf)?;
        Ok(())
    }

    /// Resolve a logical file block index to a physical block index on disk.
    pub fn get_phys_block(&self, inode: &Inode, file_block: u32) -> Result<u32, String> {
        let inner = self.inner.lock();
        self.get_phys_block_inner(&inner, inode, file_block)
    }

    fn get_phys_block_inner(&self, inner: &Ext2FsInner<B>, inode: &Inode, file_block: u32) -> Result<u32, String> {
        let pointers_per_block = (self.block_size / 4) as u32;

        // Direct blocks: 0 to 11
        if file_block < 12 {
            return Ok(inode.block[file_block as usize]);
        }

        let mut index = file_block - 12;

        // Single indirect block: inode.block[12]
        if index < pointers_per_block {
            let sib = inode.block[12];
            if sib == 0 {
                return Ok(0); // sparse block
            }
            let mut sib_buf = Vec::new();
            sib_buf.resize(self.block_size as usize, 0);
            read_raw_block(&inner.device, self.block_size, sib, &mut sib_buf)?;
            let phys = unsafe { *(sib_buf.as_ptr().add(index as usize * 4) as *const u32) };
            return Ok(phys);
        }

        index -= pointers_per_block;

        // Double indirect block: inode.block[13]
        let double_limit = pointers_per_block * pointers_per_block;
        if index < double_limit {
            let dib = inode.block[13];
            if dib == 0 {
                return Ok(0);
            }
            let mut dib_buf = Vec::new();
            dib_buf.resize(self.block_size as usize, 0);
            read_raw_block(&inner.device, self.block_size, dib, &mut dib_buf)?;

            let outer_idx = index / pointers_per_block;
            let inner_idx = index % pointers_per_block;

            let sib = unsafe { *(dib_buf.as_ptr().add(outer_idx as usize * 4) as *const u32) };
            if sib == 0 {
                return Ok(0);
            }

            let mut sib_buf = Vec::new();
            sib_buf.resize(self.block_size as usize, 0);
            read_raw_block(&inner.device, self.block_size, sib, &mut sib_buf)?;

            let phys = unsafe { *(sib_buf.as_ptr().add(inner_idx as usize * 4) as *const u32) };
            return Ok(phys);
        }

        index -= double_limit;

        // Triple indirect block: inode.block[14]
        let triple_limit = double_limit * pointers_per_block;
        if index < triple_limit {
            let tib = inode.block[14];
            if tib == 0 {
                return Ok(0);
            }
            let mut tib_buf = Vec::new();
            tib_buf.resize(self.block_size as usize, 0);
            read_raw_block(&inner.device, self.block_size, tib, &mut tib_buf)?;

            let outer_idx = index / double_limit;
            let remainder = index % double_limit;
            let mid_idx = remainder / pointers_per_block;
            let inner_idx = remainder % pointers_per_block;

            let dib = unsafe { *(tib_buf.as_ptr().add(outer_idx as usize * 4) as *const u32) };
            if dib == 0 {
                return Ok(0);
            }

            let mut dib_buf = Vec::new();
            dib_buf.resize(self.block_size as usize, 0);
            read_raw_block(&inner.device, self.block_size, dib, &mut dib_buf)?;

            let sib = unsafe { *(dib_buf.as_ptr().add(mid_idx as usize * 4) as *const u32) };
            if sib == 0 {
                return Ok(0);
            }

            let mut sib_buf = Vec::new();
            sib_buf.resize(self.block_size as usize, 0);
            read_raw_block(&inner.device, self.block_size, sib, &mut sib_buf)?;

            let phys = unsafe { *(sib_buf.as_ptr().add(inner_idx as usize * 4) as *const u32) };
            return Ok(phys);
        }

        Err(String::from("file block index out of bounds"))
    }

    /// Read the complete contents of an inode's data blocks.
    pub fn read_inode_data(&self, inode: &Inode) -> Result<Vec<u8>, String> {
        let inner = self.inner.lock();
        self.read_inode_data_inner(&inner, inode)
    }

    fn read_inode_data_inner(&self, inner: &Ext2FsInner<B>, inode: &Inode) -> Result<Vec<u8>, String> {
        let size = if (inode.mode & S_IFMT) == S_IFREG {
            let size_high = inode.dir_acl as u64;
            inode.size as u64 | (size_high << 32)
        } else {
            inode.size as u64
        };

        let mut data = Vec::with_capacity(size as usize);
        let block_size = self.block_size as u64;
        let mut bytes_left = size;
        let mut file_block = 0u32;

        let mut block_buf = Vec::new();
        block_buf.resize(self.block_size as usize, 0);

        while bytes_left > 0 {
            let phys_block = self.get_phys_block_inner(inner, inode, file_block)?;
            let to_read = core::cmp::min(bytes_left, block_size);

            if phys_block == 0 {
                data.extend_from_slice(&vec![0u8; to_read as usize]);
            } else {
                read_raw_block(&inner.device, self.block_size, phys_block, &mut block_buf)?;
                data.extend_from_slice(&block_buf[0..to_read as usize]);
            }

            bytes_left -= to_read;
            file_block += 1;
        }

        Ok(data)
    }

    /// Read all directory entries from a directory inode.
    pub fn read_dir_entries(&self, inode: &Inode) -> Result<Vec<Ext2DirEntry>, String> {
        let inner = self.inner.lock();
        self.read_dir_entries_inner(&inner, inode)
    }

    fn read_dir_entries_inner(&self, inner: &Ext2FsInner<B>, inode: &Inode) -> Result<Vec<Ext2DirEntry>, String> {
        if (inode.mode & S_IFMT) != S_IFDIR {
            return Err(String::from("inode is not a directory"));
        }

        let data = self.read_inode_data_inner(inner, inode)?;
        let mut entries = Vec::new();
        let mut offset = 0;
        let data_len = data.len();

        while offset + size_of::<Ext2RawDirEntry>() <= data_len {
            let entry: Ext2RawDirEntry = unsafe { from_bytes(&data[offset..offset + size_of::<Ext2RawDirEntry>()]) };
            if entry.rec_len == 0 {
                break; // avoid infinite loop
            }

            if entry.inode != 0 && entry.name_len > 0 {
                let name_start = offset + size_of::<Ext2RawDirEntry>();
                let name_end = name_start + entry.name_len as usize;
                if name_end <= data_len {
                    let name_bytes = &data[name_start..name_end];
                    if let Ok(name_str) = core::str::from_utf8(name_bytes) {
                        entries.push(Ext2DirEntry {
                            inode: entry.inode,
                            file_type: entry.file_type,
                            name: String::from(name_str),
                        });
                    }
                }
            }

            offset += entry.rec_len as usize;
        }

        Ok(entries)
    }

    /// Read the target of a symbolic link inode.
    pub fn read_link(&self, inode: &Inode) -> Result<String, String> {
        let inner = self.inner.lock();
        let size = inode.size as usize;
        if size < 60 {
            // Fast symlink: path is in inode.block
            let ptr = core::ptr::addr_of!(inode.block) as *const u8;
            let bytes = unsafe { core::slice::from_raw_parts(ptr, size) };
            core::str::from_utf8(bytes)
                .map(String::from)
                .map_err(|e| alloc::format!("invalid utf-8 in symlink: {:?}", e))
        } else {
            // Normal symlink: read data blocks
            let data = self.read_inode_data_inner(&inner, inode)?;
            core::str::from_utf8(&data[0..size])
                .map(String::from)
                .map_err(|e| alloc::format!("invalid utf-8 in symlink: {:?}", e))
        }
    }

    /// Resolve an absolute or relative path starting at the root directory (inode 2).
    pub fn resolve_path(&self, path: &str) -> Result<u32, String> {
        let inner = self.inner.lock();
        self.resolve_path_inner(&inner, path)
    }

    fn resolve_path_inner(&self, inner: &Ext2FsInner<B>, path: &str) -> Result<u32, String> {
        let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
        let mut current_inode = 2u32; // Root inode

        for part in parts {
            let inode = self.read_inode_inner(inner, current_inode)?;
            if (inode.mode & S_IFMT) != S_IFDIR {
                return Err(alloc::format!("not a directory during path resolution: {}", part));
            }

            let entries = self.read_dir_entries_inner(inner, &inode)?;
            let mut found = None;
            for entry in entries {
                if entry.name == part {
                    found = Some(entry.inode);
                    break;
                }
            }

            current_inode = found.ok_or_else(|| alloc::format!("file not found: {}", part))?;
        }

        Ok(current_inode)
    }

    // ============================================================================
    // Write Utilities & Allocators
    // ============================================================================

    /// Write all metadata back to the device.
    pub fn write_metadata(&self) -> Result<(), String> {
        let inner = self.inner.lock();
        // 1. Write Superblock
        let mut sb_buf = [0u8; 1024];
        unsafe {
            core::ptr::write_unaligned(sb_buf.as_mut_ptr() as *mut Superblock, inner.superblock);
        }
        inner.device.write_sector(2, &sb_buf[0..512])?;
        inner.device.write_sector(3, &sb_buf[512..1024])?;

        // 2. Write BGDT
        let bgdt_block = inner.superblock.first_data_block + 1;
        let bgdt_bytes_needed = self.groups_count as usize * size_of::<BlockGroupDescriptor>();
        let blocks_needed = (bgdt_bytes_needed + self.block_size as usize - 1) / self.block_size as usize;

        let mut bgdt_buf = Vec::new();
        bgdt_buf.resize(blocks_needed * self.block_size as usize, 0);

        for g in 0..self.groups_count {
            let offset = g as usize * size_of::<BlockGroupDescriptor>();
            unsafe {
                core::ptr::write_unaligned(
                    bgdt_buf.as_mut_ptr().add(offset) as *mut BlockGroupDescriptor,
                    inner.group_descs[g as usize],
                );
            }
        }

        for i in 0..blocks_needed {
            write_raw_block(
                &inner.device,
                self.block_size,
                bgdt_block + i as u32,
                &bgdt_buf[i * self.block_size as usize..(i + 1) * self.block_size as usize],
            )?;
        }

        inner.device.flush()
    }

    /// Allocate a block in the filesystem.
    fn alloc_block(&self) -> Result<u32, String> {
        let mut inner = self.inner.lock();
        let block_size = self.block_size;

        for g in 0..self.groups_count {
            let desc = &inner.group_descs[g as usize];
            if desc.free_blocks_count == 0 {
                continue;
            }

            let mut bitmap_buf = Vec::new();
            bitmap_buf.resize(block_size as usize, 0);
            read_raw_block(&inner.device, block_size, desc.block_bitmap, &mut bitmap_buf)?;

            if let Some(bit) = find_free_bit(&bitmap_buf) {
                let blocks_per_group = inner.superblock.blocks_per_group;
                if bit >= blocks_per_group as usize {
                    continue;
                }

                set_bit(&mut bitmap_buf, bit, true);
                write_raw_block(&inner.device, block_size, desc.block_bitmap, &bitmap_buf)?;

                let desc_mut = &mut inner.group_descs[g as usize];
                desc_mut.free_blocks_count -= 1;
                inner.superblock.free_blocks_count -= 1;

                let phys_block = g * blocks_per_group + inner.superblock.first_data_block + bit as u32;
                return Ok(phys_block);
            }
        }
        Err(String::from("ext2: out of free blocks"))
    }

    /// Free a block in the filesystem.
    fn free_block(&self, block: u32) -> Result<(), String> {
        let mut inner = self.inner.lock();
        let block_size = self.block_size;
        let first_data = inner.superblock.first_data_block;
        let blocks_per_group = inner.superblock.blocks_per_group;

        if block < first_data {
            return Err(String::from("ext2: invalid block to free"));
        }

        let relative_block = block - first_data;
        let g = relative_block / blocks_per_group;
        let bit = (relative_block % blocks_per_group) as usize;

        if g >= self.groups_count {
            return Err(String::from("ext2: block to free out of group bounds"));
        }

        let desc = &inner.group_descs[g as usize];
        let mut bitmap_buf = Vec::new();
        bitmap_buf.resize(block_size as usize, 0);
        read_raw_block(&inner.device, block_size, desc.block_bitmap, &mut bitmap_buf)?;

        set_bit(&mut bitmap_buf, bit, false);
        write_raw_block(&inner.device, block_size, desc.block_bitmap, &bitmap_buf)?;

        let desc_mut = &mut inner.group_descs[g as usize];
        desc_mut.free_blocks_count += 1;
        inner.superblock.free_blocks_count += 1;

        Ok(())
    }

    /// Allocate an inode in the filesystem.
    fn alloc_inode(&self) -> Result<u32, String> {
        let mut inner = self.inner.lock();
        let block_size = self.block_size;

        for g in 0..self.groups_count {
            let desc = &inner.group_descs[g as usize];
            if desc.free_inodes_count == 0 {
                continue;
            }

            let mut bitmap_buf = Vec::new();
            bitmap_buf.resize(block_size as usize, 0);
            read_raw_block(&inner.device, block_size, desc.inode_bitmap, &mut bitmap_buf)?;

            if let Some(bit) = find_free_bit(&bitmap_buf) {
                let inodes_per_group = inner.superblock.inodes_per_group;
                if bit >= inodes_per_group as usize {
                    continue;
                }

                set_bit(&mut bitmap_buf, bit, true);
                write_raw_block(&inner.device, block_size, desc.inode_bitmap, &bitmap_buf)?;

                let desc_mut = &mut inner.group_descs[g as usize];
                desc_mut.free_inodes_count -= 1;
                inner.superblock.free_inodes_count -= 1;

                let inode_num = g * inodes_per_group + bit as u32 + 1;
                return Ok(inode_num);
            }
        }
        Err(String::from("ext2: out of free inodes"))
    }

    /// Free an inode in the filesystem.
    fn free_inode(&self, inode_num: u32) -> Result<(), String> {
        let mut inner = self.inner.lock();
        let block_size = self.block_size;
        let inodes_per_group = inner.superblock.inodes_per_group;

        if inode_num == 0 || inode_num > inner.superblock.inodes_count {
            return Err(String::from("ext2: invalid inode number to free"));
        }

        let g = (inode_num - 1) / inodes_per_group;
        let bit = ((inode_num - 1) % inodes_per_group) as usize;

        let desc = &inner.group_descs[g as usize];
        let mut bitmap_buf = Vec::new();
        bitmap_buf.resize(block_size as usize, 0);
        read_raw_block(&inner.device, block_size, desc.inode_bitmap, &mut bitmap_buf)?;

        set_bit(&mut bitmap_buf, bit, false);
        write_raw_block(&inner.device, block_size, desc.inode_bitmap, &bitmap_buf)?;

        let desc_mut = &mut inner.group_descs[g as usize];
        desc_mut.free_inodes_count += 1;
        inner.superblock.free_inodes_count += 1;

        Ok(())
    }

    /// Append a directory entry to parent directory.
    fn add_dir_entry(
        &self,
        parent_inode_num: u32,
        name: &str,
        inode_num: u32,
        file_type: u8,
    ) -> Result<(), String> {
        let parent_inode = self.read_inode(parent_inode_num)?;
        let block_size = self.block_size as usize;

        let mut parent_blocks = Vec::new();
        let mut file_block = 0;
        loop {
            let phys = self.get_phys_block(&parent_inode, file_block)?;
            if phys == 0 {
                break;
            }
            parent_blocks.push(phys);
            file_block += 1;
        }

        // Try to insert in existing directory blocks
        for &phys in &parent_blocks {
            let mut buf = Vec::new();
            buf.resize(block_size, 0);
            self.read_block(phys, &mut buf)?;

            let mut offset = 0;
            while offset < block_size {
                let entry: Ext2RawDirEntry = unsafe { from_bytes(&buf[offset..]) };
                if entry.rec_len == 0 {
                    break;
                }

                let name_len = entry.name_len as usize;
                let actual_len = (size_of::<Ext2RawDirEntry>() + name_len + 3) & !3;

                // Check if this is the last entry in this block
                if offset + entry.rec_len as usize >= block_size {
                    let needed_len = (size_of::<Ext2RawDirEntry>() + name.len() + 3) & !3;
                    if entry.rec_len as usize - actual_len >= needed_len {
                        // Split it
                        let old_rec_len = entry.rec_len;
                        let mut updated_entry = entry;
                        updated_entry.rec_len = actual_len as u16;
                        unsafe {
                            core::ptr::write_unaligned(
                                buf.as_mut_ptr().add(offset) as *mut Ext2RawDirEntry,
                                updated_entry,
                            );
                        }

                        let new_offset = offset + actual_len;
                        let new_entry = Ext2RawDirEntry {
                            inode: inode_num,
                            rec_len: (old_rec_len as usize - actual_len) as u16,
                            name_len: name.len() as u8,
                            file_type,
                        };
                        unsafe {
                            core::ptr::write_unaligned(
                                buf.as_mut_ptr().add(new_offset) as *mut Ext2RawDirEntry,
                                new_entry,
                            );
                        }
                        buf[new_offset + size_of::<Ext2RawDirEntry>()..new_offset + size_of::<Ext2RawDirEntry>() + name.len()]
                            .copy_from_slice(name.as_bytes());

                        self.write_block(phys, &buf)?;
                        return Ok(());
                    }
                    break;
                }

                offset += entry.rec_len as usize;
            }
        }

        // Allocate a new block for the directory
        let new_block = self.alloc_block()?;
        let mut buf = Vec::new();
        buf.resize(block_size, 0);

        let new_entry = Ext2RawDirEntry {
            inode: inode_num,
            rec_len: block_size as u16,
            name_len: name.len() as u8,
            file_type,
        };
        unsafe {
            core::ptr::write_unaligned(buf.as_mut_ptr() as *mut Ext2RawDirEntry, new_entry);
        }
        buf[size_of::<Ext2RawDirEntry>()..size_of::<Ext2RawDirEntry>() + name.len()]
            .copy_from_slice(name.as_bytes());

        self.write_block(new_block, &buf)?;

        let mut updated_parent = parent_inode;
        let mut assigned = false;
        for i in 0..12 {
            if updated_parent.block[i] == 0 {
                updated_parent.block[i] = new_block;
                assigned = true;
                break;
            }
        }

        if !assigned {
            self.free_block(new_block)?;
            return Err(String::from("ext2: directory entries direct block limit exceeded"));
        }

        updated_parent.size += block_size as u32;
        updated_parent.blocks += (block_size / 512) as u32;
        self.write_inode(parent_inode_num, &updated_parent)?;

        Ok(())
    }

    /// Remove a directory entry from parent directory.
    fn remove_dir_entry(&self, parent_inode_num: u32, name: &str) -> Result<(), String> {
        let parent_inode = self.read_inode(parent_inode_num)?;
        let block_size = self.block_size as usize;

        let mut file_block = 0;
        loop {
            let phys = self.get_phys_block(&parent_inode, file_block)?;
            if phys == 0 {
                break;
            }

            let mut buf = Vec::new();
            buf.resize(block_size, 0);
            self.read_block(phys, &mut buf)?;

            let mut offset = 0;
            let mut prev_offset = None;

            while offset < block_size {
                let entry: Ext2RawDirEntry = unsafe { from_bytes(&buf[offset..]) };
                if entry.rec_len == 0 {
                    break;
                }

                let name_start = offset + size_of::<Ext2RawDirEntry>();
                let name_end = name_start + entry.name_len as usize;
                let name_bytes = &buf[name_start..name_end];
                if let Ok(name_str) = core::str::from_utf8(name_bytes) {
                    if name_str == name {
                        if let Some(prev) = prev_offset {
                            let mut prev_entry: Ext2RawDirEntry = unsafe { from_bytes(&buf[prev..]) };
                            prev_entry.rec_len += entry.rec_len;
                            unsafe {
                                core::ptr::write_unaligned(
                                    buf.as_mut_ptr().add(prev) as *mut Ext2RawDirEntry,
                                    prev_entry,
                                );
                            }
                        } else {
                            let mut updated_entry = entry;
                            updated_entry.inode = 0;
                            unsafe {
                                core::ptr::write_unaligned(
                                    buf.as_mut_ptr() as *mut Ext2RawDirEntry,
                                    updated_entry,
                                );
                            }
                        }

                        self.write_block(phys, &buf)?;
                        return Ok(());
                    }
                }

                prev_offset = Some(offset);
                offset += entry.rec_len as usize;
            }

            file_block += 1;
        }

        Err(alloc::format!("file not found in directory: {}", name))
    }
}

// ============================================================================
// Filesystem Trait Implementation
// ============================================================================

impl<B: BlockDevice> Filesystem for Ext2Fs<B> {
    fn list_dir(&self, path: &str) -> Result<Vec<DirEntry>, String> {
        let inode_num = self.resolve_path(path)?;
        let inode = self.read_inode(inode_num)?;
        let entries = self.read_dir_entries(&inode)?;
        
        let mut result = Vec::new();
        for entry in entries {
            let child_inode = self.read_inode(entry.inode)?;
            let is_dir = (child_inode.mode & S_IFMT) == S_IFDIR;
            let size = if is_dir {
                0
            } else {
                child_inode.size as usize
            };
            result.push(DirEntry {
                name: entry.name,
                is_dir,
                size,
            });
        }
        Ok(result)
    }

    fn read_file(&self, path: &str) -> Result<String, String> {
        let inode_num = self.resolve_path(path)?;
        let inode = self.read_inode(inode_num)?;
        if (inode.mode & S_IFMT) != S_IFREG {
            return Err(String::from("not a regular file"));
        }
        let data = self.read_inode_data(&inode)?;
        String::from_utf8(data)
            .map_err(|_| String::from("file content is not valid UTF-8"))
    }

    fn read_file_offset(&self, path: &str, offset: u64, buf: &mut [u8]) -> Result<usize, String> {
        let inode_num = self.resolve_path(path)?;
        let inode = self.read_inode(inode_num)?;
        if (inode.mode & S_IFMT) != S_IFREG {
            return Err(String::from("not a regular file"));
        }

        let size = if (inode.mode & S_IFMT) == S_IFREG {
            let size_high = inode.dir_acl as u64;
            inode.size as u64 | (size_high << 32)
        } else {
            inode.size as u64
        };

        if offset >= size {
            return Ok(0);
        }

        let to_read_total = core::cmp::min(buf.len() as u64, size - offset) as usize;
        let mut bytes_read = 0;
        let block_size = self.block_size as u64;

        let mut block_buf = vec![0u8; self.block_size as usize];
        let inner = self.inner.lock();

        while bytes_read < to_read_total {
            let curr_offset = offset + bytes_read as u64;
            let file_block = (curr_offset / block_size) as u32;
            let block_offset = (curr_offset % block_size) as usize;

            let phys_block = self.get_phys_block_inner(&inner, &inode, file_block)?;
            let chunk_len = core::cmp::min(to_read_total - bytes_read, (block_size - block_offset as u64) as usize);

            if phys_block == 0 {
                buf[bytes_read..bytes_read + chunk_len].fill(0);
            } else {
                read_raw_block(&inner.device, self.block_size, phys_block, &mut block_buf)?;
                buf[bytes_read..bytes_read + chunk_len].copy_from_slice(&block_buf[block_offset..block_offset + chunk_len]);
            }

            bytes_read += chunk_len;
        }

        Ok(bytes_read)
    }

    /// Create a file, or overwrite it in place if it already exists (matching
    /// the in-memory vfs's `create_file`, and what every caller of `write`
    /// already assumes - see `work.md` finding 2.1). New content is fully
    /// allocated and written before any of the old file's blocks are freed,
    /// so a failure partway through leaves the original file untouched.
    fn create_file(&self, path: &str, content: &str) -> Result<(), String> {
        let (parent_path, file_name) = split_path(path)?;
        let parent_inode_num = self.resolve_path(&parent_path)?;

        let existing = match self.resolve_path(path) {
            Ok(inode_num) => {
                let inode = self.read_inode(inode_num)?;
                if (inode.mode & S_IFMT) != S_IFREG {
                    return Err(String::from("write: not a regular file"));
                }
                Some((inode_num, inode))
            }
            Err(_) => None,
        };

        let new_inode_num = match &existing {
            Some((inode_num, _)) => *inode_num,
            None => self.alloc_inode()?,
        };
        let block_size = self.block_size as usize;
        let content_bytes = content.as_bytes();
        let mut blocks_allocated = Vec::new();

        let chunks = (content_bytes.len() + block_size - 1) / block_size;
        for i in 0..chunks {
            match self.alloc_block() {
                Ok(blk) => {
                    blocks_allocated.push(blk);
                    let offset = i * block_size;
                    let to_write = core::cmp::min(content_bytes.len() - offset, block_size);
                    let mut chunk_buf = Vec::new();
                    chunk_buf.resize(block_size, 0);
                    chunk_buf[0..to_write].copy_from_slice(&content_bytes[offset..offset + to_write]);
                    if let Err(e) = self.write_block(blk, &chunk_buf) {
                        for &b in &blocks_allocated {
                            let _ = self.free_block(b);
                        }
                        if existing.is_none() {
                            let _ = self.free_inode(new_inode_num);
                        }
                        return Err(e);
                    }
                }
                Err(e) => {
                    for &b in &blocks_allocated {
                        let _ = self.free_block(b);
                    }
                    if existing.is_none() {
                        let _ = self.free_inode(new_inode_num);
                    }
                    return Err(e);
                }
            }
        }

        if chunks > 12 {
            for &b in &blocks_allocated {
                let _ = self.free_block(b);
            }
            if existing.is_none() {
                let _ = self.free_inode(new_inode_num);
            }
            return Err(String::from("ext2: file size exceeds direct block limit (12 blocks)"));
        }

        let mut inode = Inode {
            mode: S_IFREG | 0o644,
            uid: 0,
            size: content_bytes.len() as u32,
            atime: 0,
            ctime: 0,
            mtime: 0,
            dtime: 0,
            gid: 0,
            links_count: 1,
            blocks: (chunks * block_size / 512) as u32,
            flags: 0,
            osd1: 0,
            block: [0; 15],
            generation: 0,
            file_acl: 0,
            dir_acl: 0,
            faddr: 0,
            osd2: [0; 12],
        };

        for (i, &blk) in blocks_allocated.iter().enumerate() {
            inode.block[i] = blk;
        }

        // New content is safely on disk at this point - now it's safe to
        // free the old file's data blocks (if this was an overwrite).
        if let Some((_, old_inode)) = &existing {
            let old_size = old_inode.size as usize;
            let old_blocks: [u32; 15] = old_inode.block;
            let old_chunks = (old_size + block_size - 1) / block_size;
            for &blk in old_blocks.iter().take(old_chunks.min(old_blocks.len())) {
                if blk != 0 {
                    let _ = self.free_block(blk);
                }
            }
        }

        self.write_inode(new_inode_num, &inode)?;

        if existing.is_none() {
            if let Err(e) = self.add_dir_entry(parent_inode_num, &file_name, new_inode_num, FT_REG_FILE) {
                for &b in &blocks_allocated {
                    let _ = self.free_block(b);
                }
                let _ = self.free_inode(new_inode_num);
                return Err(e);
            }
        }

        self.write_metadata()?;
        Ok(())
    }

    fn create_dir(&self, path: &str) -> Result<(), String> {
        let (parent_path, dir_name) = split_path(path)?;
        let parent_inode_num = self.resolve_path(&parent_path)?;

        if self.resolve_path(path).is_ok() {
            return Err(String::from("directory already exists"));
        }

        let new_inode_num = self.alloc_inode()?;
        let new_block_num = match self.alloc_block() {
            Ok(blk) => blk,
            Err(e) => {
                let _ = self.free_inode(new_inode_num);
                return Err(e);
            }
        };

        let block_size = self.block_size as usize;
        let mut buf = Vec::new();
        buf.resize(block_size, 0);

        let entry_self = Ext2RawDirEntry {
            inode: new_inode_num,
            rec_len: 12,
            name_len: 1,
            file_type: FT_DIR,
        };
        unsafe {
            core::ptr::write_unaligned(buf.as_mut_ptr() as *mut Ext2RawDirEntry, entry_self);
        }
        buf[8] = b'.';

        let entry_parent = Ext2RawDirEntry {
            inode: parent_inode_num,
            rec_len: (block_size - 12) as u16,
            name_len: 2,
            file_type: FT_DIR,
        };
        unsafe {
            core::ptr::write_unaligned(buf.as_mut_ptr().add(12) as *mut Ext2RawDirEntry, entry_parent);
        }
        buf[20] = b'.';
        buf[21] = b'.';

        if let Err(e) = self.write_block(new_block_num, &buf) {
            let _ = self.free_block(new_block_num);
            let _ = self.free_inode(new_inode_num);
            return Err(e);
        }

        let mut inode = Inode {
            mode: S_IFDIR | 0o755,
            uid: 0,
            size: block_size as u32,
            atime: 0,
            ctime: 0,
            mtime: 0,
            dtime: 0,
            gid: 0,
            links_count: 2,
            blocks: (block_size / 512) as u32,
            flags: 0,
            osd1: 0,
            block: [0; 15],
            generation: 0,
            file_acl: 0,
            dir_acl: 0,
            faddr: 0,
            osd2: [0; 12],
        };
        inode.block[0] = new_block_num;

        if let Err(e) = self.write_inode(new_inode_num, &inode) {
            let _ = self.free_block(new_block_num);
            let _ = self.free_inode(new_inode_num);
            return Err(e);
        }

        if let Err(e) = self.add_dir_entry(parent_inode_num, &dir_name, new_inode_num, FT_DIR) {
            let _ = self.free_block(new_block_num);
            let _ = self.free_inode(new_inode_num);
            return Err(e);
        }

        let mut parent_inode = self.read_inode(parent_inode_num)?;
        parent_inode.links_count += 1;
        self.write_inode(parent_inode_num, &parent_inode)?;

        let group;
        {
            let mut inner = self.inner.lock();
            group = (new_inode_num - 1) / inner.superblock.inodes_per_group;
            let desc_mut = &mut inner.group_descs[group as usize];
            desc_mut.used_dirs_count += 1;
        }

        self.write_metadata()?;
        Ok(())
    }

    fn remove(&self, path: &str) -> Result<(), String> {
        let (parent_path, name) = split_path(path)?;
        let parent_inode_num = self.resolve_path(&parent_path)?;
        let target_inode_num = self.resolve_path(path)?;

        let target_inode = self.read_inode(target_inode_num)?;
        let is_dir = (target_inode.mode & S_IFMT) == S_IFDIR;

        if is_dir {
            let entries = self.read_dir_entries(&target_inode)?;
            for entry in entries {
                if entry.name != "." && entry.name != ".." {
                    return Err(String::from("directory not empty"));
                }
            }
        }

        self.remove_dir_entry(parent_inode_num, &name)?;

        let block_size = self.block_size as u64;
        let size = if (target_inode.mode & S_IFMT) == S_IFREG {
            let size_high = target_inode.dir_acl as u64;
            target_inode.size as u64 | (size_high << 32)
        } else {
            target_inode.size as u64
        };
        let chunks = (size + block_size - 1) / block_size;

        for blk in 0..chunks as u32 {
            let phys = self.get_phys_block(&target_inode, blk)?;
            if phys != 0 {
                self.free_block(phys)?;
            }
        }

        self.free_inode(target_inode_num)?;

        let mut parent_inode = self.read_inode(parent_inode_num)?;
        if is_dir {
            parent_inode.links_count -= 1;
            let group;
            {
                let mut inner = self.inner.lock();
                group = (target_inode_num - 1) / inner.superblock.inodes_per_group;
                let desc_mut = &mut inner.group_descs[group as usize];
                desc_mut.used_dirs_count -= 1;
            }
        }
        self.write_inode(parent_inode_num, &parent_inode)?;

        self.write_metadata()?;
        Ok(())
    }

    fn stat(&self, path: &str) -> Result<FsStat, String> {
        let inode_num = self.resolve_path(path)?;
        let inode = self.read_inode(inode_num)?;
        let is_dir = (inode.mode & S_IFMT) == S_IFDIR;
        let size = inode.size as usize;
        let children = if is_dir {
            self.read_dir_entries(&inode)?.len()
        } else {
            0
        };

        Ok(FsStat {
            path: normalize_path(path),
            is_dir,
            size,
            children,
        })
    }

    fn usage(&self) -> Result<FsUsage, String> {
        let inner = self.inner.lock();
        let total_inodes = inner.superblock.inodes_count;
        let free_inodes = inner.superblock.free_inodes_count;
        let used_inodes = total_inodes - free_inodes;

        let total_blocks = inner.superblock.blocks_count;
        let free_blocks = inner.superblock.free_blocks_count;
        let used_blocks = total_blocks - free_blocks;
        let used_bytes = used_blocks as usize * self.block_size as usize;

        Ok(FsUsage {
            files: used_inodes as usize,
            directories: 0,
            bytes: used_bytes,
        })
    }

    fn sync(&self) -> Result<(), String> {
        self.write_metadata()
    }

    fn fs_type(&self) -> &str {
        "ext2"
    }
}

// ============================================================================
// Local Helpers for Path Formatting
// ============================================================================

fn normalize_path(path: &str) -> String {
    if path.is_empty() {
        String::from("/")
    } else if path.starts_with('/') {
        String::from(path)
    } else {
        alloc::format!("/{}", path)
    }
}

fn split_path(path: &str) -> Result<(String, String), String> {
    let clean = path.trim_start_matches('/');
    if clean.is_empty() {
        return Err(String::from("invalid path"));
    }
    
    if let Some(pos) = clean.rfind('/') {
        let parent = alloc::format!("/{}", &clean[..pos]);
        let name = String::from(&clean[pos + 1..]);
        Ok((parent, name))
    } else {
        Ok((String::from("/"), String::from(clean)))
    }
}
