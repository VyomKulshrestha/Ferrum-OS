// fi2 kernel workstream K1 harness: run-time checks for SMEP, SMAP, the
// console's process-output marking, the per-process kernel heap ledger, ext2
// on real mke2fs disks and x87 error delivery. Each `test-syscall <name>`
// runs a kernel self-test from src/shell/selftest_k5.rs; the `*-off`
// switches restore the old behaviour on the same image (negative controls).
//
//   node scripts/verify_kernel_k5.mjs
//
// Boot A uses -cpu Haswell (SMEP, no SMAP), boot B -cpu Broadwell-noTSX
// (SMEP and SMAP under WHPX on the reference host), boots C and D attach two
// ext2 disks made by mke2fs in Docker (fixes on, fixes off).
// FERRUMOS_K5_BOOTS=A,C (for example) runs a subset. FERRUMOS_SKIP_SELFTESTS=name,... skips self-tests.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report, sleep } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);
const note = (text) => console.log(`NOTE\t${text}`);
const skip = new Set((process.env.FERRUMOS_SKIP_SELFTESTS || "").split(",").filter(Boolean));
const boots = (process.env.FERRUMOS_K5_BOOTS || "A,B,C,D").split(",");
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

// Item 6: CR0.NE set; an unmasked x87 error ends the process that caused it.
async function x87Checks() {
  if (skip.has("x87-mf")) return;
  let out = await run("x87-mf", 30);
  check("A: x87: CR0.NE is set; an unmasked x87 divide by zero raises #MF in the process, which ends with exit 136",
    field(out, "cr0_ne") === "true" && field(out, "mf_exceptions") === "1" && field(out, "ended") === "true"
      && field(out, "exit") === "136", line(out, "x87-mf"));
  check("A: x87: the next process computes 1 + 1 on the x87 normally (exit 2)",
    field(out, "next_ended") === "true" && field(out, "next_exit") === "2");
  await run("cr0-ne-off");
  out = await run("x87-mf", 30);
  await run("cr0-ne-on");
  check("A: x87 control (CR0.NE cleared, same image): no #MF, the process runs on until it is killed (137)",
    field(out, "cr0_ne") === "false" && field(out, "mf_exceptions") === "0" && field(out, "exit") === "137", line(out, "x87-mf"));
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
    await x87Checks();
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

// ---- boots C and D: ext2 on disks made by a real mke2fs (item 5) -------------
// The disks are built in a throw-away Alpine container (scripts/
// k5_ext2_images.sh) and attached as the secondary IDE master (clean.img)
// and slave (crafted.img). Boot C runs the self-test with the fixes; boot D
// switches them off first (negative control). After each boot, e2fsck -fn
// checks the clean disk.
const sub2 = (text, label) => ((text || "").match(new RegExp(`selftest ext2-real: ${label}(.*)`)) || [, ""])[1];

function docker(args) {
  const r = spawnSync("docker", args, { encoding: "utf8", timeout: 300000 });
  return { code: r.status, out: `${r.stdout || ""}${r.stderr || ""}` };
}

function buildDisks(dir) {
  fs.mkdirSync(dir, { recursive: true });
  // Without carriage returns (a CRLF checkout would break `sh`).
  fs.writeFileSync(path.join(dir, "k5_ext2_images.sh"),
    fs.readFileSync(path.join(repo, "scripts", "k5_ext2_images.sh"), "utf8").replace(/\r/g, ""));
  const r = docker(["run", "--rm", "--name", "fi2k-mkext2", "-v", `${dir.replace(/\\/g, "/")}:/work`, "alpine:3.20", "sh", "/work/k5_ext2_images.sh"]);
  return r.code === 0 && fs.existsSync(path.join(dir, "clean.img")) && fs.existsSync(path.join(dir, "crafted.img"));
}

function fsck(dir, file) {
  const r = docker(["run", "--rm", "--name", "fi2k-fsck", "-v", `${dir.replace(/\\/g, "/")}:/work`, "alpine:3.20", "sh", "-c",
    `apk add --no-cache e2fsprogs >/dev/null && e2fsck -fn /work/${file}; echo "fsck_exit=$?"`]);
  const exit = Number((r.out.match(/fsck_exit=(\d+)/) || [])[1] ?? -1);
  return { exit, out: r.out };
}

async function ext2Boot(tag, control) {
  const dir = path.join(repo, "target", "k5ext2");
  const clean = `${tag}-clean.img`;
  const crafted = `${tag}-crafted.img`;
  fs.copyFileSync(path.join(dir, "clean.img"), path.join(dir, clean));
  fs.copyFileSync(path.join(dir, "crafted.img"), path.join(dir, crafted));
  let out = "";
  try {
    shell = await bootShell(repo, `kernel-k5-${tag.toLowerCase()}-serial.log`, {
      cpu: "Haswell",
      extraArgs: ["-drive", `format=raw,file=${path.join(dir, clean)},if=ide,index=2`,
        "-drive", `format=raw,file=${path.join(dir, crafted)},if=ide,index=3`],
    });
    if (control) await run("ext2-fi2-off");
    out = await run("ext2-real", 600);
    if (control) await run("ext2-fi2-on");
    check(`${tag}: no kernel fault`, !kernelFault(shell.serial()));
  } catch (error) {
    check(`${tag}: ext2 boot completed`, false, String(error?.message || error).split("\n")[0]);
  } finally {
    shell?.close();
  }
  await sleep(1500);
  return { out, fsck: fsck(dir, clean) };
}

if (boots.includes("C") || boots.includes("D")) {
  const dir = path.join(repo, "target", "k5ext2");
  const built = buildDisks(dir);
  check("C/D: mke2fs (e2fsprogs in Alpine 3.20) builds the clean and the crafted disk; the clean disk passes e2fsck -fn before the kernel touches it",
    built && /0\.0% non-contiguous|files \(/.test(fs.readFileSync(path.join(dir, "clean.fsck.txt"), "utf8"))
      && !/Fix\?/.test(fs.readFileSync(path.join(dir, "clean.fsck.txt"), "utf8")),
    built ? fs.readFileSync(path.join(dir, "layout.txt"), "utf8").split("\n").filter((l) => /features|Reserved GDT|Backup superblock at 8193/.test(l)).join(" | ") : "docker build failed");
  if (built && boots.includes("C")) {
    const { out, fsck: f } = await ext2Boot("C", false);
    const m = sub2(out, "clean mount=ok");
    check("C: a real mke2fs disk mounts (features ext_attr resize_inode dir_index filetype sparse_super large_file); a 300 KiB file through double indirect blocks reads whole; a 302-entry directory lists",
      /root_has_big=true root_has_lost_found=true bigdir_entries=302 big_bytes_read=307200/.test(m), m || line(out, "ext2-real").slice(0, 300));
    const ow = sub2(out, "clean unlink");
    check("C: removing one of two hard links keeps the other (round 4 finding 4, real disk)", /_one_of_two=true other_link_intact=true/.test(`unlink${ow}`), `unlink${ow}`);
    check("C: overwriting the 300 KiB file frees its 300 data blocks and 3 indirect blocks (5 new blocks taken)",
      /big_data_blocks=300 big_pointer_blocks=3 overwrite=true overwrite_freed=298/.test(ow), ow);
    const gd = sub2(out, "clean growdir_made");
    check("C: a directory grows past 12 blocks (120 entries of 100 bytes) and every name resolves",
      /=true created=120 listed=122/.test(`growdir_made${gd}`) && Number(field(gd, "dir_blocks")) > 12 && /last_found=true removed=20/.test(gd), `growdir_made${gd}`);
    const rm = sub2(out, "clean remove_big");
    check("C: remove of files and of a nested directory (round 2 and 3 paths, real disk)",
      /=true remove_small=true nested=true unnested=true/.test(`remove_big${rm}`), `remove_big${rm}`);
    check("C: e2fsck -fn finds the clean disk clean after the kernel's writes",
      f.exit === 0 && !/Fix\?|differences|ERROR/i.test(f.out), f.out.split("\n").filter((l) => /Fix|differences|files \(|exit/.test(l)).slice(0, 6).join(" | "));
    const cr = sub2(out, "crafted mount=ok");
    check("C: a block shared by two files (cross-link) stays allocated when one is removed; the other file's data survives later writes",
      /remove_xlink=true/.test(cr) && /victim_before=true victim_intact_after=true/.test(cr), cr);
    check("C: backup superblock and reserved descriptor blocks marked free are never handed out; a pointer to one is not freed",
      field(cr, "file_blocks_in_backup_metadata") === "0" && field(cr, "backup_superblock_magic") === "0xef53"
        && Number(field(cr, "files_written")) === 40, cr);
    check("C: removing the 6.5 MiB filler frees every data and indirect block",
      Number(field(cr, "filler_freed")) === Number(field(cr, "filler_data_blocks")) + Number(field(cr, "filler_pointer_blocks"))
        && Number(field(cr, "filler_pointer_blocks")) > 2, cr);
  }
  if (built && boots.includes("D")) {
    const { out, fsck: f } = await ext2Boot("D", true);
    const ow = sub2(out, "clean unlink");
    const gd = sub2(out, "clean growdir_made");
    const cr = sub2(out, "crafted mount=ok");
    note(`D (fixes off): ${ow} | growdir_made${gd} | ${cr}`);
    check("D control (fixes off, same image): overwrite frees only the 12 direct blocks (indirect blocks and their data leak)",
      Number(field(ow, "overwrite_freed")) < 298, ow);
    check("D control: the directory stops at 12 blocks", Number(field(gd, "created")) < 120, `growdir_made${gd}`);
    check("D control: e2fsck -fn reports damage on the clean disk",
      f.exit !== 0 && /differences|Fix\?/.test(f.out), f.out.split("\n").filter((l) => /differences|Fix|exit/.test(l)).slice(0, 4).join(" | "));
    check("D control: the cross-linked block is freed and reused (the other file's data changes) or backup metadata is handed out",
      /victim_intact_after=false/.test(cr) || Number(field(cr, "file_blocks_in_backup_metadata")) > 0, cr);
    check("D control: files are written over the backup superblock",
      Number(field(cr, "file_blocks_in_backup_metadata")) > 0 && field(cr, "backup_superblock_magic") !== "0xef53", cr);
  }
}

report("Kernel fi2 K1 self-test verification", results);
