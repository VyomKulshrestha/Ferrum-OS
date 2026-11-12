//! Compiles the syscall-free decision modules of `heliox-daemon` from their
//! own source files, so the authority gate is tested on the host exactly as
//! the daemon builds it. Run:
//!   cargo test --manifest-path userland/heliox-gate-tests/Cargo.toml --target <host triple>
extern crate alloc;

pub mod cognitive {
    #[path = "../../../heliox-daemon/src/cognitive/json.rs"]
    pub mod json;
    #[path = "../../../heliox-daemon/src/cognitive/authority.rs"]
    pub mod authority;
    #[path = "../../../heliox-daemon/src/cognitive/confirmation.rs"]
    pub mod confirmation;
}

/// The daemon sources, for consistency checks between the tier table, the
/// advertised tool list and the dispatch arms.
pub const TOOL_MAPPER_SOURCE: &str =
    include_str!("../../heliox-daemon/src/cognitive/tool_mapper.rs");
pub const ORCHESTRATOR_SOURCE: &str =
    include_str!("../../heliox-daemon/src/cognitive/orchestrator.rs");
pub const MAIN_SOURCE: &str = include_str!("../../heliox-daemon/src/main.rs");
pub const SELF_EVOLVE_SOURCE: &str =
    include_str!("../../heliox-daemon/src/cognitive/self_evolve.rs");
pub const ASSISTANT_PANEL_SOURCE: &str =
    include_str!("../../heliox-assistant-panel/src/main.rs");

/// Kernel sources, for checks of the syscall contract the daemon relies on
/// (the kernel itself builds only in CI; its run-time behaviour is checked by
/// `test-syscall` self-tests in the QEMU harnesses).
pub const KERNEL_SYSCALL_SOURCE: &str = include_str!("../../../src/syscall/mod.rs");
pub const KERNEL_SYSCALL_FS_SOURCE: &str = include_str!("../../../src/syscall/fs.rs");
pub const KERNEL_SYSCALL_PROCESS_SOURCE: &str = include_str!("../../../src/syscall/process.rs");
pub const KERNEL_FS_SOURCE: &str = include_str!("../../../src/fs/mod.rs");

/// A file-version source for tests that are not about file versions: every
/// file is absent and stays so. The daemon's own default fails closed
/// (`confirmation::versions_unavailable`); the daemon installs the kernel's.
pub fn stable_versions(_path: &str) -> Result<cognitive::confirmation::FileVersion, ()> {
    Ok(cognitive::confirmation::FileVersion::Absent)
}
