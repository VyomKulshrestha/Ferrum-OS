// ============================================================================
// FerrumOS - Kernel build script
// ============================================================================
// Builds the Phase 1.1+ userspace binaries (currently only `init`) and makes
// sure their ELFs exist before the kernel crate is compiled. The kernel then
// pulls the bytes in via `include_bytes!` from the corresponding module.
// ============================================================================

use std::env;
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
}
