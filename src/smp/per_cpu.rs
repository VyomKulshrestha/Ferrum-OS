

/// Holds state specific to a single CPU core.
/// In a full OS, this would be accessed via the `gs` segment register.
#[repr(C)]
pub struct PerCpu {
    /// APIC ID of this core
    pub apic_id: u32,
    
    /// Current task/process context placeholder
    pub current_task: u64,
}

impl PerCpu {
    pub fn new(apic_id: u32) -> Self {
        Self {
            apic_id,
            current_task: 0,
        }
    }

    /// Sets up the GS register to point to this PerCpu struct
    pub fn setup_gs(&mut self) {
        let ptr = self as *mut PerCpu as u64;
        
        // Write the pointer to the IA32_GS_BASE MSR (0xC0000101)
        // Note: x86_64 crate has Msr abstractions for this
        use x86_64::registers::model_specific::Msr;
        let mut gs_base = Msr::new(0xC0000101);
        unsafe { gs_base.write(ptr) };
    }
}
