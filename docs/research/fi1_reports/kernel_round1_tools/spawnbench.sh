#!/usr/bin/env bash
# usage: spawnbench.sh <label> <i> <out>: boots, runs `ring3 init`, and measures the wall time from init's
# "[init] Spawning heliox-daemon..." to the daemon's first serial line (Exec of the daemon image).
cd ${FI1_IMAGES:?image dir}
label=$1; i=$2; out=$3
log=logs/spawn_${label}_$i.log
BOOT_WAIT=700 bash lockrun.sh node probe.mjs $label/bootimage-ferrumos.bin ${FI1_IMAGES:?image dir}/$log --wait 5 -- "write /tmp/mmap_test 1" "ring3 init" "@sleep 150000" > /dev/null 2>&1
python - "$log.timeline" "$label" "$i" >> $out <<'PY'
import sys
t=[l.split('\t',1) for l in open(sys.argv[1],encoding='utf-8',errors='replace').read().splitlines() if '\t' in l]
s=next((float(a) for a,b in t if 'Spawning heliox-daemon' in b),None)
d=next((float(a) for a,b in t if s is not None and float(a)>=s and b.startswith('[heliox-daemon]')),None)
m=next((float(a) for a,b in t if 'mmap validation success' in b),None)
print(f"{sys.argv[2]}\t{sys.argv[3]}\tspawn_to_daemon_s={None if d is None or s is None else round(d-s,1)}\tspawn_to_mmap_ok_s={None if m is None or s is None else round(m-s,1)}")
PY
tail -n1 $out
