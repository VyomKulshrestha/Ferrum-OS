#!/bin/bash
# usage: suite.sh <image> <label> <harness...>; reruns a failing harness once
K=C:/Users/marcu/AppData/Local/Temp/claude/cf53934102d831c4/7cecf9a0-0835-404a-817d-a57cf6c44e08/scratchpad/k2
img=$1; label=$2; shift 2
mkdir -p $K/runs
for h in "$@"; do
  for attempt in 1 2; do
    out=$K/runs/${label}_${h}_$attempt.txt
    start=$(date +%s)
    bash $K/h.sh $img $h > $out 2>&1
    res=$(grep -o "[0-9]*/[0-9]* checks passed" $out | tail -1)
    echo -e "$label\t$h\tattempt=$attempt\t${res:-no-result}\t$(( $(date +%s)-start ))s" >> $K/runs/summary.tsv
    if echo "$res" | awk -F'[/ ]' '{exit !($1==$2)}'; then break; fi
  done
done
