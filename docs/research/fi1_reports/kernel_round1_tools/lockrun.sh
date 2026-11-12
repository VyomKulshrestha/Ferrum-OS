#!/usr/bin/env bash
# usage: lockrun.sh <command...>   runs the command holding the shared QEMU lock
LOCK=${FI1_LOCK:?shared QEMU lock dir}
MEM="${FI1_MEMFREE:?path to memfree.py}"
while true; do
  until python "$MEM" 0.5 3 >/dev/null; do sleep 20; done
  mkdir $LOCK 2>/dev/null && break
  age=$(( $(date +%s) - $(stat -c %Y $LOCK 2>/dev/null || date +%s) ))
  if [ $age -gt 1200 ]; then rmdir $LOCK 2>/dev/null; continue; fi
  sleep 30
done
"$@"; rc=$?
rmdir $LOCK
exit $rc
