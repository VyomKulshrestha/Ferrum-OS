// fi1 kernel round 2 harness: run-time checks for the round-2 kernel fixes
// (memory protection, quotas and limits, sockets, services, task names, ext2
// mount validation, ring-0 faults). Each `test-syscall <name>` runs a kernel
// self-test from src/shell/selftest_k2.rs.
//
//   node scripts/verify_kernel_selftests_k2.mjs
//
// FERRUMOS_SKIP_SELFTESTS=ext2-shift,... skips self-tests by name (on an image
// where one of them halts the kernel, to see the later ones).
// FERRUMOS_SKIP_SELFTESTS=ring0-fault keeps the destructive last test out.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const skip = new Set((process.env.FERRUMOS_SKIP_SELFTESTS || "").split(",").filter(Boolean));
const field = (text, name) => (text.match(new RegExp(`\\b${name}=([^\\s]+)`)) || [])[1];
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
    // No prompt came back: the kernel stopped (or hung) in this self-test.
    check(`${name} returns to the shell`, false, String(error?.message || error).split("\n")[0]);
    throw error;
  }
}

try {
  shell = await bootShell(repo, "kernel-selftests-k2-serial.log");
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);

  let out = await run("nx-flags");
  if (out) {
    const d = line(out, "nx-flags");
    check("EFER.NXE is on", field(out, "nxe") === "true", d);
    check("user data pages are not executable", field(out, "data_nx") === "true");
    check("the user stack is not executable", field(out, "stack_nx") === "true");
    check("user code pages stay executable", field(out, "code_nx") === "false");
    check("kernel heap pages are not executable", field(out, "heap_nx") === "true");
    check("the physical-memory alias is not executable", field(out, "physmap_nx") === "true");
    check("no kernel P4 entry besides the user slot is user-accessible", field(out, "kernel_user_p4_entries") === "none");
  }

  out = await run("quota-exempt");
  if (out) {
    check("a process without the exemption cannot create an unlimited child by program name",
      field(out, "unprivileged_child_pages") === "2048", line(out, "quota-exempt"));
    check("the kernel still launches the daemon unlimited", field(out, "kernel_child_pages") === "unlimited");
  }

  out = await run("process-limit");
  if (out) {
    check("one process can have at most 16 live children", field(out, "children_created") === "16", line(out, "process-limit"));
  }

  out = await run("mmap-quota", 60);
  if (out) {
    const frames = Number(field(out, "frames_after_fault"));
    check("mmap demand paging stays within the page quota (4)", Number.isFinite(frames) && frames <= 4, line(out, "mmap-quota"));
    check("the faulting page itself is still mapped", field(out, "first_fault_ok") === "true");
  }

  out = await run("socket-limits");
  if (out) {
    const d = line(out, "socket-limits");
    check("one process holds at most 16 sockets", field(out, "created_for_one_process") === "16", d);
    check("another process can still create a socket", field(out, "other_process_can_create") === "true");
    check("a port above 65535 is refused, not truncated", field(out, "port_above_65535_bound") === "false");
    check("port 0 is refused for connect", field(out, "port_zero_connected") === "false");
    check("the first listener binds", field(out, "first_bind") === "true");
    check("another process cannot bind a port in use", field(out, "other_process_bound_same_port") === "false");
  }

  out = await run("rx-header");
  if (out) {
    const d = line(out, "rx-header");
    check("a 64-byte frame is delivered", field(out, "good_64") === "deliver60", d);
    check("an oversized receive length is never delivered", field(out, "oversize_60004") === "skip");
    check("a header without ROK resets the receiver", field(out, "no_rok") === "reset");
    check("a header with an error bit resets the receiver", field(out, "crc_error") === "reset");
    check("a good header for a runt frame is skipped, not treated as lost ring position", field(out, "runt_14") === "skip");
  }

  out = await run("service-lifecycle");
  if (out) {
    check("a process without capabilities cannot stop kernel.security", field(out, "no_cap_stop_allowed") === "false", line(out, "service-lifecycle"));
    check("cap:system:all still can", field(out, "root_restart_allowed") === "true");
  }

  out = await run("task-name");
  if (out) {
    check("a task name cannot carry a JSON quote", field(out, "stored_has_quote") === "false", line(out, "task-name"));
  }

  out = await run("ext2-valid");
  if (out) check("a well-formed ext2 image mounts", field(out, "rejected") === "false" && field(out, "inode_reads") === "ok,ok,ok", line(out, "ext2-valid"));
  for (const [name, what] of [
    ["ext2-shift", "log_block_size 40"],
    ["ext2-groups", "inodes_count 2^32-1 with one inode per group"],
    ["ext2-inode-size", "inode size 200"],
    ["ext2-bpg", "blocks_per_group 0"],
    ["ext2-gdt", "inode table at block 2^32-1"],
  ]) {
    out = await run(name);
    if (out) check(`a crafted superblock (${what}) is rejected at mount`, field(out, "rejected") === "true", line(out, name));
  }

  out = await run("cpu-quota", 60);
  if (out) {
    const d = line(out, "cpu-quota");
    check("a ring-3 task spinning without syscalls is ended by the CPU quota", field(out, "ended_by_kernel") === "true" && field(out, "exit_code") === "140", d);
  }

  out = await run("perf");
  if (out) console.log(`INFO\t${line(out, "perf")}`);

  check("no kernel panic or fault before the ring-0 test", !/panicked at|PAGE FAULT|Page Fault|General Protection|DOUBLE FAULT/.test(shell.serial()));

  // Destructive, last: a ring-0 fault with a process current must stop the
  // kernel, not kill that process and continue.
  if (!skip.has("ring0-fault")) {
    const from = shell.serial().length;
    await shell.type("test-syscall ring0-fault");
    await shell.key("ret");
    await sleep(8000);
    const tail = shell.serial().slice(from);
    check("a ring-0 fault is not blamed on the current process", !/Userspace process \d+ caused/.test(tail), (tail.match(/\[KERNEL\][^\n]*/) || [""])[0].trim());
    check("a ring-0 fault stops the kernel", /in ring 0/.test(tail) && !/survived=true/.test(tail) && !/FerrumOS:~\$/.test(tail.slice(tail.indexOf("ring0-fault: reading"))));
  }
} catch (error) {
  check("verification", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}
report("Kernel round-2 self-test verification", results);
