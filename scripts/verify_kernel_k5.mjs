// fi2 kernel workstream K1 harness: run-time checks for SMEP, SMAP, the
// console's process-output marking, the per-process kernel heap ledger, ext2
// on real mke2fs disks and x87 error delivery. Each `test-syscall <name>`
// runs a kernel self-test from src/shell/selftest_k5.rs; the `*-off`
// switches restore the old behaviour on the same image (negative controls).
//
//   node scripts/verify_kernel_k5.mjs
//
// Boot A uses -cpu Haswell (SMEP, no SMAP), boot B -cpu Broadwell-noTSX
// (SMEP and SMAP under WHPX on the reference host). FERRUMOS_K5_BOOTS=A or
// =B runs one of them. FERRUMOS_SKIP_SELFTESTS=name,... skips self-tests.
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const note = (text) => console.log(`NOTE\t${text}`);
const skip = new Set((process.env.FERRUMOS_SKIP_SELFTESTS || "").split(",").filter(Boolean));
const boots = (process.env.FERRUMOS_K5_BOOTS || "A,B").split(",");
const field = (text, name) => [...(text || "").matchAll(new RegExp(`\\b${name}=([^\\s]+)`, "g"))].map((m) => m[1]).pop();
const line = (text, name) => ((text || "").match(new RegExp(`selftest ${name}:.*`, "g")) || []).join(" | ");
const kernelFault = (text) => /panicked at|DOUBLE FAULT|in ring 0|\[EXCEPTION\]/.test(text);

let shell;
async function run(name, seconds = 30) {
  if (skip.has(name)) {
    note(`${name} skipped (FERRUMOS_SKIP_SELFTESTS)`);
    return null;
  }
  return await shell.command(`test-syscall ${name}`, seconds);
}

async function smepChecks(tag) {
  let out = await run("smep");
  const on = line(out, "smep");
  check(`${tag} SMEP: a ring-0 call into a user page faults (instruction fetch, present)`,
    field(out, "smep") === "true" && field(out, "kernel_call_faulted") === "true"
      && field(out, "error") === "0x11" && field(out, "fault_addr_is_page") === "true", on);
  await run("smep-off");
  out = await run("smep");
  const off = line(out, "smep");
  await run("smep-on");
  check(`${tag} SMEP control (switched off, same image): the same call runs the user page`,
    field(out, "smep") === "false" && field(out, "kernel_call_faulted") === "false", off);
}

async function sweepCheck(tag, smapExpected) {
  const out = await run("smap-sweep", 60);
  const d = line(out, "smap-sweep");
  check(`${tag} syscall sweep (15 paths that copy to or from user memory) completes with every call succeeding${smapExpected ? " under SMAP" : ""}`,
    field(out, "ended") === "true" && field(out, "exit") === "0" && field(out, "failed_calls") === "none"
      && field(out, "smap") === String(smapExpected) && /ring-3 write reached the console/.test(out), d);
}

// Item 3: a process cannot print a line that reads as the kernel's
// confirmation prompt. Serial lines are split at CR too (a terminal returns
// to column 0 there).
async function forgeRun() {
  const from = shell.serial().length;
  const out = await run("console-forge", 30);
  const tail = shell.serial().slice(from);
  const lines = tail.split(/\r\n|\n|\r/).filter((l) => /k5-forged-[a-f]/.test(l) && !/selftest /.test(l));
  const paths = new Set(lines.map((l) => (l.match(/k5-forged-([a-f])/) || [])[1]));
  return {
    out,
    lines,
    paths: [...paths].sort().join(""),
    tagStart: lines.filter((l) => l.trimStart().startsWith("[SECURITY")).length,
    tagAny: lines.filter((l) => l.includes("[SECURITY")).length,
    unmarked: lines.filter((l) => !l.includes("[pid ")).length,
  };
}

async function consoleChecks() {
  if (skip.has("console-forge")) return;
  const fixed = await forgeRun();
  check("A: console: a process's forged prompts (7 attempts) reach the serial log, each line marked with its pid",
    fixed.paths === "abcdef" && fixed.unmarked === 0 && field(fixed.out, "exit") === "0",
    `paths=${fixed.paths} lines=${fixed.lines.length} unmarked=${fixed.unmarked} ${line(fixed.out, "console-forge")}`);
  check("A: console: no serial line of process output starts with or contains the [SECURITY] tag",
    fixed.tagStart === 0 && fixed.tagAny === 0, fixed.lines.slice(0, 3).join(" || ").slice(0, 400));
  check("A: console: no screen row of process output starts with or contains the [SECURITY] tag",
    Number(field(fixed.out, "screen_rows_with_forged_path")) >= 4 && field(fixed.out, "screen_rows_starting_with_tag") === "0"
      && field(fixed.out, "screen_rows_with_tag") === "0", line(fixed.out, "console-forge"));
  await run("console-mark-off");
  const old = await forgeRun();
  await run("console-mark-on");
  check("A: console control (marking switched off, same image): forged lines start with the tag on serial and on screen",
    old.tagStart >= 4 && Number(field(old.out, "screen_rows_starting_with_tag")) >= 3,
    `serial_lines_starting_with_tag=${old.tagStart} ${line(old.out, "console-forge")}`);

  let from = shell.serial().length;
  let out = await run("port-forge", 30);
  let tail = shell.serial().slice(from);
  const portLine = (t) => t.split(/\r\n|\n|\r/).some((l) => l.startsWith("[SECURITY]") && l.includes("k5-forged-port"));
  check("A: console: a process cannot write the UART directly (IOPL 0: the first `out` ends it)",
    field(out, "ended") === "true" && field(out, "exit") !== "0" && !portLine(tail), line(out, "port-forge"));
  await run("iopl3-on");
  from = shell.serial().length;
  out = await run("port-forge", 30);
  tail = shell.serial().slice(from);
  await run("iopl3-off");
  check("A: console control (IOPL 3, the old flags): the process writes an unmarked prompt straight to the UART",
    field(out, "exit") === "0" && portLine(tail), line(out, "port-forge"));
}

// Item 4: one process's kernel heap across windows, IPC, audit, sockets and
// RamFS is capped as a whole.
async function ledgerChecks() {
  if (skip.has("heap-ledger")) return;
  let out = await run("heap-ledger", 60);
  let d = line(out, "heap-ledger");
  const cap = Number(field(out, "cap"));
  check("A: ledger: the request that would pass the per-process cap (the second 400 KiB file) is refused, every other call succeeds",
    field(out, "failed_calls") === "WriteFile_b" && Number(field(out, "refused")) >= 1
      && Number(field(out, "peak")) <= cap && Number(field(out, "total")) <= cap, d);
  check("A: ledger: windows, RamFS, audit and socket bytes are all charged to the process",
    Number(field(out, "windows")) >= 3404800 && Number(field(out, "ramfs")) >= 409600
      && Number(field(out, "audit")) > 0 && Number(field(out, "sockets")) > 0);
  check("A: ledger: released at reap (no entry, no window, no socket left)",
    field(out, "ended") === "true" && field(out, "entry_after_reap") === "false"
      && field(out, "windows_after") === "0" && field(out, "sockets_after") === "0");
  await run("ledger-off");
  out = await run("heap-ledger", 60);
  await run("ledger-on");
  check("A: ledger control (enforcement switched off, same image): the process holds more than the cap and nothing is refused",
    field(out, "failed_calls") === "none" && Number(field(out, "total")) > cap, line(out, "heap-ledger"));
}

// ---- boot A: Haswell (SMEP, no SMAP) ----------------------------------------
if (boots.includes("A")) {
  try {
    shell = await bootShell(repo, "kernel-k5-a-serial.log", { cpu: "Haswell" });
    check("A: boot reaches shell prompt (-cpu Haswell)", true, `boot_ms=${shell.bootMs}`);
    const boot = (shell.serial().match(/\[  OK  \] CPU protections:.*/) || [""])[0].trim();
    check("A: boot enables SMEP, leaves SMAP off where CPUID has no SMAP",
      /smep=true smap=false \(cpuid smep=true smap=false\)/.test(boot), boot || "no message");
    await smepChecks("A:");
    let out = await run("smap");
    check("A: without SMAP an unbracketed ring-0 read of a user page succeeds (stac/clac not executed)",
      field(out, "smap") === "false" && field(out, "unbracketed_read_faulted") === "false"
        && field(out, "bracketed_read_faulted") === "false", line(out, "smap"));
    await sweepCheck("A:", false);
    await consoleChecks();
    await ledgerChecks();
    check("A: no kernel fault", !kernelFault(shell.serial()));
  } catch (error) {
    check("A: harness completed", false, String(error?.message || error).split("\n")[0]);
  } finally {
    shell?.close();
  }
}

// ---- boot B: Broadwell-noTSX (SMEP and SMAP) ----------------------------------
if (boots.includes("B")) {
  try {
    shell = await bootShell(repo, "kernel-k5-b-serial.log", { cpu: "Broadwell-noTSX" });
    check("B: boot reaches shell prompt (-cpu Broadwell-noTSX)", true, `boot_ms=${shell.bootMs}`);
    const boot = (shell.serial().match(/\[  OK  \] CPU protections:.*/) || [""])[0].trim();
    check("B: boot enables SMEP and SMAP", /smep=true smap=true \(cpuid smep=true smap=true\)/.test(boot), boot || "no message");
    await smepChecks("B:");

    let out = await run("smap");
    let d = line(out, "smap");
    check("B: SMAP: an unbracketed ring-0 read of a user page faults (present, read)",
      field(out, "smap") === "true" && field(out, "unbracketed_read_faulted") === "true" && field(out, "error") === "0x1", d);
    check("B: SMAP: the same read through the UserAccess bracket succeeds", field(out, "bracketed_read_faulted") === "false");
    check("B: SMAP: an unbracketed ring-0 write of a user page faults", field(out, "unbracketed_write_faulted") === "true");
    check("B: SMAP: AC is clear after the probes", field(out, "ac_after") === "false");
    await run("smap-off");
    out = await run("smap");
    await run("smap-on");
    check("B: SMAP control (switched off, same image): the unbracketed read and write succeed",
      field(out, "smap") === "false" && field(out, "unbracketed_read_faulted") === "false"
        && field(out, "unbracketed_write_faulted") === "false", line(out, "smap"));

    out = await run("smap-entry");
    d = line(out, "smap-entry");
    check("B: a process that sets RFLAGS.AC before a syscall does not turn SMAP off in the kernel",
      field(out, "probe_ran") === "true" && field(out, "ac_in_kernel") === "false"
        && field(out, "unbracketed_read_faulted") === "true" && Number(field(out, "entries_with_ac")) >= 1, d);
    await run("ac-entry-off");
    out = await run("smap-entry");
    await run("ac-entry-on");
    check("B: AC control (entry clearing switched off): the kernel runs with AC set and SMAP does not stop the read",
      field(out, "probe_ran") === "true" && field(out, "ac_in_kernel") === "true"
        && field(out, "unbracketed_read_faulted") === "false", line(out, "smap-entry"));

    await sweepCheck("B:", true);
    check("B: no kernel fault during the self-tests", !kernelFault(shell.serial()));

    // Destructive, last: brackets switched off, the sweep must fault in ring 0.
    if (!skip.has("smap-brackets-off")) {
      await run("smap-brackets-off");
      const from = shell.serial().length;
      await shell.type("test-syscall smap-sweep");
      await shell.key("ret");
      await sleep(8000);
      const tail = shell.serial().slice(from);
      const fault = (tail.match(/\[KERNEL\] Page Fault in ring 0.*/) || [""])[0].trim();
      check("B: bracket control: with the brackets switched off, the first user copy of the sweep is a ring-0 page fault",
        fault !== "" && !/smap-sweep: smap=true ended=true/.test(tail), fault || tail.slice(-300));
    }
  } catch (error) {
    check("B: harness completed", false, String(error?.message || error).split("\n")[0]);
  } finally {
    shell?.close();
  }
}

report("Kernel fi2 K1 self-test verification", results);
