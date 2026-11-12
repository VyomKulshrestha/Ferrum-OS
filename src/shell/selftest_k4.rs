// ============================================================================
// FerrumOS - Kernel self-tests, fi1 kernel round 4
// ============================================================================
// `test-syscall <name>` falls through to these after `selftest_k3::run`. Each
// prints `selftest <name>: key=value ...` lines that
// `scripts/verify_kernel_k4.mjs` checks. `static-stack-overflow` stops the
// kernel and must run last.
// ============================================================================

extern crate alloc;

use super::selftest_k3::{
    add_file, ext2_base, put16, put_dirent, put_inode, recurse, run_until_dead, start_ring3,
    yield_for, RamDisk, BS, ITABLE, ROOT_BLOCK,
};
use crate::println;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;

pub fn run(name: &str) -> bool {
    match name {
        "avx-state" => avx_state(),
        "smp-state" => smp_state(),
        "static-stack-guards" => static_stack_guards(),
        "ext2-r4" => ext2_r4(),
        "delete-prompt" => delete_prompt(),
        "exec-embedded-version" => exec_embedded_version(),
        "exit-closes-windows" => exit_closes_windows(),
        "reap-others" => reap_others(),
        "user-x87" => user_x87(),
        "window-budget" => window_budget(),
        "static-stack-overflow" => static_stack_overflow(),
        _ => return false,
    }
    true
}

fn show(r: Result<(), String>) -> String {
    match r {
        Ok(()) => String::from("ok"),
        Err(e) => alloc::format!("err:{}", e.replace(' ', "_")),
    }
}

/// Machine code: exit(edi = ebx); jmp $.
const EXIT_WITH_EBX: [u8; 11] = [0x89, 0xDF, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xFE];

/// Machine code: exit(0).
const EXIT_ZERO: [u8; 13] = [0x31, 0xFF, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xFE, 0x90, 0x90];

// ---- vector state across switches -------------------------------------------

/// VEX.256.F3.0F 6F: vmovdqu ymmN, [rsp]
fn ymm_load_rsp(n: u8) -> [u8; 5] {
    [0xC5, if n < 8 { 0xFE } else { 0x7E }, 0x6F, ((n & 7) << 3) | 0x04, 0x24]
}

/// VEX.256.F3.0F 7F: vmovdqu [rsp - 32], ymmN
fn ymm_store_below_rsp(n: u8) -> [u8; 6] {
    [0xC5, if n < 8 { 0xFE } else { 0x7E }, 0x7F, ((n & 7) << 3) | 0x44, 0x24, 0xE0]
}

/// mov eax, 32 (Sleep); mov edi, ms; int 0x80
fn sleep_ms(code: &mut Vec<u8>, ms: u32) {
    code.extend_from_slice(&[0xB8, 0x20, 0x00, 0x00, 0x00, 0xBF]);
    code.extend_from_slice(&ms.to_le_bytes());
    code.extend_from_slice(&[0xCD, 0x80]);
}

/// A process that fills all sixteen YMM registers with `pattern`, sleeps,
/// spins (so the timer preempts it), sleeps again, then exits with the
/// number of registers whose upper half still holds `pattern`.
fn ymm_writer(pattern: u64, spins: u64) -> Vec<u8> {
    let mut code = Vec::new();
    code.extend_from_slice(&[0x49, 0xB8]); // mov r8, pattern
    code.extend_from_slice(&pattern.to_le_bytes());
    for _ in 0..4 {
        code.extend_from_slice(&[0x41, 0x50]); // push r8
    }
    for n in 0..16 {
        code.extend_from_slice(&ymm_load_rsp(n));
    }
    code.extend_from_slice(&[0x48, 0x83, 0xC4, 0x20]); // add rsp, 32
    sleep_ms(&mut code, 300);
    code.extend_from_slice(&[0x48, 0xB9]); // mov rcx, spins
    code.extend_from_slice(&spins.to_le_bytes());
    code.extend_from_slice(&[0x48, 0xFF, 0xC9, 0x75, 0xFB]); // dec rcx; jnz
    sleep_ms(&mut code, 300);
    code.extend_from_slice(&[0x49, 0xB8]); // mov r8, pattern
    code.extend_from_slice(&pattern.to_le_bytes());
    code.extend_from_slice(&[0x31, 0xDB]); // xor ebx, ebx
    for n in 0..16 {
        code.extend_from_slice(&ymm_store_below_rsp(n));
        code.extend_from_slice(&[
            0x48, 0x8B, 0x44, 0x24, 0xF0, // mov rax, [rsp-16]
            0x48, 0x8B, 0x54, 0x24, 0xF8, // mov rdx, [rsp-8]
            0x4C, 0x39, 0xC0, 0x75, 0x07, // cmp rax, r8; jne +7
            0x4C, 0x39, 0xC2, 0x75, 0x02, // cmp rdx, r8; jne +2
            0xFF, 0xC3, // inc ebx
        ]);
    }
    code.extend_from_slice(&EXIT_WITH_EBX);
    code
}

/// A process that exits with the number of YMM registers whose upper half
/// is not zero, as it finds them at its first instruction.
fn ymm_reader() -> Vec<u8> {
    let mut code = vec![0x31, 0xDB]; // xor ebx, ebx
    for n in 0..16 {
        code.extend_from_slice(&ymm_store_below_rsp(n));
        code.extend_from_slice(&[
            0x48, 0x8B, 0x44, 0x24, 0xF0, // mov rax, [rsp-16]
            0x48, 0x0B, 0x44, 0x24, 0xF8, // or rax, [rsp-8]
            0x74, 0x02, // jz +2
            0xFF, 0xC3, // inc ebx
        ]);
    }
    code.extend_from_slice(&EXIT_WITH_EBX);
    code
}

fn exit_str(exit: Option<u32>) -> String {
    exit.map(|c| alloc::format!("{}", c)).unwrap_or_else(|| String::from("none"))
}

/// Two processes fill the YMM registers with different patterns and check
/// them after being switched out; a third reads the upper halves it finds
/// when it starts. With FXSAVE-only switching the reader saw the writers'
/// upper halves and each writer saw the other's.
fn avx_state() {
    let c1 = core::arch::x86_64::__cpuid(1);
    let cpu_avx = c1.ecx & (1 << 28) != 0;
    let cpu_xsave = c1.ecx & (1 << 26) != 0;
    let osxsave = c1.ecx & (1 << 27) != 0;
    let xcr0 = if osxsave {
        let (lo, hi): (u32, u32);
        unsafe { core::arch::asm!("xgetbv", in("ecx") 0u32, out("eax") lo, out("edx") hi) };
        (hi as u64) << 32 | lo as u64
    } else {
        0
    };
    let leaf_d = if cpu_xsave { core::arch::x86_64::__cpuid_count(0xD, 0).ebx } else { 0 };
    let (area, xsave_switching) = crate::scheduler::simd_area_info();
    let model = core::arch::x86_64::__cpuid(0);
    let vendor: Vec<u8> = [model.ebx, model.edx, model.ecx].iter().flat_map(|r| r.to_le_bytes()).collect();
    println!(
        "selftest avx-state: cpu_vendor={} cpu_avx={} cpu_xsave={} osxsave={} xcr0={:#x} cpuid_d_size={} area_size={} xsave_switching={}",
        core::str::from_utf8(&vendor).unwrap_or("?"),
        cpu_avx,
        cpu_xsave,
        osxsave,
        xcr0,
        leaf_d,
        area,
        xsave_switching
    );
    if !(cpu_avx && osxsave && xcr0 & 0x6 == 0x6) {
        println!("selftest avx-state: skipped=avx_not_enabled");
        return;
    }
    let (pa, pb) = (0xA5A5_0001_A5A5_0001u64, 0x5A5A_0002_5A5A_0002u64);
    let spins = 200_000_000;
    let w1 = start_ring3("selftest-ymm-a", &ymm_writer(pa, spins), &[]);
    yield_for(100);
    let w2 = start_ring3("selftest-ymm-b", &ymm_writer(pb, spins), &[]);
    yield_for(100);
    let r = start_ring3("selftest-ymm-r", &ymm_reader(), &[]);
    let (r_ended, r_exit) = match r {
        Ok(pid) => run_until_dead(pid, 4000),
        Err(_) => (false, None),
    };
    let (a_ended, a_exit) = match w1 {
        Ok(pid) => run_until_dead(pid, 15000),
        Err(_) => (false, None),
    };
    let (b_ended, b_exit) = match w2 {
        Ok(pid) => run_until_dead(pid, 15000),
        Err(_) => (false, None),
    };
    println!(
        "selftest avx-state: reader_ended={} reader_nonzero_upper_halves={} writer_a_ended={} writer_a_intact={} writer_b_ended={} writer_b_intact={}",
        r_ended,
        exit_str(r_exit),
        a_ended,
        exit_str(a_exit),
        b_ended,
        exit_str(b_exit)
    );
}

// ---- single processor -------------------------------------------------------

fn smp_state() {
    use crate::smp::{APS_STARTED, MADT_APPLICATION_PROCESSORS, ONLINE_CPUS, TRAMPOLINE_COPIED};
    let region = crate::memory::boot_region_type(0x8000);
    crate::smp::assert_single_cpu();
    println!(
        "selftest smp-state: online_cpus={} application_processors_started={} madt_application_processors={} trampoline_region={:?} trampoline_copied={}",
        ONLINE_CPUS,
        APS_STARTED.load(Ordering::SeqCst),
        MADT_APPLICATION_PROCESSORS.load(Ordering::SeqCst),
        region,
        TRAMPOLINE_COPIED.load(Ordering::SeqCst) == 1
    );
}

// ---- static stacks ----------------------------------------------------------

fn static_stack_guards() {
    use crate::memory::kstack::{leaf_flags, static_stacks, STATIC_GUARDS};
    let rsp: u64;
    unsafe { core::arch::asm!("mov {}, rsp", out(reg) rsp) };
    let mut line = alloc::format!("guards_unmapped={}", STATIC_GUARDS.load(Ordering::SeqCst));
    for (name, bottom, top) in static_stacks() {
        line.push_str(&alloc::format!(
            " {}_stack_mapped={} {}_guard_mapped={}",
            name,
            leaf_flags(bottom).is_some() && leaf_flags(top - 8).is_some(),
            name,
            leaf_flags(bottom - 1).is_some()
        ));
    }
    let (shell_bottom, shell_top) = crate::shell::static_stack_bounds();
    line.push_str(&alloc::format!(" running_on_shell_stack={}", rsp >= shell_bottom && rsp < shell_top));
    println!("selftest static-stack-guards: {}", line);
}

/// Destructive: recurse past the bottom of the shell's 64 KiB stack (the
/// task that runs this command). With the guard the overflow faults on the
/// guard page and ends in a double fault on the IST stack.
fn static_stack_overflow() {
    let rsp: u64;
    unsafe { core::arch::asm!("mov {}, rsp", out(reg) rsp) };
    let (bottom, top) = crate::shell::static_stack_bounds();
    println!(
        "selftest static-stack-overflow: running_on_shell_stack={} recursing below {:#x}",
        rsp >= bottom && rsp < top,
        bottom
    );
    let r = x86_64::instructions::interrupts::without_interrupts(|| recurse(core::hint::black_box(400)));
    println!("selftest static-stack-overflow: survived=true result={}", r);
}

// ---- ext2 write paths -------------------------------------------------------

fn ext2_r4() {
    use crate::fs::ext2::Ext2Fs;
    use crate::fs::vfs::Filesystem;
    let mount = |img: Vec<u8>| Ext2Fs::mount(RamDisk { bytes: spin::Mutex::new(img) });
    let content = |n: usize, b: u8| -> Vec<u8> { vec![b; n] };
    let read_is = |fs: &Ext2Fs<RamDisk>, path: &str, want: &[u8]| {
        fs.read_file(path).map(|s| s.as_bytes() == want).unwrap_or(false)
    };

    // Control: create, remove, create again (the freed inode is reused).
    let control = match mount(ext2_base()) {
        Ok(fs) => {
            let a = fs.create_file_bytes("/a", b"one").is_ok();
            let first = fs.resolve_path("/a").unwrap_or(0);
            let removed = fs.remove("/a").is_ok();
            let b = fs.create_file_bytes("/b", b"two").is_ok();
            let second = fs.resolve_path("/b").unwrap_or(0);
            alloc::format!("{}_inode_reused={}", a && removed && b && read_is(&fs, "/b", b"two"), first == second)
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: control={}", control);

    // The block bitmap marks the superblock, descriptor table, bitmaps and
    // inode table (blocks 1-6) free. Two 1 KiB files.
    let mut img = ext2_base();
    img[3 * BS] = 0x40; // only block 7 (root) marked used
    let meta = match mount(img) {
        Ok(fs) => {
            let m = fs.create_file_bytes("/m", &content(BS, b'M')).is_ok();
            let n = fs.create_file_bytes("/n", &content(BS, b'N')).is_ok();
            let intact = read_is(&fs, "/m", &content(BS, b'M')) && read_is(&fs, "/n", &content(BS, b'N'));
            let root_ok = fs.list_dir("/").map(|e| e.iter().any(|d| d.name == "n")).unwrap_or(false);
            alloc::format!("created={} files_read_back={} root_listed={}", m && n, intact, root_ok)
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: metadata_marked_free {}", meta);

    // The inode bitmap marks inodes 2-11 (reserved; 2 is the root) free.
    let mut img = ext2_base();
    img[4 * BS] = 0x01;
    img[4 * BS + 1] = 0x00;
    let reserved = match mount(img) {
        Ok(fs) => {
            let r = show(fs.create_file_bytes("/r", b"r"));
            let inode = fs.resolve_path("/r").unwrap_or(0);
            let root_dir = fs.stat("/").map(|s| s.is_dir).unwrap_or(false);
            alloc::format!("create={} new_inode={} root_still_dir={}", r, inode, root_dir)
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: reserved_inodes_marked_free {}", reserved);

    // The inode bitmap marks the live file f (inode 12) free.
    let mut img = ext2_base();
    add_file(&mut img, b"f", 2, &[9], (BS - 24) as u16);
    img[9 * BS..9 * BS + 2].copy_from_slice(b"ff");
    img[3 * BS + 1] |= 0x01; // block 9 used
    img[4 * BS + 1] &= !0x08; // inode 12 marked free
    let live = match mount(img) {
        Ok(fs) => {
            let g = show(fs.create_file_bytes("/g", b"gg"));
            let shared = fs.resolve_path("/g").ok() == fs.resolve_path("/f").ok();
            alloc::format!("create={} g_shares_f_inode={} f_intact={}", g, shared, read_is(&fs, "/f", b"ff"))
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: live_inode_marked_free {}", live);

    // A hard link: h1 and h2 both name inode 12 (links_count 2). Remove h1,
    // then create a file.
    let mut img = ext2_base();
    add_file(&mut img, b"h1", 2, &[9], 12);
    put_dirent(&mut img, ROOT_BLOCK as usize * BS + 36, 12, (BS - 36) as u16, b"h2", 1);
    put16(&mut img, ITABLE + 11 * 128 + 26, 2);
    img[9 * BS..9 * BS + 2].copy_from_slice(b"hh");
    img[3 * BS + 1] |= 0x01;
    let link = match mount(img) {
        Ok(fs) => {
            let removed = show(fs.remove("/h1"));
            let kept = read_is(&fs, "/h2", b"hh");
            let x = show(fs.create_file_bytes("/x", b"xx"));
            let still = read_is(&fs, "/h2", b"hh");
            let links = fs.read_inode(12).map(|i| i.links_count).unwrap_or(0);
            alloc::format!(
                "remove={} h2_intact={} create={} h2_intact_after_create={} links_now={}",
                removed, kept, x, still, links
            )
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: hard_link {}", link);

    // `/d/.`: the entry `.` of an empty directory.
    let dot = match mount(ext2_base()) {
        Ok(fs) => {
            let made = fs.create_dir("/d").is_ok();
            let r = show(fs.remove("/d/."));
            let e = fs.create_dir("/e").is_ok();
            let aliases = fs.resolve_path("/d").ok() == fs.resolve_path("/e").ok();
            alloc::format!("made={} remove={} e_made={} d_aliases_e={}", made, r, e, aliases)
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: dot_remove {}", dot);

    // Round 1, finding 10 (never run before): a deleted entry named s ahead
    // of the live s; a 256-byte name.
    let mut img = ext2_base();
    let rb = ROOT_BLOCK as usize * BS;
    put16(&mut img, rb + 12 + 4, 12);
    put_dirent(&mut img, rb + 24, 0, 12, b"s", 1);
    put_dirent(&mut img, rb + 36, 12, (BS - 36) as u16, b"s", 1);
    put_inode(&mut img, 12, 0x81A4, 0, &[]);
    img[4 * BS + 1] |= 0x08;
    let stale = match mount(img) {
        Ok(fs) => {
            let r = show(fs.remove("/s"));
            let gone = fs.stat("/s").is_err();
            let long = fs.create_file_bytes(&alloc::format!("/{}", "n".repeat(256)), b"1").is_err();
            alloc::format!("remove={} live_entry_gone={} long_name_refused={}", r, gone, long)
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: stale_entry {}", stale);

    // write_inode with numbers outside the table.
    let bounds = match mount(ext2_base()) {
        Ok(fs) => {
            let inode = fs.read_inode(2).ok();
            match inode {
                Some(i) => alloc::format!(
                    "zero_refused={} past_end_refused={}",
                    fs.write_inode(0, &i).is_err(),
                    fs.write_inode(u32::MAX, &i).is_err()
                ),
                None => String::from("read_failed"),
            }
        }
        Err(e) => alloc::format!("mount_err:{}", e.replace(' ', "_")),
    };
    println!("selftest ext2-r4: write_inode_bounds {}", bounds);
}

// ---- small items ------------------------------------------------------------

/// A ring-3 DeleteFile whose path carries an escape sequence and a newline.
/// The prompt must name the path, escaped. Nobody answers: the 5 s timeout
/// denies it.
fn delete_prompt() {
    let path: &[u8] = b"/tmp/k4-\x1b[2J\nAPPROVED";
    // lea rdi, [rip + 24]; mov esi, len; mov eax, 22; int 0x80;
    // mov rdi, rax; mov eax, 30; int 0x80; jmp $; path
    let mut code = vec![0x48, 0x8D, 0x3D, 24, 0, 0, 0, 0xBE];
    code.extend_from_slice(&(path.len() as u32).to_le_bytes());
    code.extend_from_slice(&[
        0xB8, 0x16, 0x00, 0x00, 0x00, 0xCD, 0x80, 0x48, 0x89, 0xC7, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB,
        0xFE,
    ]);
    code.extend_from_slice(path);
    println!("selftest delete-prompt: starting");
    let (ended, exit) = match start_ring3("selftest-delprompt", &code, &[]) {
        Ok(pid) => {
            println!("selftest delete-prompt: pid={}", pid);
            run_until_dead(pid, 12000)
        }
        Err(e) => {
            println!("selftest delete-prompt: start_error={}", e.replace(' ', "_"));
            return;
        }
    };
    let denied = crate::syscall::SyscallStatus::PermissionDenied as i64 as u64 as u32;
    println!(
        "selftest delete-prompt: ended={} denied={} expected_subject=DeleteFile_path=\"{}\"",
        ended,
        exit == Some(denied),
        crate::syscall::escape_printable(core::str::from_utf8(path).unwrap_or(""))
    );
}

/// ExecIfVersion for a compiled-in program name, with a VFS file written at
/// that path; and the same check on an ordinary VFS file (control).
fn exec_embedded_version() {
    use crate::syscall::process::exec_version_check;
    let made_bin = crate::fs::create_dir("/bin").is_ok();
    let wrote = crate::fs::create_file_bytes("/bin/task-manager", b"not an elf").is_ok();
    let embedded = exec_version_check("/bin/task-manager", 0).is_ok();
    let _ = crate::fs::remove("/bin/task-manager");
    if made_bin {
        let _ = crate::fs::remove("/bin");
    }
    let control_wrote = crate::fs::create_file_bytes("/tmp-k4-exec", b"x").is_ok();
    let control_refused = exec_version_check("/tmp-k4-exec", 0).is_err();
    let _ = crate::fs::remove("/tmp-k4-exec");
    println!(
        "selftest exec-embedded-version: vfs_file_written={} embedded_check_passes={} control_written={} control_mismatch_refused={}",
        wrote, embedded, control_wrote, control_refused
    );
}

/// Largest canvases for ten processes (four windows each would be allowed
/// per process): the app windows together must stay within the budget and
/// the kernel must keep running.
fn window_budget() {
    use crate::gui::app_window::{close_for_pid, create_window, total_canvas_bytes, MAX_TOTAL_CANVAS_BYTES};
    let before = total_canvas_bytes();
    println!("selftest window-budget: starting canvas_bytes_before={}", before);
    let mut created = 0;
    let mut refused = 0;
    for i in 0..10u64 {
        let pid = 900_000 + i;
        if create_window(pid, "k4-budget", 760, 560) != 0 {
            created += 1;
        } else {
            refused += 1;
        }
    }
    let peak = total_canvas_bytes();
    for i in 0..10u64 {
        close_for_pid(900_000 + i);
    }
    println!(
        "selftest window-budget: created={} refused={} peak_canvas_bytes={} budget={} within_budget={} after={}",
        created,
        refused,
        peak,
        MAX_TOTAL_CANVAS_BYTES,
        peak <= MAX_TOTAL_CANVAS_BYTES,
        total_canvas_bytes()
    );
}

// ---- earlier rounds' untested fixes ------------------------------------------

/// Round 1, finding 8: windows of a process that exits are closed.
fn exit_closes_windows() {
    let pid = match start_ring3("selftest-win", &EXIT_ZERO, &[]) {
        Ok(pid) => pid,
        Err(e) => {
            println!("selftest exit-closes-windows: start_error={}", e.replace(' ', "_"));
            return;
        }
    };
    let id = crate::gui::app_window::create_window(pid, "k4", 64, 48);
    let before = crate::gui::app_window::window_count_for(pid);
    let (ended, exit) = run_until_dead(pid, 3000);
    let after = crate::gui::app_window::window_count_for(pid);
    println!(
        "selftest exit-closes-windows: window_id={} windows_before={} ended={} exit={} windows_after={}",
        id,
        before,
        ended,
        exit_str(exit),
        after
    );
}

/// Round 1, finding 9: the deferred reap of one dead process frees the other
/// dead processes too.
fn reap_others() {
    let a = start_ring3("selftest-reap-a", &EXIT_ZERO, &[]);
    let b = start_ring3("selftest-reap-b", &EXIT_ZERO, &[]);
    let (Ok(a), Ok(b)) = (a, b) else {
        println!("selftest reap-others: start_error=true");
        return;
    };
    let dead = |pid| crate::scheduler::task_state(pid) == Some(crate::scheduler::TaskState::Dead);
    let start = crate::scheduler::total_ticks();
    while !(dead(a) && dead(b)) && crate::scheduler::total_ticks() < start + 3000 / crate::interrupts::PIT_TICK_MS {
        yield_for(20);
    }
    let both_dead = dead(a) && dead(b);
    let registered_before = crate::process::is_registered(a) && crate::process::is_registered(b);
    crate::scheduler::defer_reap(a);
    let shell = crate::scheduler::list_tasks().into_iter().find(|t| t.name == "shell").map(|t| t.id).unwrap_or(0);
    crate::scheduler::reap_deferred(shell);
    println!(
        "selftest reap-others: both_dead={} registered_before={} a_freed={} b_freed={}",
        both_dead,
        registered_before,
        !crate::process::is_registered(a),
        !crate::process::is_registered(b)
    );
    crate::process::reap_dead();
}

/// Round 3 left #MF untested: an x87 divide by zero with the zero-divide
/// exception unmasked, reported at the next `fwait`. Needs CR0.NE.
fn user_x87() {
    let cr0: u64;
    unsafe { core::arch::asm!("mov {}, cr0", out(reg) cr0) };
    // push 0x037B; fldcw [rsp]; fld1; fldz; fdivp; fwait; jmp $
    let code = [
        0x68, 0x7B, 0x03, 0x00, 0x00, 0xD9, 0x2C, 0x24, 0xD9, 0xE8, 0xD9, 0xEE, 0xDE, 0xF9, 0x9B, 0xEB, 0xFE,
    ];
    let (ended, exit) = match start_ring3("selftest-x87", &code, &[]) {
        Ok(pid) => run_until_dead(pid, 2000),
        Err(_) => (false, None),
    };
    println!(
        "selftest user-x87: cr0_ne={} ended={} exit={} kernel_alive=true",
        cr0 & (1 << 5) != 0,
        ended,
        exit_str(exit)
    );
}
