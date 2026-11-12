// fi2 kernel audit harness (workstream K2): run-time checks for the fixes of
// the areas no fi1 round examined (the virtio-gpu backing, kernel records the
// fs syscalls now refuse, audit log escaping, trimming and flushing, the
// privileged PackageInstall prompt, package names, titles in the serial log,
// an HDA codec response). Each `test-syscall <name>` runs a kernel self-test
// from src/shell/selftest_k6.rs.
//
//   node scripts/verify_kernel_k6.mjs
//
// Three boots: the first attaches a virtio-gpu-pci device; the second and
// third each run one self-test that stops the kernel when its fix is absent.
// FERRUMOS_SKIP_SELFTESTS=virtio-backing,... skips self-tests by name.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const note = (text) => console.log(`NOTE\t${text}`);
const skip = new Set((process.env.FERRUMOS_SKIP_SELFTESTS || "").split(",").filter(Boolean));
const field = (text, name) => [...(text || "").matchAll(new RegExp(`\\b${name}=([^\\s]+)`, "g"))].map((m) => m[1]).pop();
const line = (text, name) => ((text || "").match(new RegExp(`selftest ${name}:.*`, "g")) || []).join(" | ");
const faulted = (text) => /panicked at|DOUBLE FAULT|in ring 0|\[EXCEPTION\]/.test(text);

let shell;
async function run(name, seconds = 30) {
  if (skip.has(name)) {
    note(`${name} skipped (FERRUMOS_SKIP_SELFTESTS)`);
    return null;
  }
  try {
    return await shell.command(`test-syscall ${name}`, seconds);
  } catch (error) {
    check(`${name} returns to the shell`, false, String(error?.message || error).split("\n")[0]);
    throw error;
  }
}

// Serial output written while `fn` runs.
async function serialDuring(fn) {
  const from = shell.serial().length;
  const out = await fn();
  return { out, tail: shell.serial().slice(from) };
}

try {
  shell = await bootShell(repo, "kernel-k6-serial.log", { extraArgs: ["-device", "virtio-gpu-pci"] });
  check("boot reaches shell prompt (virtio-gpu-pci attached)", true, `boot_ms=${shell.bootMs}`);

  let out = await run("virtio-backing", 60);
  if (out) {
    const d = line(out, "virtio-backing");
    check("virtio-gpu: the device is found and initialised", field(out, "device") === "present", d);
    check("virtio-gpu: the backing holds a whole 1024x768 frame",
      Number(field(out, "backing_bytes")) >= Number(field(out, "frame_bytes")) && Number(field(out, "frame_bytes")) === 3145728);
    check("virtio-gpu: a present writes nothing past the backing",
      field(out, "present") === "ok" && field(out, "past_end_pattern_words") === "0", d);
  }

  out = await run("kernel-records", 60);
  if (out) {
    const d = line(out, "kernel-records");
    check("ring 3 with fs:write cannot write the account table", field(out, "write_accounts") === "permission_denied", d);
    check("ring 3 cannot write the account table through doubled slashes",
      field(out, "write_accounts_slashes") === "permission_denied");
    check("ring 3 with fs:write cannot write the audit log", field(out, "write_audit_log") === "permission_denied");
    check("ring 3 cannot delete the directory above the audit log",
      field(out, "delete_audit_dir") === "permission_denied" && field(out, "heliox_dir_exists") === "true");
    check("a write elsewhere still succeeds (control)", field(out, "control_write") === "ok");
  }

  if (!skip.has("audit-escape")) {
    const { out: o, tail } = await serialDuring(() => run("audit-escape", 60));
    const d = line(o, "audit-escape");
    check("a denied write's path with a line break stays one audit entry",
      field(o, "write_status") === "permission_denied" && field(o, "path_entry_found") === "true"
        && field(o, "path_entry_has_line_break") === "false", d);
    check("AuditWrite text with a line break stays one audit entry",
      field(o, "auditwrite_status") === "ok" && field(o, "auditwrite_entry_found") === "true"
        && field(o, "auditwrite_entry_has_line_break") === "false");
    const forged = tail.match(/^\[(1\] SecurityViolation: forged-path|2\] SecurityViolation: forged-write).*/m);
    check("no forged line starts a serial line", !forged, forged ? forged[0] : "none");
  }

  out = await run("audit-flush", 120);
  if (out) {
    const d = line(out, "audit-flush");
    check("audit log: once the file passes what the filesystem holds, a flush still writes the newest entry",
      field(out, "marker_on_disk") === "true" && field(out, "last_flush") === "ok", d);
    check("audit log: the file on the 12 KiB-file ext2 image reached its limit (precondition)",
      Number(field(out, "largest_file_bytes")) >= 10 * 1024);
  }

  if (!skip.has("pkg-confirm")) {
    const control = await serialDuring(() => run("pkg-confirm-unclaimed", 30));
    check("PackageInstall without the confirmation claim gets no prompt and fails at once (control)",
      field(control.out, "status") === "invalid_argument" && Number(field(control.out, "ms")) < 3000
        && !/requesting destructive syscall: PackageInstall/.test(control.tail), line(control.out, "pkg-confirm-unclaimed"));
    const claimed = await serialDuring(() => run("pkg-confirm", 30));
    const prompt = (claimed.tail.match(/\[SECURITY\] Process \d+ is requesting destructive syscall: PackageInstall.*/) || [""])[0];
    check("a self-confirmed privileged PackageInstall waits for the operator's prompt",
      prompt.includes('PackageInstall name="k6-none"'), prompt.trim() || "no prompt");
    check("the unanswered PackageInstall prompt times out as a denial",
      field(claimed.out, "status") === "permission_denied" && Number(field(claimed.out, "ms")) >= 4000,
      line(claimed.out, "pkg-confirm"));
  }

  out = await run("pkg-name", 30);
  if (out) {
    const d = line(out, "pkg-name");
    check("a package entry cannot replace a compiled-in program's capabilities",
      field(out, "register_accepted") === "false" && field(out, "capabilities_unchanged") === "true", d);
    check("package verification refuses a compiled-in program's name, not a free one",
      field(out, "name_taken") === "true" && field(out, "free_name_taken") === "false");
  }

  if (!skip.has("serial-titles")) {
    const { out: o, tail } = await serialDuring(() => run("serial-titles", 30));
    const forged = tail.match(/^\[SECURITY\] forged-title.*/m);
    check("a notification title cannot start a forged serial line",
      field(o, "post_status") === "ok" && !forged, `${line(o, "serial-titles")} forged=${forged ? forged[0] : "none"}`);
  }

  out = await run("query-names", 30);
  if (out) {
    const d = line(out, "query-names");
    check("SystemQuery's process list escapes task names (no forged entry)", field(out, "forged_entry") === "false", d);
    check("with escaping switched off the same name forges an entry (control on the same image)",
      field(out, "forged_entry_escaping_off") === "true");
  }

  out = await run("device-bounds", 30);
  if (out) {
    const d = line(out, "device-bounds");
    check("xhci: a controller asking for 1023 scratchpads is refused, 4 accepted (control)",
      field(out, "xhci_scratchpads_1023") === "refused" && field(out, "xhci_scratchpads_4") === "ok:4"
        && field(out, "old_array_bytes") === "8184", d);
    check("virtio-gpu: an offered queue of 32768 entries is cut to 256, 64 kept",
      field(out, "virtio_queue_32768") === "256" && field(out, "virtio_queue_64") === "64");
    check("virtio-gpu: a capability pointer past 0xEC is not followed (0x40 is)",
      field(out, "cap_ptr_0xf8_usable") === "false" && field(out, "cap_ptr_0x40_usable") === "true"
        && field(out, "old_ptr_plus_16_fits_u8") === "false");
    check("virtio-gpu: a capability naming BAR 61 is refused, BAR 5 maps to 0x24",
      field(out, "bar_61_offset") === "None" && field(out, "bar_5_offset") === "Some(36)"
        && field(out, "old_bar_61_fits_u8") === "false");
  }

  check("no kernel fault during the self-tests", !faulted(shell.serial()));
} catch (error) {
  check("harness completed", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}

// One boot each for the self-tests that stop the kernel without their fix.
for (const [name, log, judge] of [
  ["audit-trim-utf8", "kernel-k6-trim-serial.log", (out, serial) => {
    check("audit log: trimming at a byte inside a multi-byte character leaves the kernel running",
      field(out, "survived") === "true" && !faulted(serial), line(out, "audit-trim-utf8") || (serial.match(/panicked at[^\n]*/) || ["no outcome"])[0]);
    check("audit log: the trimmed log keeps the newest bytes, within the cap",
      field(out, "ends_with_b") === "true" && Number(field(out, "kept_bytes")) <= 131072);
  }],
  ["hda-subnodes", "kernel-k6-hda-serial.log", (out, serial) => {
    check("hda: a SUBNODE_COUNT response past node 255 leaves the kernel running",
      field(out, "survived") === "true" && !faulted(serial), line(out, "hda-subnodes") || (serial.match(/panicked at[^\n]*/) || ["no outcome"])[0]);
    check("hda: the node range is cut at 255", field(out, "end") === "255" && field(out, "nodes") === "15");
  }],
]) {
  if (skip.has(name)) {
    note(`${name} skipped (FERRUMOS_SKIP_SELFTESTS)`);
    continue;
  }
  let s;
  try {
    s = await bootShell(repo, log);
    let out = "";
    try {
      out = await s.command(`test-syscall ${name}`, 30);
    } catch (error) {
      out = "";
    }
    judge(out, s.serial());
  } catch (error) {
    check(`${name} boot`, false, String(error?.message || error).split("\n")[0]);
  } finally {
    s?.close();
  }
}

report("Kernel audit (fi2 K2) self-test verification", results);
