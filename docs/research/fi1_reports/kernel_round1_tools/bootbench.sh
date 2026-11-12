#!/usr/bin/env bash
# usage: bootbench.sh <image-label> <n> <outfile>   boots the image n times (one at a time, under the lock)
# and records the wall time from QEMU start to the first shell prompt on serial.
cd ${FI1_IMAGES:?image dir}
label=$1; n=$2; out=$3
for i in $(seq 1 $n); do
  log=logs/boot_${label}_$i.log
  ms=$(bash lockrun.sh node probe.mjs $label/bootimage-ferrumos.bin ${FI1_IMAGES:?image dir}/$log 2>&1 | grep -o 'boot_ms [0-9]*' | cut -d' ' -f2)
  load=$(powershell -c "(Get-CimInstance Win32_Processor).LoadPercentage" 2>/dev/null | tr -d '\r')
  echo -e "$label\t$i\tboot_ms=${ms:-none}\thost_load_after=${load}" | tee -a $out
done
