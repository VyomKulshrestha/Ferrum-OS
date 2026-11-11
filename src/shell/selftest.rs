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
