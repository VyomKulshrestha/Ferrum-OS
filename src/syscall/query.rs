// ============================================================================
// FerrumOS — System Query Syscall Handler
// ============================================================================
// Provides a direct kernel query interface for the agent runtime.
// Instead of fire-and-forget IPC, the agent can now read live system
// data directly into a userspace buffer.
//
// Syscall:
//   SystemQuery = 29
//     args[0] = query_type:
//       0 = system info (uptime, CPU count, kernel version, boot mode)
//       1 = process list (pid, name, state, ticks)
//       2 = memory stats (heap used, heap free, heap total)
//       3 = device list (name, class, state, driver)
//     args[1] = buf_ptr — pointer to user buffer for JSON output
//     args[2] = buf_len — size of buffer in bytes
//   Returns: number of bytes written on success
// ============================================================================

extern crate alloc;
use alloc::string::String;
use alloc::format;
use super::{SyscallResult, SyscallStatus};

/// Execute a system query and write the result as JSON into the user buffer.
pub fn sys_system_query(args: [u64; 6]) -> SyscallResult {
    let query_type = args[0];
    let buf_ptr = args[1] as usize;
    let buf_len = args[2] as usize;

    if buf_ptr == 0 || buf_len == 0 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }

    let json = match query_type {
        0 => query_system_info(),
        1 => query_process_list(),
        2 => query_memory_stats(),
        3 => query_device_list(),
        _ => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };

    let bytes = json.as_bytes();
    let copy_len = core::cmp::min(bytes.len(), buf_len);

    // Safety: buf_ptr is in the calling process's address space.
    // The syscall dispatcher validates this before calling us.
    let dest = buf_ptr as *mut u8;
    if copy_len > 0 {
        let end = buf_ptr.saturating_add(copy_len);
        if end >= 0x0000_7FFF_FFFF_FFFF {
            return SyscallResult::err(SyscallStatus::InvalidArgument);
        }
        unsafe {
            core::ptr::copy_nonoverlapping(bytes.as_ptr(), dest, copy_len);
        }
    }

    SyscallResult::ok(copy_len as u64)
}

/// Query type 0: System information.
fn query_system_info() -> String {
    let uptime = crate::scheduler::total_ticks();
    let active_tasks = crate::scheduler::active_task_count();
    let boot_mode = if crate::graphics::is_initialized() {
        "graphical"
    } else {
        "text"
    };

    let (ram_mb, avx2, tier) = if let Some(info) = crate::hardware::get_info() {
        (info.ram_mb, info.avx2, info.tier)
    } else {
        (0, false, "low")
    };

    format!(
        "{{\"uptime_ticks\":{},\"cpu_count\":1,\"kernel_version\":\"0.1.0\",\"boot_mode\":\"{}\",\"active_tasks\":{},\"ram_mb\":{},\"avx2\":{},\"tier\":\"{}\"}}",
        uptime, boot_mode, active_tasks, ram_mb, avx2, tier
    )
}

/// Query type 1: Process / task list.
fn query_process_list() -> String {
    let tasks = crate::scheduler::list_tasks();
    let mut json = String::from("[");

    for (i, task) in tasks.iter().enumerate() {
        if i > 0 {
            json.push(',');
        }

        let state_str = match task.state {
            crate::scheduler::TaskState::Ready => "Ready",
            crate::scheduler::TaskState::Running => "Running",
            crate::scheduler::TaskState::Blocked => "Blocked",
            crate::scheduler::TaskState::Dead => "Dead",
        };

        let priority_str = match task.priority {
            crate::scheduler::Priority::Idle => "Idle",
            crate::scheduler::Priority::Normal => "Normal",
            crate::scheduler::Priority::High => "High",
            crate::scheduler::Priority::System => "System",
        };

        json.push_str(&format!(
            "{{\"pid\":{},\"name\":\"{}\",\"state\":\"{}\",\"priority\":\"{}\",\"ticks\":{}}}",
            task.id, task.name, state_str, priority_str, task.ticks
        ));
    }

    json.push(']');
    json
}

/// Query type 2: Memory statistics.
fn query_memory_stats() -> String {
    let (used, free) = crate::memory::heap::heap_stats();
    let total = crate::memory::heap::HEAP_SIZE;

    format!(
        "{{\"heap_used\":{},\"heap_free\":{},\"heap_total\":{}}}",
        used, free, total
    )
}

/// Query type 3: Device list.
fn query_device_list() -> String {
    let devices = crate::devices::list_devices();
    let mut json = String::from("[");

    for (i, dev) in devices.iter().enumerate() {
        if i > 0 {
            json.push(',');
        }

        let class_str = match dev.class {
            crate::devices::DeviceClass::Display => "Display",
            crate::devices::DeviceClass::Serial => "Serial",
            crate::devices::DeviceClass::Input => "Input",
            crate::devices::DeviceClass::Timer => "Timer",
            crate::devices::DeviceClass::Storage => "Storage",
            crate::devices::DeviceClass::Network => "Network",
            crate::devices::DeviceClass::Audio => "Audio",
            crate::devices::DeviceClass::Camera => "Camera",
        };

        let state_str = match dev.state {
            crate::devices::DeviceState::Online => "Online",
            crate::devices::DeviceState::Planned => "Planned",
            crate::devices::DeviceState::Disabled => "Disabled",
        };

        json.push_str(&format!(
            "{{\"name\":\"{}\",\"class\":\"{}\",\"state\":\"{}\",\"driver\":\"{}\"}}",
            dev.name, class_str, state_str, dev.driver
        ));
    }

    json.push(']');
    json
}
