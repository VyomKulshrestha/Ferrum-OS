// ============================================================================
// FerrumOS - Kernel self-tests for the QEMU harnesses
// ============================================================================
// `test-syscall <name>` runs one of these from the shell. Each drives the same
// kernel function a ring-3 caller reaches, with arguments no shipped userland
// program sends (a 4097-byte kexec image, a fifth window, a recorder whose
// owner is gone, a malformed ELF), and prints one `selftest <name>:` line that
// `scripts/verify_kernel_selftests.mjs` checks. Every test cleans up after
// itself and never needs a ring-3 process.
// ============================================================================

extern crate alloc;

use crate::println;
use alloc::vec::Vec;

/// Pids no process can hold (process ids count up from 1, scheduler ids from
/// 100), used as the owners of test-only state.
const TEST_PID: u64 = u64::MAX - 1000;

pub fn run(name: &str) -> bool {
    match name {
        "kexec-bound" => kexec_bound(),
        "window-cap" => window_cap(),
        "dead-recorder" => dead_recorder(),
        "elf-bounds" => elf_bounds(),
        "heap-bounds" => heap_bounds(),
        "exec-path" => exec_path(),
        "injected-key" => injected_key(),
        "ipc-sender" => ipc_sender(),
        "injected-terminal" => injected_terminal(),
        "file-version" => file_version(),
        _ => return false,
    }
    true
}

fn kexec_bound() {
    let mut image = alloc::vec![0u8; crate::syscall::kexec::MAX_KEXEC_IMAGE + 1];
    image[..4].copy_from_slice(b"\x7FELF");
    let oversize_rejected = crate::syscall::kexec::validate_image(&image).is_err();
    let page_accepted =
        crate::syscall::kexec::validate_image(&image[..crate::syscall::kexec::MAX_KEXEC_IMAGE]).is_ok();
    println!(
        "selftest kexec-bound: oversize_rejected={} page_accepted={}",
        oversize_rejected, page_accepted
    );
}

fn window_cap() {
    use crate::syscall::SyscallStatus;
    let mut created = 0usize;
    let mut refused = 0usize;
    for _ in 0..6 {
        let result = crate::syscall::gui_window::create_window_for(TEST_PID, "selftest", 32, 32);
        match result.status {
            SyscallStatus::Ok => created += 1,
            _ => refused += 1,
        }
    }
    let left_before_close = crate::gui::app_window::window_count_for(TEST_PID);
    crate::gui::app_window::close_for_pid(TEST_PID);
    let left_after_close = crate::gui::app_window::window_count_for(TEST_PID);
    println!(
        "selftest window-cap: created={} refused={} cap={} held={} after_close={}",
        created,
        refused,
        crate::syscall::gui_window::MAX_WINDOWS_PER_PROCESS,
        left_before_close,
        left_after_close
    );
}

fn dead_recorder() {
    match crate::syscall::audio::selftest_dead_recorder() {
        Ok(released) => println!("selftest dead-recorder: stale_session_released={}", released),
        Err(err) => println!("selftest dead-recorder: skipped ({})", err),
    }
}

/// One-segment ELF64 executable with a PT_LOAD at `vaddr` of `memsz` bytes and
/// no file bytes.
fn tiny_elf(vaddr: u64, memsz: u64) -> Vec<u8> {
    let mut elf = alloc::vec![0u8; 64 + 56];
    elf[0..4].copy_from_slice(b"\x7FELF");
    elf[4] = 2; // ELFCLASS64
    elf[5] = 1; // little endian
    elf[6] = 1; // EV_CURRENT
    elf[16..18].copy_from_slice(&2u16.to_le_bytes()); // ET_EXEC
    elf[18..20].copy_from_slice(&62u16.to_le_bytes()); // EM_X86_64
    elf[20..24].copy_from_slice(&1u32.to_le_bytes());
    elf[24..32].copy_from_slice(&vaddr.to_le_bytes()); // e_entry
    elf[32..40].copy_from_slice(&64u64.to_le_bytes()); // e_phoff
    elf[52..54].copy_from_slice(&64u16.to_le_bytes()); // e_ehsize
    elf[54..56].copy_from_slice(&56u16.to_le_bytes()); // e_phentsize
    elf[56..58].copy_from_slice(&1u16.to_le_bytes()); // e_phnum
    let ph = 64;
    elf[ph..ph + 4].copy_from_slice(&1u32.to_le_bytes()); // PT_LOAD
    elf[ph + 4..ph + 8].copy_from_slice(&6u32.to_le_bytes()); // R + W
    elf[ph + 16..ph + 24].copy_from_slice(&vaddr.to_le_bytes()); // p_vaddr
    elf[ph + 24..ph + 32].copy_from_slice(&vaddr.to_le_bytes()); // p_paddr
    elf[ph + 40..ph + 48].copy_from_slice(&memsz.to_le_bytes()); // p_memsz
    elf[ph + 48..ph + 56].copy_from_slice(&4096u64.to_le_bytes()); // p_align
    elf
}

fn elf_bounds() {
    // 1. A non-canonical segment address must be refused, not panic in
    //    `VirtAddr::new` (which halts the kernel).
    println!("selftest elf-bounds: loading non-canonical PT_LOAD");
    let noncanonical_rejected = match crate::process::create("selftest-elf") {
        Ok(mut process) => process.load_elf(&tiny_elf(0x0000_8000_0000_0000, 0x1000)).is_err(),
        Err(_) => false,
    };
    println!("selftest elf-bounds: noncanonical_rejected={}", noncanonical_rejected);

    // 2. A segment of 0xFFF bytes starting one byte into a page covers exactly
    //    one page. The loader used to map the page after it as well; for a
    //    segment ending at the top of the user region (0x100_0000_0000) that
    //    extra page lands in P4[2], which is shared with the kernel.
    let (pages, mapped_len) = match crate::process::create("selftest-elf") {
        Ok(mut process) => {
            let flags = x86_64::structures::paging::PageTableFlags::PRESENT
                | x86_64::structures::paging::PageTableFlags::USER_ACCESSIBLE
                | x86_64::structures::paging::PageTableFlags::WRITABLE;
            let len = process
                .map_user(x86_64::VirtAddr::new(0x80_1000_0001), 0xFFF, &[], flags)
                .unwrap_or(0);
            (process.user_frame_count(), len)
        }
        Err(_) => (usize::MAX, 0),
    };
    println!(
        "selftest elf-bounds: unaligned_tail_pages={} mapped_len={:#x}",
        pages, mapped_len
    );
}

fn heap_bounds() {
    // Larger than the whole 12 MiB kernel heap: must fail cleanly. The
    // 64 MiB size is /disk/mmap_verify's, the file Exec could be pointed at.
    let huge = crate::fs::try_zeroed_vec(64 * 1024 * 1024).is_none();
    let small = crate::fs::try_zeroed_vec(4096).is_some();
    println!("selftest heap-bounds: oversize_refused={} small_ok={}", huge, small);
}

/// Delivers one key the way InjectKey does (flag set around the event) and
/// reports whether it was kept out of the kernel shell. On a kernel that feeds
/// injected keys to the shell, the `q` also lands on the next command line.
fn injected_key() {
    use core::sync::atomic::Ordering;
    let desktop_owns_keyboard = crate::gui::captures_keyboard();
    let before = crate::input::INJECTED_KEYS_KEPT_FROM_SHELL.load(Ordering::SeqCst);
    crate::input::INJECTING_AGENT_KEY.store(true, Ordering::SeqCst);
    crate::input::inject_key_event(b'q', true);
    crate::input::inject_key_event(b'q', false);
    crate::input::INJECTING_AGENT_KEY.store(false, Ordering::SeqCst);
    let kept = crate::input::INJECTED_KEYS_KEPT_FROM_SHELL.load(Ordering::SeqCst) - before;
    println!(
        "selftest injected-key: kept_from_shell={} desktop_owns_keyboard={}",
        kept, desktop_owns_keyboard
    );
}

fn exec_path() {
    let bypass = "/disk//pkgs-available/demo/bin";
    let dotted = "/tmp/../disk/pkgs/demo";
    let repo = "/disk/pkgs-available/demo/bin";
    let plain = "/tmp/worker";
    println!(
        "selftest exec-path: double_slash_denied={} dotdot_denied={} repo_denied={} plain_allowed={}",
        !crate::syscall::process::exec_path_allowed(bypass),
        !crate::syscall::process::exec_path_allowed(dotted),
        !crate::syscall::process::exec_path_allowed(repo),
        crate::syscall::process::exec_path_allowed(plain)
    );
}

/// K4: how the kernel tells the daemon who sent a control message. A process
/// gets the assistant-panel flag only after a kernel launch path marks it;
/// the mark goes with the pid; a VFS file cannot take a compiled-in name.
fn ipc_sender() {
    let unmarked = crate::ipc::process_sender_flags(TEST_PID);
    crate::ipc::mark_operator_panel(TEST_PID);
    let marked = crate::ipc::process_sender_flags(TEST_PID);
    crate::ipc::forget_pid(TEST_PID);
    let forgotten = crate::ipc::process_sender_flags(TEST_PID);
    let shell_message = crate::ipc::Message::new(
        0,
        crate::ipc::Endpoint::new("heliox", "control"),
        crate::ipc::MessageKind::Request,
        "ipc:send:*",
        b"CONFIRM:1",
    )
    .map(|message| message.with_sender_flags(crate::ipc::SENDER_KERNEL_SHELL).sender_flags)
    .unwrap_or(0);
    let process_message = crate::ipc::Message::new(
        TEST_PID,
        crate::ipc::Endpoint::new("heliox", "default"),
        crate::ipc::MessageKind::Event,
        "ipc:send:*",
        b"CONFIRM:1",
    )
    .map(|message| message.sender_flags)
    .unwrap_or(u64::MAX);
    println!(
        "selftest ipc-sender: unmarked_flags={} panel_flags={} after_reap_flags={} shell_flags={} new_message_flags={}",
        unmarked, marked, forgotten, shell_message, process_message
    );
    println!(
        "selftest ipc-sender: vfs_panel_name_denied={} vfs_daemon_name_denied={} vfs_init_name_denied={} vfs_plain_allowed={}",
        !crate::syscall::process::vfs_exec_name_allowed("/tmp/heliox-assistant-panel"),
        !crate::syscall::process::vfs_exec_name_allowed("/disk/x/heliox-daemon"),
        !crate::syscall::process::vfs_exec_name_allowed("/tmp/init"),
        crate::syscall::process::vfs_exec_name_allowed("/tmp/worker")
    );
}

/// K1: keys and clicks injected through InjectKey / InjectMouse travel the
/// real path (input queue, `cursor::process_input`, compositor) and must not
/// reach the terminal window (a kernel shell) or the launcher, while an app
/// window still receives them, marked as injected.
fn injected_terminal() {
    use core::sync::atomic::Ordering;
    use crate::gui::compositor::{COMPOSITOR, INJECTED_EVENTS_KEPT_FROM_OPERATOR_CONTROLS};
    const KEY_Z: u8 = 0x7A;
    const KEY_K: u8 = 0x6B;
    let terminal_len = || {
        COMPOSITOR
            .lock()
            .windows
            .iter()
            .find(|window| window.win_type == crate::gui::window::WindowType::Terminal)
            .map(|window| window.content.len())
            .unwrap_or(usize::MAX)
    };
    // Drain whatever is queued (and the one-time stale-key discard).
    crate::gui::cursor::process_input();
    let kept_before = INJECTED_EVENTS_KEPT_FROM_OPERATOR_CONTROLS.load(Ordering::SeqCst);

    // 1. Terminal focused, agent types into it.
    crate::gui::compositor::spawn_terminal();
    let before = terminal_len();
    let _ = crate::syscall::input::sys_inject_key([KEY_Z as u64, 0, 0, 0, 0, 0]);
    crate::gui::cursor::process_input();
    let after_injected = terminal_len();
    // Positive control: the same key from the operator reaches it.
    crate::gui::compositor::handle_key_press(KEY_Z, false);
    let after_physical = terminal_len();
    if let Some(window) = COMPOSITOR
        .lock()
        .windows
        .iter_mut()
        .find(|window| window.win_type == crate::gui::window::WindowType::Terminal)
    {
        if after_physical > after_injected {
            window.content.pop();
        }
    }
    println!(
        "selftest injected-terminal: terminal_kept={} physical_reaches_terminal={}",
        after_injected == before && before != usize::MAX,
        after_physical == after_injected + 1
    );

    // 2. An ordinary app window (focused on creation) gets the injected key,
    //    marked, through the same path.
    let window_id = crate::syscall::gui_window::create_window_for(TEST_PID, "selftest", 96, 48).value;
    let _ = crate::syscall::input::sys_inject_key([KEY_K as u64, 0, 0, 0, 0, 0]);
    crate::gui::cursor::process_input();
    let delivered = crate::gui::app_window::poll_input(window_id, TEST_PID);
    crate::gui::app_window::close_for_pid(TEST_PID);
    println!(
        "selftest injected-terminal: app_delivered={} app_marked_injected={}",
        delivered.map(|event| event.tag == 0 && event.a == KEY_K as u32).unwrap_or(false),
        delivered.map(|event| event.injected).unwrap_or(false)
    );

    // 3. An injected click on the launcher's assistant-panel entry launches
    //    nothing.
    let mut probe = None;
    'scan: for y in (0..1080u32).step_by(4) {
        for x in (0..1920u32).step_by(8) {
            if crate::gui::desktop::launcher_entry_at(x, y) == Some(2) {
                probe = Some((x, y));
                break 'scan;
            }
        }
    }
    let panels = || {
        crate::process::list()
            .iter()
            .filter(|(_, name, _)| name == "heliox-assistant-panel")
            .count()
    };
    let launched = match probe {
        Some((x, y)) => {
            let panels_before = panels();
            COMPOSITOR.lock().launcher_open = true;
            crate::gui::compositor::handle_mouse_down(x, y, true);
            crate::gui::compositor::handle_mouse_up(x, y, true);
            COMPOSITOR.lock().launcher_open = false;
            alloc::format!("{}", panels() != panels_before)
        }
        None => alloc::string::String::from("skipped"),
    };
    let kept = INJECTED_EVENTS_KEPT_FROM_OPERATOR_CONTROLS.load(Ordering::SeqCst) - kept_before;
    println!(
        "selftest injected-terminal: launcher_injected_launched={} kept_from_operator_controls={}",
        launched, kept
    );
}

/// K3: the per-file change counter the daemon binds approvals to.
fn file_version() {
    let path = "/tmp/selftest-file-version";
    let _ = crate::fs::remove(path);
    let absent = crate::fs::file_version(path);
    let parent_before = crate::fs::file_version("/tmp").ok().flatten();
    let created = crate::fs::create_file(path, "a").is_ok();
    let v1 = crate::fs::file_version(path).ok().flatten();
    let parent_after = crate::fs::file_version("/tmp").ok().flatten();
    let _ = crate::fs::create_file(path, "a");
    let v2 = crate::fs::file_version(path).ok().flatten();
    let _ = crate::fs::remove(path);
    let after_remove = crate::fs::file_version(path);
    let _ = crate::fs::create_file(path, "a");
    let v3 = crate::fs::file_version(path).ok().flatten();
    let _ = crate::fs::remove(path);
    let below_sign_bit = [v1, v2, v3]
        .iter()
        .all(|v| v.map(|v| v != 0 && v < (1u64 << 63)).unwrap_or(false));
    println!(
        "selftest file-version: absent_is_none={} created={} present={} same_content_rewrite_changes={} parent_changes={}",
        matches!(absent, Ok(None)),
        created,
        v1.is_some(),
        v1.is_some() && v2.is_some() && v1 != v2,
        parent_before.is_some() && parent_before != parent_after
    );
    println!(
        "selftest file-version: removed_is_none={} recreate_is_new={} positive_nonzero={} dotdot_is_error={} file_as_dir_is_error={}",
        matches!(after_remove, Ok(None)),
        v3.is_some() && v3 != v1 && v3 != v2,
        below_sign_bit,
        crate::fs::file_version("/tmp/../etc/hostname").is_err(),
        crate::fs::file_version("/etc/hostname/x").is_err()
    );
}
