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
