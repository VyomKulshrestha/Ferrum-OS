// ============================================================================
// FerrumOS - ext2 Filesystem Driver (Read-Only)
// ============================================================================
// Read-only implementation of the ext2 filesystem.
// Supports Revision 0 and Revision 1, block sizes up to 4096 bytes,
// direct, single-indirect, double-indirect, and triple-indirect block pointers.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::vec;
use core::mem::size_of;

use crate::fs::block::BlockDevice;

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
pub struct DirEntry {
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
// ext2 Filesystem State
// ============================================================================

pub struct Ext2Fs<B: BlockDevice> {
    pub device: B,
    pub superblock: Superblock,
    pub block_size: u32,
    pub groups_count: u32,
    pub group_descs: Vec<BlockGroupDescriptor>,
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

        Ok(Self {
            device,
            superblock,
            block_size,
            groups_count,
            group_descs,
        })
    }

    /// Read an ext2 block using the filesystem's block size.
    pub fn read_block(&self, block: u32, buf: &mut [u8]) -> Result<(), String> {
        read_raw_block(&self.device, self.block_size, block, buf)
    }

    /// Read an Inode structure by its 1-indexed inode number.
    pub fn read_inode(&self, inode_num: u32) -> Result<Inode, String> {
        if inode_num == 0 || inode_num > self.superblock.inodes_count {
            return Err(alloc::format!("invalid inode number: {}", inode_num));
        }

        let inodes_per_group = self.superblock.inodes_per_group;
        let group = (inode_num - 1) / inodes_per_group;
        let index = (inode_num - 1) % inodes_per_group;

        if group >= self.groups_count {
            return Err(alloc::format!("inode group out of bounds: {}", group));
        }

        let desc = &self.group_descs[group as usize];
        let inode_size = if self.superblock.rev_level >= 1 {
            self.superblock.inode_size as usize
        } else {
            128
        };

        let byte_offset = index as usize * inode_size;
        let block_offset = (byte_offset / self.block_size as usize) as u32;
        let offset_in_block = byte_offset % self.block_size as usize;

        let target_block = desc.inode_table + block_offset;
        let mut block_buf = Vec::new();
        block_buf.resize(self.block_size as usize, 0);
        self.read_block(target_block, &mut block_buf)?;

        let inode: Inode = unsafe { from_bytes(&block_buf[offset_in_block..offset_in_block + 128]) };
        Ok(inode)
    }

    /// Resolve a logical file block index to a physical block index on disk.
    pub fn get_phys_block(&self, inode: &Inode, file_block: u32) -> Result<u32, String> {
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
            self.read_block(sib, &mut sib_buf)?;
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
            self.read_block(dib, &mut dib_buf)?;

            let outer_idx = index / pointers_per_block;
            let inner_idx = index % pointers_per_block;

            let sib = unsafe { *(dib_buf.as_ptr().add(outer_idx as usize * 4) as *const u32) };
            if sib == 0 {
                return Ok(0);
            }

            let mut sib_buf = Vec::new();
            sib_buf.resize(self.block_size as usize, 0);
            self.read_block(sib, &mut sib_buf)?;

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
            self.read_block(tib, &mut tib_buf)?;

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
            self.read_block(dib, &mut dib_buf)?;

            let sib = unsafe { *(dib_buf.as_ptr().add(mid_idx as usize * 4) as *const u32) };
            if sib == 0 {
                return Ok(0);
            }

            let mut sib_buf = Vec::new();
            sib_buf.resize(self.block_size as usize, 0);
            self.read_block(sib, &mut sib_buf)?;

            let phys = unsafe { *(sib_buf.as_ptr().add(inner_idx as usize * 4) as *const u32) };
            return Ok(phys);
        }

        Err(String::from("file block index out of bounds"))
    }

    /// Read the complete contents of an inode's data blocks.
    pub fn read_inode_data(&self, inode: &Inode) -> Result<Vec<u8>, String> {
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
            let phys_block = self.get_phys_block(inode, file_block)?;
            let to_read = core::cmp::min(bytes_left, block_size);

            if phys_block == 0 {
                // Sparse block / hole, filled with zeros
                data.extend_from_slice(&vec![0u8; to_read as usize]);
            } else {
                self.read_block(phys_block, &mut block_buf)?;
                data.extend_from_slice(&block_buf[0..to_read as usize]);
            }

            bytes_left -= to_read;
            file_block += 1;
        }

        Ok(data)
    }

    /// Read all directory entries from a directory inode.
    pub fn read_dir_entries(&self, inode: &Inode) -> Result<Vec<Ext2DirEntry>, String> {
        if (inode.mode & S_IFMT) != S_IFDIR {
            return Err(String::from("inode is not a directory"));
        }

        let data = self.read_inode_data(inode)?;
        let mut entries = Vec::new();
        let mut offset = 0;
        let data_len = data.len();

        while offset + size_of::<DirEntry>() <= data_len {
            let entry: DirEntry = unsafe { from_bytes(&data[offset..offset + size_of::<DirEntry>()]) };
            if entry.rec_len == 0 {
                break; // avoid infinite loop
            }

            if entry.inode != 0 && entry.name_len > 0 {
                let name_start = offset + size_of::<DirEntry>();
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
        if (inode.mode & S_IFMT) != S_IFLNK {
            return Err(String::from("inode is not a symbolic link"));
        }

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
            let data = self.read_inode_data(inode)?;
            core::str::from_utf8(&data[0..size])
                .map(String::from)
                .map_err(|e| alloc::format!("invalid utf-8 in symlink: {:?}", e))
        }
    }

    /// Resolve a absolute or relative path starting at the root directory (inode 2).
    pub fn resolve_path(&self, path: &str) -> Result<u32, String> {
        let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
        let mut current_inode = 2u32; // Root inode

        for part in parts {
            let inode = self.read_inode(current_inode)?;
            if (inode.mode & S_IFMT) != S_IFDIR {
                return Err(alloc::format!("not a directory during path resolution: {}", part));
            }

            let entries = self.read_dir_entries(&inode)?;
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
}
