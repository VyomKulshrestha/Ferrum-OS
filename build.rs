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

    // Flags every userland binary must build with. They are linked non-PIE at
    // the dedicated user P4 slot (P4[1], base 0x80_0000_0000) with the large
    // code model so 64-bit absolute relocations resolve at that high address.
    // We pass them through CARGO_ENCODED_RUSTFLAGS (units separated by 0x1f)
    // *explicitly* because this build script inherits the kernel build's own
    // CARGO_ENCODED_RUSTFLAGS, and that env var overrides any .cargo/config a
    // child cargo would otherwise read — so the userland configs alone are not
    // enough when built transitively. RUSTFLAGS is cleared for the same reason.
    let userland_rustflags = [
        "-C",
        "relocation-model=static",
        "-C",
        "code-model=large",
        "--cfg",
        "aes_force_soft",
        "--cfg",
        "polyval_force_soft",
        "-C",
        "link-arg=-no-pie",
        "-C",
        "link-arg=--image-base=0x8000000000",
    ]
    .join("\u{1f}");

    let init_dir = PathBuf::from(&manifest_dir).join("userland/init");
    let init_status = Command::new(&cargo)
        .arg("build")
        .arg("--release")
        .arg("--target")
        .arg("x86_64-unknown-none")
        .current_dir(&init_dir)
        .env("CARGO_ENCODED_RUSTFLAGS", &userland_rustflags)
        .env_remove("RUSTFLAGS")
        .status()
        .expect("failed to spawn cargo for userland init build");

    if !init_status.success() {
        panic!(
            "ferrumos userland init build failed (dir={}); see output above",
            init_dir.display()
        );
    }

    // Build heliox-daemon
    let daemon_dir = PathBuf::from(&manifest_dir).join("userland/heliox-daemon");
    let daemon_manifest = daemon_dir.join("Cargo.toml");
    println!("cargo:rerun-if-changed=userland/heliox-daemon/Cargo.toml");
    println!("cargo:rerun-if-changed=userland/heliox-daemon/.cargo/config.toml");
    println!("cargo:rerun-if-changed=userland/heliox-daemon/src");

    if daemon_manifest.exists() {
        let ucrt_junction = PathBuf::from(&manifest_dir).join("target").join("ucrt");
        if !ucrt_junction.exists() {
            let ucrt_base = PathBuf::from("C:\\Program Files (x86)\\Windows Kits\\10\\Include");
            if ucrt_base.exists() {
                if let Ok(entries) = std::fs::read_dir(&ucrt_base) {
                    let mut versions: Vec<PathBuf> = entries
                        .filter_map(|e| e.ok())
                        .map(|e| e.path())
                        .filter(|p| p.is_dir() && p.file_name().unwrap().to_str().unwrap().starts_with("10."))
                        .collect();
                    versions.sort();
                    if let Some(latest) = versions.last() {
                        let ucrt_dir = latest.join("ucrt");
                        if ucrt_dir.exists() {
                            let _ = Command::new("cmd")
                                .args(&[
                                    "/c",
                                    "mklink",
                                    "/j",
                                    ucrt_junction.to_str().unwrap(),
                                    ucrt_dir.to_str().unwrap(),
                                ])
                                .status();
                        }
                    }
                }
            }
        }

        let msvc_junction = PathBuf::from(&manifest_dir).join("target").join("msvc");
        if !msvc_junction.exists() {
            if let Some(msvc_dir) = find_msvc_include() {
                let _ = Command::new("cmd")
                    .args(&[
                        "/c",
                        "mklink",
                        "/j",
                        msvc_junction.to_str().unwrap(),
                        msvc_dir.to_str().unwrap(),
                    ])
                    .status();
            }
        }

        let cflags = format!(
            "-I{} -I{}",
            ucrt_junction.to_str().unwrap(),
            msvc_junction.to_str().unwrap()
        );

        let daemon_status = Command::new(&cargo)
            .arg("build")
            .arg("--release")
            .arg("--target")
            .arg("x86_64-unknown-none")
            .current_dir(&daemon_dir)
            .env("CARGO_ENCODED_RUSTFLAGS", &userland_rustflags)
            .env("CC", "C:\\Program Files\\LLVM\\bin\\clang.exe")
            .env("AR", "C:\\Program Files\\LLVM\\bin\\llvm-ar.exe")
            .env("CFLAGS", &cflags)
            .env_remove("RUSTFLAGS")
            .status()
            .expect("failed to spawn cargo for heliox-daemon build");

        if !daemon_status.success() {
            panic!(
                "ferrumos heliox-daemon build failed (dir={}); see output above",
                daemon_dir.display()
            );
        }
    }

    // The userland crates link themselves directly at the dedicated user P4
    // slot (P4[1], base 0x80_0000_0000) via `--image-base` in their
    // .cargo/config.toml. Because the images are non-PIE with absolute
    // addressing, the link address must equal the runtime load address — so
    // there is deliberately no post-link ELF patching here. If a userland
    // binary ever links outside the user region, the kernel ELF loader
    // rejects it at load time (see `process::AddressSpace`), which surfaces
    // the misconfiguration loudly instead of silently corrupting memory.
}

fn find_msvc_include() -> Option<PathBuf> {
    let base = PathBuf::from("C:\\Program Files\\Microsoft Visual Studio\\2022");
    if !base.exists() {
        return None;
    }
    if let Ok(entries) = std::fs::read_dir(&base) {
        for entry in entries.filter_map(|e| e.ok()) {
            let msvc_dir = entry.path().join("VC/Tools/MSVC");
            if msvc_dir.exists() {
                if let Ok(subentries) = std::fs::read_dir(&msvc_dir) {
                    let mut versions: Vec<PathBuf> = subentries
                        .filter_map(|e| e.ok())
                        .map(|e| e.path())
                        .collect();
                    versions.sort();
                    if let Some(latest) = versions.last() {
                        let inc_dir = latest.join("include");
                        if inc_dir.exists() {
                            return Some(inc_dir);
                        }
                    }
                }
            }
        }
    }
    None
}

