// fi1 kernel round 4 harness: run-time checks for the round-4 kernel fixes
// (vector state across process switches, the single-processor facts, guard
// pages below the static kernel stacks, ext2 write paths on crafted images,
// the DeleteFile prompt, ExecIfVersion for compiled-in names) and for fixes
// of earlier rounds that had no run-time test. Each `test-syscall <name>`
// runs a kernel self-test from src/shell/selftest_k4.rs.
//
//   node scripts/verify_kernel_k4.mjs
//
// FERRUMOS_SKIP_SELFTESTS=avx-state,... skips self-tests by name.
// FERRUMOS_SKIP_SMP2=1 skips the second boot with two CPUs.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const note = (text) => console.log(`NOTE\t${text}`);
const skip = new Set((process.env.FERRUMOS_SKIP_SELFTESTS || "").split(",").filter(Boolean));
const field = (text, name) => [...text.matchAll(new RegExp(`\\b${name}=([^\\s]+)`, "g"))].map((m) => m[1]).pop();
const line = (text, name) => (text.match(new RegExp(`selftest ${name}:.*`, "g")) || []).join(" | ");
const sub = (text, label) => (text.match(new RegExp(`selftest ext2-r4: ${label} (.*)`)) || [, ""])[1];

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

try {
  shell = await bootShell(repo, "kernel-k4-serial.log");
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);
  const boot = shell.serial();
  const smpBoot = (boot.match(/\[ INFO \] SMP: online_cpus.*/) || [""])[0];
  check("boot reports one CPU online and no application processor started",
    /online_cpus=1 application_processors_started=0/.test(smpBoot), smpBoot.trim());
  check("boot unmaps the guard page below all six static kernel stacks",
    /Guard pages below 6 of 6 static kernel stacks/.test(boot), (boot.match(/Guard pages below .*/) || ["no message"])[0].trim());

  let out = await run("smp-state");
  if (out) {
    const d = line(out, "smp-state");
    check("smp-state: no application processor entered the kernel", field(out, "application_processors_started") === "0", d);
    check("smp-state: the trampoline frame at 0x8000 is not a usable frame",
      field(out, "trampoline_region") !== "Some(Usable)" && field(out, "trampoline_region") !== "None");
  }

  out = await run("static-stack-guards");
  if (out) {
    const d = line(out, "static-stack-guards");
    for (const name of ["shell", "desktop", "dashboard", "idle", "return", "double_fault"]) {
      check(`the page below the ${name} stack is unmapped, the stack mapped`,
        field(out, `${name}_guard_mapped`) === "false" && field(out, `${name}_stack_mapped`) === "true",
        name === "shell" ? d : "");
    }
    check("test-syscall runs on the shell's static stack", field(out, "running_on_shell_stack") === "true");
  }

  out = await run("avx-state", 120);
  if (out) {
    const d = line(out, "avx-state");
    if (field(out, "skipped")) {
      check("the guest CPU exposes AVX and the kernel enables it (precondition)", false, d);
    } else {
      check("the kernel switches vector state with XSAVE when AVX is on",
        field(out, "xsave_switching") === "true" && Number(field(out, "area_size")) >= 832, d);
      check("a new process starts with zero YMM upper halves (no leak from the previous process)",
        field(out, "reader_ended") === "true" && field(out, "reader_nonzero_upper_halves") === "0");
      check("a process's YMM registers survive switches to another AVX process (writer A)",
        field(out, "writer_a_ended") === "true" && field(out, "writer_a_intact") === "16");
      check("a process's YMM registers survive switches to another AVX process (writer B)",
        field(out, "writer_b_ended") === "true" && field(out, "writer_b_intact") === "16");
    }
  }

  out = await run("ext2-r4", 180);
  if (out) {
    const d = line(out, "ext2-r4");
    check("ext2 control: create, remove, create reuses the freed inode",
      field(out, "control") === "true_inode_reused=true", d.slice(0, 300));
    const meta = sub(out, "metadata_marked_free");
    check("ext2: a bitmap marking metadata blocks free never gets them used as file data",
      /created=true files_read_back=true root_listed=true/.test(meta), meta);
    const reserved = sub(out, "reserved_inodes_marked_free");
    check("ext2: a bitmap marking reserved inodes free never hands one out",
      /create=ok/.test(reserved) && Number(field(reserved, "new_inode")) >= 11 && /root_still_dir=true/.test(reserved), reserved);
    const live = sub(out, "live_inode_marked_free");
    check("ext2: a bitmap marking a linked inode free never hands it to a second name",
      /g_shares_f_inode=false f_intact=true/.test(live), live);
    const link = sub(out, "hard_link");
    check("ext2: removing one of two hard links keeps the inode and data",
      /remove=ok h2_intact=true create=ok h2_intact_after_create=true links_now=1/.test(link), link);
    const dot = sub(out, "dot_remove");
    check("ext2: removing `dir/.` is refused and leaves no dangling entry",
      /remove=err/.test(dot) && /d_aliases_e=false/.test(dot), dot);
    const stale = sub(out, "stale_entry");
    check("ext2 (round 1 finding 10): a deleted entry with the same name is skipped; 256-byte names refused",
      /remove=ok live_entry_gone=true long_name_refused=true/.test(stale), stale);
    const bounds = sub(out, "write_inode_bounds");
    check("ext2: write_inode refuses inode 0 and numbers past the table",
      /zero_refused=true past_end_refused=true/.test(bounds), bounds);
  }

  out = await run("exec-embedded-version");
  if (out) {
    const d = line(out, "exec-embedded-version");
    check("ExecIfVersion of a compiled-in name ignores a VFS file written at that path",
      field(out, "vfs_file_written") === "true" && field(out, "embedded_check_passes") === "true", d);
    check("ExecIfVersion still refuses a changed VFS file (control)",
      field(out, "control_written") === "true" && field(out, "control_mismatch_refused") === "true");
  }

  out = await run("exit-closes-windows");
  if (out) {
    check("round 1 finding 8: a process that exits leaves no window",
      field(out, "windows_before") === "1" && field(out, "ended") === "true" && field(out, "windows_after") === "0",
      line(out, "exit-closes-windows"));
  }

  out = await run("reap-others");
  if (out) {
    check("round 1 finding 9: a deferred reap frees the other dead processes too",
      field(out, "both_dead") === "true" && field(out, "registered_before") === "true"
        && field(out, "a_freed") === "true" && field(out, "b_freed") === "true", line(out, "reap-others"));
  }

  out = await run("user-x87", 30);
  if (out) {
    const d = line(out, "user-x87");
    if (field(out, "cr0_ne") === "true") {
      check("an unmasked ring-3 x87 exception (#MF) ends the process, not the kernel", field(out, "ended") === "true", d);
    } else {
      note(`CR0.NE is clear: #MF is not raised (${d})`);
      check("an x87 exception with CR0.NE clear leaves the kernel running", field(out, "kernel_alive") === "true", d);
    }
  }

  if (!skip.has("delete-prompt")) {
    const from = shell.serial().length;
    out = await run("delete-prompt", 60);
    const tail = shell.serial().slice(from);
    const prompt = (tail.match(/\[SECURITY\] Process \d+ is requesting destructive syscall: .*/) || [""])[0];
    const expected = 'DeleteFile path="/tmp/k4-\\x1b[2J\\x0aAPPROVED"';
    check("the DeleteFile prompt names the path, escaped to printable ASCII", prompt.includes(expected), prompt.trim() || "no prompt");
    check("the unanswered prompt times out as a denial", field(out, "denied") === "true", line(out, "delete-prompt"));
  }

  check("no kernel fault during the self-tests",
    !/panicked at|DOUBLE FAULT|in ring 0|\[EXCEPTION\]/.test(shell.serial()));

  // Destructive, last: overflow the shell's static stack.
  if (!skip.has("static-stack-overflow")) {
    const from = shell.serial().length;
    await shell.type("test-syscall static-stack-overflow");
    await shell.key("ret");
    await sleep(10000);
    const tail = shell.serial().slice(from);
    check("an overflow of the shell's static stack stops the kernel with a double fault",
      /running_on_shell_stack=true/.test(tail) && /DOUBLE FAULT/.test(tail) && !/survived=true/.test(tail),
      (tail.match(/DOUBLE FAULT|survived=true|panicked at[^\n]*/) || ["no outcome"])[0]);
  }
} catch (error) {
  check("harness completed", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}

// Second boot with two CPUs: the MADT lists one application processor and
// the kernel still runs on one.
if (!process.env.FERRUMOS_SKIP_SMP2) {
  let shell2;
  try {
    shell2 = await bootShell(repo, "kernel-k4-smp2-serial.log", { extraArgs: ["-smp", "2"] });
    const boot = shell2.serial();
    const smpBoot = (boot.match(/\[ INFO \] SMP: online_cpus.*/) || [""])[0];
    check("with -smp 2 the MADT lists one application processor and none is started",
      /online_cpus=1 application_processors_started=0 madt_application_processors=1/.test(smpBoot), smpBoot.trim());
    const out = await shell2.command("test-syscall smp-state", 30);
    check("with -smp 2 the shell runs and no application processor entered the kernel",
      field(out, "application_processors_started") === "0", line(out, "smp-state"));
  } catch (error) {
    check("boot with -smp 2", false, String(error?.message || error).split("\n")[0]);
  } finally {
    shell2?.close();
  }
}
report("Kernel round-4 self-test verification", results);
