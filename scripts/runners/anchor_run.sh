#!/bin/bash
# Anchor runner (llama-4-maverick on the 100 anchor questions). Run from anywhere.
#   anchor_run.sh <fw> <normal|inject> [limit]
#   fw: medagents_mc | mac_groupchat | llm_debate | mdagents
#   env: OUT  output dir (default /home/claude/anchor_runs)
#        SUFFIX  appended to the output file name (e.g. _pi4, _sham, _shamstyle2)
#        EXTRA   main.py run args for inject mode (default "--num_runs 2")
# Strategy is picked by run_index via strategy_cycle in the anchor YAML:
#   run 0 = RC inplace, 1 = PI (length-matched), 2 = sham, 3 = sham_style.
# Batches used so far (each resumes: done (id, run_index) pairs are skipped,
# --limit N takes the next N unprocessed questions):
#   SUFFIX=_pi4        EXTRA="--num_runs 1 --run_index_start 1"
#   SUFFIX=_sham       EXTRA="--num_runs 1 --run_index_start 2"
#   SUFFIX=_shamstyle  EXTRA="--num_runs 1 --run_index_start 3"   (old single wording)
# Keys come from /home/claude/.mht_api.env (never committed). The api config and the
# resolved YAML are written to $OUT with mode 600 and must not be committed.
set -e
fw=$1; mode=$2; lim=${3:-100}
OUT=${OUT:-/home/claude/anchor_runs}; mkdir -p "$OUT"
REPO=$(cd "$(dirname "$0")/../.." && pwd); cd "$REPO"
set -a; . /home/claude/.mht_api.env; set +a
api=$OUT/real_api.json
python3 - "$api" <<'PY'
import json, os, sys
m = {"model_name": "llama-4-maverick", "model_url": "https://aihubmix.com/v1", "api_key": os.environ["AIHUBMIX_API_KEY"]}
json.dump({"llama-4-maverick": {"model_list": [m], "max_workers_per_model": 2}}, open(sys.argv[1], "w"))
os.chmod(sys.argv[1], 0o600)
PY
cfg=$OUT/_cfg_${fw}_${mode}.yaml
python3 - experiments/fm_injection/anchor/${fw}_${mode}.yaml "$cfg" <<'PY'
import os, sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
c["llm_config"].update(model_name="llama-4-maverick", model_url="https://aihubmix.com/v1", api_key=os.environ["AIHUBMIX_API_KEY"])
open(sys.argv[2], "w").write(yaml.safe_dump(c, sort_keys=False, allow_unicode=True)); os.chmod(sys.argv[2], 0o600)
PY
out=$OUT/${fw}__${mode}${SUFFIX}.jsonl
extra="${EXTRA:---num_runs 2}"; [ "$mode" = normal ] && extra="--num_runs 3 --no_inject"
echo "$(date +%H:%M:%S) start $fw $mode $SUFFIX" >> "$OUT/progress.txt"
set +e
python3 main.py --method_name "$fw" --experiment_config "$cfg" --model_api_config "$api" --model_name llama-4-maverick \
  --dataset_file datasets/data/anchor_medxpertqa100.json --test_dataset_name medxpertqa_text --output_path "$out" --limit "$lim" \
  --model_temperature 0.7 --model_max_tokens 4096 --max_workers 16 $extra > "$out.log" 2>&1
echo "$(date +%H:%M:%S) done $fw $mode $SUFFIX exit=$? lines=$(wc -l < "$out")" >> "$OUT/progress.txt"
