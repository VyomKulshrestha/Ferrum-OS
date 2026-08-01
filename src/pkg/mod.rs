// ============================================================================
// FerrumOS - Package Manager (ferrumpkg)
// ============================================================================
// Real install/remove/list semantics, honestly scoped: packages are staged
// onto the appliance disk at build time (scripts/make-appliance.ps1, via
// debugfs - the same mechanism that packages the real model checkpoint),
// not fetched from a network repository. What's "real" here is that
// install/remove genuinely gate whether `sys_exec` will run a package's
// binary at all (see src/syscall/process.rs), backed by a serialized,
// checksummed dual-slot registry that persists across reboots.
//
// A package never needs its binary physically copied at runtime: ext2's
// own `create_file` (src/fs/ext2.rs) only supports direct blocks (12 max),
// so writing a multi-hundred-KB ELF through it at runtime would fail long
// before install ever got there. Instead, only small registry snapshots
// change at runtime; the (potentially large) binary stays where debugfs
// put it under /disk/pkgs-available/ whether installed or not.
// ============================================================================

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec::Vec;
use ed25519_dalek::{Signature, VerifyingKey};
use sha2::{Digest, Sha256};
use spin::Mutex;

pub const AVAILABLE_ROOT: &str = "/disk/pkgs-available";
const LEGACY_REGISTRY_PATH: &str = "/disk/pkgs/registry.txt";
const REGISTRY_A_PATH: &str = "/disk/pkgs/registry.a";
const REGISTRY_B_PATH: &str = "/disk/pkgs/registry.b";
const REGISTRY_FORMAT: &str = "1";
const MANIFEST_FORMAT: &str = "1";
const TRUSTED_KEY_ID: &str = "ferrumos-release-1";
const TRUSTED_PUBLIC_KEY: [u8; 32] = [
    0x51, 0x65, 0xa8, 0x06, 0x8d, 0xf3, 0x06, 0x51, 0xf0, 0xfe, 0xc7, 0x54, 0x33, 0xa3, 0x50, 0x28,
    0x68, 0xe4, 0x9c, 0x8d, 0x82, 0x6b, 0xb2, 0xa1, 0x4b, 0x72, 0xad, 0x28, 0xc6, 0xdd, 0xfe, 0x16,
];
const MAX_MANIFEST_BYTES: usize = 4096;
const MAX_REGISTRY_BYTES: usize = 48 * 1024;
const MAX_INSTALLED_PACKAGES: usize = 128;

/// Serializes every registry read-modify-write transaction. The ext2 driver
/// serializes individual filesystem calls, but without this higher-level lock
/// two App Store/shell operations could both read generation N and overwrite
/// each other's generation N+1 result.
static PACKAGE_STATE: Mutex<()> = Mutex::new(());

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

pub const PRIVILEGED_PACKAGE_CAPABILITIES: &[&str] =
    &["cap:fs:read", "cap:fs:write", "cap:audio:play"];

#[derive(Debug, Clone)]
pub struct PackageMeta {
    pub name: String,
    pub version: String,
    pub description: String,
    pub capabilities: Vec<String>,
    pub binary_sha256: [u8; 32],
    pub signing_key: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct InstalledPackage {
    name: String,
    version: String,
    binary_sha256: [u8; 32],
}

#[derive(Debug, Clone)]
struct RegistrySnapshot {
    generation: u64,
    packages: Vec<InstalledPackage>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RegistrySlot {
    A,
    B,
}

impl RegistrySlot {
    fn path(self) -> &'static str {
        match self {
            Self::A => REGISTRY_A_PATH,
            Self::B => REGISTRY_B_PATH,
        }
    }

    fn other(self) -> Self {
        match self {
            Self::A => Self::B,
            Self::B => Self::A,
        }
    }
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

pub fn privileged_capabilities(meta: &PackageMeta) -> Vec<String> {
    meta.capabilities
        .iter()
        .filter(|cap| PRIVILEGED_PACKAGE_CAPABILITIES.contains(&cap.as_str()))
        .cloned()
        .collect()
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

fn registry_body(snapshot: &RegistrySnapshot) -> String {
    let mut packages = snapshot.packages.clone();
    packages.sort_by(|a, b| a.name.cmp(&b.name));
    let mut body = format!(
        "format={}\ngeneration={}\n",
        REGISTRY_FORMAT, snapshot.generation
    );
    for package in packages {
        body.push_str(&format!(
            "package={}|{}|{}\n",
            package.name,
            package.version,
            hex_encode(&package.binary_sha256)
        ));
    }
    body
}

fn serialize_registry(snapshot: &RegistrySnapshot) -> Result<String, String> {
    if snapshot.packages.len() > MAX_INSTALLED_PACKAGES {
        return Err(String::from("package registry capacity exceeded"));
    }
    let body = registry_body(snapshot);
    let checksum = Sha256::digest(body.as_bytes());
    let content = format!("{}checksum={}\n", body, hex_encode(checksum.as_slice()));
    if content.len() > MAX_REGISTRY_BYTES {
        return Err(String::from("package registry exceeds 48 KiB limit"));
    }
    Ok(content)
}

fn parse_registry(content: &str) -> Result<RegistrySnapshot, String> {
    if content.len() > MAX_REGISTRY_BYTES {
        return Err(String::from("registry exceeds 48 KiB limit"));
    }
    let checksum_line = content
        .lines()
        .last()
        .ok_or_else(|| String::from("registry is empty"))?;
    let checksum_text = checksum_line
        .strip_prefix("checksum=")
        .ok_or_else(|| String::from("registry checksum must be last"))?;
    let expected = parse_hex::<32>(checksum_text)
        .ok_or_else(|| String::from("registry checksum is invalid"))?;
    let checksum_offset = content
        .rfind("checksum=")
        .ok_or_else(|| String::from("registry checksum missing"))?;
    let body = &content[..checksum_offset];
    if Sha256::digest(body.as_bytes()).as_slice() != expected {
        return Err(String::from("registry checksum mismatch"));
    }

    let mut format_seen = false;
    let mut generation = None;
    let mut packages = Vec::new();
    for line in body.lines() {
        if line == format!("format={}", REGISTRY_FORMAT) && !format_seen {
            format_seen = true;
            continue;
        }
        if let Some(value) = line.strip_prefix("generation=") {
            if generation.is_some() {
                return Err(String::from("duplicate registry generation"));
            }
            generation = Some(
                value
                    .parse::<u64>()
                    .map_err(|_| String::from("invalid registry generation"))?,
            );
            continue;
        }
        if let Some(value) = line.strip_prefix("package=") {
            let mut fields = value.split('|');
            let (Some(name), Some(version), Some(digest), None) =
                (fields.next(), fields.next(), fields.next(), fields.next())
            else {
                return Err(String::from("invalid registry package record"));
            };
            if !valid_package_name(name) || !valid_version(version) {
                return Err(String::from("invalid package identity in registry"));
            }
            if packages
                .iter()
                .any(|package: &InstalledPackage| package.name == name)
            {
                return Err(format!("duplicate registry package: {}", name));
            }
            packages.push(InstalledPackage {
                name: name.to_string(),
                version: version.to_string(),
                binary_sha256: parse_hex::<32>(digest)
                    .ok_or_else(|| String::from("invalid package digest in registry"))?,
            });
            continue;
        }
        return Err(format!("unknown registry line: {}", line));
    }
    if !format_seen {
        return Err(String::from("unsupported or missing registry format"));
    }
    if packages.len() > MAX_INSTALLED_PACKAGES {
        return Err(String::from("package registry capacity exceeded"));
    }
    Ok(RegistrySnapshot {
        generation: generation.ok_or_else(|| String::from("registry generation missing"))?,
        packages,
    })
}

fn read_slot(slot: RegistrySlot) -> Result<Option<RegistrySnapshot>, String> {
    let content = match crate::fs::read_file(slot.path()) {
        Ok(content) => content,
        Err(_) => return Ok(None),
    };
    parse_registry(&content)
        .map(Some)
        .map_err(|err| format!("{} is corrupt: {}", slot.path(), err))
}

fn legacy_snapshot() -> RegistrySnapshot {
    let mut packages = Vec::new();
    if let Ok(content) = crate::fs::read_file(LEGACY_REGISTRY_PATH) {
        for name in content
            .lines()
            .map(str::trim)
            .filter(|name| !name.is_empty())
        {
            if packages.len() >= MAX_INSTALLED_PACKAGES
                || packages
                    .iter()
                    .any(|package: &InstalledPackage| package.name == name)
            {
                continue;
            }
            if let Ok(meta) = verify_package_dir(name) {
                packages.push(InstalledPackage {
                    name: meta.name,
                    version: meta.version,
                    binary_sha256: meta.binary_sha256,
                });
            }
        }
    }
    RegistrySnapshot {
        generation: 0,
        packages,
    }
}

fn registry_snapshots() -> Result<Vec<(RegistrySlot, RegistrySnapshot)>, String> {
    let mut snapshots = Vec::new();
    let mut errors = Vec::new();
    for slot in [RegistrySlot::A, RegistrySlot::B] {
        match read_slot(slot) {
            Ok(Some(snapshot)) => snapshots.push((slot, snapshot)),
            Ok(None) => {}
            Err(err) => errors.push(err),
        }
    }
    snapshots.sort_by(|a, b| b.1.generation.cmp(&a.1.generation));
    if !errors.is_empty() {
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::SecurityViolation,
            &format!(
                "ferrumpkg ignored corrupt registry slot(s): {}",
                errors.join("; ")
            ),
        );
    }
    if snapshots.is_empty() && !errors.is_empty() {
        let message = errors.join("; ");
        crate::logging::audit::log_event(
            crate::logging::audit::AuditEvent::SecurityViolation,
            &format!("ferrumpkg registry recovery failed: {}", message),
        );
        return Err(message);
    }
    Ok(snapshots)
}

fn current_registry() -> Result<(Option<RegistrySlot>, RegistrySnapshot), String> {
    let snapshots = registry_snapshots()?;
    Ok(snapshots
        .into_iter()
        .next()
        .map(|(slot, snapshot)| (Some(slot), snapshot))
        .unwrap_or_else(|| (None, legacy_snapshot())))
}

fn write_verified(slot: RegistrySlot, snapshot: &RegistrySnapshot) -> Result<(), String> {
    let content = serialize_registry(snapshot)?;
    crate::fs::create_file(slot.path(), &content)?;
    let persisted = crate::fs::read_file(slot.path())?;
    let read_back = parse_registry(&persisted)?;
    let mut expected_packages = snapshot.packages.clone();
    expected_packages.sort_by(|a, b| a.name.cmp(&b.name));
    if read_back.generation != snapshot.generation || read_back.packages != expected_packages {
        return Err(format!(
            "registry read-back verification failed for {}",
            slot.path()
        ));
    }
    crate::fs::sync()
}

fn commit_registry(
    current_slot: Option<RegistrySlot>,
    current: &RegistrySnapshot,
    mut packages: Vec<InstalledPackage>,
) -> Result<u64, String> {
    let next_generation = current
        .generation
        .checked_add(1)
        .ok_or_else(|| String::from("registry generation exhausted"))?;

    let target = match current_slot {
        Some(slot) => slot.other(),
        None => {
            // Seed the pre-transaction state first so the very first install
            // can be rolled back just like every later mutation.
            write_verified(RegistrySlot::A, current)?;
            RegistrySlot::B
        }
    };
    packages.sort_by(|a, b| a.name.cmp(&b.name));
    let next = RegistrySnapshot {
        generation: next_generation,
        packages,
    };
    write_verified(target, &next)?;
    Ok(next_generation)
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
    let _guard = PACKAGE_STATE.lock();
    installed_meta(name).is_ok()
}

fn installed_meta(name: &str) -> Result<PackageMeta, String> {
    let (_, registry) = current_registry()?;
    let meta = verify_package_dir(name)?;
    if registry.packages.iter().any(|installed| {
        installed.name == meta.name
            && installed.version == meta.version
            && installed.binary_sha256 == meta.binary_sha256
    }) {
        Ok(meta)
    } else {
        Err(format!(
            "not installed or installed version changed: {}",
            name
        ))
    }
}

/// Atomically validates installation state, signature/version/digest binding,
/// and loads the executable bytes under the package transaction lock. Removal
/// may proceed after this returns, but it cannot interleave between the launch
/// authorization check and loading a different payload.
pub fn load_installed(name: &str) -> Result<(PackageMeta, Vec<u8>), String> {
    let _guard = PACKAGE_STATE.lock();
    let meta = installed_meta(name)?;
    let binary = crate::fs::read_file_bytes(&bin_path(name))?;
    Ok((meta, binary))
}

pub fn list_installed() -> Vec<PackageMeta> {
    let _guard = PACKAGE_STATE.lock();
    let Ok((_, registry)) = current_registry() else {
        return Vec::new();
    };
    list_available()
        .into_iter()
        .filter(|meta| {
            registry.packages.iter().any(|installed| {
                installed.name == meta.name
                    && installed.version == meta.version
                    && installed.binary_sha256 == meta.binary_sha256
            })
        })
        .collect()
}

pub fn install(name: &str, privileged_confirmed: bool) -> Result<u64, String> {
    let _guard = PACKAGE_STATE.lock();
    let meta = verify(name).map_err(|err| format!("package verification failed: {}", err))?;
    let privileged = privileged_capabilities(&meta);
    if !privileged.is_empty() && !privileged_confirmed {
        return Err(format!(
            "confirmation required for capabilities: {} (rerun with --confirm)",
            privileged.join(", ")
        ));
    }
    let (slot, registry) = current_registry()?;
    if registry.packages.iter().any(|package| package.name == name) {
        return Err(format!("already installed: {}", name));
    }
    let mut packages = registry.packages.clone();
    packages.push(InstalledPackage {
        name: meta.name,
        version: meta.version,
        binary_sha256: meta.binary_sha256,
    });
    let generation = commit_registry(slot, &registry, packages)?;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &format!(
            "ferrumpkg: installed '{}' at generation {}",
            name, generation
        ),
    );
    Ok(generation)
}

pub fn remove(name: &str) -> Result<u64, String> {
    let _guard = PACKAGE_STATE.lock();
    let (slot, registry) = current_registry()?;
    let mut packages = registry.packages.clone();
    let before = packages.len();
    packages.retain(|package| package.name != name);
    if packages.len() == before {
        return Err(format!("not installed: {}", name));
    }
    let generation = commit_registry(slot, &registry, packages)?;
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &format!("ferrumpkg: removed '{}' at generation {}", name, generation),
    );
    Ok(generation)
}

pub fn rollback() -> Result<u64, String> {
    let _guard = PACKAGE_STATE.lock();
    let snapshots = registry_snapshots()?;
    if snapshots.len() < 2 {
        return Err(String::from("no previous valid registry generation"));
    }
    let (current_slot, current) = &snapshots[0];
    let previous = &snapshots[1].1;
    let generation = commit_registry(Some(*current_slot), current, previous.packages.clone())?;
    for removed in current.packages.iter().filter(|package| {
        !previous
            .packages
            .iter()
            .any(|prior| prior.name == package.name)
    }) {
        crate::userspace::unregister_dynamic_program(&removed.name, &bin_path(&removed.name));
    }
    crate::logging::audit::log_event(
        crate::logging::audit::AuditEvent::FileAccess,
        &format!(
            "ferrumpkg: rolled back registry at generation {}",
            generation
        ),
    );
    Ok(generation)
}

pub fn registry_status() -> Result<(u64, usize, bool), String> {
    let _guard = PACKAGE_STATE.lock();
    let snapshots = registry_snapshots()?;
    if let Some((_, current)) = snapshots.first() {
        Ok((
            current.generation,
            current.packages.len(),
            snapshots.len() >= 2,
        ))
    } else {
        let legacy = legacy_snapshot();
        Ok((legacy.generation, legacy.packages.len(), false))
    }
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
    let _guard = PACKAGE_STATE.lock();
    installed_meta(name)
        .map(|package| package.capabilities)
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
