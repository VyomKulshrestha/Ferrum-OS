# Build the round-4 negative control: every round-4 self-test and harness
# stays in, the round-4 kernel fixes are held back. Run from the worktree
# root on the candidate commit; the result is committed, built by CI and then
# reverted (never left as the branch head).
#
# Held back: XSAVE switching (AVX stays enabled in XCR0, switches use FXSAVE
# as before), the static-stack guard pages, the ext2 allocator checks
# (metadata blocks, reserved inodes, linked inodes), remove's links_count and
# `dir/.` checks, the DeleteFile prompt's path, ExecIfVersion's compiled-in
# name rule, the system-wide window canvas budget and fallible canvas
# allocation.
# Not held back: the SMP boot report and assertion (a checked fact, no
# defect), write_inode's bounds (not reachable from a disk; holding it back
# stops the kernel inside ext2-r4), the Kexec mapping error (not run).
import sys

def patch(path, pairs):
    s = open(path, encoding='utf-8').read()
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f'{path}: expected one match for {old[:70]!r}, found {s.count(old)}')
        s = s.replace(old, new)
    open(path, 'w', encoding='utf-8', newline='').write(s)

patch('src/lib.rs', [(
    '        scheduler::enable_xsave(size);\n',
    '        let _ = size; // negctl: XSAVE switching held back\n')])

patch('src/memory/kstack.rs', [(
    '        let ok = x86_64::instructions::interrupts::without_interrupts(|| match mapper().unmap(page) {',
    '        let ok = false && x86_64::instructions::interrupts::without_interrupts(|| match mapper().unmap(page) {')])

patch('src/fs/ext2.rs', [
    ('                if self.is_metadata_block(&inner, phys_block) {',
     '                if false && self.is_metadata_block(&inner, phys_block) {'),
    ('                if inode_num < first_ino {',
     '                if false && inode_num < first_ino {'),
    ('                    Ok(inode) if inode.links_count == 0 => {',
     '                    Ok(_inode) => {'),
    ('        if name == "." || name == ".." {\n            return Err(String::from("invalid path"));',
     '        if false && (name == "." || name == "..") {\n            return Err(String::from("invalid path"));'),
    ('        if !is_dir && links > 1 {',
     '        if false && !is_dir && links > 1 {'),
    ('        if name.is_empty() || name == "." || name == ".." {',
     '        if name.is_empty() {'),
])

patch('src/syscall/mod.rs', [(
    '    match unsafe { fs::read_user_str(args[0], args[1]) } {\n        Some(path) =>',
    '    if true {\n        return alloc::string::String::from(name); // negctl\n    }\n    match unsafe { fs::read_user_str(args[0], args[1]) } {\n        Some(path) =>')])

patch('src/syscall/process.rs', [(
    '    if is_embedded_exec_path(path) {\n        return Ok(());',
    '    if false && is_embedded_exec_path(path) {\n        return Ok(());')])
patch('src/gui/app_window.rs', [(
    '    if total_canvas_bytes() + requested > MAX_TOTAL_CANVAS_BYTES {',
    '    if false && total_canvas_bytes() + requested > MAX_TOTAL_CANVAS_BYTES {')])

patch('src/gui/window.rs', [(
    '        pixels.try_reserve_exact(len).ok()?;',
    '        let _ = pixels.try_reserve_exact(0).ok()?; // negctl: infallible resize below')])
print('negctl applied')
