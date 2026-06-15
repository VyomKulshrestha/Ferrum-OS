// ============================================================================
// Heliox-OS — Host-Assisted Self-Evolution Trigger
// ============================================================================

extern crate alloc;

use alloc::vec::Vec;

fn read_file_to_vec(path: &str) -> Result<Vec<u8>, &'static str> {
    const SYS_READ_FILE: u64 = 15;
    // We allocate a buffer on the heap (up to 4 MB for dummy kernel image)
    let mut buf = alloc::vec![0u8; 4 * 1024 * 1024];
    let bytes_read = unsafe {
        crate::syscall4(
            SYS_READ_FILE,
            path.as_ptr() as u64,
            path.len() as u64,
            buf.as_mut_ptr() as u64,
            buf.len() as u64,
        )
    };
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
