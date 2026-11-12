// ============================================================================
// FerrumOS - Kernel self-tests, fi2 kernel audit (workstream K2)
// ============================================================================
// `test-syscall <name>` reaches these after every earlier self-test file. Each
// prints `selftest <name>: key=value ...` lines that
// `scripts/verify_kernel_k6.mjs` checks.
//
//   virtio-backing     a present stays inside the virtio-gpu backing
//   kernel-records     ring 3 cannot write or delete the audit log or the
//                      account table
//   audit-escape       a line break in a logged path or AuditWrite text
//                      cannot forge an audit entry
//   audit-flush        a flush the filesystem refuses keeps the newest lines
//   pkg-confirm        a self-confirmed privileged PackageInstall waits for
//                      the operator
//   pkg-name           a package cannot take a compiled-in program's name
//   serial-titles      a notification title cannot forge a serial line
//   query-names        a task name cannot add entries to SystemQuery's
//                      process list (switched off first: the control)
//   audit-trim-utf8    trimming the audit log inside a multi-byte character
//                      (stops the kernel without the fix: run last)
//   hda-subnodes       a codec SUBNODE_COUNT past node 255 (stops the kernel
//                      without the fix: run last)
// ============================================================================

extern crate alloc;

use super::selftest_k3::{ext2_base, run_until_dead, start_ring3, RamDisk};
use crate::println;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;

pub fn run(name: &str) -> bool {
    match name {
        "virtio-backing" => virtio_backing(),
        "kernel-records" => kernel_records(),
        "audit-escape" => audit_escape(),
        "audit-flush" => audit_flush(),
        "pkg-confirm" => pkg_confirm(true),
        "pkg-confirm-unclaimed" => pkg_confirm(false),
        "pkg-name" => pkg_name(),
        "serial-titles" => serial_titles(),
        "audit-trim-utf8" => audit_trim_utf8(),
        "hda-subnodes" => hda_subnodes(),
        "query-names" => query_names(),
        _ => return false,
    }
    true
}

fn caps(list: &[&str]) -> Vec<String> {
    list.iter().map(|c| String::from(*c)).collect()
}

/// Machine code: syscall `number` with rdi = address of `text`, rsi = its
/// length and `extra` (more argument set-up) in between, then exit with the
/// result. `text` follows the code.
fn syscall_with_text(number: u32, extra: &[u8], text: &[u8]) -> Vec<u8> {
    // lea rdi, [rip + disp]; mov esi, len
    let disp = 24 + extra.len() as u32;
    let mut code = vec![0x48, 0x8D, 0x3D];
    code.extend_from_slice(&disp.to_le_bytes());
    code.push(0xBE);
    code.extend_from_slice(&(text.len() as u32).to_le_bytes());
    code.extend_from_slice(extra);
    // mov eax, number; int 0x80; mov rdi, rax; mov eax, 30; int 0x80; jmp $
    code.push(0xB8);
    code.extend_from_slice(&number.to_le_bytes());
    code.extend_from_slice(&[0xCD, 0x80, 0x48, 0x89, 0xC7, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xFE]);
    code.extend_from_slice(text);
    code
}

/// mov rdx, rdi; mov r10d, 1: a second buffer argument that is the first
/// byte of `text`.
const SECOND_BUFFER_IS_TEXT: [u8; 9] = [0x48, 0x89, 0xFA, 0x41, 0xBA, 0x01, 0x00, 0x00, 0x00];

/// Runs `code` as a ring-3 process holding `held`; returns its exit status
/// as a syscall status name.
fn run_program(name: &str, code: &[u8], held: &[&str], ms: u64) -> String {
    match start_ring3(name, code, &caps(held)) {
        Ok(pid) => {
            let (ended, exit) = run_until_dead(pid, ms);
            status_name(ended, exit)
        }
        Err(e) => alloc::format!("start_error:{}", e.replace(' ', "_")),
    }
}

fn status_name(ended: bool, exit: Option<u32>) -> String {
    use crate::syscall::SyscallStatus as S;
    let code = |s: S| s as i64 as u64 as u32;
    match (ended, exit) {
        (false, _) => String::from("still_running"),
        (true, Some(0)) => String::from("ok"),
        (true, Some(x)) if x == code(S::PermissionDenied) => String::from("permission_denied"),
        (true, Some(x)) if x == code(S::InvalidArgument) => String::from("invalid_argument"),
        (true, Some(x)) => alloc::format!("exit_{:#x}", x),
        (true, None) => String::from("no_status"),
    }
}

// ---- virtio-gpu backing ------------------------------------------------------

/// Presents a frame of one colour and counts how many of the 1024 words just
/// past the backing hold that colour afterwards (the copy ran past the end).
fn virtio_backing() {
    let Some((backing_phys, backing_bytes)) = crate::devices::virtio_gpu::backing_region() else {
        println!("selftest virtio-backing: device=absent");
        return;
    };
    const PATTERN: u32 = 0x005A_C3E7;
    let (w, h) = (1024u32, 768u32);
    let frame_bytes = (w * h * 4) as usize;
    let past = crate::memory::phys_to_virt(x86_64::PhysAddr::new(backing_phys + backing_bytes as u64)).as_u64()
        as *const u32;
    let count_pattern = || (0..1024).filter(|&i| unsafe { core::ptr::read_volatile(past.add(i)) } == PATTERN).count();
    let before = count_pattern();
    let mut pixels: Vec<u32> = Vec::new();
    if pixels.try_reserve_exact((w * h) as usize).is_err() {
        println!("selftest virtio-backing: device=present alloc=failed");
        return;
    }
    pixels.resize((w * h) as usize, PATTERN);
    let present = match crate::devices::virtio_gpu::present(&pixels, w, h) {
        Ok(()) => String::from("ok"),
        Err(e) => e.replace(' ', "_"),
    };
    let after = count_pattern();
    println!(
        "selftest virtio-backing: device=present backing_bytes={} frame_bytes={} present={} past_end_pattern_words_before={} past_end_pattern_words={}",
        backing_bytes, frame_bytes, present, before, after
    );
}

// ---- kernel records ----------------------------------------------------------

/// A ring-3 process with fs:write (and the confirmation bypass, so DeleteFile
/// does not wait for a prompt) writes the account table and the audit log
/// and deletes the directory above the audit log; a write elsewhere is the
/// control.
fn kernel_records() {
    let _ = crate::fs::create_dir("/disk");
    let _ = crate::fs::create_dir("/disk/heliox");
    let _ = crate::fs::create_dir("/tmp");
    let held = ["cap:fs:read", "cap:fs:write", "cap:confirmation:bypass"];
    let write = |path: &[u8]| syscall_with_text(16, &SECOND_BUFFER_IS_TEXT, path);
    let accounts = run_program("k6-rec-acct", &write(b"/disk/accounts.txt"), &held, 3000);
    let accounts_slashes = run_program("k6-rec-acct2", &write(b"//disk//accounts.txt"), &held, 3000);
    let audit = run_program("k6-rec-audit", &write(b"/disk/heliox/audit.log"), &held, 3000);
    let delete_dir = run_program("k6-rec-rmdir", &syscall_with_text(22, &[], b"/disk/heliox"), &held, 3000);
    let control = run_program("k6-rec-ctl", &write(b"/tmp/k6-record-control"), &held, 3000);
    let heliox_dir_exists = crate::fs::stat("/disk/heliox").is_ok();
    println!(
        "selftest kernel-records: write_accounts={} write_accounts_slashes={} write_audit_log={} delete_audit_dir={} heliox_dir_exists={} control_write={}",
        accounts, accounts_slashes, audit, delete_dir, heliox_dir_exists, control
    );
    // A control image may have written them; leave no stray record behind.
    let _ = crate::fs::remove("/disk/accounts.txt");
    let _ = crate::fs::remove("/tmp/k6-record-control");
}

// ---- audit log ---------------------------------------------------------------

/// A denied write whose path carries a line break, and AuditWrite text with
/// one: the entry in the ring must be one line.
fn audit_escape() {
    let path: &[u8] = b"/k6\n[1] SecurityViolation: forged-path";
    let denied = run_program("k6-audit-path", &syscall_with_text(16, &SECOND_BUFFER_IS_TEXT, path), &[], 3000);
    let text: &[u8] = b"k6\n[2] SecurityViolation: forged-write";
    let written = run_program("k6-audit-write", &syscall_with_text(6, &[], text), &["cap:audit:write"], 3000);
    let entries = crate::logging::audit::recent_entries(crate::logging::audit::MAX_ENTRIES);
    let find = |marker: &str| entries.iter().rev().find(|e| e.message.contains(marker)).map(|e| e.message.clone());
    let path_entry = find("forged-path");
    let write_entry = find("forged-write");
    let has_break = |m: &Option<String>| m.as_ref().is_some_and(|m| m.contains('\n') || m.contains('\r'));
    println!(
        "selftest audit-escape: write_status={} path_entry_found={} path_entry_has_line_break={} auditwrite_status={} auditwrite_entry_found={} auditwrite_entry_has_line_break={} path_entry={}",
        denied,
        path_entry.is_some(),
        has_break(&path_entry),
        written,
        write_entry.is_some(),
        has_break(&write_entry),
        crate::syscall::escape_printable(path_entry.as_deref().unwrap_or("none"))
    );
}

/// Flushes the log to an ext2 image (1 KiB blocks: the driver writes files
/// of at most 12 KiB) until the file passes that size, then logs a marker
/// and flushes once more. The marker must reach the file.
fn audit_flush() {
    use crate::fs::ext2::Ext2Fs;
    use crate::logging::audit;
    let fs = match Ext2Fs::mount(RamDisk { bytes: spin::Mutex::new(ext2_base()) }) {
        Ok(fs) => fs,
        Err(e) => {
            println!("selftest audit-flush: mount_error={}", e.replace(' ', "_"));
            return;
        }
    };
    if let Err(e) = crate::fs::vfs::mount("/k6audit", alloc::sync::Arc::new(fs), "k6-ramdisk") {
        println!("selftest audit-flush: vfs_mount_error={}", e.replace(' ', "_"));
        return;
    }
    *audit::FLUSH_PATH_OVERRIDE.lock() = Some(String::from("/k6audit/audit.log"));
    let trimmed_before = audit::FLUSH_TRIMMED.load(core::sync::atomic::Ordering::SeqCst);
    let filler = "a".repeat(200);
    let mut largest = 0usize;
    for i in 0..80 {
        audit::log_event_from(0, audit::AuditEvent::UserAudit, &alloc::format!("k6-flush entry {} {}", i, filler));
        let _ = audit::flush_to_disk();
        if let Ok(stat) = crate::fs::stat("/k6audit/audit.log") {
            largest = largest.max(stat.size as usize);
        }
    }
    audit::log_event_from(0, audit::AuditEvent::UserAudit, "k6-flush-last");
    let last_flush = match audit::flush_to_disk() {
        Ok(()) => String::from("ok"),
        Err(e) => e.replace(' ', "_"),
    };
    let content = crate::fs::read_file("/k6audit/audit.log").unwrap_or_default();
    *audit::FLUSH_PATH_OVERRIDE.lock() = None;
    let _ = crate::fs::vfs::umount("/k6audit");
    println!(
        "selftest audit-flush: largest_file_bytes={} final_file_bytes={} last_flush={} marker_on_disk={} trimmed_flushes={}",
        largest,
        content.len(),
        last_flush,
        content.contains("k6-flush-last"),
        audit::FLUSH_TRIMMED.load(core::sync::atomic::Ordering::SeqCst) - trimmed_before
    );
}

/// Trims a log made of two-byte characters at a byte offset inside one.
fn audit_trim_utf8() {
    let mut content = String::from("a");
    for _ in 0..65536 {
        content.push('\u{e9}');
    }
    content.push('b');
    let total = content.len();
    println!("selftest audit-trim-utf8: starting total_bytes={} cut_at=2", total);
    let kept = crate::logging::audit::trim_log(content, 128 * 1024);
    println!(
        "selftest audit-trim-utf8: survived=true kept_bytes={} ends_with_b={}",
        kept.len(),
        kept.ends_with('b')
    );
}

// ---- packages ----------------------------------------------------------------

/// A process holding pkg:request asks to install a package with
/// args[2] = 1 ("the operator confirmed"). With `claim` false it passes 0
/// (control: nothing to confirm).
fn pkg_confirm(claim: bool) {
    let extra: &[u8] = if claim { &[0xBA, 0x01, 0x00, 0x00, 0x00] } else { &[0x31, 0xD2] };
    let start = crate::scheduler::total_ticks();
    let status = run_program("k6-pkg", &syscall_with_text(48, extra, b"k6-none"), &["cap:pkg:request"], 9000);
    let ms = (crate::scheduler::total_ticks() - start) * crate::interrupts::PIT_TICK_MS;
    println!(
        "selftest {}: claimed_confirmation={} status={} ms={}",
        if claim { "pkg-confirm" } else { "pkg-confirm-unclaimed" },
        claim,
        status,
        ms
    );
}

/// Registers a package entry under a compiled-in program's name.
fn pkg_name() {
    let before = crate::userspace::capabilities_for_program("calculator");
    let accepted = crate::userspace::register_dynamic_program(
        "calculator",
        "k6 package",
        &crate::pkg::bin_path("calculator"),
        vec![String::from("cap:fs:write")],
    );
    let after = crate::userspace::capabilities_for_program("calculator");
    let unchanged = after == before;
    if !unchanged {
        // Control image: put the compiled-in set back.
        crate::userspace::register_dynamic_program("calculator", "", &crate::pkg::bin_path("calculator"), before.clone());
    }
    println!(
        "selftest pkg-name: register_accepted={} capabilities_unchanged={} capabilities_after={} name_taken={} free_name_taken={}",
        accepted,
        unchanged,
        after.join(","),
        crate::pkg::name_taken_by_program("calculator"),
        crate::pkg::name_taken_by_program("k6-free-name")
    );
}

// ---- serial log --------------------------------------------------------------

/// A notification whose title carries a line break and a forged kernel line.
fn serial_titles() {
    let title: &[u8] = b"k6\n[SECURITY] forged-title line";
    let status = run_program(
        "k6-notify",
        &syscall_with_text(55, &SECOND_BUFFER_IS_TEXT, title),
        &["cap:notification:post"],
        3000,
    );
    let _ = crate::notification::dismiss(0);
    println!("selftest serial-titles: post_status={}", status);
}

// ---- HDA codec response --------------------------------------------------------

fn hda_subnodes() {
    println!("selftest hda-subnodes: starting response=0x00f00020");
    let range = crate::devices::hda::subnode_range(0x00F0_0020);
    println!(
        "selftest hda-subnodes: survived=true start={} end={} nodes={}",
        range.start,
        range.end,
        range.len()
    );
}

// ---- SystemQuery process list ------------------------------------------------

/// A task whose name closes the JSON string and adds a forged entry; the
/// list is read with name escaping off (the old behaviour) and on.
fn query_names() {
    use core::sync::atomic::Ordering;
    let name = "k6\",\"state\":\"Ready\"},{\"pid\":4242,\"name\":\"init";
    let pid = match start_ring3(name, &[0xEB, 0xFE], &[]) {
        Ok(pid) => pid,
        Err(e) => {
            println!("selftest query-names: start_error={}", e.replace(' ', "_"));
            return;
        }
    };
    let forged = |json: &str| json.contains("{\"pid\":4242,");
    crate::syscall::query::ESCAPE_TASK_NAMES.store(false, Ordering::SeqCst);
    let off = forged(&crate::syscall::query::query_process_list_for_test());
    crate::syscall::query::ESCAPE_TASK_NAMES.store(true, Ordering::SeqCst);
    let on = forged(&crate::syscall::query::query_process_list_for_test());
    crate::scheduler::kill(pid);
    crate::process::reap_dead();
    println!("selftest query-names: forged_entry_escaping_off={} forged_entry={}", off, on);
}
