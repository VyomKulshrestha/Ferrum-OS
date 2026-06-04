// ============================================================================
// FerrumOS - Virtual Filesystem (VFS) Layer
// ============================================================================
// High-level abstraction that maps paths to their corresponding mounted
// filesystems. Handles mount/unmount and prefix resolution.
// ============================================================================

extern crate alloc;

use alloc::string::String;
use alloc::sync::Arc;
use alloc::vec::Vec;
use spin::Mutex;

use crate::fs::{DirEntry, FsStat, FsUsage};

// ============================================================================
// Filesystem Trait
// ============================================================================

pub trait Filesystem: Send + Sync {
    /// List directory contents
    fn list_dir(&self, path: &str) -> Result<Vec<DirEntry>, String>;

    /// Read file content as string
    fn read_file(&self, path: &str) -> Result<String, String>;

    /// Create/write a file
    fn create_file(&self, path: &str, content: &str) -> Result<(), String>;

    /// Create a directory
    fn create_dir(&self, path: &str) -> Result<(), String>;

    /// Remove a file or directory
    fn remove(&self, path: &str) -> Result<(), String>;

    /// Query node stats
    fn stat(&self, path: &str) -> Result<FsStat, String>;

    /// Query space/inode usage stats
    fn usage(&self) -> Result<FsUsage, String>;

    /// Flush metadata and dirty block buffers to the disk device
    fn sync(&self) -> Result<(), String>;

    /// Return the filesystem name (e.g. "ext2", "ramfs")
    fn fs_type(&self) -> &str;
}

// ============================================================================
// VFS Types
// ============================================================================

pub struct MountPoint {
    pub path: String,
    pub fs: Arc<dyn Filesystem>,
    pub device: String,
}

pub struct MountInfo {
    pub path: String,
    pub fs_type: String,
    pub device: String,
}

// ============================================================================
// Global State
// ============================================================================

static MOUNT_TABLE: Mutex<Option<Vec<MountPoint>>> = Mutex::new(None);

// ============================================================================
// Public APIs
// ============================================================================

/// Initialize the Virtual Filesystem layer.
pub fn init() {
    let mut table = MOUNT_TABLE.lock();
    if table.is_none() {
        *table = Some(Vec::new());
    }
}

/// Mount a filesystem at the given path.
pub fn mount(path: &str, fs: Arc<dyn Filesystem>, device: &str) -> Result<(), String> {
    let mut table_guard = MOUNT_TABLE.lock();
    let table = table_guard.as_mut().ok_or("VFS not initialized")?;

    // Normalize path
    let norm_path = normalize_vfs_path(path);

    // Prevent duplicate mounts
    if table.iter().any(|mp| mp.path == norm_path) {
        return Err(alloc::format!("directory already mounted: {}", norm_path));
    }

    table.push(MountPoint {
        path: norm_path,
        fs,
        device: String::from(device),
    });

    Ok(())
}

/// Unmount the filesystem at the given path.
pub fn umount(path: &str) -> Result<(), String> {
    let mut table_guard = MOUNT_TABLE.lock();
    let table = table_guard.as_mut().ok_or("VFS not initialized")?;

    let norm_path = normalize_vfs_path(path);
    if norm_path == "/" {
        return Err(String::from("cannot unmount root filesystem"));
    }

    let pos = table
        .iter()
        .position(|mp| mp.path == norm_path)
        .ok_or_else(|| alloc::format!("no filesystem mounted at: {}", norm_path))?;

    table.remove(pos);
    Ok(())
}

/// Resolve a path to its corresponding filesystem and local path.
pub fn resolve(path: &str) -> Result<(Arc<dyn Filesystem>, String), String> {
    let table_guard = MOUNT_TABLE.lock();
    let table = table_guard.as_ref().ok_or("VFS not initialized")?;

    let norm_path = normalize_vfs_path(path);
    let mut best_match: Option<&MountPoint> = None;

    for mp in table {
        let is_match = if mp.path == "/" {
            true
        } else if norm_path == mp.path {
            true
        } else if norm_path.starts_with(&alloc::format!("{}/", mp.path)) {
            true
        } else {
            false
        };

        if is_match {
            if let Some(best) = best_match {
                if mp.path.len() > best.path.len() {
                    best_match = Some(mp);
                }
            } else {
                best_match = Some(mp);
            }
        }
    }

    let best = best_match.ok_or_else(|| alloc::format!("no mount point for path: {}", path))?;
    
    let rel_path = if best.path == "/" {
        norm_path
    } else {
        let suffix = &norm_path[best.path.len()..];
        if suffix.is_empty() {
            String::from("/")
        } else if suffix.starts_with('/') {
            String::from(suffix)
        } else {
            alloc::format!("/{}", suffix)
        }
    };

    Ok((best.fs.clone(), rel_path))
}

/// Return all active mounts.
pub fn mounts() -> Vec<MountInfo> {
    let table_guard = MOUNT_TABLE.lock();
    let mut result = Vec::new();
    if let Some(ref table) = *table_guard {
        for mp in table {
            result.push(MountInfo {
                path: mp.path.clone(),
                fs_type: String::from(mp.fs.fs_type()),
                device: mp.device.clone(),
            });
        }
    }
    result
}

// ============================================================================
// Helpers
// ============================================================================

fn normalize_vfs_path(path: &str) -> String {
    if path.is_empty() {
        return String::from("/");
    }
    let mut norm = if path.starts_with('/') {
        String::from(path)
    } else {
        alloc::format!("/{}", path)
    };
    if norm.len() > 1 && norm.ends_with('/') {
        norm.pop();
    }
    norm
}
