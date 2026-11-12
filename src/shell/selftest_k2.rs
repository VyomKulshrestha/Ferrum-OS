// ============================================================================
// FerrumOS - Kernel self-tests, fi1 kernel round 2
// ============================================================================
// `test-syscall <name>` falls through to these after `selftest::run`. Each
// drives the kernel function a ring-3 caller (or a packet, or a disk image)
// reaches and prints `selftest <name>: key=value ...` lines that
// `scripts/verify_kernel_selftests_k2.mjs` and `scripts/verify_net_k2.mjs`
// check. Every test cleans up after itself.
// ============================================================================

extern crate alloc;

use crate::println;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;
use x86_64::structures::paging::{PageTableFlags, PhysFrame};
use x86_64::{PhysAddr, VirtAddr};

/// Owners no process or task can be (pids count up from 1, task ids from 100).
const TEST_PID: u64 = u64::MAX - 2000;
const TEST_PID_2: u64 = u64::MAX - 2001;
const USER_BASE: u64 = 0x80_0000_0000;

pub fn run(name: &str) -> bool {
    match name {
        "nx-flags" => nx_flags(),
        "quota-exempt" => quota_exempt(),
        "process-limit" => process_limit(),
        "mmap-quota" => mmap_quota(),
        "cpu-quota" => cpu_quota(),
        "socket-limits" => socket_limits(),
        "rx-header" => rx_header(),
        "net-listen" => net_listen(),
        "service-lifecycle" => service_lifecycle(),
        "task-name" => task_name(),
        "ext2-valid" => ext2_case("valid"),
        "ext2-shift" => ext2_case("shift"),
        "ext2-groups" => ext2_case("groups"),
        "ext2-inode-size" => ext2_case("inode-size"),
        "ext2-bpg" => ext2_case("bpg"),
        "ext2-gdt" => ext2_case("gdt"),
        "perf" => perf(),
        "ring0-fault" => ring0_fault(),
        _ => return super::selftest_k3::run(name),
    }
    true
}

// ---- helpers ---------------------------------------------------------------

/// ELF64 executable with one PT_LOAD at USER_BASE holding the headers and
/// `code`, entry at the code. `flags` are the segment's p_flags.
fn elf_with_code(code: &[u8], flags: u32) -> Vec<u8> {
    let code_off = 64 + 56;
    let mut elf = vec![0u8; code_off + code.len()];
    elf[0..4].copy_from_slice(b"\x7FELF");
    elf[4] = 2;
    elf[5] = 1;
    elf[6] = 1;
    elf[16..18].copy_from_slice(&2u16.to_le_bytes());
    elf[18..20].copy_from_slice(&62u16.to_le_bytes());
    elf[20..24].copy_from_slice(&1u32.to_le_bytes());
    elf[24..32].copy_from_slice(&(USER_BASE + code_off as u64).to_le_bytes());
    elf[32..40].copy_from_slice(&64u64.to_le_bytes());
    elf[52..54].copy_from_slice(&64u16.to_le_bytes());
    elf[54..56].copy_from_slice(&56u16.to_le_bytes());
    elf[56..58].copy_from_slice(&1u16.to_le_bytes());
    let ph = 64;
    let size = elf.len() as u64;
    elf[ph..ph + 4].copy_from_slice(&1u32.to_le_bytes());
    elf[ph + 4..ph + 8].copy_from_slice(&flags.to_le_bytes());
    elf[ph + 8..ph + 16].copy_from_slice(&0u64.to_le_bytes()); // p_offset
    elf[ph + 16..ph + 24].copy_from_slice(&USER_BASE.to_le_bytes());
    elf[ph + 24..ph + 32].copy_from_slice(&USER_BASE.to_le_bytes());
    elf[ph + 32..ph + 40].copy_from_slice(&size.to_le_bytes()); // p_filesz
    elf[ph + 40..ph + 48].copy_from_slice(&size.to_le_bytes()); // p_memsz
    elf[ph + 48..ph + 56].copy_from_slice(&4096u64.to_le_bytes());
    elf[code_off..].copy_from_slice(code);
    elf
}

/// Flags of `addr` in the address space whose L4 is `l4`.
fn page_flags(l4: PhysFrame, addr: u64) -> Option<PageTableFlags> {
    use x86_64::structures::paging::mapper::{Translate, TranslateResult};
    use x86_64::structures::paging::{OffsetPageTable, PageTable};
    let table = unsafe { &mut *crate::memory::phys_to_virt(l4.start_address()).as_mut_ptr::<PageTable>() };
    let mapper = unsafe { OffsetPageTable::new(table, crate::memory::phys_to_virt(PhysAddr::new(0))) };
    match mapper.translate(VirtAddr::new(addr)) {
        TranslateResult::Mapped { flags, .. } => Some(flags),
        _ => None,
    }
}

fn nx(flags: Option<PageTableFlags>) -> String {
    match flags {
        Some(f) => alloc::format!("{}", f.contains(PageTableFlags::NO_EXECUTE)),
        None => String::from("unmapped"),
    }
}

/// Run `f` as if `pid` were the current process (the caller identity that
/// `process::create` and the syscall layer read), then restore.
fn as_pid<T>(pid: u64, f: impl FnOnce() -> T) -> T {
    let saved = crate::scheduler::CURRENT_PID.swap(pid, Ordering::SeqCst);
    let out = f();
    crate::scheduler::CURRENT_PID.store(saved, Ordering::SeqCst);
    out
}

/// Let other tasks run for about `ms` milliseconds: park the shell at its
/// safepoint the way its own idle loop does.
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

// ---- memory protection -----------------------------------------------------

fn nx_flags() {
    use x86_64::registers::model_specific::{Efer, EferFlags};
    let nxe = Efer::read().contains(EferFlags::NO_EXECUTE_ENABLE);
    // Data segment (R+W) and code segment (R+X), each with the user stack.
    let probe = |flags: u32| -> (Option<PageTableFlags>, Option<PageTableFlags>) {
        match crate::process::create("selftest-nx") {
            Ok(mut process) => {
                if process.load_elf(&elf_with_code(&[0xEB, 0xFE], flags)).is_err() {
                    return (None, None);
                }
                let l4 = process.address_space().map(|s| s.l4_frame());
                let stack = process.user_stack_top().as_u64() - 8;
                match l4 {
                    Some(l4) => (page_flags(l4, USER_BASE), page_flags(l4, stack)),
                    None => (None, None),
                }
            }
            Err(_) => (None, None),
        }
    };
    let (data, stack) = probe(6);
    let (code, _) = probe(5);
    let heap = page_flags(
        crate::memory::active_p4_frame(),
        crate::memory::heap::HEAP_START as u64,
    );
    let phys_index = crate::memory::PHYS_MAP_NX_INDEX.load(Ordering::SeqCst);
    let physmap_nx = phys_index != usize::MAX
        && crate::memory::kernel_p4_flags(phys_index).contains(PageTableFlags::NO_EXECUTE);
    println!(
        "selftest nx-flags: nxe={} data_nx={} stack_nx={} code_nx={} heap_nx={} physmap_nx={}",
        nxe,
        nx(data),
        nx(stack),
        nx(code),
        nx(heap),
        physmap_nx
    );
    // Audit: no kernel P4 entry other than the user slot is user-accessible
    // (P4[2], next to the user slot, is shared with the kernel).
    let mut user_entries = String::new();
    for index in 0..512 {
        if index == crate::process::USER_P4_INDEX {
            continue;
        }
        let flags = crate::memory::kernel_p4_flags(index);
        if flags.contains(PageTableFlags::PRESENT) && flags.contains(PageTableFlags::USER_ACCESSIBLE) {
            user_entries.push_str(&alloc::format!("{},", index));
        }
    }
    if user_entries.is_empty() {
        user_entries.push_str("none");
    }
    println!("selftest nx-flags: kernel_user_p4_entries={}", user_entries);
}

fn quota_exempt() {
    // A process without the exemption creates the daemon's image under the
    // daemon's name; the kernel itself still may.
    let from_unprivileged = as_pid(TEST_PID, || {
        crate::process::create("heliox-daemon").map(|p| p.max_memory_pages)
    });
    let from_kernel = crate::process::create("heliox-daemon").map(|p| p.max_memory_pages);
    let fmt = |r: Result<u64, &str>| match r {
        Ok(u64::MAX) => String::from("unlimited"),
        Ok(n) => alloc::format!("{}", n),
        Err(e) => alloc::format!("error({})", e),
    };
    println!(
        "selftest quota-exempt: unprivileged_child_pages={} kernel_child_pages={}",
        fmt(from_unprivileged),
        fmt(from_kernel)
    );
}

fn process_limit() {
    let mut pids = Vec::new();
    let mut refused = String::from("none");
    for _ in 0..24 {
        match as_pid(TEST_PID, || crate::process::create("selftest-child")) {
            Ok(process) => pids.push(crate::process::register(process)),
            Err(e) => {
                refused = String::from(e).replace(' ', "_");
                break;
            }
        }
    }
    let created = pids.len();
    for pid in pids {
        crate::process::drop_by_pid(pid);
    }
    println!(
        "selftest process-limit: children_created={} refusal={} limit={} global_limit={}",
        created,
        refused,
        crate::process::MAX_CHILDREN_PER_PROCESS,
        crate::process::MAX_PROCESSES
    );
}

fn mmap_quota() {
    let path = "/tmp/selftest-k2-mmap";
    let content = "a".repeat(64 * 4096);
    let _ = crate::fs::create_file(path, &content);
    let result = match crate::process::create("selftest-mmap") {
        Ok(mut process) => {
            process.max_memory_pages = 4;
            let pid = crate::process::register(process);
            let outcome = match crate::process::register_mmap(pid, String::from(path), 64 * 4096, 0) {
                Ok(base) => {
                    let first = crate::process::fault_in_page(pid, base);
                    let frames = crate::process::list()
                        .into_iter()
                        .find(|(p, _, _)| *p == pid)
                        .map(|(_, _, f)| f)
                        .unwrap_or(usize::MAX);
                    alloc::format!("first_fault_ok={} frames_after_fault={}", first, frames)
                }
                Err(e) => alloc::format!("mmap_error={}", e.replace(' ', "_")),
            };
            crate::process::drop_by_pid(pid);
            outcome
        }
        Err(e) => alloc::format!("create_error={}", e),
    };
    let _ = crate::fs::remove(path);
    println!("selftest mmap-quota: page_quota=4 {}", result);
}

/// A ring-3 process that spins (`jmp $`) without a syscall. With the
/// continuous-CPU quota enforced the kernel ends it (exit 140) after about
/// 5.5 s of ring-3 time; otherwise it runs until this test kills it.
fn cpu_quota() {
    let mut process = match crate::process::create("selftest-spin") {
        Ok(p) => p,
        Err(e) => {
            println!("selftest cpu-quota: create_error={}", e);
            return;
        }
    };
    let entry = match process.load_elf(&elf_with_code(&[0xEB, 0xFE], 5)) {
        Ok(entry) => entry,
        Err(e) => {
            println!("selftest cpu-quota: load_error={}", e);
            return;
        }
    };
    let pid = process.pid();
    let kernel_rsp = process.kernel_stack_top();
    let user_rsp = process.user_stack_top().as_u64() - 8;
    let cr3 = process
        .address_space()
        .map(|s| s.l4_frame().start_address().as_u64())
        .unwrap_or(0);
    crate::process::register(process);
    crate::scheduler::register_user(pid, "selftest-spin", crate::scheduler::Priority::Normal, kernel_rsp, cr3, &[]);
    crate::scheduler::write_context(pid, crate::scheduler::TaskContext::ring3(entry, user_rsp));
    println!("selftest cpu-quota: spinner pid={} started", pid);

    let start = crate::scheduler::total_ticks();
    let mut ended_by_kernel = false;
    let mut charged = 0;
    while crate::scheduler::total_ticks() < start + 30_000 / crate::interrupts::PIT_TICK_MS {
        yield_for(250);
        charged = charged.max(crate::scheduler::continuous_cpu_ticks(pid).unwrap_or(0));
        let dead = crate::scheduler::list_tasks()
            .iter()
            .find(|t| t.id == pid)
            .map(|t| t.state == crate::scheduler::TaskState::Dead)
            .unwrap_or(true);
        if dead {
            ended_by_kernel = true;
            break;
        }
    }
    let elapsed_ms = (crate::scheduler::total_ticks() - start) * crate::interrupts::PIT_TICK_MS;
    let exit = crate::scheduler::exit_status(pid);
    if !ended_by_kernel {
        crate::scheduler::kill(pid);
    }
    crate::process::reap_dead();
    println!(
        "selftest cpu-quota: ended_by_kernel={} exit_code={} elapsed_ms={} max_charged_ticks={}",
        ended_by_kernel,
        exit.map(|c| alloc::format!("{}", c)).unwrap_or_else(|| String::from("none")),
        elapsed_ms,
        charged
    );
}

// ---- network ---------------------------------------------------------------

fn socket_limits() {
    use crate::net::iface;
    // 1. Per-process descriptor limit.
    let mut fds = Vec::new();
    for _ in 0..24 {
        match iface::socket_create_tcp(TEST_PID) {
            Ok(fd) => fds.push(fd),
            Err(_) => break,
        }
    }
    let created = fds.len();
    let other_still_can = match iface::socket_create_tcp(TEST_PID_2) {
        Ok(fd) => {
            let _ = iface::socket_close(TEST_PID_2, fd);
            true
        }
        Err(_) => false,
    };
    iface::close_sockets_for_owner(TEST_PID);
    println!(
        "selftest socket-limits: created_for_one_process={} other_process_can_create={}",
        created, other_still_can
    );

    // 2. Port numbers above 65535 are refused, not truncated.
    let truncated_bind = iface::socket_create_tcp(TEST_PID)
        .map(|fd| iface::socket_bind(TEST_PID, fd, 65536 + 7781).is_ok())
        .unwrap_or(false);
    let zero_connect = iface::socket_create_tcp(TEST_PID)
        .map(|fd| iface::socket_connect(TEST_PID, fd, 0x0A00_0202, 0).is_ok())
        .unwrap_or(false);
    iface::close_sockets_for_owner(TEST_PID);

    // 3. A second process cannot bind a port another process listens on.
    let first = iface::socket_create_tcp(TEST_PID)
        .map(|fd| iface::socket_bind(TEST_PID, fd, 7781).is_ok())
        .unwrap_or(false);
    let hijack = iface::socket_create_tcp(TEST_PID_2)
        .map(|fd| iface::socket_bind(TEST_PID_2, fd, 7781).is_ok())
        .unwrap_or(false);
    let same_owner_second = iface::socket_create_tcp(TEST_PID)
        .map(|fd| iface::socket_bind(TEST_PID, fd, 7781).is_ok())
        .unwrap_or(false);
    iface::close_sockets_for_owner(TEST_PID);
    iface::close_sockets_for_owner(TEST_PID_2);
    println!(
        "selftest socket-limits: port_above_65535_bound={} port_zero_connected={} first_bind={} other_process_bound_same_port={} same_process_second_bind={}",
        truncated_bind, zero_connect, first, hijack, same_owner_second
    );
}

fn rx_header() {
    use crate::net::rtl8139::{classify_rx_header, RxHeader};
    let show = |h: RxHeader| match h {
        RxHeader::Deliver(n) => alloc::format!("deliver{}", n),
        RxHeader::Skip => String::from("skip"),
        RxHeader::Reset => String::from("reset"),
        // Any other decision (the old driver left a bad header in place
        // and stalled).
        #[allow(unreachable_patterns)]
        _ => String::from("stall"),
    };
    println!(
        "selftest rx-header: good_64={} oversize_60004={} no_rok={} crc_error={} short_3={} runt_14={}",
        show(classify_rx_header(0x0001, 64)),
        show(classify_rx_header(0x0001, 60004)),
        show(classify_rx_header(0x0000, 64)),
        show(classify_rx_header(0x0005, 64)),
        show(classify_rx_header(0x0001, 3)),
        show(classify_rx_header(0x0001, 14))
    );
}

/// Listen on port 7781 for 25 s while polling the interface, for the host
/// side of `verify_net_k2.mjs` (which sends crafted frames meanwhile).
fn net_listen() {
    use crate::net::{iface, rtl8139};
    let fd = match iface::socket_create_tcp(TEST_PID) {
        Ok(fd) => fd,
        Err(e) => {
            println!("selftest net-listen: socket_error={}", e);
            return;
        }
    };
    if let Err(e) = iface::socket_bind(TEST_PID, fd, 7781) {
        println!("selftest net-listen: bind_error={}", e);
        let _ = iface::socket_close(TEST_PID, fd);
        return;
    }
    println!("selftest net-listen: listening port=7781");
    let start = crate::scheduler::total_ticks();
    let mut last = "";
    while crate::scheduler::total_ticks() < start + 25_000 / crate::interrupts::PIT_TICK_MS {
        iface::poll();
        let state = iface::socket_state_name(TEST_PID, fd);
        if state != last {
            println!(
                "selftest net-listen: state={} t_ms={}",
                state,
                (crate::scheduler::total_ticks() - start) * crate::interrupts::PIT_TICK_MS
            );
            last = state;
        }
        if state == "ESTABLISHED" || state == "OTHER" || state == "CLOSED" {
            // A completed handshake (the harness's control connection):
            // close it and listen again.
            let _ = iface::socket_close(TEST_PID, fd);
            break;
        }
        x86_64::instructions::interrupts::enable_and_hlt();
    }
    let _ = iface::socket_close(TEST_PID, fd);
    iface::close_sockets_for_owner(TEST_PID);
    println!(
        "selftest net-listen: half_open_resets={} rx_delivered={} rx_dropped_oversize={} rx_resets={} rx_max_delivered_len={}",
        iface::HALF_OPEN_RESETS.load(Ordering::Relaxed),
        rtl8139::RX_DELIVERED.load(Ordering::Relaxed),
        rtl8139::RX_DROPPED_OVERSIZE.load(Ordering::Relaxed),
        rtl8139::RX_RESETS.load(Ordering::Relaxed),
        rtl8139::RX_MAX_DELIVERED_LEN.load(Ordering::Relaxed)
    );
}

// ---- services, names -------------------------------------------------------

fn service_lifecycle() {
    let Some(security) = crate::services::find_service("kernel.security") else {
        println!("selftest service-lifecycle: skipped (no kernel.security)");
        return;
    };
    let no_caps: [String; 0] = [];
    let stop_without_caps = crate::services::stop_service_authorized(security.id, &no_caps).is_ok();
    let state_after = crate::services::find_service("kernel.security")
        .map(|s| s.state == crate::services::ServiceState::Running)
        .unwrap_or(false);
    // Put it back whatever happened.
    let _ = crate::services::start_service(security.id);
    let root = [String::from("cap:system:all")];
    let root_restart = crate::services::restart_service_authorized(security.id, &root).is_ok();
    println!(
        "selftest service-lifecycle: no_cap_stop_allowed={} still_running={} root_restart_allowed={}",
        stop_without_caps, state_after, root_restart
    );
}

fn task_name() {
    // An Exec path's last component becomes the task name.
    let crafted = "x\",\"pid\":1,\"name\":\"init";
    x86_64::instructions::interrupts::without_interrupts(|| {
        crate::scheduler::register_user(
            TEST_PID,
            crafted,
            crate::scheduler::Priority::Idle,
            VirtAddr::new(0),
            1,
            &[],
        );
        crate::scheduler::kill(TEST_PID);
    });
    let stored = crate::scheduler::list_tasks()
        .into_iter()
        .find(|t| t.id == TEST_PID)
        .map(|t| t.name)
        .unwrap_or_default();
    crate::process::reap_dead();
    println!(
        "selftest task-name: stored_has_quote={} stored_len={}",
        stored.contains('"'),
        stored.len()
    );
}

// ---- ext2 mount validation -------------------------------------------------

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

fn put32(b: &mut [u8], off: usize, v: u32) {
    b[off..off + 4].copy_from_slice(&v.to_le_bytes());
}

/// A 64 KiB ext2 image: 1 KiB blocks, 64 blocks, 16 inodes of 128 bytes,
/// descriptor table in block 2, bitmaps in blocks 3 and 4, inode table in
/// blocks 5 and 6. `case` breaks one field.
fn ext2_image(case: &str) -> Vec<u8> {
    let mut img = vec![0u8; 64 * 1024];
    let sb = 1024;
    put32(&mut img, sb, 16); // inodes_count
    put32(&mut img, sb + 4, 64); // blocks_count
    put32(&mut img, sb + 20, 1); // first_data_block
    put32(&mut img, sb + 24, 0); // log_block_size
    put32(&mut img, sb + 32, 8192); // blocks_per_group
    put32(&mut img, sb + 36, 8192); // frags_per_group
    put32(&mut img, sb + 40, 16); // inodes_per_group
    img[sb + 56..sb + 58].copy_from_slice(&0xEF53u16.to_le_bytes());
    put32(&mut img, sb + 76, 1); // rev_level
    put32(&mut img, sb + 84, 11); // first_ino
    img[sb + 88..sb + 90].copy_from_slice(&128u16.to_le_bytes()); // inode_size
    let gd = 2048;
    put32(&mut img, gd, 3);
    put32(&mut img, gd + 4, 4);
    put32(&mut img, gd + 8, 5);
    match case {
        "shift" => put32(&mut img, sb + 24, 40),
        "groups" => {
            put32(&mut img, sb, u32::MAX);
            put32(&mut img, sb + 40, 1);
        }
        "inode-size" => img[sb + 88..sb + 90].copy_from_slice(&200u16.to_le_bytes()),
        "bpg" => put32(&mut img, sb + 32, 0),
        "gdt" => put32(&mut img, gd + 8, u32::MAX),
        _ => {}
    }
    img
}

fn ext2_case(case: &str) {
    println!("selftest ext2-{}: mounting", case);
    let disk = RamDisk { bytes: spin::Mutex::new(ext2_image(case)) };
    match crate::fs::ext2::Ext2Fs::mount(disk) {
        Err(e) => println!("selftest ext2-{}: rejected=true reason={}", case, e.replace(' ', "_")),
        Ok(fs) => {
            // Use the geometry the way later file operations would.
            let reads = [1u32, 6, 16]
                .iter()
                .map(|n| if fs.read_inode(*n).is_ok() { "ok" } else { "err" })
                .collect::<Vec<_>>()
                .join(",");
            println!("selftest ext2-{}: rejected=false inode_reads={}", case, reads);
        }
    }
}

// ---- performance -----------------------------------------------------------

fn perf() {
    use crate::interrupts::{
        SYSCALL_COUNT, SYSCALL_CYCLES, TICK_FN_COUNT, TICK_FN_CYCLES, TIMER_COUNT, TIMER_CYCLES,
        TIMER_EOI_COUNT, TIMER_EOI_CYCLES,
    };
    let avg = |cycles: u64, count: u64| if count == 0 { 0 } else { cycles / count };
    let (tc, tn) = (TIMER_CYCLES.load(Ordering::Relaxed), TIMER_COUNT.load(Ordering::Relaxed));
    let (sc, sn) = (SYSCALL_CYCLES.load(Ordering::Relaxed), SYSCALL_COUNT.load(Ordering::Relaxed));
    // Frame allocator: 2000 allocations then 2000 frees.
    let t0 = unsafe { core::arch::x86_64::_rdtsc() };
    let mut frames = Vec::with_capacity(2000);
    for _ in 0..2000 {
        if let Some(frame) = crate::memory::allocate_frame() {
            frames.push(frame);
        }
    }
    let t1 = unsafe { core::arch::x86_64::_rdtsc() };
    let n = frames.len() as u64;
    for frame in frames {
        crate::memory::deallocate_frame(frame);
    }
    let t2 = unsafe { core::arch::x86_64::_rdtsc() };
    println!(
        "selftest perf: tick_fn_avg_cycles={} timer_eoi_avg_cycles={}",
        avg(TICK_FN_CYCLES.load(Ordering::Relaxed), TICK_FN_COUNT.load(Ordering::Relaxed)),
        avg(TIMER_EOI_CYCLES.load(Ordering::Relaxed), TIMER_EOI_COUNT.load(Ordering::Relaxed))
    );
    println!(
        "selftest perf: timer_ticks={} timer_avg_cycles={} syscalls={} syscall_avg_cycles={} frame_alloc_avg_cycles={} frame_free_avg_cycles={} tasks={}",
        tn,
        avg(tc, tn),
        sn,
        avg(sc, sn),
        avg(t1 - t0, n),
        avg(t2 - t1, n),
        crate::scheduler::list_tasks().len()
    );
}

// ---- ring-0 faults ---------------------------------------------------------

/// Destructive: a ring-0 page fault while a process is current. A fixed
/// kernel stops (it must not blame the process); the old handler killed
/// the "current process" and carried on. Run last.
fn ring0_fault() {
    println!("selftest ring0-fault: reading an unmapped kernel address with pid {} current", TEST_PID);
    as_pid(TEST_PID, || unsafe {
        core::ptr::read_volatile(0x0000_7F00_0000_0000u64 as *const u64)
    });
    println!("selftest ring0-fault: survived=true");
}
