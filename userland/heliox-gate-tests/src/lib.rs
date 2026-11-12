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
