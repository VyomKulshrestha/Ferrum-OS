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

pub fn trigger_hot_reload() -> Result<(), &'static str> {
    let kernel_path = "/disk/boot/kernel.bin";
    
    // Read the compiled new kernel binary
    let bytes = match read_file_to_vec(kernel_path) {
        Ok(b) => b,
        Err(_) => return Err("Failed to load /disk/boot/kernel.bin"),
    };

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
