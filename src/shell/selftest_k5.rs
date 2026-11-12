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
    let d = p.put(alloc::format!("{}{}", " ".repeat(100), prompt("d")).as_bytes());
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
