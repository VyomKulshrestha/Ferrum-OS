// fi1 kernel round 3 harness: run-time checks for the round-3 kernel fixes
// (interrupt and syscall entry state, interrupt-context locking, kernel and
// user stack guards, writes to read-only user memory, IPC mailbox ownership
// and quotas, RamFS limits, ext2 on crafted images). Each `test-syscall
// <name>` runs a kernel self-test from src/shell/selftest_k3.rs.
//
//   node scripts/verify_kernel_k3.mjs
//
// FERRUMOS_SKIP_SELFTESTS=ext2-r3,... skips self-tests by name (on an image
// where one of them stops the kernel, to see the later ones).
// FERRUMOS_SKIP_SELFTESTS=kstack-overflow keeps the destructive last test out.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const skip = new Set((process.env.FERRUMOS_SKIP_SELFTESTS || "").split(",").filter(Boolean));
// The last value printed for `name` (ext2-r3 prints "<case>=starting" first).
const field = (text, name) => [...text.matchAll(new RegExp(`\\b${name}=([^\\s]+)`, "g"))].map((m) => m[1]).pop();
const line = (text, name) => (text.match(new RegExp(`selftest ${name}:.*`, "g")) || []).join(" | ");

let shell;
async function run(name, seconds = 30) {
  if (skip.has(name)) {
    console.log(`NOTE\t${name} skipped (FERRUMOS_SKIP_SELFTESTS)`);
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
  shell = await bootShell(repo, "kernel-k3-serial.log");
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);

  let out = await run("boot-nx");
  if (out) {
    const d = line(out, "boot-nx");
    check("the bootloader's stack is not executable", field(out, "boot_stack_nx") === "true", d);
    check("the boot-information page is not executable", field(out, "boot_info_nx") === "true");
    check("the kernel image stays executable", field(out, "kernel_code_p4_nx") === "false");
  }

  out = await run("kstack-guard");
  if (out) {
    const d = line(out, "kstack-guard");
    check("a process kernel stack is mapped", field(out, "top_mapped") === "true", d);
    check("the page below a process kernel stack is unmapped (guard)", field(out, "below_stack_mapped") === "false");
    check("a process kernel stack is not executable", field(out, "stack_nx") === "true");
    check("a freed kernel stack is unmapped and its slot returned",
      field(out, "freed_unmapped") === "true" && field(out, "live_after") === field(out, "live_before"));
  }

  out = await run("df-entry");
  if (out) {
    const d = line(out, "df-entry");
    check("syscalls from a ring-3 task with DF set run kernel code with DF clear", field(out, "syscall_entries_with_df") === "0", d);
    check("timer interrupts of a ring-3 task with DF set run kernel code with DF clear", field(out, "timer_entries_with_df") === "0");
    check("the kernel's memcpy copies correctly during those syscalls",
      Number(field(out, "copy_probes")) > 0 && field(out, "bad_copies") === "0");
  }

  out = await run("irq-alloc", 60);
  if (out) {
    check("the timer can wake tasks while kernel code allocates with interrupts on",
      field(out, "survived") === "true" && Number(field(out, "sleeper_wakes")) > 100, line(out, "irq-alloc"));
  }

  if (!skip.has("kbd-lock")) {
    const from = shell.serial().length;
    await shell.type("test-syscall kbd-lock");
    await shell.key("ret");
    try {
      await shell.waitFor("polling for 6 s", 20, from);
      for (let i = 0; i < 40; i++) await shell.key("k");
      const tail = await shell.waitFor(/selftest kbd-lock: survived[^\n]*\n[\s\S]*FerrumOS:~\$/, 40, from);
      check("keys typed while the shell polls its queues do not hang the kernel",
        field(tail, "survived") === "true" && Number(field(tail, "keys")) >= 10, line(tail, "kbd-lock"));
    } catch (error) {
      check("kbd-lock returns to the shell", false, String(error?.message || error).split("\n")[0]);
      throw error;
    }
  }

  out = await run("user-stack", 60);
  if (out) {
    const d = line(out, "user-stack");
    check("no mmap region can end at the user stack", field(out, "mmap_reaches_stack") === "false", d);
    check("no ELF segment can end at the user stack", field(out, "segment_below_stack_accepted") === "false");
    check("a user stack overflow ends the process (killed, 137) and the kernel runs on",
      field(out, "overflow_ended") === "true" && field(out, "overflow_exit") === "137");
  }

  out = await run("ipc-mailbox");
  if (out) {
    const d = line(out, "ipc-mailbox");
    check("the first process registered under a name owns its mailbox", field(out, "owner_first") === "first", d);
    check("a second instance does not take the mailbox while the first lives", field(out, "owner_with_two") === "first");
    check("the mailbox does not pass to the second instance when the first dies", field(out, "owner_after_first_died") === "none");
    check("a message queued for the first instance never reaches the second", field(out, "second_got_firsts_message") === "false");
    check("a process registered after the owner died owns the mailbox", field(out, "owner_new") === "third");
    check("unflagged senders get at most 12 of 16 slots", field(out, "unflagged_accepted") === "12");
    check("an operator message is accepted when unflagged senders filled the mailbox", field(out, "operator_accepted_when_full") === "true");
    check("every accepted message is delivered to the owner", field(out, "delivered") === "13");
  }

  out = await run("ramfs-limits", 60);
  if (out) {
    const d = line(out, "ramfs-limits");
    check("RamFS refuses writes past its byte budget",
      field(out, "refused_at") !== "none" && Number(field(out, "files_1mib_written")) <= 4, d);
    check("RamFS refuses directories deeper than 32", field(out, "deepest_dir") === "32");
    check("a deep RamFS tree is removed whole", field(out, "tree_removed") === "true");
    check("a file name with a newline is refused", field(out, "newline_name_created") === "false");
  }

  out = await run("ext2-r3", 180);
  if (out) {
    const d = line(out, "ext2-r3");
    const err = (name) => (field(out, name) || "").startsWith("err");
    check("ext2 control: create, read back and remove on a well-formed image", field(out, "control_create_read_remove") === "true", d);
    check("a 2^64-1 byte ext2 file is refused, not allocated", err("huge_file_read"));
    check("a 4 GiB ext2 directory is refused, not allocated", err("huge_dir_list"));
    check("a create next to an entry with rec_len 0xFFFF and name_len 255 is refused", err("bad_reclen_create"));
    check("a remove merging an entry with rec_len 0xFFFF is refused", err("bad_reclen_remove"));
    check("a directory whose indirect blocks loop is walked only as far as its size",
      field(out, "looped_dir_create") === "ok" && Number(field(out, "looped_dir_ms")) < 5000);
    check("remove of a path with an empty last component is refused", err("empty_name_remove"));
    check("no name is left pointing at a freed inode", field(out, "f_now_aliases_new_file") === "false");
    check("free counts above the totals are rejected at mount", (field(out, "free_count_mount") || "").startsWith("rejected"));
    check("a superblock free count of 0 does not underflow", field(out, "zero_sb_free_create") === "ok");
    check("a remove whose block free fails still removes the name and changes the parent's version",
      field(out, "entry_gone") === "true" && field(out, "parent_version_changed") === "true");
  }

  out = await run("user-exceptions", 90);
  if (out) {
    for (const name of ["divide", "trap_flag", "icebp", "noncanonical_stack", "simd"]) {
      check(`a ring-3 ${name.replace("_", " ")} exception ends the process, not the kernel`,
        field(out, `${name}_ended`) === "true", `exit=${field(out, `${name}_exit`)}`);
    }
    check("the kernel runs on after the ring-3 exceptions", field(out, "kernel_alive") === "true");
  }

  out = await run("user-write-ro", 60);
  if (out) {
    check("a syscall told to write into the caller's read-only text is refused (kernel runs on)",
      field(out, "refused") === "true", line(out, "user-write-ro"));
  }

  check("no kernel panic or fault before the destructive test",
    !/panicked at|DOUBLE FAULT|in ring 0|\[EXCEPTION\]/.test(shell.serial()));

  // Destructive, last: overflow a process's kernel stack.
  if (!skip.has("kstack-overflow")) {
    const from = shell.serial().length;
    await shell.type("test-syscall kstack-overflow");
    await shell.key("ret");
    await sleep(10000);
    const tail = shell.serial().slice(from);
    check("a kernel stack overflow hits the guard and stops the kernel (double fault)",
      /DOUBLE FAULT/.test(tail) && !/survived=true/.test(tail), (tail.match(/DOUBLE FAULT|survived=true|returned=true/) || ["no outcome"])[0]);
  }
} catch (error) {
  check("verification", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}
report("Kernel round-3 self-test verification", results);
