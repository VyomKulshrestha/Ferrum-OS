// ============================================================================
// FerrumOS - Package Manager (ferrumpkg)
// ============================================================================
// Real install/remove/list semantics, honestly scoped: packages are staged
// onto the appliance disk at build time (scripts/make-appliance.ps1, via
// debugfs - the same mechanism that packages the real model checkpoint),
// not fetched from a network repository. What's "real" here is that
// install/remove genuinely gate whether `sys_exec` will run a package's
// binary at all (see src/syscall/process.rs), backed by state that
// persists across reboots - not a UI-only toggle.
//
// A package never needs its binary physically copied at runtime: ext2's
// own `create_file` (src/fs/ext2.rs) only supports direct blocks (12 max),
// so writing a multi-hundred-KB ELF through it at runtime would fail long
// before install ever got there. Instead, only a small text registry file
// changes at runtime; the (potentially large) binary stays where debugfs
// put it under /disk/pkgs-available/ whether installed or not.
// ============================================================================

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;

pub const AVAILABLE_ROOT: &str = "/disk/pkgs-available";
const REGISTRY_PATH: &str = "/disk/pkgs/registry.txt";

/// Capabilities a package manifest may request. Deliberately excludes
/// net:*, exec/delete-tier, quota:exempt, confirmation:bypass, and
/// system:* - those stay reserved for the kernel's own compiled-in
/// program manifests (src/userspace/mod.rs), never delegated to code
/// installed from a local package cache. Default-deny: anything a
/// manifest asks for outside this list is silently dropped, not an error.
pub const PACKAGE_CAP_ALLOWLIST: &[&str] = &[
    "cap:gui:window",
    "cap:fs:read",
    "cap:fs:write",
    "cap:audio:play",
];

#[derive(Debug, Clone)]
pub struct PackageMeta {
    pub name: String,
    pub version: String,
    pub description: String,
    pub capabilities: Vec<String>,
}

/// Parses the flat `key=value` manifest format (no JSON parser exists in
/// kernel space, and a package manifest doesn't need one - matches the
/// same pragmatic scoping `userland/settings`'s substring-based JSON field
/// extraction already uses instead of a real parser).
fn parse_manifest(text: &str) -> Option<PackageMeta> {
    let mut name = None;
    let mut version = String::from("0.0.0");
    let mut description = String::new();
    let mut capabilities = Vec::new();

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((key, value)) = line.split_once('=') {
            match key.trim() {
                "name" => name = Some(value.trim().to_string()),
                "version" => version = value.trim().to_string(),
                "description" => description = value.trim().to_string(),
                "capabilities" => {
                    capabilities = value
                        .split(',')
                        .map(|c| c.trim().to_string())
                        .filter(|c| !c.is_empty())
                        .collect();
                }
                _ => {}
            }
        }
    }

    name.map(|name| PackageMeta { name, version, description, capabilities })
}

fn read_registry() -> Vec<String> {
    match crate::fs::read_file(REGISTRY_PATH) {
        Ok(content) => content
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty())
            .collect(),
        Err(_) => Vec::new(),
    }
}

fn write_registry(names: &[String]) -> Result<(), String> {
    let content = names.join("\n");
    // ext2's create_file errors on an existing path rather than
    // truncating - remove-then-create is the same read-modify-write
    // pattern config.rs already uses for /disk/heliox/config.json.
    let _ = crate::fs::remove(REGISTRY_PATH);
    crate::fs::create_file(REGISTRY_PATH, &content)
}

/// Every package staged on disk under AVAILABLE_ROOT, whether installed
/// or not - this is the local package cache, analogous to apt's
/// downloaded-but-not-yet-`dpkg`-installed .deb files.
pub fn list_available() -> Vec<PackageMeta> {
    let entries = match crate::fs::list_dir(AVAILABLE_ROOT) {
        Ok(e) => e,
        Err(_) => return Vec::new(),
    };

    let mut out = Vec::new();
    for entry in entries {
        if !entry.is_dir {
            continue;
        }
        let manifest_path = format!("{}/{}/manifest.txt", AVAILABLE_ROOT, entry.name);
        if let Ok(text) = crate::fs::read_file(&manifest_path) {
            if let Some(meta) = parse_manifest(&text) {
                out.push(meta);
            }
        }
    }
    out
}

pub fn is_installed(name: &str) -> bool {
    read_registry().iter().any(|n| n == name)
}

pub fn list_installed() -> Vec<PackageMeta> {
    let installed = read_registry();
    list_available()
        .into_iter()
        .filter(|p| installed.iter().any(|n| n == &p.name))
        .collect()
}

pub fn install(name: &str) -> Result<(), String> {
    if !list_available().iter().any(|p| p.name == name) {
        return Err(format!("no such package: {}", name));
    }
    let mut registry = read_registry();
    if registry.iter().any(|n| n == name) {
        return Err(format!("already installed: {}", name));
    }
    registry.push(name.to_string());
    write_registry(&registry)?;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &format!("ferrumpkg: installed '{}'", name),
    );
    Ok(())
}

pub fn remove(name: &str) -> Result<(), String> {
    let mut registry = read_registry();
    let before = registry.len();
    registry.retain(|n| n != name);
    if registry.len() == before {
        return Err(format!("not installed: {}", name));
    }
    write_registry(&registry)?;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &format!("ferrumpkg: removed '{}'", name),
    );
    Ok(())
}

/// The path `sys_exec` should read a package's ELF from. Never physically
/// moved on install/remove - see the module doc comment.
pub fn bin_path(name: &str) -> String {
    format!("{}/{}/bin", AVAILABLE_ROOT, name)
}

/// Capabilities to grant an installed package, clamped against
/// `PACKAGE_CAP_ALLOWLIST`. Empty (not an error) if the package or its
/// manifest can't be found - `sys_exec` treats that the same as any other
/// program with no matching manifest.
pub fn capabilities_for(name: &str) -> Vec<String> {
    list_available()
        .into_iter()
        .find(|p| p.name == name)
        .map(|p| {
            p.capabilities
                .into_iter()
                .filter(|c| PACKAGE_CAP_ALLOWLIST.contains(&c.as_str()))
                .collect()
        })
        .unwrap_or_default()
}

/// Extracts the package name from a path of the form
/// "/disk/pkgs-available/<name>/bin", or None if it doesn't match that
/// shape. Used by `sys_exec` to recognize a package-launch request.
pub fn package_name_from_bin_path(path: &str) -> Option<String> {
    let rest = path.strip_prefix(AVAILABLE_ROOT)?.strip_prefix('/')?;
    let name = rest.strip_suffix("/bin")?;
    if name.is_empty() || name.contains('/') {
        None
    } else {
        Some(name.to_string())
    }
}
