// ============================================================================
// FerrumOS - Kernel build script
// ============================================================================
// Builds the Phase 1.1+ userspace binaries (currently only `init`) and makes
// sure their ELFs exist before the kernel crate is compiled. The kernel then
// pulls the bytes in via `include_bytes!` from the corresponding module.
// ============================================================================

use std::env;
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let manifest_dir =
        env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set by cargo");
    let manifest_path = PathBuf::from(&manifest_dir).join("userland/init/Cargo.toml");

    println!("cargo:rerun-if-changed=userland/init/Cargo.toml");
    println!("cargo:rerun-if-changed=userland/init/.cargo/config.toml");
    println!("cargo:rerun-if-changed=userland/init/src");

    if !manifest_path.exists() {
        // Allow the build to proceed in environments where the userland has
        // not been vendored yet. The kernel can still boot; the embedded
        // init ELF will simply be a zero-length blob until the userland
        // workspace is present.
        return;
    }

    let cargo = env::var("CARGO").unwrap_or_else(|_| String::from("cargo"));

    let status = Command::new(&cargo)
        .arg("build")
        .arg("--manifest-path")
        .arg(&manifest_path)
        .status()
        .expect("failed to spawn cargo for userland build");

    if !status.success() {
        panic!(
            "ferrumos userland build failed (manifest={}); see output above",
            manifest_path.display()
        );
    }

    // The Rust target `x86_64-unknown-none` places .text at 0x201000,
    // which collides with the kernel text page. rust-lld ignores the
    // `-T` linker-script override, so we rewrite the resulting ELF in
    // place: shift every PT_LOAD segment from 0x201000 -> 0x400000 and
    // rewrite the ELF entry point by the same delta.
    let init_bin = PathBuf::from(&manifest_dir)
        .join("userland/init/target/x86_64-unknown-none/debug/init");
    if init_bin.exists() {
        if let Err(e) = rewrite_load_address(&init_bin, 0x200000, 0x400000) {
            println!(
                "cargo:warning=[ferrumos build.rs] ELF rewrite failed for {}: {}",
                init_bin.display(),
                e
            );
        }
    }
}

/// Shift every PT_LOAD segment by the delta `to - from`. The userland
/// is a single-image freestanding ELF whose lowest PT_LOAD lives at
/// `from`; we just translate the whole image to `to`.
fn rewrite_load_address(path: &std::path::Path, from: u64, to: u64) -> std::io::Result<()> {
    let mut f = fs::OpenOptions::new().read(true).write(true).open(path)?;
    let mut buf = [0u8; 64];
    f.read_exact(&mut buf)?;
    if &buf[..4] != b"\x7fELF" || buf[4] != 2 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "not an ELF64 file",
        ));
    }
    if buf[5] != 1 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "big-endian ELF not supported",
        ));
    }
    let entry_off: usize = 0x18;
    let phoff = usize::from_le_bytes(buf[0x20..0x28].try_into().unwrap());
    let phentsize = u16::from_le_bytes(buf[0x36..0x38].try_into().unwrap()) as usize;
    let phnum = u16::from_le_bytes(buf[0x38..0x3a].try_into().unwrap()) as usize;
    let entry = u64::from_le_bytes(buf[entry_off..entry_off + 8].try_into().unwrap());
    let delta = to.wrapping_sub(from);

    for i in 0..phnum {
        let off = phoff + i * phentsize;
        f.seek(SeekFrom::Start(off as u64))?;
        let mut ph = [0u8; 56];
        f.read_exact(&mut ph)?;
        let p_type = u32::from_le_bytes(ph[0..4].try_into().unwrap());
        if p_type != 1 {
            continue;
        }
        let p_vaddr = u64::from_le_bytes(ph[16..24].try_into().unwrap());
        let p_paddr = u64::from_le_bytes(ph[24..32].try_into().unwrap());
        if (from..from + 0x100000).contains(&p_vaddr) {
            let new_vaddr = to.wrapping_add(p_vaddr.wrapping_sub(from));
            let new_paddr = to.wrapping_add(p_paddr.wrapping_sub(from));
            ph[16..24].copy_from_slice(&new_vaddr.to_le_bytes());
            ph[24..32].copy_from_slice(&new_paddr.to_le_bytes());
            f.seek(SeekFrom::Start(off as u64))?;
            f.write_all(&ph)?;
        }
    }

    let new_entry = entry.wrapping_add(delta);
    f.seek(SeekFrom::Start(entry_off as u64))?;
    f.write_all(&new_entry.to_le_bytes())?;
    Ok(())
}
