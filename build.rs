// ============================================================================
// FerrumOS - Kernel build script
// ============================================================================
// Builds the userspace binaries and makes sure their ELFs exist before the
// kernel crate is compiled. The kernel then pulls the bytes in via
// `include_bytes!` from the corresponding module.
// ============================================================================

use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Build a plain userland crate (no extra C toolchain needs) at
/// `manifest_dir/userland/<subdir>` with the shared userland rustflags.
/// Silently skipped if the crate directory doesn't exist yet, same as the
/// top-level init check - lets the kernel still build in environments
/// where the full userland tree hasn't been vendored.
fn build_userland_crate(cargo: &str, manifest_dir: &str, subdir: &str, rustflags: &str) {
    println!("cargo:rerun-if-changed=userland/{subdir}/Cargo.toml");
    println!("cargo:rerun-if-changed=userland/{subdir}/.cargo/config.toml");
    println!("cargo:rerun-if-changed=userland/{subdir}/src");

    let dir = PathBuf::from(manifest_dir).join("userland").join(subdir);
    if !dir.join("Cargo.toml").exists() {
        return;
    }

    let status = Command::new(cargo)
        .arg("build")
        .arg("--release")
        .arg("--target")
        .arg("x86_64-unknown-none")
        .current_dir(&dir)
        .env("CARGO_ENCODED_RUSTFLAGS", rustflags)
        .env_remove("RUSTFLAGS")
        .status()
        .unwrap_or_else(|e| panic!("failed to spawn cargo for {subdir} build: {e}"));

    if !status.success() {
        panic!("ferrumos {subdir} build failed (dir={}); see output above", dir.display());
    }
}

fn main() {
    let manifest_dir =
        env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set by cargo");
    let manifest_path = Path::new(&manifest_dir).join("userland/init/Cargo.toml");

    if !manifest_path.exists() {
        // Allow the build to proceed in environments where the userland has
        // not been vendored yet. The kernel can still boot; the embedded
        // init ELF will simply be a zero-length blob until the userland
        // workspace is present.
        println!("cargo:rerun-if-changed=userland/init/Cargo.toml");
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

    build_userland_crate(&cargo, &manifest_dir, "init", &userland_rustflags);

    // Build heliox-daemon - needs its own C toolchain env for a couple of
    // dependencies that fall back to a C implementation, unlike every other
    // userland crate here.
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

    // gui-smoke-test (D1 app-window framework verification binary) and the
    // real installed apps built on top of it (libferrumgui is a plain path
    // dependency of each, so building the app crate builds the library too
    // - it doesn't need its own entry here).
    build_userland_crate(&cargo, &manifest_dir, "gui-smoke-test", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "text-editor", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "calculator", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "file-manager", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "heliox-assistant-panel", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "settings", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "browser", &userland_rustflags);
    build_userland_crate(&cargo, &manifest_dir, "app-store", &userland_rustflags);
    // Deliberately NOT embedded into the kernel binary via include_bytes!
    // (unlike every app above) - notes is the demo package for ferrumpkg,
    // staged onto the appliance disk image by scripts/make-appliance.ps1
    // and loaded at runtime via sys_exec's VFS-read fallback path
    // (src/syscall/process.rs), proving the kernel can run code it never
    // shipped with, not just bookkeeping around pre-embedded binaries.
    build_userland_crate(&cargo, &manifest_dir, "notes", &userland_rustflags);

    // The userland crates link themselves directly at the dedicated user P4
    // slot (P4[1], base 0x80_0000_0000) via `--image-base` in their
    // .cargo/config.toml. Because the images are non-PIE with absolute
    // addressing, the link address must equal the runtime load address — so
    // there is deliberately no post-link ELF patching here. If a userland
    // binary ever links outside the user region, the kernel ELF loader
    // rejects it at load time (see `process::AddressSpace`), which surfaces
    // the misconfiguration loudly instead of silently corrupting memory.
}
