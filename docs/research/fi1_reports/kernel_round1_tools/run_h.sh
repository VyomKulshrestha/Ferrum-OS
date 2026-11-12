#!/usr/bin/env bash
# usage: run_h.sh <image-label> <outfile> <harness.mjs> [<harness.mjs> ...]
# Copies ${FI1_IMAGES:?image dir}/<label>/bootimage-ferrumos.bin into the fi1-kernel worktree,
# then runs each harness one at a time under the shared QEMU lock, rerunning a failure once.
WT=${FI1_WORKTREE:?worktree}
IMGDIR=${FI1_IMAGES:?image dir}
LOCK=${FI1_LOCK:?shared QEMU lock dir}
MEM="${FI1_MEMFREE:?path to memfree.py}"
label=$1; out=$2; shift 2
mkdir -p $WT/target/x86_64-unknown-none/debug $IMGDIR/logs

acquire() {
  # Wait for memory before taking the lock, so a memory wait never blocks the other agent.
  while true; do
    until python "$MEM" 0.5 3 >/dev/null; do sleep 20; done
    mkdir $LOCK 2>/dev/null && break
    age=$(( $(date +%s) - $(stat -c %Y $LOCK 2>/dev/null || date +%s) ))
    if [ $age -gt 1200 ]; then echo "removing stale lock (age $age s)" >&2; rmdir $LOCK 2>/dev/null; continue; fi
    sleep 30
  done
}

for h in "$@"; do
  for attempt in 1 2; do
    acquire
    cp $IMGDIR/$label/bootimage-ferrumos.bin $WT/target/x86_64-unknown-none/debug/bootimage-ferrumos.bin
    log=$IMGDIR/logs/${label}_$(basename $h .mjs)_a${attempt}.log
    t0=$(date +%s.%N)
    (cd $WT && node scripts/$h > $log 2>&1); rc=$?
    t1=$(date +%s.%N)
    rmdir $LOCK
    summ=$(grep -Eo '[0-9]+/[0-9]+ checks passed' $log | tail -1)
    [ -z "$summ" ] && summ="$(grep -c '^PASS' $log)/$(grep -cE '^(PASS|FAIL)' $log) (counted)"
    wall=$(python -c "print(f'{$t1-$t0:.1f}')")
    echo -e "$label\t$h\tattempt=$attempt\trc=$rc\t$summ\twall=${wall}s" | tee -a $out
    [ $rc -eq 0 ] && break
    sleep 5
  done
done
