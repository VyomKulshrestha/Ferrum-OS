// ============================================================================
// FerrumOS - Kernel self-tests, fi2 kernel workstream K1
// ============================================================================
// `test-syscall <name>` falls through to these after `selftest_k4::run`. Each
// prints `selftest <name>: key=value ...` lines that
// `scripts/verify_kernel_k5.mjs` checks. Switches (`*-off`, `*-on`) restore
// the old behaviour on the same image for the negative controls.
// ============================================================================

extern crate alloc;

use super::selftest_k3::{run_until_dead, start_ring3, USER_BASE};
use crate::println;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use core::sync::atomic::Ordering;
use x86_64::structures::paging::{PageTable, PageTableFlags, PhysFrame};

pub fn run(name: &str) -> bool {
    match name {
        "cpu-protect" => cpu_protect_state(),
        "smep" => smep(),
        "smep-off" => {
            crate::cpu_protect::set_smep(false);
            println!("selftest smep-off: smep={}", crate::cpu_protect::smep_on());
        }
        "smep-on" => {
            crate::cpu_protect::set_smep(true);
            println!("selftest smep-on: smep={}", crate::cpu_protect::smep_on());
        }
        "smap" => smap(),
        "smap-off" => {
            crate::cpu_protect::set_smap(false);
            println!("selftest smap-off: smap={}", crate::cpu_protect::smap_on());
        }
        "smap-on" => {
            crate::cpu_protect::set_smap(true);
            println!("selftest smap-on: smap={}", crate::cpu_protect::smap_on());
        }
        "smap-entry" => smap_entry(),
        "ac-entry-off" => {
            crate::cpu_protect::CLEAR_AC_ON_ENTRY.store(false, Ordering::SeqCst);
            println!("selftest ac-entry-off: clear_ac_on_entry=false");
        }
        "ac-entry-on" => {
            crate::cpu_protect::CLEAR_AC_ON_ENTRY.store(true, Ordering::SeqCst);
            println!("selftest ac-entry-on: clear_ac_on_entry=true");
        }
        "smap-sweep" => smap_sweep(),
        // Destructive with SMAP on: the next user access stops the kernel.
        "smap-brackets-off" => {
            crate::cpu_protect::BRACKETS_ENABLED.store(false, Ordering::SeqCst);
            println!("selftest smap-brackets-off: brackets=false");
        }
        "console-forge" => console_forge(),
        "console-mark-off" => {
            crate::syscall::console::MARK_PROCESS_OUTPUT.store(false, Ordering::SeqCst);
            println!("selftest console-mark-off: mark_process_output=false");
        }
        "console-mark-on" => {
            crate::syscall::console::MARK_PROCESS_OUTPUT.store(true, Ordering::SeqCst);
            println!("selftest console-mark-on: mark_process_output=true");
        }
        "port-forge" => port_forge(),
        "iopl3-on" => {
            crate::scheduler::USER_IOPL3.store(true, Ordering::SeqCst);
            println!("selftest iopl3-on: user_iopl3=true");
        }
        "iopl3-off" => {
            crate::scheduler::USER_IOPL3.store(false, Ordering::SeqCst);
            println!("selftest iopl3-off: user_iopl3=false");
        }
        "heap-ledger" => heap_ledger(),
        "ledger-off" => {
            crate::memory::ledger::ENFORCE.store(false, Ordering::SeqCst);
            println!("selftest ledger-off: enforce=false");
        }
        "ledger-on" => {
            crate::memory::ledger::ENFORCE.store(true, Ordering::SeqCst);
            println!("selftest ledger-on: enforce=true");
        }
        "ext2-real" => ext2_real(),
        "ext2-fi2-off" => {
            crate::fs::ext2::FI2_FIXES.store(false, Ordering::SeqCst);
            println!("selftest ext2-fi2-off: fi2_fixes=false");
        }
        "ext2-fi2-on" => {
            crate::fs::ext2::FI2_FIXES.store(true, Ordering::SeqCst);
            println!("selftest ext2-fi2-on: fi2_fixes=true");
        }
        _ => return false,
    }
    true
}

fn exit_str(exit: Option<u32>) -> String {
    exit.map(|c| alloc::format!("{}", c)).unwrap_or_else(|| String::from("none"))
}

fn cr4() -> u64 {
    let v: u64;
    unsafe { core::arch::asm!("mov {}, cr4", out(reg) v) };
    v
}

fn cpu_protect_state() {
    use crate::cpu_protect::*;
    println!(
        "selftest cpu-protect: cpuid_smep={} cpuid_smap={} cr4={:#x} smep={} smap={} ac_set_at_entry={}",
        CPU_HAS_SMEP.load(Ordering::SeqCst),
        CPU_HAS_SMAP.load(Ordering::SeqCst),
        cr4(),
        smep_on(),
        smap_on(),
        AC_SET_AT_ENTRY.load(Ordering::SeqCst)
    );
}

// ---- a user page in the active address space ----------------------------------

/// A 4 KiB page with the user bit at every level, in a P4 slot no one else
/// uses, mapped for the duration of one test with interrupts off.
struct UserPage {
    index: usize,
    frames: [PhysFrame; 4],
}

impl UserPage {
    fn address(&self) -> u64 {
        let raw = (self.index as u64) << 39;
        if raw & (1 << 47) != 0 { raw | 0xFFFF_0000_0000_0000 } else { raw }
    }

    fn table(frame: PhysFrame) -> &'static mut PageTable {
        unsafe { &mut *crate::memory::phys_to_virt(frame.start_address()).as_mut_ptr::<PageTable>() }
    }

    /// Map a page holding `content`, executable or not.
    fn map(content: &[u8], executable: bool) -> Option<UserPage> {
        let p4 = Self::table(crate::memory::active_p4_frame());
        let index = (300..500).find(|&i| !p4[i].flags().contains(PageTableFlags::PRESENT))?;
        let mut frames = [PhysFrame::containing_address(x86_64::PhysAddr::new(0)); 4];
        for f in frames.iter_mut() {
            *f = crate::memory::allocate_frame()?;
        }
        let table_flags = PageTableFlags::PRESENT | PageTableFlags::WRITABLE | PageTableFlags::USER_ACCESSIBLE;
        let mut leaf = table_flags;
        if !executable {
            leaf |= PageTableFlags::NO_EXECUTE;
        }
        let data = unsafe {
            core::slice::from_raw_parts_mut(
                crate::memory::phys_to_virt(frames[3].start_address()).as_mut_ptr::<u8>(),
                4096,
            )
        };
        data[..content.len()].copy_from_slice(content);
        Self::table(frames[2])[0].set_frame(frames[3], leaf);
        Self::table(frames[1])[0].set_frame(frames[2], table_flags);
        Self::table(frames[0])[0].set_frame(frames[1], table_flags);
        p4[index].set_frame(frames[0], table_flags);
        x86_64::instructions::tlb::flush_all();
        Some(UserPage { index, frames })
    }
}

impl Drop for UserPage {
    fn drop(&mut self) {
        let p4 = Self::table(crate::memory::active_p4_frame());
        p4[self.index].set_unused();
        x86_64::instructions::tlb::flush_all();
        for f in self.frames {
            crate::memory::deallocate_frame(f);
        }
    }
}

// ---- SMEP ---------------------------------------------------------------------

/// Call into a user page holding `ret` from ring 0. With SMEP the
/// instruction fetch faults (error code: present, instruction fetch).
fn smep() {
    let (faulted, err, cr2, addr) = x86_64::instructions::interrupts::without_interrupts(|| {
        let Some(page) = UserPage::map(&[0xC3], true) else {
            return (false, 0, 0, 0);
        };
        let addr = page.address();
        let faulted = crate::cpu_protect::probe_call(addr, 0);
        let r = (
            faulted,
            crate::cpu_protect::PROBE_ERROR.load(Ordering::SeqCst),
            crate::cpu_protect::PROBE_CR2.load(Ordering::SeqCst),
            addr,
        );
        drop(page);
        r
    });
    println!(
        "selftest smep: smep={} user_page={:#x} kernel_call_faulted={} error={:#x} fault_addr_is_page={}",
        crate::cpu_protect::smep_on(),
        addr,
        faulted,
        if faulted { err } else { 0 },
        faulted && cr2 == addr
    );
}

// ---- SMAP ---------------------------------------------------------------------

/// Ring-0 reads and writes of a user page: without a bracket, through the
/// bracket (`UserAccess`), and an unbracketed write.
fn smap() {
    use crate::cpu_protect::*;
    let r = x86_64::instructions::interrupts::without_interrupts(|| {
        let page = UserPage::map(&[0xA7], false)?;
        let addr = page.address();
        let plain = probe_call(read_byte_unbracketed as *const () as u64, addr);
        let plain_err = PROBE_ERROR.load(Ordering::SeqCst);
        let bracketed = probe_call(read_byte_bracketed as *const () as u64, addr);
        let write = probe_call(write_byte_unbracketed as *const () as u64, addr);
        let ac_after = ac_set();
        drop(page);
        Some((addr, plain, plain_err, bracketed, write, ac_after))
    });
    match r {
        Some((addr, plain, err, bracketed, write, ac_after)) => println!(
            "selftest smap: smap={} user_page={:#x} unbracketed_read_faulted={} error={:#x} bracketed_read_faulted={} unbracketed_write_faulted={} ac_after={}",
            smap_on(),
            addr,
            plain,
            if plain { err } else { 0 },
            bracketed,
            write,
            ac_after
        ),
        None => println!("selftest smap: map_failed=true"),
    }
}

/// A ring-3 process sets RFLAGS.AC and makes a syscall; at entry the kernel
/// reads the process's memory without a bracket. AC cleared at entry: the
/// read faults (with SMAP on). AC left as the process set it: SMAP is off for
/// the whole syscall and the read succeeds.
fn smap_entry() {
    use crate::cpu_protect::*;
    // pushfq; or dword [rsp], 0x40000; popfq; lea rdi, [rip]; mov eax, 31;
    // int 0x80; xor edi, edi; mov eax, 30; int 0x80; jmp $
    let code = [
        0x9C, 0x81, 0x0C, 0x24, 0x00, 0x00, 0x04, 0x00, 0x9D, 0x48, 0x8D, 0x3D, 0x00, 0x00, 0x00, 0x00, 0xB8, 0x1F,
        0x00, 0x00, 0x00, 0xCD, 0x80, 0x31, 0xFF, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xFE,
    ];
    ENTRY_PROBE_RESULT.store(0, Ordering::SeqCst);
    let before = AC_SET_AT_ENTRY.load(Ordering::SeqCst);
    let (ended, exit) = match start_ring3("selftest-smap-ac", &code, &[]) {
        Ok(pid) => {
            ENTRY_PROBE_PID.store(pid, Ordering::SeqCst);
            run_until_dead(pid, 3000)
        }
        Err(_) => (false, None),
    };
    ENTRY_PROBE_PID.store(0, Ordering::SeqCst);
    let r = ENTRY_PROBE_RESULT.load(Ordering::SeqCst);
    println!(
        "selftest smap-entry: smap={} clear_ac_on_entry={} probe_ran={} ac_in_kernel={} unbracketed_read_faulted={} entries_with_ac={} ended={} exit={}",
        smap_on(),
        CLEAR_AC_ON_ENTRY.load(Ordering::SeqCst),
        r & 4 != 0,
        r & 1 != 0,
        r & 2 != 0,
        AC_SET_AT_ENTRY.load(Ordering::SeqCst) - before,
        ended,
        exit_str(exit)
    );
}

// ---- syscall sweep ------------------------------------------------------------

/// Builds a ring-3 program that makes a list of syscalls and exits with a
/// bitmask of the calls that returned an error. Data (paths, payloads) sits
/// behind a leading jump; output buffers are at the bottom of the user stack.
struct SweepProgram {
    data: Vec<u8>,
    calls: Vec<(u32, [u64; 5])>,
}

const CODE_VADDR: u64 = USER_BASE + 64 + 56;

impl SweepProgram {
    fn data_vaddr() -> u64 {
        CODE_VADDR + 5
    }

    /// Place `bytes` in the data area; returns (address, length).
    fn put(&mut self, bytes: &[u8]) -> (u64, u64) {
        let at = Self::data_vaddr() + self.data.len() as u64;
        self.data.extend_from_slice(bytes);
        (at, bytes.len() as u64)
    }

    fn call(&mut self, number: u32, args: [u64; 5]) {
        self.calls.push((number, args));
    }

    fn build(&self) -> Vec<u8> {
        let mut code = vec![0xE9];
        code.extend_from_slice(&(self.data.len() as u32).to_le_bytes());
        code.extend_from_slice(&self.data);
        code.extend_from_slice(&[0x31, 0xDB]); // xor ebx, ebx
        let regs: [[u8; 2]; 5] = [[0x48, 0xBF], [0x48, 0xBE], [0x48, 0xBA], [0x49, 0xBA], [0x49, 0xB8]];
        for (i, (number, args)) in self.calls.iter().enumerate() {
            code.push(0xB8);
            code.extend_from_slice(&number.to_le_bytes());
            for (r, a) in regs.iter().zip(args.iter()) {
                code.extend_from_slice(r);
                code.extend_from_slice(&a.to_le_bytes());
            }
            code.extend_from_slice(&[0xCD, 0x80, 0x48, 0x85, 0xC0, 0x79, 0x06, 0x81, 0xCB]);
            code.extend_from_slice(&(1u32 << i).to_le_bytes());
        }
        // exit(ebx); jmp $
        code.extend_from_slice(&[0x89, 0xDF, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xFE]);
        code
    }
}

/// Every syscall path that copies to or from user memory, called from ring 3
/// with valid buffers. With SMAP on, a path whose access is not bracketed
/// stops the kernel here (a ring-0 page fault) instead of in production.
fn smap_sweep() {
    let out = |n: u64| crate::process::USER_STACK_BASE + 0x1000 * n;
    let mut p = SweepProgram { data: Vec::new(), calls: Vec::new() };
    let msg = p.put(b"selftest smap-sweep: ring-3 write reached the console\n");
    let dir = p.put(b"/k5smap");
    let file = p.put(b"/k5smap/f");
    let payload = p.put(b"k5 sweep payload");
    let root = p.put(b"/");
    let clip = p.put(b"k5 clipboard");
    let title = p.put(b"k5 title");
    let body = p.put(b"k5 body");
    let audit = p.put(b"k5 smap sweep audit record");
    let names = [
        "Write", "CreateDir", "WriteFile", "ReadFile", "FileVersion", "ReadDir", "SystemQuery", "GetRandom",
        "ClipboardWrite", "ClipboardRead", "NotificationPost", "NotificationList", "LaunchContext", "CreateWindow",
        "AuditWrite",
    ];
    p.call(34, [2, msg.0, msg.1, 0, 0]);
    p.call(21, [dir.0, dir.1, 0, 0, 0]);
    p.call(16, [file.0, file.1, payload.0, payload.1, 0]);
    p.call(15, [file.0, file.1, out(1), 256, 0]);
    p.call(62, [file.0, file.1, 0, 0, 0]);
    p.call(17, [root.0, root.1, out(2), 1024, 0]);
    p.call(29, [0, out(3), 1024, 0, 0]);
    p.call(42, [out(4), 64, 0, 0, 0]);
    p.call(54, [clip.0, clip.1, 0, 0, 0]);
    p.call(53, [out(5), 256, 0, 0, 0]);
    p.call(55, [title.0, title.1, body.0, body.1, 0]);
    p.call(56, [out(6), 2048, 0, 0, 0]);
    p.call(59, [out(7), 256, 0, 0, 0]);
    p.call(44, [title.0, title.1, 16, 16, 0]);
    p.call(6, [audit.0, audit.1, 0, 0, 0]);
    let code = p.build();
    let caps = [String::from("cap:system:all")];
    println!("selftest smap-sweep: starting smap={} calls={}", crate::cpu_protect::smap_on(), names.len());
    let (ended, exit) = match start_ring3("selftest-smap-sweep", &code, &caps) {
        Ok(pid) => run_until_dead(pid, 8000),
        Err(_) => (false, None),
    };
    let _ = crate::fs::remove("/k5smap/f");
    let _ = crate::fs::remove("/k5smap");
    let failed: Vec<&str> = match exit {
        Some(mask) => names.iter().enumerate().filter(|(i, _)| mask & (1 << i) != 0).map(|(_, n)| *n).collect(),
        None => Vec::new(),
    };
    println!(
        "selftest smap-sweep: smap={} ended={} exit={} failed_calls={}",
        crate::cpu_protect::smap_on(),
        ended,
        exit_str(exit),
        if failed.is_empty() { String::from("none") } else { failed.join(",") }
    );
}

// ---- per-process heap ledger (item 4) -------------------------------------------

/// One ring-3 process asks the kernel to hold more than its budget through
/// five kinds of objects: two of the largest windows (3.4 MB), a 4 KiB IPC
/// message to its own mailbox, an audit record, a socket, and two 400 KiB
/// RamFS files. Each kind alone is within its own bound; together they pass
/// the 4 MiB ledger cap at the second file. The process then receives its
/// message, sleeps while the test samples the ledger, and exits.
fn heap_ledger() {
    use crate::memory::ledger;
    let out = |n: u64| crate::process::USER_STACK_BASE + 0x1000 * n;
    let big = crate::process::USER_STACK_BASE + 0x10000; // 400 KiB of zeros
    let mut p = SweepProgram { data: Vec::new(), calls: Vec::new() };
    let title = p.put(b"k5 ledger");
    let me = p.put(b"selftest-ledger");
    let audit = p.put(b"k5 ledger audit record");
    let fa = p.put(b"/k5ledger-a");
    let fb = p.put(b"/k5ledger-b");
    let names = [
        "CreateWindow", "CreateWindow", "IpcSend", "AuditWrite", "Socket", "WriteFile_a", "WriteFile_b",
        "IpcReceive", "Sleep",
    ];
    p.call(44, [title.0, title.1, 760, 560, 0]);
    p.call(44, [title.0, title.1, 760, 560, 0]);
    p.call(1, [me.0, me.1, out(1), 4096, 0]);
    p.call(6, [audit.0, audit.1, 0, 0, 0]);
    p.call(7, [2, 1, 0, 0, 0]);
    p.call(16, [fa.0, fa.1, big, 400 * 1024, 0]);
    p.call(16, [fb.0, fb.1, big, 400 * 1024, 0]);
    p.call(2, [out(3), 4096, me.0, me.1, 0]);
    p.call(32, [1500, 0, 0, 0, 0]);
    let code = p.build();
    let caps = [String::from("cap:system:all")];
    let refused_before = ledger::REFUSED.load(Ordering::SeqCst);
    let pid = match start_ring3("selftest-ledger", &code, &caps) {
        Ok(pid) => pid,
        Err(e) => {
            println!("selftest heap-ledger: start_error={}", e.replace(' ', "_"));
            return;
        }
    };
    super::selftest_k3::yield_for(700);
    let u = ledger::usage(pid);
    let total: usize = u.iter().sum();
    let peak = ledger::peak(pid);
    let (ended, exit) = run_until_dead(pid, 6000);
    let _ = crate::fs::remove("/k5ledger-a");
    let _ = crate::fs::remove("/k5ledger-b");
    let failed: Vec<&str> = match exit {
        Some(mask) => names.iter().enumerate().filter(|(i, _)| mask & (1 << i) != 0).map(|(_, n)| *n).collect(),
        None => Vec::new(),
    };
    println!(
        "selftest heap-ledger: enforce={} cap={} ipc={} launch={} audit={} ramfs={} windows={} sockets={} total={} peak={} refused={} ended={} exit={} failed_calls={} entry_after_reap={} windows_after={} sockets_after={}",
        ledger::ENFORCE.load(Ordering::SeqCst),
        ledger::PROCESS_HEAP_CAP,
        u[0],
        u[1],
        u[2],
        u[3],
        u[4],
        u[5],
        total,
        peak,
        ledger::REFUSED.load(Ordering::SeqCst) - refused_before,
        ended,
        exit_str(exit),
        if failed.is_empty() { String::from("none") } else { failed.join(",") },
        ledger::has_entry(pid),
        crate::gui::app_window::canvas_bytes_of(pid),
        crate::net::iface::sockets_owned_by(pid)
    );
}

// ---- ext2 on disks made by mke2fs (item 5) ---------------------------------------

/// The disk on the secondary IDE channel, `drive` 0 (master) or 1 (slave),
/// mounted on a private ext2 instance (not in the VFS, so nothing else
/// writes it during the test).
fn mount_secondary(drive: u8) -> Result<crate::fs::ext2::Ext2Fs<crate::fs::block::AtaBlockDevice>, String> {
    let info = crate::ata::list_drives()
        .into_iter()
        .find(|d| d.bus == crate::ata::AtaBus::Secondary && d.drive == drive && d.present)
        .ok_or_else(|| String::from("no_disk"))?;
    crate::fs::ext2::Ext2Fs::mount(crate::fs::block::AtaBlockDevice::new(info.bus, info.drive, info.sectors))
}

fn ext2_real() {
    use crate::fs::vfs::Filesystem;
    let fixes = crate::fs::ext2::FI2_FIXES.load(Ordering::SeqCst);
    println!("selftest ext2-real: fi2_fixes={}", fixes);
    let ok = |r: Result<(), String>| r.is_ok();

    // ---- clean.img (secondary master): ordinary work, checked by e2fsck --
    match mount_secondary(0) {
        Err(e) => println!("selftest ext2-real: clean mount=err:{}", e.replace(' ', "_")),
        Ok(fs) => {
            let root: Vec<String> = fs.list_dir("/").map(|v| v.into_iter().map(|e| e.name).collect()).unwrap_or_default();
            let bigdir = fs.list_dir("/bigdir").map(|v| v.len()).unwrap_or(0);
            let mut buf = vec![0u8; 320 * 1024];
            let big_read = fs.read_file_offset("/big", 0, &mut buf).unwrap_or(0);
            println!(
                "selftest ext2-real: clean mount=ok root_has_big={} root_has_lost_found={} bigdir_entries={} big_bytes_read={}",
                root.iter().any(|n| n == "big"),
                root.iter().any(|n| n == "lost+found"),
                bigdir,
                big_read
            );
            // A hard link (round 4 finding 4 on a real disk).
            let unlink = ok(fs.remove("/link1"));
            let link2 = fs.read_file("/link2").map(|s| s == "hard link content\n").unwrap_or(false);
            // Overwrite the 300 KiB file (12 direct, 256 through the single
            // indirect block, 32 through the double) with 5 KiB.
            let big_inode = fs.resolve_path("/big").and_then(|n| fs.read_inode(n));
            let (data, pointers) = big_inode.as_ref().ok().and_then(|i| fs.inode_blocks(i).ok()).unwrap_or_default();
            let (free0, _) = fs.free_counts();
            let over = ok(fs.create_file_bytes("/big", &[b'b'; 5 * 1024]));
            let (free1, _) = fs.free_counts();
            println!(
                "selftest ext2-real: clean unlink_one_of_two={} other_link_intact={} big_data_blocks={} big_pointer_blocks={} overwrite={} overwrite_freed={}",
                unlink,
                link2,
                data.len(),
                pointers.len(),
                over,
                free1 as i64 - free0 as i64
            );
            // A directory past 12 blocks: 120 names of 100 bytes (9 per block).
            let made = ok(fs.create_dir("/growdir"));
            let mut created = 0;
            for i in 0..120 {
                let name = alloc::format!("/growdir/{:0>100}", i);
                if fs.create_file_bytes(&name, b"").is_ok() {
                    created += 1;
                } else {
                    break;
                }
            }
            let listed = fs.list_dir("/growdir").map(|v| v.len()).unwrap_or(0);
            let gd = fs.resolve_path("/growdir").and_then(|n| fs.read_inode(n));
            let gd_blocks = gd.as_ref().map(|i| i.size / fs.block_size).unwrap_or(0);
            let last_found = fs.resolve_path(&alloc::format!("/growdir/{:0>100}", 119)).is_ok();
            let mut removed = 0;
            for i in (0..120).step_by(6) {
                if fs.remove(&alloc::format!("/growdir/{:0>100}", i)).is_ok() {
                    removed += 1;
                }
            }
            println!(
                "selftest ext2-real: clean growdir_made={} created={} listed={} dir_blocks={} last_found={} removed={}",
                made, created, listed, gd_blocks, last_found, removed
            );
            // Remove the rewritten file and a small one; a nested directory.
            let (f2, _) = fs.free_counts();
            let rm_big = ok(fs.remove("/big"));
            let rm_small = ok(fs.remove("/small"));
            let nested = ok(fs.create_dir("/n1")) && ok(fs.create_dir("/n1/n2")) && ok(fs.create_file_bytes("/n1/n2/f", b"x"));
            let unnest = ok(fs.remove("/n1/n2/f")) && ok(fs.remove("/n1/n2")) && ok(fs.remove("/n1"));
            let (f3, _) = fs.free_counts();
            println!(
                "selftest ext2-real: clean remove_big={} remove_small={} nested={} unnested={} freed={}",
                rm_big,
                rm_small,
                nested,
                unnest,
                f3 as i64 - f2 as i64
            );
            // A second 300 KiB file is not creatable (12-block files), so the
            // indirect remove path is exercised on the crafted disk's filler.
        }
    }

    // ---- crafted.img (secondary slave): damaged by debugfs ------------------
    match mount_secondary(1) {
        Err(e) => println!("selftest ext2-real: crafted mount=err:{}", e.replace(' ', "_")),
        Ok(fs) => {
            let victim0 = fs.read_file("/victim").ok();
            // `xlink` shares its block with `victim`.
            let rm_xlink = ok(fs.remove("/xlink"));
            // `evil` points at group 1's backup superblock (block 8193).
            let rm_evil = ok(fs.remove("/evil"));
            // The filler (6.5 MiB: single, double indirect) is removed: every
            // data and pointer block must come back.
            let filler = fs.resolve_path("/filler").and_then(|n| fs.read_inode(n));
            let (fd, fp) = filler.as_ref().ok().and_then(|i| fs.inode_blocks(i).ok()).unwrap_or_default();
            let (g0, _) = fs.free_counts();
            let rm_filler = ok(fs.remove("/filler"));
            let (g1, _) = fs.free_counts();
            // Fill: 40 files of 12 blocks. Group 0 is marked full, so they
            // come from group 1, whose backup superblock, descriptor and
            // reserved descriptor blocks (8193-8321) the bitmap calls free.
            let mut in_meta = 0;
            let mut written = 0;
            for i in 0..40 {
                let name = alloc::format!("/fill{}", i);
                if fs.create_file_bytes(&name, &[b'F'; 12 * 1024]).is_err() {
                    break;
                }
                written += 1;
                if let Ok(inode) = fs.resolve_path(&name).and_then(|n| fs.read_inode(n)) {
                    let blocks = inode.block;
                    in_meta += blocks.iter().take(12).filter(|&&b| (8193..=8321).contains(&b)).count();
                }
            }
            let mut sb = vec![0u8; fs.block_size as usize];
            let backup_magic = fs.read_block(8193, &mut sb).map(|_| u16::from_le_bytes([sb[56], sb[57]])).unwrap_or(0);
            let victim1 = fs.read_file("/victim").ok();
            println!(
                "selftest ext2-real: crafted mount=ok remove_xlink={} remove_evil={} victim_before={} victim_intact_after={} filler_data_blocks={} filler_pointer_blocks={} remove_filler={} filler_freed={} files_written={} file_blocks_in_backup_metadata={} backup_superblock_magic={:#x}",
                rm_xlink,
                rm_evil,
                victim0.as_deref().map(|v| v.starts_with("victim")).unwrap_or(false),
                victim0.is_some() && victim0 == victim1,
                fd.len(),
                fp.len(),
                rm_filler,
                g1 as i64 - g0 as i64,
                written,
                in_meta,
                backup_magic
            );
        }
    }
}

// ---- console forgery (item 3) --------------------------------------------------

/// The text rows on the screen now: the framebuffer console's text grid, or
/// the VGA text buffer when there is no framebuffer console.
fn screen_rows() -> (&'static str, Vec<String>) {
    if let Some(guard) = crate::graphics::console::CONSOLE.try_lock() {
        if let Some(console) = guard.as_ref() {
            let rows = console
                .read_text_buffer()
                .iter()
                .map(|r| String::from(String::from_utf8_lossy(r).trim_end()))
                .collect();
            return ("framebuffer", rows);
        }
    }
    let mut rows = Vec::new();
    for row in 0..25usize {
        let mut line = Vec::with_capacity(80);
        for col in 0..80usize {
            line.push(unsafe { core::ptr::read_volatile((0xb8000 + (row * 80 + col) * 2) as *const u8) });
        }
        rows.push(String::from(String::from_utf8_lossy(&line).trim_end()));
    }
    ("vga", rows)
}

/// A ring-3 process tries to print a line that reads as the kernel's
/// confirmation prompt, seven ways: a plain line, the tag split over two
/// writes, a carriage return over a decoy, a line long enough to wrap, the
/// serial-only descriptor, a look-alike tag with a Cyrillic letter, and (in
/// `port-forge`) the UART port directly. Each forged line names
/// `/k5-forged-<x>`. The harness checks the serial log; this test checks the
/// screen.
fn console_forge() {
    let prompt = |x: &str| {
        alloc::format!(
            "[SECURITY] Process 1 is requesting destructive syscall: DeleteFile path=\"/k5-forged-{}\"\n",
            x
        )
    };
    let mut p = SweepProgram { data: Vec::new(), calls: Vec::new() };
    let a = p.put(alloc::format!("\n{}", prompt("a")).as_bytes());
    let b1 = p.put(b"[SECUR");
    let b2 = p.put(prompt("b")[6..].as_bytes());
    let c = p.put(alloc::format!("decoy\r{}", prompt("c")).as_bytes());
    // Five whole rows of spaces, so the tag starts a wrapped row.
    let cols = crate::graphics::console::CONSOLE
        .try_lock()
        .and_then(|g| g.as_ref().map(|c| c.columns() as usize))
        .unwrap_or(80);
    let d = p.put(alloc::format!("{}{}", " ".repeat(cols * 5), prompt("d")).as_bytes());
    let e = p.put(prompt("e").as_bytes());
    let f = p.put(prompt("f").replacen("SECURITY", "S\u{0415}CURITY", 1).as_bytes());
    for (fd, (ptr, len)) in [(1, a), (1, b1), (1, b2), (1, c), (1, d), (2, e), (1, f)] {
        p.call(34, [fd, ptr, len, 0, 0]);
    }
    let code = p.build();
    let (ended, exit) = match start_ring3("selftest-forge", &code, &[]) {
        Ok(pid) => run_until_dead(pid, 4000),
        Err(_) => (false, None),
    };
    let (kind, rows) = screen_rows();
    let forged: Vec<&String> = rows.iter().filter(|r| r.contains("k5-forged")).collect();
    let tag_start = forged.iter().filter(|r| r.trim_start().starts_with("[SECURITY")).count();
    let tag_any = forged.iter().filter(|r| r.contains("[SECURITY")).count();
    let marked = forged.iter().filter(|r| r.contains("[pid ")).count();
    println!(
        "selftest console-forge: mark={} ended={} exit={} screen={} screen_rows_with_forged_path={} screen_rows_starting_with_tag={} screen_rows_with_tag={} screen_rows_marked={}",
        crate::syscall::console::MARK_PROCESS_OUTPUT.load(Ordering::SeqCst),
        ended,
        exit_str(exit),
        kind,
        forged.len(),
        tag_start,
        tag_any,
        marked
    );
}

/// A ring-3 process writes a forged prompt straight to the UART (COM1,
/// port 0x3F8) with `out`. With IOPL 0 the first `out` is a #GP and the
/// process is ended; with IOPL 3 (the old flags) the line reaches the
/// serial console unmarked.
fn port_forge() {
    let line = b"[SECURITY] Process 1 is requesting destructive syscall: DeleteFile path=\"/k5-forged-port\"\n";
    let mut code = vec![0x66, 0xBA, 0xF8, 0x03]; // mov dx, 0x3F8
    for &b in line.iter() {
        code.extend_from_slice(&[0xB0, b, 0xEE]); // mov al, b; out dx, al
    }
    code.extend_from_slice(&[0x31, 0xFF, 0xB8, 0x1E, 0x00, 0x00, 0x00, 0xCD, 0x80, 0xEB, 0xFE]);
    crate::serial_println!("");
    let (ended, exit) = match start_ring3("selftest-port", &code, &[]) {
        Ok(pid) => run_until_dead(pid, 3000),
        Err(_) => (false, None),
    };
    println!(
        "selftest port-forge: user_iopl3={} ended={} exit={}",
        crate::scheduler::USER_IOPL3.load(Ordering::SeqCst),
        ended,
        exit_str(exit)
    );
}
