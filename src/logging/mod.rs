// ============================================================================
// FerrumOS — Logging Subsystem
// ============================================================================

pub mod audit;

/// Initialize the logging subsystem
pub fn init() {
    audit::init();
}
