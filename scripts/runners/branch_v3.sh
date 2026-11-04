#!/bin/bash
# Protocol v3 branching eval set for one framework (v11 r8, user approval 2026-11-03).
#   branch_v3.sh <fw> <dir> <port_base> <n_parents> [extra branch_pilot args, e.g. --recorded F --dataset F]
# Stage 1: reps 0-1 of both arms on every LLM step of <n_parents> wrong-ending recorded runs (gemini backbone).
# Stage 2: reps 2-5 of both arms on points whose 4 stage-1 finals differ (scripts/branch_v3_analysis.py plan).
set -u
fw=$1; D=$2; pb=$3; npar=$4; shift 4; EXTRA="$*"
cd "$(dirname "$0")/../.."
mkdir -p "$D"
BP="python3 scripts/branch_pilot.py --backbone gemini --protocol v3 --max_workers ${MW:-6} --skip_done --fw $fw $EXTRA"
EXP="eval-v3-$(basename "$D")"
[ -f "$D/${fw}_candidates.jsonl" ] || { $BP select_all --out "$D" --limit "$npar" && $BP deps --dir "$D"; } >> "$D/driver_$fw.log" 2>&1
passes=$(python3 -c "import json;print(' '.join(map(str,sorted({json.loads(l)['pass'] for l in open('$D/${fw}_candidates.jsonl')}))))")
lane() {   # lane <port> <arm> <reps...>  [ONLY_FILE]
  local port=$1 arm=$2; shift 2
  for rep in "$@"; do
    if [ -n "${PLAN:-}" ]; then
      while read p q; do
        $BP run --dir "$D" --arm $arm --pass $p --rep $rep --only "$q" --upstream ${UP:-real} --port $port --experiment_id $EXP >> "$D/lane_${fw}_${arm}.log" 2>&1
      done < "$PLAN"
    else
      for p in $passes; do
        $BP run --dir "$D" --arm $arm --pass $p --rep $rep --upstream ${UP:-real} --port $port --experiment_id $EXP >> "$D/lane_${fw}_${arm}.log" 2>&1
      done
    fi
  done
}
echo "$(date +%T) $fw stage1 start" >> "$D/driver_$fw.log"
# each stage runs twice: the second pass only redoes batches that crashed (finished batches are skipped)
for try in 1 2; do
  PLAN= lane $pb branch 0 & PLAN= lane $((pb+1)) branch 1 & PLAN= lane $((pb+2)) control 0 & PLAN= lane $((pb+3)) control 1 & wait
done
python3 scripts/branch_v3_analysis.py plan --dir "$D" >> "$D/driver_$fw.log" 2>&1
echo "$(date +%T) $fw stage2 start" >> "$D/driver_$fw.log"
if [ -s "$D/${fw}_stage2_plan.txt" ]; then
  export PLAN="$D/${fw}_stage2_plan.txt"
  for try in 1 2; do
    lane $pb branch 2 3 & lane $((pb+1)) branch 4 5 & lane $((pb+2)) control 2 3 & lane $((pb+3)) control 4 5 & wait
  done
fi
echo "$(date +%T) $fw done" >> "$D/driver_$fw.log"
