use acpi::{AcpiHandler, AcpiTables, PhysicalMapping};
use core::ptr::NonNull;
use x86_64::{PhysAddr, VirtAddr};
use x86_64::instructions::port::Port;
use crate::println;
use crate::sync::DeadlockMutex;
use lazy_static::lazy_static;

#[derive(Clone)]
pub struct FerrumAcpiHandler {
    phys_mem_offset: VirtAddr,
}

impl FerrumAcpiHandler {
    pub fn new(phys_mem_offset: VirtAddr) -> Self {
        Self { phys_mem_offset }
    }
}

impl AcpiHandler for FerrumAcpiHandler {
    unsafe fn map_physical_region<T>(
        &self,
        physical_address: usize,
        size: usize,
    ) -> PhysicalMapping<Self, T> {
        let phys_addr = PhysAddr::new(physical_address as u64);
        let virt_addr = self.phys_mem_offset + phys_addr.as_u64();
        
        PhysicalMapping::new(
            physical_address,
            NonNull::new(virt_addr.as_mut_ptr()).unwrap(),
            size,
            size,
            self.clone(),
        )
    }

    fn unmap_physical_region<T>(_region: &PhysicalMapping<Self, T>) {
        // Direct physical mapping requires no unmapping
    }
}

pub struct AcpiSubsystem {
    pub tables: AcpiTables<FerrumAcpiHandler>,
}

lazy_static! {
    pub static ref ACPI_SUBSYSTEM: DeadlockMutex<Option<AcpiSubsystem>> = DeadlockMutex::new(None);
}

pub fn init(phys_mem_offset: VirtAddr) {
    let handler = FerrumAcpiHandler::new(phys_mem_offset);
    
    // In legacy BIOS boot (which we use), the RSDP is located in the 0xE0000..=0xFFFFF memory range.
    match unsafe { AcpiTables::search_for_rsdp_bios(handler) } {
        Ok(tables) => {
            println!("[  OK  ] ACPI Tables parsed successfully");
            
            if let Ok(platform_info) = acpi::PlatformInfo::new(&tables) {
                if let acpi::InterruptModel::Apic(_apic) = platform_info.interrupt_model {
                    println!("         Found APIC model. BSP APIC ID: {}", platform_info.processor_info.as_ref().unwrap().boot_processor.local_apic_id);
                    println!("         Found {} Application Processors", platform_info.processor_info.as_ref().unwrap().application_processors.len());
                }
            }
            
            *ACPI_SUBSYSTEM.lock() = Some(AcpiSubsystem { tables });
        }
        Err(e) => {
            println!("[ FAIL ] Failed to parse ACPI tables: {:?}", e);
        }
    }
}

pub fn shutdown() -> ! {
    println!("Initiating ACPI shutdown...");
    // A full ACPI shutdown involves parsing the \_S5 object using AML to get the SLP_TYPa and SLP_TYPb values,
    // then writing them along with the SLP_EN bit to the PM1a and PM1b control registers from the FADT.
    // For this minimal kernel, we'll try a common QEMU/Bochs shutdown sequence first.
    
    // QEMU shutdown via ISA debug exit port
    let mut port = Port::<u16>::new(0x604);
    unsafe { port.write(0x2000) };
    
    // QEMU fallback via old Bochs port
    let mut port = Port::<u16>::new(0xB004);
    unsafe { port.write(0x2000) };
    
    // VirtualBox fallback
    let mut port = Port::<u16>::new(0x4004);
    unsafe { port.write(0x3400) };
    
    loop {
        x86_64::instructions::hlt();
    }
}

pub fn reboot() -> ! {
    println!("Initiating reboot...");
    
    // Try 8042 keyboard controller pulse
    let mut port = Port::<u8>::new(0x64);
    unsafe {
        // Empty the keyboard buffer
        let mut temp = Port::<u8>::new(0x60);
        while port.read() & 0x02 != 0 {
            temp.read();
        }
        port.write(0xFE); // Pulse reset line
    }
    
    loop {
        x86_64::instructions::hlt();
    }
}
