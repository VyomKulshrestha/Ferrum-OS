// FerrumOS trusted built-in application launcher syscall.

use super::{SyscallResult, SyscallStatus};

pub fn sys_app_launch(args: [u64; 6]) -> SyscallResult {
    let name = match unsafe { super::fs::read_user_str(args[0], args[1]) } {
        Some(name) => name,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    match crate::userspace::launch_embedded_app(&name) {
        Ok(pid) => SyscallResult::ok(pid),
        Err(error) => {
            crate::serial_println!("[app-launch] {} failed: {}", name, error);
            SyscallResult::err(SyscallStatus::InvalidArgument)
        }
    }
}
