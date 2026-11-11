// fi1 kernel harness: run-time checks for kernel fixes that no shipped ring-3
// program exercises. Each `test-syscall <name>` runs a kernel self-test
// (src/shell/selftest.rs) against the same function a ring-3 caller reaches.
// It also checks that the debug shell's `syscall <pid> ...` command is not
// available to a guest session (it runs a syscall with any pid's authority).
//
//   node scripts/verify_kernel_selftests.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const field = (text, name) => (text.match(new RegExp(`${name}=([^\\s]+)`)) || [])[1];

let shell;
try {
  shell = await bootShell(repo, "kernel-selftests-serial.log");
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);

  // PR 1 fix 6: kexec copies into one mapped 4 KiB page.
  let out = await shell.command("test-syscall kexec-bound");
  check("kexec rejects an image larger than its one mapped page", field(out, "oversize_rejected") === "true", out.trim().split("\n").find((l) => l.includes("selftest")) || "");
  check("kexec still accepts a one-page image", field(out, "page_accepted") === "true");

  // PR 1 fix 4: at most four windows per process.
  out = await shell.command("test-syscall window-cap");
  check("CreateWindow stops at 4 windows for one process", field(out, "created") === "4" && field(out, "refused") === "2", (out.match(/selftest window-cap:.*/) || [""])[0]);
  check("closing the owner's windows frees them all", field(out, "after_close") === "0");

  // PR 1 fix 5: a capture whose owner is gone is released for the next recorder.
  out = await shell.command("test-syscall dead-recorder");
  check("a dead recorder's capture session is released", field(out, "stale_session_released") === "true", (out.match(/selftest dead-recorder:.*/) || [""])[0]);

  // Second audit: ELF loader.
  out = await shell.command("test-syscall elf-bounds", 20);
  check("a non-canonical PT_LOAD address is refused without a kernel panic", field(out, "noncanonical_rejected") === "true", (out.match(/selftest elf-bounds: noncanonical.*/) || ["no result line (kernel halted?)"])[0]);
  check("an unaligned one-page segment maps exactly one page", field(out, "unaligned_tail_pages") === "1", (out.match(/selftest elf-bounds: unaligned.*/) || [""])[0]);

  // Second audit: caller-sized kernel buffers fail cleanly instead of aborting.
  out = await shell.command("test-syscall heap-bounds", 20);
  check("a buffer larger than the kernel heap is refused, not fatal", field(out, "oversize_refused") === "true", (out.match(/selftest heap-bounds:.*/) || ["no result line (kernel halted?)"])[0]);
  check("ordinary buffers still allocate", field(out, "small_ok") === "true");

  // Second audit: Exec path that slipped past the package signature gate.
  out = await shell.command("test-syscall exec-path");
  check("Exec refuses /disk//pkgs-available/<name>/bin (package gate bypass)", field(out, "double_slash_denied") === "true", (out.match(/selftest exec-path:.*/) || [""])[0]);
  check("Exec refuses dot components and the package repository", field(out, "dotdot_denied") === "true" && field(out, "repo_denied") === "true");
  check("Exec still accepts a plain absolute path", field(out, "plain_allowed") === "true");

  // Second audit: the debug shell's `syscall` command and session profiles.
  const users = await shell.command("users");
  const initPid = (users.match(/^\s*(\d+)\s+\S+\s+\S+\s+\S+\s+init\s*$/m) || [])[1] || "101";
  await shell.command("session guest");
  out = await shell.command(`syscall ${initPid} 5 4`);
  check(`a guest session cannot run a syscall as init (pid ${initPid})`, !/syscall result/.test(out) && /permission denied/.test(out), out.trim().split("\n").slice(-2, -1)[0] || "");
  await shell.command("session root");
  out = await shell.command(`syscall ${initPid} 5 4`);
  check("the root session still can", /syscall result: Ok value=1/.test(out));

  check("no kernel panic or fault", !/panicked at|PAGE FAULT|Page Fault|General Protection|DOUBLE FAULT/.test(shell.serial()));
} catch (error) {
  check("verification", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}
report("Kernel self-test verification", results);
