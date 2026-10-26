#!/bin/bash
# Replay recorded normal runs through scripts/replay_openai_server.py (no API, no key; v10 round 15).
#   env: OUTDIR (default /home/claude/replay_runs), OV = overrides JSONL (simulated branch)
#   replay_run.sh <fw> <limit> <port> <run_index>
fw=$1; lim=$2; port=$3; ri=${4:-0}
S=${OUTDIR:-/home/claude/replay_runs}; mkdir -p "$S"
REPO=$(cd "$(dirname "$0")/../.." && pwd); cd "$REPO"
log=$S/${fw}_r${ri}_calls.jsonl; rm -f "$log"
python3 scripts/replay_openai_server.py --port $port --run_index $ri --results /home/claude/anchor_runs/${fw}__normal.jsonl --log "$log" ${OV:+--overrides $OV} > $S/${fw}_server.log 2>&1 &
spid=$!
sleep 3
api=$S/${fw}_api.json
python3 - "$api" $port <<'PY'
import json, sys
json.dump({"llama-4-maverick": {"model_list": [{"model_name": "llama-4-maverick", "model_url": f"http://127.0.0.1:{sys.argv[2]}/v1", "api_key": "replay-no-key"}], "max_workers_per_model": 2}}, open(sys.argv[1], "w"))
PY
cfg=$S/_cfg_${fw}.yaml
python3 - experiments/fm_injection/anchor/${fw}_normal.yaml "$cfg" $port <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
c["llm_config"].update(model_name="llama-4-maverick", model_url=f"http://127.0.0.1:{sys.argv[3]}/v1", api_key="replay-no-key")
open(sys.argv[2], "w").write(yaml.safe_dump(c, sort_keys=False, allow_unicode=True))
PY
out=$S/${fw}_r${ri}_replayed.jsonl; rm -f "$out"
env -u AIHUBMIX_API_KEY -u OPENAI_API_KEY python3 main.py --method_name "$fw" --experiment_config "$cfg" --model_api_config "$api" --model_name llama-4-maverick \
  --dataset_file datasets/data/anchor_medxpertqa100.json --test_dataset_name medxpertqa_text --output_path "$out" --limit "$lim" \
  --model_temperature 0.7 --model_max_tokens 4096 --max_workers 16 --num_runs 1 --run_index_start $ri --no_inject > "$out.log" 2>&1
echo "$fw exit=$? lines=$(wc -l < "$out") calls=$(wc -l < "$log")"
kill $spid
