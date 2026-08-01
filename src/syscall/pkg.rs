// ============================================================================
// FerrumOS - Signed Package Manager Syscalls
// ============================================================================
// A narrow request API for the first-party App Store. Callers never receive
// cap:pkg:manage and cannot touch repository/registry files directly; the
// kernel performs every mutation through ferrumpkg's signed, serialized,
// rollback-capable transaction path.
// ============================================================================

extern crate alloc;

use alloc::format;
use alloc::string::String;

use super::{SyscallResult, SyscallStatus};

const MAX_CATALOG_BYTES: usize = 32 * 1024;

/// Wire format, one package per line:
/// name|version|installed(0/1)|privileged-capability-csv|description
pub fn sys_package_list(args: [u64; 6]) -> SyscallResult {
    let out_ptr = args[0];
    let out_len = args[1] as usize;
    if out_ptr == 0 || out_len == 0 || out_len > MAX_CATALOG_BYTES {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let mut output = String::new();
    for entry in crate::pkg::catalog() {
        output.push_str(&format!(
            "{}|{}|{}|{}|{}\n",
            entry.package.name,
            entry.package.version,
            if entry.installed { "1" } else { "0" },
            entry.privileged_capabilities.join(","),
            entry.package.description,
        ));
    }
    if output.len() > out_len {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let copied = unsafe { super::fs::copy_to_user(out_ptr, output.as_bytes(), out_len) };
    SyscallResult::ok(copied as u64)
}

pub fn sys_package_install(args: [u64; 6]) -> SyscallResult {
    let name = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(name) => name,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    match crate::pkg::install(&name, args[2] == 1) {
        Ok(generation) => SyscallResult::ok(generation),
        Err(error) => {
            crate::serial_println!("[package-api] install {} failed: {}", name, error);
            if error.starts_with("confirmation required") {
                SyscallResult::err(SyscallStatus::PermissionDenied)
            } else {
                SyscallResult::err(SyscallStatus::InvalidArgument)
            }
        }
    }
}

pub fn sys_package_remove(args: [u64; 6]) -> SyscallResult {
    if args[2] != 1 {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }
    let name = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(name) => name,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    match crate::pkg::remove(&name) {
        Ok(generation) => {
            crate::userspace::unregister_dynamic_program(&name, &crate::pkg::bin_path(&name));
            SyscallResult::ok(generation)
        }
        Err(error) => {
            crate::serial_println!("[package-api] remove {} failed: {}", name, error);
            SyscallResult::err(SyscallStatus::InvalidArgument)
        }
    }
}

pub fn sys_package_rollback(args: [u64; 6]) -> SyscallResult {
    if args[0] != 1 {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }
    match crate::pkg::rollback() {
        Ok(generation) => SyscallResult::ok(generation),
        Err(error) => {
            crate::serial_println!("[package-api] rollback failed: {}", error);
            SyscallResult::err(SyscallStatus::InvalidArgument)
        }
    }
}

pub fn sys_package_launch(args: [u64; 6]) -> SyscallResult {
    let name = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(name) => name,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let (meta, binary) = match crate::pkg::load_installed(&name) {
        Ok(package) => package,
        Err(error) => {
            crate::serial_println!("[package-api] launch {} failed: {}", name, error);
            return SyscallResult::err(SyscallStatus::PermissionDenied);
        }
    };
    match crate::process::spawn_elf(&name, &binary, &meta.capabilities) {
        Ok(pid) => SyscallResult::ok(pid),
        Err(error) => {
            crate::serial_println!("[package-api] launch {} failed: {}", name, error);
            SyscallResult::err(SyscallStatus::InvalidArgument)
        }
    }
}
