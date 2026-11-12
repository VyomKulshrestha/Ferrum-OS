#!/bin/bash
# usage: h.sh <image.bin> <harness> [env...]  -- runs one harness under the shared lock
img="$1"; shift; harness="$1"; shift
W=/c/Users/marcu/Videos/cursor-os-base-fi1-kernel2
LOCK=/c/Users/marcu/Videos/fi1-qemu.lock
until mkdir "$LOCK" 2>/dev/null; do
  age=$(( $(date +%s) - $(stat -c %Y "$LOCK") ))
  if [ $age -gt 1200 ]; then echo "removing stale lock ($age s)"; rmdir "$LOCK"; continue; fi
  sleep 30
done
trap 'rmdir "$LOCK"' EXIT
python "C:/Users/marcu/AppData/Local/Temp/claude/cf53934102d831c4/7cecf9a0-0835-404a-817d-a57cf6c44e08/scratchpad/memfree.py" 2 3
mkdir -p $W/target/x86_64-unknown-none/debug
cp "$img" $W/target/x86_64-unknown-none/debug/bootimage-ferrumos.bin
echo "image sha256 $(sha256sum $W/target/x86_64-unknown-none/debug/bootimage-ferrumos.bin | cut -c1-64)"
cd $W && env FERRUMOS_BOOT_SECONDS=600 "$@" node scripts/$harness.mjs 2>&1 | tail -45
mkdir -p "C:/Users/marcu/AppData/Local/Temp/claude/cf53934102d831c4/7cecf9a0-0835-404a-817d-a57cf6c44e08/scratchpad/k4/logs"
for f in $W/target/*serial*.log; do [ -f "$f" ] && [ "$f" -nt $W/target/x86_64-unknown-none/debug/bootimage-ferrumos.bin ] && cp "$f" "C:/Users/marcu/AppData/Local/Temp/claude/cf53934102d831c4/7cecf9a0-0835-404a-817d-a57cf6c44e08/scratchpad/k4/logs/$(date +%H%M%S)_${harness}_$(basename $f)"; done
