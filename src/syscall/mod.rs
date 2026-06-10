// ============================================================================
// FerrumOS - Syscall ABI Skeleton
// ============================================================================
// This module defines the stable kernel/userspace boundary before true
// userspace execution exists. Handlers are intentionally minimal in v0.1:
// they document the ABI and provide a deterministic dispatch point for future
// ring-3 process support.
// ============================================================================

/// Stable syscall numbers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub enum SyscallNumber {
    Yield = 0,
    IpcSend = 1,
    IpcReceive = 2,
    ServiceStart = 3,
    ServiceStop = 4,
    CapabilityCheck = 5,
    AuditWrite = 6,
    Socket = 7,
    Bind = 8,
    Listen = 9,
    Accept = 10,
    Recv = 11,
    Send = 12,
    Wait = 13,
    Connect = 14,
    ReadFile = 15,
    WriteFile = 16,
    ReadDir = 17,
    Exec = 18,
    ReadFramebufferInfo = 19,
    ReadTextBuffer = 20,
    CreateDir = 21,
    DeleteFile = 22,
    PlayAudio = 23,
    RecordAudio = 24,
    SetVolume = 25,
    InjectKey = 26,
    InjectMouse = 27,
    PollInput = 28,
    SystemQuery = 29,
    /// Terminate the calling process. args[0] = exit code.
    /// Handled directly in the interrupt layer (it must context-switch
    /// away); never reaches `dispatch_with_capabilities`.
    Exit = 30,
    /// Return the calling process's pid.
    GetPid = 31,
    /// Sleep for args[0] milliseconds. Handled in the interrupt layer
    /// like `Exit` (it blocks the caller and switches away).
    Sleep = 32,
    /// Poll a child's exit status. args[0] = pid, or u64::MAX for
    /// "any". Returns the exit code, or u64::MAX if still running.
    WaitPid = 33,
    /// Write bytes to the console. args[0] = fd (1 = console+serial,
    /// 2 = serial only), args[1] = ptr, args[2] = len.
    Write = 34,
}

/// Syscall return status.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i64)]
pub enum SyscallStatus {
    Ok = 0,
    UnknownSyscall = -1,
    PermissionDenied = -2,
    InvalidArgument = -3,
    NotImplemented = -4,
}

/// Raw syscall result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SyscallResult {
    pub status: SyscallStatus,
    pub value: u64,
}

impl SyscallResult {
    pub const fn ok(value: u64) -> Self {
        Self {
            status: SyscallStatus::Ok,
            value,
        }
    }

    pub const fn err(status: SyscallStatus) -> Self {
        Self { status, value: 0 }
    }
}

extern crate alloc;

pub mod socket;
pub mod fs;
pub mod process;
pub mod graphics;
pub mod audio;
pub mod input;
pub mod query;

use alloc::string::String;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub enum CapabilityResource {
    IpcSend = 1,
    ServiceRegister = 2,
    AuditRead = 3,
    ProcessSpawn = 4,
}

impl CapabilityResource {
    fn resource(self) -> &'static str {
        match self {
            Self::IpcSend => "ipc:send:*",
            Self::ServiceRegister => "service:register",
            Self::AuditRead => "audit:read",
            Self::ProcessSpawn => "process:spawn",
        }
    }

    fn from_raw(raw: u64) -> Option<Self> {
        match raw {
            1 => Some(Self::IpcSend),
            2 => Some(Self::ServiceRegister),
            3 => Some(Self::AuditRead),
            4 => Some(Self::ProcessSpawn),
            _ => None,
        }
    }
}

pub fn dispatch(number: u64, args: [u64; 6]) -> SyscallResult {
    let held_capabilities = alloc::vec![String::from("cap:system:all")];
    dispatch_with_capabilities(number, args, &held_capabilities)
}

pub fn dispatch_for_process(pid: u64, number: u64, args: [u64; 6]) -> SyscallResult {
    // Real ELF processes (loaded via `ring3` or `sys_exec`) live in the
    // scheduler, not in the simulated userspace model registry, so fall
    // back to the scheduler task's capability set for them.
    let held_capabilities = match crate::userspace::capabilities_for(pid) {
        Some(caps) => caps,
        None => match crate::scheduler::capabilities_of(pid) {
            Some(caps) => caps,
            None => return SyscallResult::err(SyscallStatus::InvalidArgument),
        },
    };

    // Best-effort bookkeeping; real processes are not in the model
    // registry and that must not block their syscalls.
    let _ = crate::userspace::record_syscall(pid);

    dispatch_with_capabilities(number, args, &held_capabilities)
}

pub fn dispatch_with_capabilities(
    number: u64,
    args: [u64; 6],
    held_capabilities: &[String],
) -> SyscallResult {
    match number {
        x if x == SyscallNumber::Yield as u64 => SyscallResult::ok(0),
        x if x == SyscallNumber::IpcSend as u64 => {
            // args[0] = target service string ptr
            // args[1] = target service string len
            // args[2] = payload ptr
            // args[3] = payload len
            let target_service = match unsafe { crate::syscall::fs::read_user_str(args[0], args[1]) } {
                Some(s) => s,
                None => return SyscallResult::err(SyscallStatus::InvalidArgument),
            };
            
            let payload_len = args[3] as usize;
            if payload_len > crate::ipc::MAX_PAYLOAD_BYTES || (payload_len > 0 && args[2] == 0) {
                return SyscallResult::err(SyscallStatus::InvalidArgument);
            }
            
            let payload = if payload_len == 0 {
                alloc::vec::Vec::new()
            } else {
                let slice = unsafe { core::slice::from_raw_parts(args[2] as *const u8, payload_len) };
                slice.to_vec()
            };

            let message = match crate::ipc::Message::new(
                0, // 0 for userspace/unknown pid for now since pid isn't passed down easily
                crate::ipc::Endpoint::new(&target_service, "default"),
                crate::ipc::MessageKind::Event,
                "ipc:send:*",
                &payload,
            ) {
                Ok(message) => message,
                Err(_) => return SyscallResult::err(SyscallStatus::InvalidArgument),
            };
            match crate::ipc::send(message, held_capabilities) {
                Ok(id) => SyscallResult::ok(id),
                Err(crate::ipc::IpcError::PermissionDenied) => {
                    SyscallResult::err(SyscallStatus::PermissionDenied)
                }
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::IpcReceive as u64 => {
            let service_name = if args[2] == 0 || args[3] == 0 {
                String::from("runtime.ipc")
            } else {
                match unsafe { crate::syscall::fs::read_user_str(args[2], args[3]) } {
                    Some(s) => s,
                    None => return SyscallResult::err(SyscallStatus::InvalidArgument),
                }
            };
            
            match crate::ipc::receive_for_service(&service_name) {
                Ok(message) => {
                    let buf_ptr = args[0];
                    let buf_len = args[1] as usize;
                    
                    if buf_ptr == 0 || buf_len == 0 {
                        // User just wants to consume/drop the message or check if there is one
                        return SyscallResult::ok(message.payload().len() as u64);
                    }
                    
                    let to_copy = message.payload().len().min(buf_len);
                    if to_copy > 0 {
                        let end = buf_ptr.saturating_add(to_copy as u64);
                        if end >= 0x0000_7FFF_FFFF_FFFF {
                            return SyscallResult::err(SyscallStatus::InvalidArgument);
                        }
                        unsafe {
                            core::ptr::copy_nonoverlapping(
                                message.payload().as_ptr(),
                                buf_ptr as *mut u8,
                                to_copy,
                            );
                        }
                    }
                    
                    SyscallResult::ok(to_copy as u64)
                }
                Err(crate::ipc::IpcError::NoMessage) => SyscallResult::ok(0),
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::ServiceStart as u64 => {
            match crate::services::start_service_authorized(args[0], held_capabilities) {
                Ok(()) => SyscallResult::ok(args[0]),
                Err(err) if err.starts_with("missing capability") => {
                    SyscallResult::err(SyscallStatus::PermissionDenied)
                }
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::ServiceStop as u64 => {
            match crate::services::stop_service_authorized(args[0], held_capabilities) {
                Ok(()) => SyscallResult::ok(args[0]),
                Err(err) if err.starts_with("missing capability") => {
                    SyscallResult::err(SyscallStatus::PermissionDenied)
                }
                Err(_) => SyscallResult::err(SyscallStatus::InvalidArgument),
            }
        }
        x if x == SyscallNumber::CapabilityCheck as u64 => {
            let Some(resource) = CapabilityResource::from_raw(args[0]) else {
                return SyscallResult::err(SyscallStatus::InvalidArgument);
            };
            if crate::security::has_capability(held_capabilities, resource.resource()) {
                SyscallResult::ok(1)
            } else {
                SyscallResult::ok(0)
            }
        }
        x if x == SyscallNumber::AuditWrite as u64 => {
            if !crate::security::has_capability(held_capabilities, "ipc:send:*") {
                return SyscallResult::err(SyscallStatus::PermissionDenied);
            }
            crate::logging::audit::log_event(
                crate::logging::audit::AuditEvent::FileAccess,
                "userspace audit_write syscall",
            );
            SyscallResult::ok(0)
        }
        x if x == SyscallNumber::Socket as u64 => {
            socket::sys_socket(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::Bind as u64 => {
            socket::sys_bind(args[0], args[1])
        }
        x if x == SyscallNumber::Listen as u64 => {
            socket::sys_listen(args[0], args[1])
        }
        x if x == SyscallNumber::Accept as u64 => {
            socket::sys_accept(args[0])
        }
        x if x == SyscallNumber::Recv as u64 => {
            socket::sys_recv(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::Send as u64 => {
            socket::sys_send(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::Wait as u64 => {
            SyscallResult::ok(0)
        }
        x if x == SyscallNumber::Connect as u64 => {
            socket::sys_connect(args[0], args[1], args[2])
        }
        x if x == SyscallNumber::ReadFile as u64 => {
            fs::sys_read_file(args)
        }
        x if x == SyscallNumber::WriteFile as u64 => {
            fs::sys_write_file(args)
        }
        x if x == SyscallNumber::ReadDir as u64 => {
            fs::sys_read_dir(args)
        }
        x if x == SyscallNumber::Exec as u64 => {
            process::sys_exec(args)
        }
        x if x == SyscallNumber::ReadFramebufferInfo as u64 => {
            graphics::sys_read_framebuffer_info(args)
        }
        x if x == SyscallNumber::ReadTextBuffer as u64 => {
            graphics::sys_read_text_buffer(args)
        }
        x if x == SyscallNumber::CreateDir as u64 => {
            fs::sys_create_dir(args)
        }
        x if x == SyscallNumber::DeleteFile as u64 => {
            fs::sys_delete_file(args)
        }
        x if x == SyscallNumber::PlayAudio as u64 => {
            audio::sys_play_audio(args)
        }
        x if x == SyscallNumber::RecordAudio as u64 => {
            audio::sys_record_audio(args)
        }
        x if x == SyscallNumber::SetVolume as u64 => {
            audio::sys_set_volume(args)
        }
        x if x == SyscallNumber::InjectKey as u64 => {
            input::sys_inject_key(args)
        }
        x if x == SyscallNumber::InjectMouse as u64 => {
            input::sys_inject_mouse(args)
        }
        x if x == SyscallNumber::PollInput as u64 => {
            input::sys_poll_input(args)
        }
        x if x == SyscallNumber::SystemQuery as u64 => {
            query::sys_system_query(args)
        }
        x if x == SyscallNumber::GetPid as u64 => {
            let pid = crate::scheduler::CURRENT_PID.load(core::sync::atomic::Ordering::SeqCst);
            SyscallResult::ok(pid)
        }
        x if x == SyscallNumber::WaitPid as u64 => sys_waitpid(args),
        x if x == SyscallNumber::Write as u64 => sys_write_console(args),
        // Exit and Sleep must context-switch away from the caller, so
        // they are handled directly in the interrupt layer. Reaching
        // this dispatcher means a kernel-context caller invoked them,
        // which has no meaning.
        x if x == SyscallNumber::Exit as u64 || x == SyscallNumber::Sleep as u64 => {
            SyscallResult::err(SyscallStatus::NotImplemented)
        }
        _ => SyscallResult::err(SyscallStatus::UnknownSyscall),
    }
}

/// `sys_waitpid` — Poll the exit status of a task.
///
/// args[0] = pid to wait for, or u64::MAX for "any finished task".
///
/// Returns the exit code if the task has finished, u64::MAX if it is
/// still alive, or InvalidArgument if no such task ever existed.
/// Non-blocking: callers poll with `Sleep` between attempts.
fn sys_waitpid(args: [u64; 6]) -> SyscallResult {
    let target = args[0];
    if target == u64::MAX {
        return match crate::scheduler::take_any_exit_status() {
            Some((_pid, code)) => SyscallResult::ok(code as u64),
            None => SyscallResult::ok(u64::MAX),
        };
    }
    if let Some(code) = crate::scheduler::exit_status(target) {
        return SyscallResult::ok(code as u64);
    }
    let alive = crate::scheduler::list_tasks()
        .iter()
        .any(|t| t.id == target && t.state != crate::scheduler::TaskState::Dead);
    if alive {
        SyscallResult::ok(u64::MAX)
    } else {
        SyscallResult::err(SyscallStatus::InvalidArgument)
    }
}

/// `sys_write_console` — Write bytes from userspace to the console.
///
/// args[0] = fd: 1 = console + serial, 2 = serial only.
/// args[1] = ptr (user pointer to bytes)
/// args[2] = len (capped at 4096)
///
/// Returns the number of bytes written.
fn sys_write_console(args: [u64; 6]) -> SyscallResult {
    let fd = args[0];
    if fd != 1 && fd != 2 {
        return SyscallResult::err(SyscallStatus::InvalidArgument);
    }
    let bytes = match unsafe { fs::read_user_bytes(args[1], args[2], 4096) } {
        Some(b) => b,
        None => return SyscallResult::err(SyscallStatus::InvalidArgument),
    };
    let text = alloc::string::String::from_utf8_lossy(&bytes);
    // `print!` already tees to the serial port (see vga::_print), so
    // fd=1 must not also call serial_print! or every byte doubles on
    // the serial console. fd=2 is the serial-only path.
    if fd == 1 {
        crate::print!("{}", text);
    } else {
        crate::serial_print!("{}", text);
    }
    SyscallResult::ok(bytes.len() as u64)
}
