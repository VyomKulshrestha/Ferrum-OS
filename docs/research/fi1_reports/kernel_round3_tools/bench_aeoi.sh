#!/bin/bash
# usage: bench_aeoi.sh <image> <label> -- five boots; per boot: 20 s idle, counters reset,
# 20 s idle with the PIC's normal EOI, perf; auto-EOI on, reset, 20 s idle, perf.
K=C:/Users/marcu/AppData/Local/Temp/claude/cf53934102d831c4/7cecf9a0-0835-404a-817d-a57cf6c44e08/scratchpad/k3
T=/c/Users/marcu/Videos/cursor-os-base-fi1-kernel2/docs/research/fi1_reports/kernel_round1_tools
LOCK=/c/Users/marcu/Videos/fi1-qemu.lock
img=$1; label=$2
mkdir -p $K/bench
for i in 1 2 3 4 5; do
  until mkdir "$LOCK" 2>/dev/null; do sleep 30; done
  python "C:/Users/marcu/AppData/Local/Temp/claude/cf53934102d831c4/7cecf9a0-0835-404a-817d-a57cf6c44e08/scratchpad/memfree.py" 2 3 > /dev/null
  log=$K/bench/${label}_$i.log
  out=$(cd $T && node probe.mjs $img $log --wait 20 -- "@sleep 20000" "test-syscall perf-reset" "@sleep 20000" "test-syscall perf" "test-syscall pic-aeoi-on" "test-syscall perf-reset" "@sleep 20000" "test-syscall perf" 2>&1)
  rmdir "$LOCK"
  ms=$(echo "$out" | grep -o 'boot_ms [0-9]*' | cut -d' ' -f2)
  perf=$(grep -a "selftest perf: timer_ticks\|aeoi" $log | tr '\r\n' '  ')
  load=$(powershell -c "(Get-CimInstance Win32_Processor).LoadPercentage" 2>/dev/null | tr -d '\r')
  echo -e "$label\t$i\tboot_ms=${ms:-none}\tload=$load\t$perf" >> $K/bench/bench.tsv
  rm -f $log.img
done
echo bench-done
