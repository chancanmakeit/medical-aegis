#!/bin/bash
# Gemini batch runner (v11 r6): normal runs with gemini-2.5-flash-lite on the xiaojingai endpoint.
#   gemini_run.sh <fw> <pool: eval|corpus> <limit> [num_runs]
#   fw: llm_debate | mdagents | medagents_mc | mac_groupchat | dylan | agentverse
#   env: OUT (default /home/claude/gemini_runs)  SUFFIX (output name suffix)  START (run_index_start, default 0)
#        DATASET (a dataset JSON instead of datasets/data/pools_v1/<pool>.json; <pool> then only names the output)
# Questions: datasets/data/pools_v1/<pool>.json, first <limit> in the seeded group order.
# Keys from /home/claude/.mht_api.env (XIAOJINGAI_GEMINI_API_KEY, XIAOJINGAI_BASE_URL; ENDPOINT=duckcoding uses DUCKCODING_*); the resolved api
# config and YAML are written to $OUT with mode 600 and must not be committed.
set -e
fw=$1; pool=$2; lim=$3; K=${4:-1}
MODEL=gemini-2.5-flash-lite
OUT=${OUT:-/home/claude/gemini_runs}; mkdir -p "$OUT"
REPO=$(cd "$(dirname "$0")/../.." && pwd); cd "$REPO"
set -a; . /home/claude/.mht_api.env; set +a
# ENDPOINT=duckcoding (v11 r13): same model on api.duckcoding.ai (DUCKCODING_API_KEY / DUCKCODING_BASE_URL)
if [ "${ENDPOINT:-xiaojingai}" = duckcoding ]; then
  XIAOJINGAI_BASE_URL=$DUCKCODING_BASE_URL; XIAOJINGAI_GEMINI_API_KEY=$DUCKCODING_API_KEY
  export XIAOJINGAI_BASE_URL XIAOJINGAI_GEMINI_API_KEY
fi
api=$OUT/real_api.json
python3 - "$api" "$MODEL" <<'PY'
import json, os, sys
m = {"model_name": sys.argv[2], "model_url": os.environ["XIAOJINGAI_BASE_URL"], "api_key": os.environ["XIAOJINGAI_GEMINI_API_KEY"]}
json.dump({sys.argv[2]: {"model_list": [m], "max_workers_per_model": 2}}, open(sys.argv[1], "w"))
os.chmod(sys.argv[1], 0o600)
PY
cfg=$OUT/_cfg_${fw}_normal.yaml
python3 - experiments/fm_injection/gemini/${fw}_normal.yaml "$cfg" "$MODEL" <<'PY'
import os, sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
c["llm_config"].update(model_name=sys.argv[3], model_url=os.environ["XIAOJINGAI_BASE_URL"], api_key=os.environ["XIAOJINGAI_GEMINI_API_KEY"])
open(sys.argv[2], "w").write(yaml.safe_dump(c, sort_keys=False, allow_unicode=True)); os.chmod(sys.argv[2], 0o600)
PY
out=$OUT/${fw}__normal_${pool}${SUFFIX}.jsonl
echo "$(date +%H:%M:%S) start $fw $pool lim=$lim K=$K" >> "$OUT/progress.txt"
set +e
python3 main.py --method_name "$fw" --experiment_config "$cfg" --model_api_config "$api" --model_name $MODEL \
  --dataset_file ${DATASET:-datasets/data/pools_v1/${pool}.json} --test_dataset_name medxpertqa_text --output_path "$out" --limit "$lim" \
  --model_temperature 0.7 --model_max_tokens 4096 --max_workers ${MAXW:-16} --num_runs $K --run_index_start ${START:-0} --no_inject > "$out.log" 2>&1
echo "$(date +%H:%M:%S) done $fw $pool exit=$? lines=$(wc -l < "$out")" >> "$OUT/progress.txt"
