#!/bin/bash
# MAFA Stage 1 on the medical-aegis batch ma_v1 (320 traces): arm <model> <taxonomy: mast|maa> <schema-mode> <trace-workers>
# Resumable (run_stage1 skips traces already in stage1.jsonl). Keys from .mht_api.env (A6API_*).
cd /home/claude/mafa-human-ai-annotation
set -a; . /home/claude/.mht_api.env; set +a
export OPENAI_API_KEY=$A6API_KEY MAFA_CLIENT_TIMEOUT=600
m=$1; tax=$2; sm=$3; tw=$4; IDS=$5; NT=$6; SUF=$7
W=work_ma/${tax}_${m}${SUF}
TX=""; [ "$tax" = mast ] && TX="--taxonomy mafa/seeds/mast_seed_v1.json"
for try in 1 2 3; do
  n=$( [ -f $W/stage1.jsonl ] && wc -l < $W/stage1.jsonl || echo 0)
  [ "$n" -ge $NT ] && break
  python3 scripts/run_stage1.py --data data --work $W --trace-ids $IDS $TX --model $m \
    --base-url "$A6API_BASE_URL" --annotator-backend chat --schema-mode $sm --images datasets/medical_aegis_images \
    --trace-workers $tw >> $W.log 2>&1
done
echo "$(date +%T) $W lines=$(wc -l < $W/stage1.jsonl)" >> work_ma/master.log
