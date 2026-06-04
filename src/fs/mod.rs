// ============================================================================
// FerrumOS - Filesystem Module Root
// ============================================================================
// Coordinates the VFS layer, RamFS, block devices, and ext2.
// ============================================================================

extern crate alloc;

pub mod block;
pub mod ext2;
pub mod vfs;

use alloc::collections::BTreeMap;
use alloc::string::{String, ToString};
use alloc::sync::Arc;
use alloc::vec::Vec;
use spin::Mutex;

// ============================================================================
// Shared Types
// ============================================================================

/// Directory listing entry (returned to callers)
#[derive(Debug, Clone)]
pub struct DirEntry {
    pub name: String,
    pub is_dir: bool,
    pub size: usize,
}

#[derive(Debug, Clone)]
pub struct FsStat {
    pub path: String,
    pub is_dir: bool,
    pub size: usize,
    pub children: usize,
}

#[derive(Debug, Clone)]
pub struct FsUsage {
    pub files: usize,
    pub directories: usize,
    pub bytes: usize,
}

#[derive(Debug, Clone)]
pub struct Mount {
    pub path: String,
    pub fs_type: String,
    pub device: String,
    pub flags: String,
}

// ============================================================================
// RamFS Implementation
// ============================================================================

/// A filesystem entry - either a file or directory
#[derive(Debug, Clone)]
enum FsNode {
    File { content: String },
    Directory { children: BTreeMap<String, FsNode> },
}

pub struct RamFs {
    root: Mutex<FsNode>,
}

impl RamFs {
    pub fn new() -> Self {
        let mut children = BTreeMap::new();
        
        // Create standard directories
        children.insert("etc".to_string(), FsNode::Directory { children: BTreeMap::new() });
        children.insert("tmp".to_string(), FsNode::Directory { children: BTreeMap::new() });
        children.insert("var".to_string(), FsNode::Directory { children: BTreeMap::new() });
        children.insert("srv".to_string(), FsNode::Directory { children: BTreeMap::new() });
        
        // Create a welcome file
        children.insert("readme.txt".to_string(), FsNode::File {
            content: String::from("Welcome to FerrumOS v0.1.0\nAI-Native Autonomous OS Foundation\n"),
        });
        
        // Create /etc/motd
        if let Some(FsNode::Directory { children: ref mut etc_children }) = children.get_mut("etc") {
            etc_children.insert("hostname".to_string(), FsNode::File {
                content: String::from("FerrumOS"),
            });
            etc_children.insert("version".to_string(), FsNode::File {
                content: String::from("0.1.0"),
            });
        }
        
        Self {
            root: Mutex::new(FsNode::Directory { children }),
        }
    }
}

impl vfs::Filesystem for RamFs {
    fn list_dir(&self, path: &str) -> Result<Vec<DirEntry>, String> {
        let root_guard = self.root.lock();
        let node = navigate(&root_guard, path)?;
        match node {
            FsNode::Directory { children } => {
                let mut entries = Vec::new();
                for (name, child) in children {
                    let (is_dir, size) = match child {
                        FsNode::File { content } => (false, content.len()),
                        FsNode::Directory { children } => (true, children.len()),
                    };
                    entries.push(DirEntry { name: name.clone(), is_dir, size });
                }
                Ok(entries)
            }
            FsNode::File { .. } => Err(String::from("not a directory")),
        }
    }

    fn read_file(&self, path: &str) -> Result<String, String> {
        let root_guard = self.root.lock();
        let node = navigate(&root_guard, path)?;
        match node {
            FsNode::File { content } => Ok(content.clone()),
            FsNode::Directory { .. } => Err(String::from("is a directory")),
        }
    }

    fn create_file(&self, path: &str, content: &str) -> Result<(), String> {
        let mut root_guard = self.root.lock();
        let (parent_path, file_name) = split_path(path)?;
        let parent = navigate_mut(&mut root_guard, &parent_path)?;
        
        match parent {
            FsNode::Directory { children } => {
                children.insert(file_name, FsNode::File { content: String::from(content) });
                Ok(())
            }
            _ => Err(String::from("parent is not a directory")),
        }
    }

    fn create_dir(&self, path: &str) -> Result<(), String> {
        let mut root_guard = self.root.lock();
        let (parent_path, dir_name) = split_path(path)?;
        let parent = navigate_mut(&mut root_guard, &parent_path)?;
        
        match parent {
            FsNode::Directory { children } => {
                if children.contains_key(&dir_name) {
                    return Err(String::from("already exists"));
                }
                children.insert(dir_name, FsNode::Directory { children: BTreeMap::new() });
                Ok(())
            }
            _ => Err(String::from("parent is not a directory")),
        }
    }

    fn remove(&self, path: &str) -> Result<(), String> {
        let mut root_guard = self.root.lock();
        let (parent_path, name) = split_path(path)?;
        let parent = navigate_mut(&mut root_guard, &parent_path)?;
        
        match parent {
            FsNode::Directory { children } => {
                children.remove(&name).ok_or_else(|| String::from("not found"))?;
                Ok(())
            }
            _ => Err(String::from("parent is not a directory")),
        }
    }

    fn stat(&self, path: &str) -> Result<FsStat, String> {
        let root_guard = self.root.lock();
        let node = navigate(&root_guard, path)?;

        let (is_dir, size, children) = match node {
            FsNode::File { content } => (false, content.len(), 0),
            FsNode::Directory { children } => (true, children.len(), children.len()),
        };

        Ok(FsStat {
            path: normalize_path(path),
            is_dir,
            size,
            children,
        })
    }

    fn usage(&self) -> Result<FsUsage, String> {
        let root_guard = self.root.lock();
        let mut usage = FsUsage {
            files: 0,
            directories: 0,
            bytes: 0,
        };
        accumulate_usage(&root_guard, &mut usage);
        Ok(usage)
    }

    fn sync(&self) -> Result<(), String> {
        Ok(())
    }

    fn fs_type(&self) -> &str {
        "ramfs"
    }
}

// ============================================================================
// Public Dispatch APIs
// ============================================================================

/// Initialize the Virtual Filesystem and mount the default volatile root.
pub fn init() {
    vfs::init();
    let ramfs = Arc::new(RamFs::new());
    vfs::mount("/", ramfs, "ramfs.root").expect("failed to mount root filesystem");
}

pub fn list_dir(path: &str) -> Result<Vec<DirEntry>, String> {
    let (fs, rel) = vfs::resolve(path)?;
    fs.list_dir(&rel)
}

pub fn read_file(path: &str) -> Result<String, String> {
    let (fs, rel) = vfs::resolve(path)?;
    fs.read_file(&rel)
}

pub fn create_file(path: &str, content: &str) -> Result<(), String> {
    let (fs, rel) = vfs::resolve(path)?;
    fs.create_file(&rel, content)
}

pub fn create_dir(path: &str) -> Result<(), String> {
    let (fs, rel) = vfs::resolve(path)?;
    fs.create_dir(&rel)
}

pub fn remove(path: &str) -> Result<(), String> {
    let (fs, rel) = vfs::resolve(path)?;
    fs.remove(&rel)
}

pub fn stat(path: &str) -> Result<FsStat, String> {
    let (fs, rel) = vfs::resolve(path)?;
    fs.stat(&rel)
}

pub fn usage() -> Result<FsUsage, String> {
    let (fs, _) = vfs::resolve("/")?;
    fs.usage()
}

pub fn sync() -> Result<(), String> {
    vfs::sync_all()
}

pub fn mounts() -> Vec<Mount> {
    vfs::mounts().into_iter().map(|mi| {
        let flags = if mi.fs_type == "ramfs" {
            String::from("rw,volatile")
        } else if mi.fs_type == "ext2" {
            String::from("ro")
        } else {
            String::from("rw")
        };
        Mount {
            path: mi.path,
            fs_type: mi.fs_type,
            device: mi.device,
            flags,
        }
    }).collect()
}

// ============================================================================
// Private Helpers
// ============================================================================

/// Navigate to a node by path
fn navigate<'a>(root: &'a FsNode, path: &str) -> Result<&'a FsNode, String> {
    if path == "/" || path.is_empty() {
        return Ok(root);
    }
    
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').filter(|s| !s.is_empty()).collect();
    let mut current = root;
    
    for part in &parts {
        match current {
            FsNode::Directory { children } => {
                current = children.get(*part)
                    .ok_or_else(|| alloc::format!("no such file or directory: {}", path))?;
            }
            FsNode::File { .. } => {
                return Err(alloc::format!("not a directory: {}", path));
            }
        }
    }
    
    Ok(current)
}

/// Navigate to a mutable node by path
fn navigate_mut<'a>(root: &'a mut FsNode, path: &str) -> Result<&'a mut FsNode, String> {
    if path == "/" || path.is_empty() {
        return Ok(root);
    }
    
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').filter(|s| !s.is_empty()).collect();
    let mut current = root;
    
    for part in &parts {
        match current {
            FsNode::Directory { children } => {
                current = children.get_mut(*part)
                    .ok_or_else(|| alloc::format!("no such file or directory: {}", path))?;
            }
            FsNode::File { .. } => {
                return Err(alloc::format!("not a directory: {}", path));
            }
        }
    }
    
    Ok(current)
}

fn accumulate_usage(node: &FsNode, usage: &mut FsUsage) {
    match node {
        FsNode::File { content } => {
            usage.files += 1;
            usage.bytes += content.len();
        }
        FsNode::Directory { children } => {
            usage.directories += 1;
            for child in children.values() {
                accumulate_usage(child, usage);
            }
        }
    }
}

fn normalize_path(path: &str) -> String {
    if path.is_empty() {
        String::from("/")
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        alloc::format!("/{}", path)
    }
}

/// Split a path into parent and name
fn split_path(path: &str) -> Result<(String, String), String> {
    let clean = path.trim_start_matches('/');
    if clean.is_empty() {
        return Err(String::from("invalid path"));
    }
    
    if let Some(pos) = clean.rfind('/') {
        let parent = alloc::format!("/{}", &clean[..pos]);
        let name = clean[pos + 1..].to_string();
        Ok((parent, name))
    } else {
        Ok(("/".to_string(), clean.to_string()))
    }
}
