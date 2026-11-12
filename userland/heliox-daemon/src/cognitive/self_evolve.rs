// ============================================================================
// Heliox-OS — Host-Assisted Self-Evolution Trigger
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;

fn read_file_to_vec(path: &str) -> Result<Vec<u8>, &'static str> {
    const SYS_READ_FILE: u64 = 15;
    const SYS_WRITE: u64 = 34;
    const FD_CONSOLE: u64 = 1;
    // Reject a missing image before requesting one large contiguous heap
    // extent.  Long-lived daemon workloads legitimately fragment the heap;
    // the old unconditional 4 MiB allocation could therefore panic even
    // though the requested upgrade image did not exist at all.
    let mut probe = [0u8; 4];
    let probe_read = unsafe {
        crate::syscall4(
            SYS_READ_FILE,
            path.as_ptr() as u64,
            path.len() as u64,
            probe.as_mut_ptr() as u64,
            probe.len() as u64,
        )
    };
    if (probe_read as i64) < 0 {
        return Err("Failed to read file");
    }

    const MAX_KERNEL_IMAGE_BYTES: usize = 4 * 1024 * 1024;
    let mut buf = Vec::new();
    buf.try_reserve_exact(MAX_KERNEL_IMAGE_BYTES)
        .map_err(|_| "Insufficient contiguous memory for kernel image")?;
    buf.resize(MAX_KERNEL_IMAGE_BYTES, 0);
    let bytes_read = unsafe {
        crate::syscall4(
            SYS_READ_FILE,
            path.as_ptr() as u64,
            path.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
    let msg = alloc::format!("[daemon-read] read {} res: {}\n", path, bytes_read as i64);
    unsafe {
        crate::syscall3(SYS_WRITE, FD_CONSOLE, msg.as_ptr() as u64, msg.len() as u64);
    }
    if (bytes_read as i64) < 0 {
        Err("Failed to read file")
    } else {
        buf.truncate(bytes_read as usize);
        Ok(buf)
    }
}

pub fn trigger_hot_reload(bound: Option<super::confirmation::FileVersion>) -> Result<(), &'static str> {
    // The same path the authority gate binds approvals of this tool to
    // (authority::implicit_subject), so a rewrite withdraws them.
    let kernel_path = super::authority::KERNEL_UPGRADE_IMAGE;
    
    // Read the compiled new kernel binary
    let bytes = match read_file_to_vec(kernel_path) {
        Ok(b) => b,
        Err(_) => return Err("Failed to load /disk/boot/kernel.bin"),
    };

    // An approved upgrade boots only the image the operator approved: the
    // image is read in one ReadFile call, and the kernel's version of the
    // file must still be the approved one afterwards. Versions never repeat
    // within a boot, so an unchanged version means no write fell between the
    // approval check and the read (fi1 joint round 2, K3's check-then-act
    // window; Kexec takes bytes, not a path).
    if let Some(approved) = bound {
        if super::orchestrator::kernel_file_version(kernel_path) != Ok(approved) {
            return Err("the kernel image changed after the upgrade was approved; request it again");
        }
    }

    if bytes.len() < 4 {
        return Err("Kernel image is empty or invalid");
    }

    const SYS_KEXEC: u64 = 38;
    
    unsafe {
        // Trigger the sys_kexec system call to jump to the new kernel
        let res = crate::syscall3(
            SYS_KEXEC,
            bytes.as_ptr() as u64,
            bytes.len() as u64,
            0,
        );
        if (res as i64) < 0 {
            return Err("kexec failed: permission denied or invalid image");
        }
    }

    Ok(())
}
