// ============================================================================
// FerrumOS - Kernel self-tests, fi1 kernel round 3
// ============================================================================
// `test-syscall <name>` falls through to these after `selftest_k2::run`. Each
// prints `selftest <name>: key=value ...` lines that
// `scripts/verify_kernel_k3.mjs` checks. Every non-destructive test cleans up
// after itself; `kstack-overflow` stops the kernel and must run last.
// ============================================================================

extern crate alloc;

use crate::println;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;
use x86_64::structures::paging::PageTableFlags;

const USER_BASE: u64 = 0x80_0000_0000;

pub fn run(name: &str) -> bool {
    match name {
        "df-entry" => df_entry(),
        "irq-alloc" => irq_alloc(),
        "kbd-lock" => kbd_lock(),
        "kstack-guard" => kstack_guard(),
        "boot-nx" => boot_nx(),
        "user-stack" => user_stack(),
        "user-write-ro" => user_write_ro(),
        "ipc-mailbox" => ipc_mailbox(),
        "ramfs-limits" => ramfs_limits(),
        "ext2-r3" => ext2_r3(),
        "pic-aeoi-on" => pic_aeoi(true),
        "pic-aeoi-off" => pic_aeoi(false),
        "perf-reset" => perf_reset(),
        "kstack-overflow" => kstack_overflow(),
        _ => return false,
    }
    true
}

// ---- helpers ---------------------------------------------------------------

/// ELF64 executable with one PT_LOAD at `base` holding the headers and
/// `code`, entry at the code. `flags` are the segment's p_flags.
fn elf_at(base: u64, code: &[u8], flags: u32) -> Vec<u8> {
    let code_off = 64 + 56;
    let mut elf = vec![0u8; code_off + code.len()];
    elf[0..4].copy_from_slice(b"\x7FELF");
    elf[4] = 2;
    elf[5] = 1;
    elf[6] = 1;
    elf[16..18].copy_from_slice(&2u16.to_le_bytes());
    elf[18..20].copy_from_slice(&62u16.to_le_bytes());
    elf[20..24].copy_from_slice(&1u32.to_le_bytes());
    elf[24..32].copy_from_slice(&(base + code_off as u64).to_le_bytes());
    elf[32..40].copy_from_slice(&64u64.to_le_bytes());
    elf[52..54].copy_from_slice(&64u16.to_le_bytes());
    elf[54..56].copy_from_slice(&56u16.to_le_bytes());
    elf[56..58].copy_from_slice(&1u16.to_le_bytes());
    let ph = 64;
    let size = elf.len() as u64;
    elf[ph..ph + 4].copy_from_slice(&1u32.to_le_bytes());
    elf[ph + 4..ph + 8].copy_from_slice(&flags.to_le_bytes());
    elf[ph + 16..ph + 24].copy_from_slice(&base.to_le_bytes());
    elf[ph + 24..ph + 32].copy_from_slice(&base.to_le_bytes());
    elf[ph + 32..ph + 40].copy_from_slice(&size.to_le_bytes());
    elf[ph + 40..ph + 48].copy_from_slice(&size.to_le_bytes());
    elf[ph + 48..ph + 56].copy_from_slice(&4096u64.to_le_bytes());
    elf[code_off..].copy_from_slice(code);
    elf
}

/// Park the shell at its safepoint for about `ms` so other tasks run.
fn yield_for(ms: u64) {
    let shell = crate::scheduler::list_tasks()
        .into_iter()
        .find(|t| t.name == "shell")
        .map(|t| t.id)
        .unwrap_or(0);
    let end = crate::scheduler::total_ticks() + ms / crate::interrupts::PIT_TICK_MS;
    while crate::scheduler::total_ticks() < end {
        if shell != 0 {
            crate::scheduler::enter_kernel_task_safepoint(shell);
        }
        x86_64::instructions::interrupts::enable_and_hlt();
        crate::scheduler::leave_kernel_task_safepoint();
    }
}

/// Start a ring-3 process running `code` (R+X segment at USER_BASE) with
/// `caps`. Returns its pid.
fn start_ring3(name: &str, code: &[u8], caps: &[String]) -> Result<u64, String> {
    let mut process = crate::process::create(name).map_err(String::from)?;
    let entry = process.load_elf(&elf_at(USER_BASE, code, 5)).map_err(String::from)?;
    let pid = process.pid();
    let kernel_rsp = process.kernel_stack_top();
    let user_rsp = process.user_stack_top().as_u64() - 8;
    let cr3 = process
        .address_space()
        .map(|s| s.l4_frame().start_address().as_u64())
        .unwrap_or(0);
    crate::process::register(process);
    crate::scheduler::register_user(pid, name, crate::scheduler::Priority::Normal, kernel_rsp, cr3, caps);
    crate::scheduler::write_context(pid, crate::scheduler::TaskContext::ring3(entry, user_rsp));
    Ok(pid)
}

/// Let `pid` run for up to `ms`; kill it if it is still alive. Returns
/// (ended by itself or by the kernel, exit code).
fn run_until_dead(pid: u64, ms: u64) -> (bool, Option<u32>) {
    let start = crate::scheduler::total_ticks();
    let mut dead = false;
    while crate::scheduler::total_ticks() < start + ms / crate::interrupts::PIT_TICK_MS {
        yield_for(50);
        if crate::scheduler::task_state(pid).map_or(true, |s| s == crate::scheduler::TaskState::Dead) {
            dead = true;
            break;
        }
    }
    let exit = crate::scheduler::exit_status(pid);
    if !dead {
        crate::scheduler::kill(pid);
    }
    crate::process::reap_dead();
    (dead, exit)
}

fn code_with_imm64(prefix: &[u8], imm: u64, suffix: &[u8]) -> Vec<u8> {
    let mut code = Vec::from(prefix);
    code.extend_from_slice(&imm.to_le_bytes());
    code.extend_from_slice(suffix);
    code
}

// ---- interrupt and syscall entry -------------------------------------------

/// A ring-3 process sets DF (`std`) and then makes syscalls in a loop; the
/// timer interrupts it too. The kernel's Rust code must never see DF set.
fn df_entry() {
    use crate::interrupts::{
        DF_COPY_PROBE_ARMED, DF_COPY_PROBE_BAD, DF_COPY_PROBE_RUNS, DF_SET_AT_SYSCALL_ENTRY,
        DF_SET_AT_TIMER_ENTRY,
    };
    DF_SET_AT_SYSCALL_ENTRY.store(0, Ordering::SeqCst);
    DF_SET_AT_TIMER_ENTRY.store(0, Ordering::SeqCst);
    DF_COPY_PROBE_RUNS.store(0, Ordering::SeqCst);
    DF_COPY_PROBE_BAD.store(0, Ordering::SeqCst);
    // std; L: mov eax, 31 (GetPid); int 0x80; jmp L
    let code = [0xFD, 0xB8, 0x1F, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xF7];
    let pid = match start_ring3("selftest-df", &code, &[]) {
        Ok(pid) => pid,
        Err(e) => {
            println!("selftest df-entry: start_error={}", e.replace(' ', "_"));
            return;
        }
    };
    DF_COPY_PROBE_ARMED.store(true, Ordering::SeqCst);
    let (dead, _) = run_until_dead(pid, 600);
    DF_COPY_PROBE_ARMED.store(false, Ordering::SeqCst);
    println!(
        "selftest df-entry: syscall_entries_with_df={} timer_entries_with_df={} copy_probes={} bad_copies={} process_ended_early={}",
        DF_SET_AT_SYSCALL_ENTRY.load(Ordering::SeqCst),
        DF_SET_AT_TIMER_ENTRY.load(Ordering::SeqCst),
        DF_COPY_PROBE_RUNS.load(Ordering::SeqCst),
        DF_COPY_PROBE_BAD.load(Ordering::SeqCst),
        dead
    );
}

/// Kernel code allocating with interrupts enabled while the timer wakes a
/// sleeper on every tick. With the old heap lock the tick's allocation spun
/// on a lock the interrupted loop held: the kernel hung.
fn irq_alloc() {
    let sleeper = crate::scheduler::spawn(String::from("selftest-sleeper"), crate::scheduler::Priority::Idle);
    let start = crate::scheduler::total_ticks();
    let end = start + 2000 / crate::interrupts::PIT_TICK_MS;
    let mut allocations = 0u64;
    let mut wakes = 0u64;
    let mut last_tick = 0;
    crate::scheduler::selftest_park(sleeper, start + 1);
    let mut i = 0usize;
    while crate::scheduler::total_ticks() < end {
        let n = core::hint::black_box(16 + i % 300);
        let mut v: Vec<u8> = Vec::with_capacity(n);
        v.push(i as u8);
        core::hint::black_box(&v);
        drop(v);
        allocations += 1;
        i += 1;
        let now = crate::scheduler::total_ticks();
        if now != last_tick {
            last_tick = now;
            if crate::scheduler::selftest_park(sleeper, now + 1) {
                wakes += 1;
            }
        }
    }
    crate::scheduler::kill(sleeper);
    crate::scheduler::cleanup_dead_tasks();
    println!("selftest irq-alloc: survived=true allocations={} sleeper_wakes={}", allocations, wakes);
}

/// The shell's keyboard queue and the input event queue polled in a tight
/// loop with interrupts enabled while the harness types: the keyboard
/// interrupt takes the same locks.
fn kbd_lock() {
    let start = crate::scheduler::total_ticks();
    let end = start + 6000 / crate::interrupts::PIT_TICK_MS;
    let (mut keys, mut polls) = (0u64, 0u64);
    println!("selftest kbd-lock: polling for 6 s, type now");
    while crate::scheduler::total_ticks() < end {
        if crate::interrupts::read_keyboard().is_some() {
            keys += 1;
        }
        core::hint::black_box(crate::input::pending_count());
        polls += 1;
    }
    println!("selftest kbd-lock: survived=true keys={} polls={}", keys, polls);
}

// ---- stacks ----------------------------------------------------------------

fn kstack_guard() {
    use crate::memory::kstack;
    let live_before = kstack::LIVE.load(Ordering::SeqCst);
    let (top, mapped_top, guard, nx) = match crate::process::create("selftest-kstack") {
        Ok(process) => {
            let top = process.kernel_stack_top().as_u64();
            let size = crate::process::KERNEL_STACK_SIZE as u64;
            let top_page = kstack::leaf_flags(top - 8);
            let guard = kstack::leaf_flags(top - size - 8);
            let nx = top_page.map(|f| f.contains(PageTableFlags::NO_EXECUTE));
            drop(process);
            (top, top_page.is_some(), guard.is_some(), nx)
        }
        Err(e) => {
            println!("selftest kstack-guard: create_error={}", e.replace(' ', "_"));
            return;
        }
    };
    let live_after = kstack::LIVE.load(Ordering::SeqCst);
    let freed_unmapped = kstack::leaf_flags(top - 8).is_none();
    println!(
        "selftest kstack-guard: stack_top={:#x} top_mapped={} below_stack_mapped={} stack_nx={} freed_unmapped={} live_before={} live_after={}",
        top,
        mapped_top,
        guard,
        nx.map(|b| if b { "true" } else { "false" }).unwrap_or("unmapped"),
        freed_unmapped,
        live_before,
        live_after
    );
}

fn boot_nx() {
    let check = |index: usize| -> String {
        if index == usize::MAX {
            return String::from("not_marked");
        }
        let flags = crate::memory::kernel_p4_flags(index);
        alloc::format!("{}", flags.contains(PageTableFlags::NO_EXECUTE))
    };
    let rsp: u64;
    unsafe { core::arch::asm!("mov {}, rsp", out(reg) rsp) };
    println!(
        "selftest boot-nx: boot_stack_index={} boot_stack_nx={} boot_info_index={} boot_info_nx={} kernel_code_p4_nx={} shell_rsp_p4={}",
        crate::memory::BOOT_STACK_NX_INDEX.load(Ordering::SeqCst) as i64,
        check(crate::memory::BOOT_STACK_NX_INDEX.load(Ordering::SeqCst)),
        crate::memory::BOOT_INFO_NX_INDEX.load(Ordering::SeqCst) as i64,
        check(crate::memory::BOOT_INFO_NX_INDEX.load(Ordering::SeqCst)),
        crate::memory::kernel_p4_flags(0).contains(PageTableFlags::NO_EXECUTE),
        (rsp >> 39) & 0x1FF
    );
}

/// The gap below the user stack: no mmap region or ELF segment may end at
/// the stack, and an overflow ends the process (139) while the kernel runs on.
fn user_stack() {
    use crate::process::{USER_STACK_BASE, USER_STACK_GUARD};
    // Largest mmap the window can take: does it reach the stack?
    let mmap_end = match crate::process::create("selftest-ustack") {
        Ok(process) => {
            let len = USER_STACK_BASE - 0x80_4000_0000;
            let found = process
                .address_space()
                .and_then(|space| space.find_free_vaddr(len))
                .map(|base| base.as_u64() + len);
            drop(process);
            found
        }
        Err(_) => None,
    };
    let mmap_touches_stack = mmap_end.is_some_and(|end| end > USER_STACK_BASE - USER_STACK_GUARD);
    // An ELF segment ending exactly at the stack.
    let seg_base = USER_STACK_BASE - 0x1000;
    let segment_accepted = match crate::process::create("selftest-ustack") {
        Ok(mut process) => {
            let ok = process.load_elf(&elf_at(seg_base, &[0xEB, 0xFE], 6)).is_ok();
            drop(process);
            ok
        }
        Err(_) => false,
    };
    // mov rsp, USER_STACK_BASE; push rax  (the push writes below the stack)
    let code = code_with_imm64(&[0x48, 0xBC], USER_STACK_BASE, &[0x50, 0xEB, 0xFE]);
    let (ended, exit) = match start_ring3("selftest-overflow", &code, &[]) {
        Ok(pid) => run_until_dead(pid, 3000),
        Err(_) => (false, None),
    };
    println!(
        "selftest user-stack: mmap_reaches_stack={} segment_below_stack_accepted={} overflow_ended={} overflow_exit={}",
        mmap_touches_stack,
        segment_accepted,
        ended,
        exit.map(|c| alloc::format!("{}", c)).unwrap_or_else(|| String::from("none"))
    );
}

/// GetRandom into the caller's own read-only text: the kernel's write used
/// to be a ring-0 protection fault, which stops the kernel.
fn user_write_ro() {
    // mov eax, 42; mov rdi, USER_BASE; mov esi, 64; int 0x80;
    // mov rdi, rax; mov eax, 30; int 0x80; jmp $
    let code = code_with_imm64(
        &[0xB8, 0x2A, 0x00, 0x00, 0x00, 0x48, 0xBF],
        USER_BASE,
        &[
            0xBE, 0x40, 0x00, 0x00, 0x00, 0xCD, 0x80, 0x48, 0x89, 0xC7, 0xB8, 0x1E, 0x00, 0x00, 0x00,
            0xCD, 0x80, 0xEB, 0xFE,
        ],
    );
    println!("selftest user-write-ro: starting");
    let (ended, exit) = match start_ring3("selftest-rowrite", &code, &[String::from("cap:crypto:rng")]) {
        Ok(pid) => run_until_dead(pid, 3000),
        Err(e) => {
            println!("selftest user-write-ro: start_error={}", e.replace(' ', "_"));
            return;
        }
    };
    let invalid = crate::syscall::SyscallStatus::InvalidArgument as i64 as u64 as u32;
    println!(
        "selftest user-write-ro: ended={} exit={} refused={}",
        ended,
        exit.map(|c| alloc::format!("{}", c)).unwrap_or_else(|| String::from("none")),
        exit == Some(invalid)
    );
}

// ---- IPC -------------------------------------------------------------------

fn ipc_mailbox() {
    use crate::ipc::{Endpoint, Message, MessageKind, SENDER_KERNEL_SHELL};
    const SVC: &str = "selftest-mbx";
    let held = [String::from("cap:system:all")];
    let msg = |flags: u64| {
        Message::new(0, Endpoint::new(SVC, "default"), MessageKind::Request, "cap:system:all", b"x")
            .map(|m| m.with_sender_flags(flags))
    };
    let new_proc = || crate::process::create(SVC).map(crate::process::register);
    let Ok(a) = new_proc() else {
        println!("selftest ipc-mailbox: create_error");
        return;
    };
    let owner_first = crate::ipc::service_owner_pid(SVC);
    let Ok(b) = new_proc() else {
        crate::process::drop_by_pid(a);
        println!("selftest ipc-mailbox: create_error");
        return;
    };
    let owner_with_two = crate::ipc::service_owner_pid(SVC);
    let queued_for_a = msg(0).map(|m| crate::ipc::send(m, &held).is_ok()).unwrap_or(false);
    crate::process::drop_by_pid(a);
    let owner_after_first_died = crate::ipc::service_owner_pid(SVC);
    let second_got_firsts_message = crate::ipc::receive_for_owner(SVC, b).is_ok();
    crate::process::drop_by_pid(b);

    // Quota: a fresh owner, unflagged senders fill the mailbox, then the
    // operator's message.
    let Ok(c) = new_proc() else {
        println!("selftest ipc-mailbox: create_error");
        return;
    };
    let owner_new = crate::ipc::service_owner_pid(SVC);
    let mut unflagged = 0;
    for _ in 0..16 {
        if msg(0).map(|m| crate::ipc::send(m, &held).is_ok()).unwrap_or(false) {
            unflagged += 1;
        }
    }
    let operator_accepted = msg(SENDER_KERNEL_SHELL)
        .map(|m| crate::ipc::send(m, &held).is_ok())
        .unwrap_or(false);
    let mut delivered = 0;
    while crate::ipc::receive_for_owner(SVC, c).is_ok() {
        delivered += 1;
    }
    crate::process::drop_by_pid(c);
    let show = |o: Option<u64>| match o {
        None => String::from("none"),
        Some(p) if p == a => String::from("first"),
        Some(p) if p == b => String::from("second"),
        Some(p) if p == c => String::from("third"),
        Some(p) => alloc::format!("pid{}", p),
    };
    println!(
        "selftest ipc-mailbox: owner_first={} owner_with_two={} queued_for_first={} owner_after_first_died={} second_got_firsts_message={} owner_new={}",
        show(owner_first),
        show(owner_with_two),
        queued_for_a,
        show(owner_after_first_died),
        second_got_firsts_message,
        show(owner_new)
    );
    println!(
        "selftest ipc-mailbox: unflagged_accepted={} operator_accepted_when_full={} delivered={}",
        unflagged, operator_accepted, delivered
    );
}

// ---- filesystems -----------------------------------------------------------

fn ramfs_limits() {
    let (heap_used_before, _) = crate::memory::heap::heap_stats();
    let chunk = match crate::fs::try_zeroed_vec(1024 * 1024) {
        Some(v) => v,
        None => {
            println!("selftest ramfs-limits: no_heap_for_test");
            return;
        }
    };
    let mut written = 0;
    let mut refused_at = None;
    for i in 0..6 {
        let path = alloc::format!("/tmp/k3big{}", i);
        if crate::fs::create_file_bytes(&path, &chunk).is_ok() {
            written += 1;
        } else {
            refused_at = Some(i);
            break;
        }
    }
    drop(chunk);
    for i in 0..6 {
        let _ = crate::fs::remove(&alloc::format!("/tmp/k3big{}", i));
    }
    // Depth.
    let mut path = String::from("/tmp/k3d");
    let mut depth_ok = 0;
    let mut created = Vec::new();
    for _ in 0..40 {
        if crate::fs::create_dir(&path).is_err() {
            break;
        }
        created.push(path.clone());
        depth_ok = path.split('/').filter(|p| !p.is_empty()).count();
        path.push_str("/d");
    }
    let removed_tree = crate::fs::remove("/tmp/k3d").is_ok();
    let newline_name = crate::fs::create_file_bytes("/tmp/k3\nforged", b"x").is_ok();
    let _ = crate::fs::remove("/tmp/k3\nforged");
    let (heap_used_after, _) = crate::memory::heap::heap_stats();
    println!(
        "selftest ramfs-limits: files_1mib_written={} refused_at={} deepest_dir={} tree_removed={} newline_name_created={} heap_used_delta_kib={}",
        written,
        refused_at.map(|i| alloc::format!("{}", i)).unwrap_or_else(|| String::from("none")),
        depth_ok,
        removed_tree,
        newline_name,
        (heap_used_after as i64 - heap_used_before as i64) / 1024
    );
}

struct RamDisk {
    bytes: spin::Mutex<Vec<u8>>,
}

impl crate::fs::block::BlockDevice for RamDisk {
    fn read_sector(&self, lba: u64, buf: &mut [u8]) -> Result<(), String> {
        let bytes = self.bytes.lock();
        let start = (lba as usize).checked_mul(512).ok_or_else(|| String::from("lba"))?;
        if start + 512 > bytes.len() || buf.len() < 512 {
            return Err(String::from("ramdisk: sector out of range"));
        }
        buf[..512].copy_from_slice(&bytes[start..start + 512]);
        Ok(())
    }
    fn write_sector(&self, lba: u64, buf: &[u8]) -> Result<(), String> {
        let mut bytes = self.bytes.lock();
        let start = (lba as usize).checked_mul(512).ok_or_else(|| String::from("lba"))?;
        if start + 512 > bytes.len() || buf.len() < 512 {
            return Err(String::from("ramdisk: sector out of range"));
        }
        bytes[start..start + 512].copy_from_slice(&buf[..512]);
        Ok(())
    }
    fn sector_size(&self) -> usize {
        512
    }
    fn sector_count(&self) -> u64 {
        (self.bytes.lock().len() / 512) as u64
    }
    fn flush(&self) -> Result<(), String> {
        Ok(())
    }
}

fn put16(b: &mut [u8], off: usize, v: u16) {
    b[off..off + 2].copy_from_slice(&v.to_le_bytes());
}
fn put32(b: &mut [u8], off: usize, v: u32) {
    b[off..off + 4].copy_from_slice(&v.to_le_bytes());
}

const BS: usize = 1024;
const ITABLE: usize = 5 * BS;
const ROOT_BLOCK: u32 = 7;

/// Write inode `n` (128-byte inodes, table at block 5).
fn put_inode(img: &mut [u8], n: u32, mode: u16, size: u32, blocks: &[u32]) {
    let at = ITABLE + (n as usize - 1) * 128;
    put16(img, at, mode);
    put32(img, at + 4, size);
    put16(img, at + 26, if mode & 0xF000 == 0x4000 { 2 } else { 1 });
    put32(img, at + 28, (blocks.len() * BS / 512) as u32);
    for (i, b) in blocks.iter().enumerate() {
        put32(img, at + 40 + i * 4, *b);
    }
}

/// Directory entry at byte `at`.
fn put_dirent(img: &mut [u8], at: usize, inode: u32, rec_len: u16, name: &[u8], ftype: u8) {
    put32(img, at, inode);
    put16(img, at + 4, rec_len);
    img[at + 6] = name.len() as u8;
    img[at + 7] = ftype;
    img[at + 8..at + 8 + name.len()].copy_from_slice(name);
}

/// A 64 KiB ext2 image with a working root directory (inode 2, block 7) and
/// bitmaps that match: blocks 1-7 and inodes 1-11 in use, everything past the
/// end marked used. Free: 56 blocks, 5 inodes.
fn ext2_base() -> Vec<u8> {
    let mut img = vec![0u8; 64 * BS];
    let sb = 1024;
    put32(&mut img, sb, 16);
    put32(&mut img, sb + 4, 64);
    put32(&mut img, sb + 12, 56); // free blocks
    put32(&mut img, sb + 16, 5); // free inodes
    put32(&mut img, sb + 20, 1);
    put32(&mut img, sb + 24, 0);
    put32(&mut img, sb + 32, 8192);
    put32(&mut img, sb + 36, 8192);
    put32(&mut img, sb + 40, 16);
    put16(&mut img, sb + 56, 0xEF53);
    put32(&mut img, sb + 76, 1);
    put32(&mut img, sb + 84, 11);
    put16(&mut img, sb + 88, 128);
    let gd = 2 * BS;
    put32(&mut img, gd, 3);
    put32(&mut img, gd + 4, 4);
    put32(&mut img, gd + 8, 5);
    put16(&mut img, gd + 12, 56);
    put16(&mut img, gd + 14, 5);
    put16(&mut img, gd + 16, 1);
    // Block bitmap (block 3): bit i = block i + 1. Blocks 1-7 used, 64.. used.
    let bb = 3 * BS;
    img[bb] = 0x7F;
    img[bb + 7] = 0x80; // bit 63 = block 64 (past the end)
    for byte in &mut img[bb + 8..bb + BS] {
        *byte = 0xFF;
    }
    // Inode bitmap (block 4): inodes 1-11 used, 17.. used.
    let ib = 4 * BS;
    img[ib] = 0xFF;
    img[ib + 1] = 0x07;
    for byte in &mut img[ib + 2..ib + BS] {
        *byte = 0xFF;
    }
    put_inode(&mut img, 2, 0x41ED, BS as u32, &[ROOT_BLOCK]);
    let rb = ROOT_BLOCK as usize * BS;
    put_dirent(&mut img, rb, 2, 12, b".", 2);
    put_dirent(&mut img, rb + 12, 2, (BS - 12) as u16, b"..", 2);
    img
}

/// Add a regular file inode 12 named `name` as the second entry after `..`
/// (shrinks `..` to 12 bytes).
fn add_file(img: &mut [u8], name: &[u8], size: u32, blocks: &[u32], rec_len: u16) {
    let rb = ROOT_BLOCK as usize * BS;
    put16(img, rb + 12 + 4, 12);
    put_dirent(img, rb + 24, 12, rec_len, name, 1);
    put_inode(img, 12, 0x81A4, size, blocks);
    img[4 * BS + 1] |= 0x08; // inode 12 used
}

fn ext2_r3() {
    use crate::fs::vfs::Filesystem;
    use crate::fs::ext2::Ext2Fs;
    let mount = |img: Vec<u8>| Ext2Fs::mount(RamDisk { bytes: spin::Mutex::new(img) });
    let show = |r: Result<(), String>| match r {
        Ok(()) => String::from("ok"),
        Err(e) => alloc::format!("err:{}", e.replace(' ', "_")),
    };

    // Positive control: create, read back, remove.
    let control = match mount(ext2_base()) {
        Ok(fs) => {
            let wrote = fs.create_file_bytes("/hello", b"hi").is_ok();
            let read = fs.read_file("/hello").map(|s| s == "hi").unwrap_or(false);
            let removed = fs.remove("/hello").is_ok();
            let gone = fs.stat("/hello").is_err();
            alloc::format!("{}", wrote && read && removed && gone)
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r3: control_create_read_remove={}", control);

    // A regular file whose 64-bit size (dir_acl = high half) is 2^64 - 1.
    let mut img = ext2_base();
    add_file(&mut img, b"big", 100, &[], (BS - 24) as u16);
    put32(&mut img, ITABLE + 11 * 128 + 4, u32::MAX);
    put32(&mut img, ITABLE + 11 * 128 + 108, u32::MAX);
    println!("selftest ext2-r3: huge_file_read=starting");
    let huge_file = mount(img).map(|fs| show(fs.read_file("/big").map(|_| ()))).unwrap_or_else(|e| e);
    println!("selftest ext2-r3: huge_file_read={}", huge_file);

    // The root directory claiming 4 GiB.
    let mut img = ext2_base();
    put32(&mut img, ITABLE + 128 + 4, 0xFFFF_F000);
    println!("selftest ext2-r3: huge_dir_list=starting");
    let huge_dir = mount(img).map(|fs| show(fs.list_dir("/").map(|_| ()))).unwrap_or_else(|e| e);
    println!("selftest ext2-r3: huge_dir_list={}", huge_dir);

    // Last entry at 1016 with name_len 255 and rec_len 0xFFFF; then a create.
    let mut img = ext2_base();
    let rb = ROOT_BLOCK as usize * BS;
    put16(&mut img, rb + 12 + 4, (1016 - 12) as u16);
    put32(&mut img, rb + 1016, 2);
    put16(&mut img, rb + 1016 + 4, 0xFFFF);
    img[rb + 1016 + 6] = 255;
    println!("selftest ext2-r3: bad_reclen_create=starting");
    let bad_reclen = mount(img).map(|fs| show(fs.create_file_bytes("/x", b"y"))).unwrap_or_else(|e| e);
    println!("selftest ext2-r3: bad_reclen_create={}", bad_reclen);

    // Remove of an entry whose rec_len is 0xFFFF (merge into the previous).
    let mut img = ext2_base();
    let rb = ROOT_BLOCK as usize * BS;
    put16(&mut img, rb + 4, 12);
    put_dirent(&mut img, rb + 12, 12, 0xFFFF, b"victim", 1);
    put_inode(&mut img, 12, 0x81A4, 0, &[]);
    img[4 * BS + 1] |= 0x08;
    println!("selftest ext2-r3: bad_reclen_remove=starting");
    let bad_merge = mount(img).map(|fs| show(fs.remove("/victim"))).unwrap_or_else(|e| e);
    println!("selftest ext2-r3: bad_reclen_remove={}", bad_merge);

    // Root's indirect blocks point at themselves (block 8 full of 8s); root
    // size is one block. A create walks the directory's blocks.
    let mut img = ext2_base();
    put32(&mut img, ITABLE + 128 + 40 + 12 * 4, 8);
    put32(&mut img, ITABLE + 128 + 40 + 13 * 4, 8);
    put32(&mut img, ITABLE + 128 + 40 + 14 * 4, 8);
    for i in 0..BS / 4 {
        put32(&mut img, 8 * BS + i * 4, 8);
    }
    img[3 * BS] |= 0x80; // block 8 used
    println!("selftest ext2-r3: looped_dir_create=starting");
    let start = crate::scheduler::total_ticks();
    let looped = mount(img).map(|fs| show(fs.create_file_bytes("/y", b"z"))).unwrap_or_else(|e| e);
    println!(
        "selftest ext2-r3: looped_dir_create={} looped_dir_ms={}",
        looped,
        (crate::scheduler::total_ticks() - start) * crate::interrupts::PIT_TICK_MS
    );

    // `/f/`: an empty last component under the regular file f, whose data
    // holds one entry {inode 1, name_len 0}.
    let mut img = ext2_base();
    add_file(&mut img, b"f", BS as u32, &[9], (BS - 24) as u16);
    put_dirent(&mut img, 9 * BS, 1, BS as u16, b"", 0);
    img[3 * BS + 1] |= 0x01; // block 9 used
    println!("selftest ext2-r3: empty_name_remove=starting");
    let (empty_remove, dangling) = match mount(img) {
        Ok(fs) => {
            let r = show(fs.remove("/f/"));
            let listed = fs
                .list_dir("/")
                .map(|entries| entries.iter().any(|e| e.name == "f"))
                .unwrap_or(false);
            let inode_free_on_disk = fs.read_inode(12).is_ok() && {
                // Re-read the inode bitmap through a fresh allocation: if
                // inode 12 was freed, the next file created takes it.
                fs.create_file_bytes("/new", b"n").is_ok()
                    && fs.read_file("/f").map(|s| s == "n").unwrap_or(false)
            };
            (r, listed && inode_free_on_disk)
        }
        Err(e) => (e, false),
    };
    println!(
        "selftest ext2-r3: empty_name_remove={} f_now_aliases_new_file={}",
        empty_remove, dangling
    );

    // A free inode count above the total.
    let mut img = ext2_base();
    put32(&mut img, 1024 + 16, 100);
    println!("selftest ext2-r3: free_count_mount=starting");
    let free_counts = match mount(img) {
        Ok(fs) => alloc::format!("mounted_usage_{}", show(fs.usage().map(|_| ()))),
        Err(e) => alloc::format!("rejected:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r3: free_count_mount={}", free_counts);

    // Superblock free blocks 0, group free blocks 56: an allocation.
    let mut img = ext2_base();
    put32(&mut img, 1024 + 12, 0);
    println!("selftest ext2-r3: zero_sb_free_create=starting");
    let zero_free = mount(img).map(|fs| show(fs.create_file_bytes("/z", b"1"))).unwrap_or_else(|e| e);
    println!("selftest ext2-r3: zero_sb_free_create={}", zero_free);

    // Remove of a file whose block lies outside every group: the free fails
    // after the entry is gone. The parent's version must move anyway.
    let mut img = ext2_base();
    add_file(&mut img, b"bad", 10, &[70_000], (BS - 24) as u16);
    println!("selftest ext2-r3: remove_error_version=starting");
    let (removed, gone, version_moved) = match mount(img) {
        Ok(fs) => {
            let before = fs.stat("/").map(|s| s.version).unwrap_or(0);
            let r = show(fs.remove("/bad"));
            let gone = fs.stat("/bad").is_err();
            let after = fs.stat("/").map(|s| s.version).unwrap_or(0);
            (r, gone, before != after)
        }
        Err(e) => (e, false, false),
    };
    println!(
        "selftest ext2-r3: remove_error={} entry_gone={} parent_version_changed={}",
        removed, gone, version_moved
    );
}

// ---- timer cost ------------------------------------------------------------

fn pic_aeoi(on: bool) {
    crate::interrupts::set_pic_auto_eoi(on);
    println!(
        "selftest pic-aeoi-{}: auto_eoi={}",
        if on { "on" } else { "off" },
        crate::interrupts::PIC_AUTO_EOI.load(Ordering::SeqCst)
    );
}

fn perf_reset() {
    use crate::interrupts::{
        SYSCALL_COUNT, SYSCALL_CYCLES, TICK_FN_COUNT, TICK_FN_CYCLES, TIMER_COUNT, TIMER_CYCLES,
        TIMER_EOI_COUNT, TIMER_EOI_CYCLES,
    };
    for counter in [
        &TIMER_CYCLES, &TIMER_COUNT, &TICK_FN_CYCLES, &TICK_FN_COUNT, &TIMER_EOI_CYCLES,
        &TIMER_EOI_COUNT, &SYSCALL_CYCLES, &SYSCALL_COUNT,
    ] {
        counter.store(0, Ordering::SeqCst);
    }
    println!("selftest perf-reset: done");
}

// ---- destructive -----------------------------------------------------------

#[inline(never)]
fn recurse(depth: u64) -> u64 {
    let buf = core::hint::black_box([depth as u8; 512]);
    if depth == 0 {
        buf[0] as u64
    } else {
        recurse(depth - 1).wrapping_add(buf[(depth % 512) as usize] as u64)
    }
}

extern "C" fn overflow_on_stack() {
    let r = recurse(core::hint::black_box(160));
    println!("selftest kstack-overflow: survived=true result={}", r);
}

/// Destructive: recurse about 80 KiB deep on a process's 32 KiB kernel stack.
/// With a guard page the overflow is a double fault that stops the kernel;
/// without one it ran into whatever lay below the stack.
fn kstack_overflow() {
    let process = match crate::process::create("selftest-overflow-k") {
        Ok(p) => p,
        Err(e) => {
            println!("selftest kstack-overflow: create_error={}", e.replace(' ', "_"));
            return;
        }
    };
    let top = process.kernel_stack_top().as_u64();
    println!("selftest kstack-overflow: recursing on the stack below {:#x}", top);
    x86_64::instructions::interrupts::without_interrupts(|| unsafe {
        core::arch::asm!(
            "mov r12, rsp",
            "mov rsp, {top}",
            "call {f}",
            "mov rsp, r12",
            top = in(reg) top,
            f = sym overflow_on_stack,
            out("r12") _,
            clobber_abi("C"),
        );
    });
    drop(process);
    println!("selftest kstack-overflow: returned=true");
}
