# Build the fi2 kernel-audit negative control: every self-test in
# src/shell/selftest_k6.rs and the harness scripts/verify_kernel_k6.mjs stay
# in, the audit's kernel fixes are held back. Run from the worktree root on
# the candidate commit; the result is committed, built by CI and then
# reverted (never left as the branch head).
#
# Held back: the virtio-gpu backing size and its bound in present(), the HDA
# SUBNODE_COUNT range, the kernel-record refusal in the fs syscalls, audit
# message escaping, line-boundary trimming of the flushed log, the flush
# retry with a shorter tail, the operator prompt for a self-confirmed
# PackageInstall, the package-name rule, escaped titles in serial lines.
# Not held back (no run-time test reaches them): the virtio-gpu queue-size cap
# and capability-offset bounds, the xHCI scratchpad bound.
import sys


def patch(path, pairs):
    s = open(path, encoding='utf-8').read()
    for old, new, count in pairs:
        if s.count(old) != count:
            sys.exit(f'{path}: expected {count} match(es) for {old[:70]!r}, found {s.count(old)}')
        s = s.replace(old, new)
    open(path, 'w', encoding='utf-8', newline='').write(s)


patch('src/devices/virtio_gpu.rs', [
    ('        let backing_pages = BACKING_BYTES / 4096;\n',
     '        let backing_pages = 256; // negctl: the 1 MiB backing\n', 1),
    ('    if byte_len > device.backing_len || pixels.len() < pixel_count {',
     '    if false && (byte_len > device.backing_len || pixels.len() < pixel_count) {', 1),
])

patch('src/devices/hda.rs', [
    ('    start..start.saturating_add(count)\n', '    start..start + count // negctl\n', 1),
])

patch('src/syscall/fs.rs', [
    ('        || refuse_kernel_record(&path, false)\n',
     '        || (false && refuse_kernel_record(&path, false))\n', 2),
    ('|| refuse_kernel_record(&path, true) {',
     '|| (false && refuse_kernel_record(&path, true)) {', 1),
])

patch('src/logging/audit.rs', [
    ('        let message = escape_controls(message);\n',
     '        let message = String::from(message); // negctl\n', 1),
    ('    if let Err(first) = crate::fs::create_file(log_path, &content) {\n',
     '    crate::fs::create_file(log_path, &content)?; // negctl\n'
     '    if let Err(first) = Ok::<(), String>(()) {\n', 1),
    ('    let cut = content.len() - max;\n',
     '    if true {\n'
     '        // negctl: the old byte-offset cut\n'
     '        let overflow = content.len() - max;\n'
     "        return if let Some(pos) = content[overflow..].find('\\n') {\n"
     '            content[overflow + pos + 1..].to_string()\n'
     '        } else {\n'
     '            content[content.len() - max..].to_string()\n'
     '        };\n'
     '    }\n'
     '    let cut = content.len() - max;\n', 1),
])

patch('src/syscall/mod.rs', [
    ('        && crate::security::has_capability(&held_capabilities, "pkg:request");\n',
     '        && false // negctl\n'
     '        && crate::security::has_capability(&held_capabilities, "pkg:request");\n', 1),
])

patch('src/userspace/mod.rs', [
    ('        if existing.entry != entry {\n', '        if false && existing.entry != entry {\n', 1),
])
patch('src/pkg/mod.rs', [
    ('    crate::userspace::program_entry(name).is_some_and(|entry| entry != bin_path(name))\n',
     '    false && crate::userspace::program_entry(name).is_some_and(|entry| entry != bin_path(name))\n', 1),
])

patch('src/notification/mod.rs', [
    ('        crate::syscall::escape_printable(title)\n', '        title\n', 1),
])
print('negctl applied')
