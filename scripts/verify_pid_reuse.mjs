// fi1 kernel harness for pull request 1, fix 1 (pid reuse of a userspace model
// id). Ring-3 pids count up from 1; scheduler bookkeeping tasks and the
// userspace model processes built on them (the `init` model holds
// cap:system:all) take ids from 100. Syscall dispatch reads a pid's authority
// from the model registry first, so a ring-3 process that is handed the init
// model's id runs with cap:system:all. No other harness spawns enough
// processes to reach that range; this one launches and kills the calculator
// until its pid passes the highest reserved id, keeping every launch at or
// above 100 alive, then asks the kernel what each of those pids may do.
//
//   node scripts/verify_pid_reuse.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bootShell, report } from "./lib/qemu_shell.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const results = [];
const check = (name, ok, detail = "") => results.push(`${ok ? "PASS" : "FAIL"}\t${name}${detail ? "\t" + detail : ""}`);

let shell;
try {
  shell = await bootShell(repo, "pid-reuse-serial.log");
  check("boot reaches shell prompt", true, `boot_ms=${shell.bootMs}`);
  const users = await shell.command("users");
  const reserved = [...users.matchAll(/^\s*(\d+)\s+(?:RUNNING|READY|BLOCKED|DEAD)\s/mg)].map((m) => Number(m[1])).filter((id) => id >= 100);
  const initModel = (users.match(/^\s*(\d+)\s+\S+\s+\S+\s+\S+\s+init\s*$/m) || [])[1];
  const top = Math.max(...reserved);
  check("found the reserved ids and the init model", reserved.length >= 2 && !!initModel, `reserved=${reserved.join(",")} init=${initModel}`);

  const high = [];
  let launches = 0;
  for (;;) {
    const out = await shell.command("run calculator", 30);
    const pid = Number((out.match(/launched calculator as userspace pid (\d+)/) || [])[1]);
    if (!pid) throw new Error(`launch ${launches + 1} failed: ${out.trim().slice(-200)}`);
    launches++;
    if (pid >= 100) high.push(pid);
    // Stop past the reserved range, or on reaching the init model's id (a
    // kernel without the fix would hand out the shell task's id next).
    if (pid > top || pid >= Number(initModel) || launches > 140) break;
    if (pid < 100) {
      const killed = await shell.command(`kill ${pid}`, 30);
      if (!/Killed task/.test(killed)) throw new Error(`kill ${pid} failed: ${killed.trim().slice(-200)}`);
    }
  }
  const collided = high.filter((pid) => reserved.includes(pid));
  check(`no ring-3 pid reuses a reserved id (${launches} launches, pids >= 100: ${high.join(",")})`, collided.length === 0, collided.length ? `collisions=${collided.join(",")}` : "");

  const escalated = [];
  for (const pid of high) {
    const out = await shell.command(`syscall ${pid} 5 4`);
    if (/syscall result: Ok value=1/.test(out)) escalated.push(pid);
  }
  check("no calculator pid holds process:spawn (no inherited cap:system:all)", escalated.length === 0, escalated.length ? `escalated=${escalated.join(",")}` : "");
  check("the init model still holds its authority", /syscall result: Ok value=1/.test(await shell.command(`syscall ${initModel} 5 4`)));
  check("no kernel panic or fault", !/panicked at|PAGE FAULT|Page Fault|General Protection|DOUBLE FAULT/.test(shell.serial()));
} catch (error) {
  check("verification", false, String(error?.message || error).split("\n")[0]);
} finally {
  shell?.close();
}
report("Pid reuse verification", results);
