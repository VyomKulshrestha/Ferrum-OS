// ============================================================================
// FerrumOS — Kexec Syscall Handler
// ============================================================================

extern crate alloc;

use super::{SyscallResult, SyscallStatus};
use x86_64::{VirtAddr, PhysAddr};
use x86_64::structures::paging::{PageTable, OffsetPageTable, PageTableFlags, Size4KiB, Page, PhysFrame, Mapper, FrameAllocator};

struct GlobalFrameSource;

unsafe impl FrameAllocator<Size4KiB> for GlobalFrameSource {
    fn allocate_frame(&mut self) -> Option<PhysFrame<Size4KiB>> {
        crate::memory::allocate_frame()
    }
}

/// Largest image `sys_kexec` accepts: it maps exactly one 4 KiB page at
/// 0x900000 and copies the image there.
pub const MAX_KEXEC_IMAGE: usize = 4096;

/// Size and magic checks applied to a kexec image before it is copied. Split
/// out so the kernel self-test (`test-syscall kexec-bound`) runs the same
/// check without jumping to the image.
pub fn validate_image(bytes: &[u8]) -> Result<(), SyscallStatus> {
    // Only the single 4 KiB page at 0x900000 is mapped; copying a longer
    // image would write through whatever lies past it.
    if bytes.len() < 4 || bytes.len() > MAX_KEXEC_IMAGE {
        return Err(SyscallStatus::InvalidArgument);
    }
    if &bytes[0..4] != b"\x7FELF" {
        return Err(SyscallStatus::InvalidArgument);
    }
    Ok(())
}

pub fn sys_kexec(args: [u64; 6]) -> SyscallResult {
    let kernel_ptr = args[0];
    let kernel_len = args[1];

    // 1. Verify capability
    let caller_pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
    let held_capabilities = match crate::scheduler::capabilities_of(caller_pid) {
        Some(caps) => caps,
        None => alloc::vec![],
    };

    if !held_capabilities.iter().any(|c| c == "cap:system:kexec" || c == "cap:system:all") {
        return SyscallResult::err(SyscallStatus::PermissionDenied);
    }

    // 2. Read userspace bytes
    // Never copy more than the one page that is mapped below (this used to
    // read up to 8 MiB into the kernel heap first).
    let bytes = match unsafe { crate::syscall::fs::read_user_bytes(kernel_ptr, kernel_len, MAX_KEXEC_IMAGE) } {
        Some(b) => b,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    if let Err(status) = validate_image(&bytes) {
        return SyscallResult::err(status);
    }

    crate::println!("[kexec] Validated new kernel image. Preparing jump...");

    // 3. Jump MVP Test
    // Copy the code to a known identity mapped page and jump.
    let target_phys_addr = PhysAddr::new(0x900000);
    let target_virt_addr = VirtAddr::new(0x900000);
    
    // Get the active page table mapper
    let active_p4 = crate::memory::active_p4_frame();
    let l4_virt = crate::memory::phys_to_virt(active_p4.start_address());
    let l4_table = unsafe { &mut *l4_virt.as_mut_ptr::<PageTable>() };
    let mut mapper = unsafe { OffsetPageTable::new(l4_table, crate::memory::phys_to_virt(PhysAddr::new(0))) };
    
    // Map page 0x900000 to frame 0x900000
    let page: Page<Size4KiB> = Page::containing_address(target_virt_addr);
    let frame: PhysFrame<Size4KiB> = PhysFrame::containing_address(target_phys_addr);
    let flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE;
    
    // Unmap first if already mapped
    if mapper.translate_page(page).is_ok() {
        let _ = mapper.unmap(page);
    }
    
    unsafe {
        let mut allocator = GlobalFrameSource;
        // A failed mapping (no frame for a page table) was an `unwrap`, a
        // kernel panic; the call now fails instead.
        match mapper.map_to(page, frame, flags, &mut allocator) {
            Ok(flush) => flush.flush(),
            Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
        }
        
        // Copy the payload directly to 0x900000
        let dest_slice = core::slice::from_raw_parts_mut(0x900000 as *mut u8, bytes.len());
        dest_slice.copy_from_slice(&bytes);
        
        crate::println!("[kexec] Relocated payload to 0x900000. Disabling interrupts and jumping...");
        
        // Disable interrupts, set stack pointer, and jump!
        core::arch::asm!(
            "cli",
            "mov rsp, 0x902000", // Safe stack inside the identity mapped region
            "jmp rax",
            in("rax") 0x900000,
            options(noreturn)
        );
    }
}
