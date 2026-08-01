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
use ed25519_dalek::{Signature, VerifyingKey};
use sha2::{Digest, Sha256};

pub const AVAILABLE_ROOT: &str = "/disk/pkgs-available";
const REGISTRY_PATH: &str = "/disk/pkgs/registry.txt";
const MANIFEST_FORMAT: &str = "1";
const TRUSTED_KEY_ID: &str = "ferrumos-release-1";
const TRUSTED_PUBLIC_KEY: [u8; 32] = [
    0x51, 0x65, 0xa8, 0x06, 0x8d, 0xf3, 0x06, 0x51, 0xf0, 0xfe, 0xc7, 0x54, 0x33, 0xa3, 0x50, 0x28,
    0x68, 0xe4, 0x9c, 0x8d, 0x82, 0x6b, 0xb2, 0xa1, 0x4b, 0x72, 0xad, 0x28, 0xc6, 0xdd, 0xfe, 0x16,
];
const MAX_MANIFEST_BYTES: usize = 4096;

/// Capabilities a package manifest may request. Deliberately excludes
/// net:*, exec/delete-tier, quota:exempt, confirmation:bypass, and
/// system:* - those stay reserved for the kernel's own compiled-in
/// program manifests (src/userspace/mod.rs), never delegated to code
/// installed from a local package cache. Default-deny: anything a
/// manifest asks for outside this list rejects the whole package. Silent
/// capability downgrades make review misleading: the user must see exactly
/// the authority the signed publisher requested.
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
    pub binary_sha256: [u8; 32],
    pub signing_key: String,
}

/// Parses the flat `key=value` manifest format (no JSON parser exists in
/// kernel space, and a package manifest doesn't need one - matches the
/// same pragmatic scoping `userland/settings`'s substring-based JSON field
/// extraction already uses instead of a real parser).
fn parse_manifest(text: &str) -> Result<PackageMeta, String> {
    if text.len() > MAX_MANIFEST_BYTES {
        return Err(String::from("manifest exceeds 4096-byte limit"));
    }
    let mut format = None;
    let mut name = None;
    let mut version = None;
    let mut description = None;
    let mut capabilities: Option<Vec<String>> = None;
    let mut binary_sha256 = None;
    let mut signing_key = None;

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            return Err(format!("invalid manifest line: {}", line));
        };
        let key = key.trim();
        let value = value.trim();
        match key {
            "format" if format.is_none() => format = Some(value.to_string()),
            "name" if name.is_none() => name = Some(value.to_string()),
            "version" if version.is_none() => version = Some(value.to_string()),
            "description" if description.is_none() => description = Some(value.to_string()),
            "capabilities" => {
                if capabilities.is_some() {
                    return Err(String::from("duplicate manifest key: capabilities"));
                }
                capabilities = Some(
                    value
                        .split(',')
                        .map(|c| c.trim().to_string())
                        .filter(|c| !c.is_empty())
                        .collect(),
                );
            }
            "binary_sha256" if binary_sha256.is_none() => {
                binary_sha256 = Some(parse_hex::<32>(value).ok_or_else(|| {
                    String::from("binary_sha256 must be 64 lowercase hex characters")
                })?);
            }
            "signing_key" if signing_key.is_none() => signing_key = Some(value.to_string()),
            "format" | "name" | "version" | "description" | "binary_sha256" | "signing_key" => {
                return Err(format!("duplicate manifest key: {}", key));
            }
            _ => return Err(format!("unknown manifest key: {}", key)),
        }
    }

    if format.as_deref() != Some(MANIFEST_FORMAT) {
        return Err(String::from("unsupported or missing manifest format"));
    }
    let name = name.ok_or_else(|| String::from("manifest missing name"))?;
    if !valid_package_name(&name) {
        return Err(String::from(
            "package name must use lowercase ASCII letters, digits, and '-'",
        ));
    }
    let version = version.ok_or_else(|| String::from("manifest missing version"))?;
    if !valid_version(&version) {
        return Err(String::from("version must be numeric MAJOR.MINOR.PATCH"));
    }
    let description = description.ok_or_else(|| String::from("manifest missing description"))?;
    if description.is_empty() || description.len() > 160 {
        return Err(String::from("description must be 1..160 bytes"));
    }
    let capabilities = capabilities.ok_or_else(|| String::from("manifest missing capabilities"))?;
    for (idx, capability) in capabilities.iter().enumerate() {
        if !PACKAGE_CAP_ALLOWLIST.contains(&capability.as_str()) {
            return Err(format!(
                "capability is not permitted for packages: {}",
                capability
            ));
        }
        if capabilities[..idx].iter().any(|prior| prior == capability) {
            return Err(format!("duplicate capability: {}", capability));
        }
    }
    let binary_sha256 =
        binary_sha256.ok_or_else(|| String::from("manifest missing binary_sha256"))?;
    let signing_key = signing_key.ok_or_else(|| String::from("manifest missing signing_key"))?;
    if signing_key != TRUSTED_KEY_ID {
        return Err(format!("untrusted signing key: {}", signing_key));
    }

    Ok(PackageMeta {
        name,
        version,
        description,
        capabilities,
        binary_sha256,
        signing_key,
    })
}

fn valid_package_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 48
        && name
            .as_bytes()
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'-')
}

fn valid_version(version: &str) -> bool {
    let mut parts = version.split('.');
    let valid_part = |part: &str| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit());
    matches!((parts.next(), parts.next(), parts.next(), parts.next()), (Some(a), Some(b), Some(c), None) if valid_part(a) && valid_part(b) && valid_part(c))
}

fn parse_hex<const N: usize>(text: &str) -> Option<[u8; N]> {
    if text.len() != N * 2
        || !text
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    {
        return None;
    }
    let mut out = [0u8; N];
    let bytes = text.as_bytes();
    for i in 0..N {
        let nibble = |b: u8| match b {
            b'0'..=b'9' => Some(b - b'0'),
            b'a'..=b'f' => Some(b - b'a' + 10),
            _ => None,
        };
        out[i] = (nibble(bytes[i * 2])? << 4) | nibble(bytes[i * 2 + 1])?;
    }
    Some(out)
}

fn verify_package_dir(directory_name: &str) -> Result<PackageMeta, String> {
    if !valid_package_name(directory_name) {
        return Err(String::from("invalid package directory name"));
    }
    let root = format!("{}/{}", AVAILABLE_ROOT, directory_name);
    let manifest_text = crate::fs::read_file(&format!("{}/manifest.txt", root))?;
    let meta = parse_manifest(&manifest_text)?;
    if meta.name != directory_name {
        return Err(format!(
            "manifest name '{}' does not match directory '{}'",
            meta.name, directory_name
        ));
    }

    let signature_text = crate::fs::read_file(&format!("{}/manifest.sig", root))?;
    let signature_bytes = parse_hex::<64>(signature_text.trim())
        .ok_or_else(|| String::from("manifest.sig must contain 128 lowercase hex characters"))?;
    let verifying_key = VerifyingKey::from_bytes(&TRUSTED_PUBLIC_KEY)
        .map_err(|_| String::from("kernel package trust root is invalid"))?;
    let signature = Signature::from_bytes(&signature_bytes);
    verifying_key
        .verify_strict(manifest_text.as_bytes(), &signature)
        .map_err(|_| String::from("manifest signature verification failed"))?;

    let binary = crate::fs::read_file_bytes(&format!("{}/bin", root))?;
    let digest = Sha256::digest(&binary);
    if digest.as_slice() != meta.binary_sha256 {
        return Err(String::from(
            "package binary SHA-256 does not match signed manifest",
        ));
    }
    Ok(meta)
}

pub fn verify(name: &str) -> Result<PackageMeta, String> {
    verify_package_dir(name)
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
        if let Ok(meta) = verify_package_dir(&entry.name) {
            out.push(meta);
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
    verify(name).map_err(|err| format!("package verification failed: {}", err))?;
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
    verify(name).map(|p| p.capabilities).unwrap_or_default()
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
