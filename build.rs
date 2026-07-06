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
        "-C",
        "target-feature=+sse,+sse2,-soft-float",
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
        let compat_dir = PathBuf::from(&manifest_dir).join("target").join("compat");
        let cflags = format!("-I{}", compat_dir.to_str().unwrap());

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

    // Build gui-smoke-test (D1 app-window framework verification binary).
    let smoke_dir = PathBuf::from(&manifest_dir).join("userland/gui-smoke-test");
    let smoke_manifest = smoke_dir.join("Cargo.toml");
    println!("cargo:rerun-if-changed=userland/gui-smoke-test/Cargo.toml");
    println!("cargo:rerun-if-changed=userland/gui-smoke-test/.cargo/config.toml");
    println!("cargo:rerun-if-changed=userland/gui-smoke-test/src");

    if smoke_manifest.exists() {
        let smoke_status = Command::new(&cargo)
            .arg("build")
            .arg("--release")
            .arg("--target")
            .arg("x86_64-unknown-none")
            .current_dir(&smoke_dir)
            .env("CARGO_ENCODED_RUSTFLAGS", &userland_rustflags)
            .env_remove("RUSTFLAGS")
            .status()
            .expect("failed to spawn cargo for gui-smoke-test build");

        if !smoke_status.success() {
            panic!(
                "ferrumos gui-smoke-test build failed (dir={}); see output above",
                smoke_dir.display()
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

