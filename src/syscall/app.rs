// FerrumOS trusted built-in application launcher syscall.

use super::{SyscallResult, SyscallStatus};

pub fn sys_app_launch(args: [u64; 6]) -> SyscallResult {
    let name = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(name) => name,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    // Legacy three-argument callers pass a null context pointer; ignore r10
    // in that case because the old ABI did not promise to initialize it.
    let launch_context = if args[2] == 0 {
        None
    } else {
        if args[3] == 0 || args[3] as usize > crate::process::MAX_LAUNCH_CONTEXT_BYTES {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        match unsafe { super::fs::read_user_str(args[2], args[3]) } {
            Some(context) => Some(context),
            None => return SyscallResult::err(SyscallStatus::InvalidArgument),
        }
    };
    match crate::userspace::launch_embedded_app_with_context(&name, launch_context.as_deref()) {
        Ok(pid) => SyscallResult::ok(pid),
        Err(error) => {
            crate::serial_println!("[app-launch] {} failed: {}", name, error);
            SyscallResult::err(SyscallStatus::InvalidArgument)
        }
    }
}
