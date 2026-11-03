#!/bin/bash
# (v11 r7) usage: [RESULTS=<recorded jsonl>] [DATASET=<dataset json>] replay_gemini.sh <fw> <limit> <port>
# pure replay of gemini natural runs (no API: misses answered by the mock), to test prefix reproducibility
fw=$1; lim=$2; port=$3
S=/home/claude/replay_gem; mkdir -p $S; cd /home/claude/medical-aegis
log=$S/${fw}_calls.jsonl; rm -f $log
python3 scripts/replay_openai_server.py --port $port --run_index 0 --results ${RESULTS:-/home/claude/gemini_runs/${fw}__normal_eval.jsonl} --log $log > $S/${fw}_server.log 2>&1 &
spid=$!; sleep 3
python3 - $S/${fw}_api.json $port <<'PY'
import json, sys
json.dump({"gemini-2.5-flash-lite": {"model_list": [{"model_name": "gemini-2.5-flash-lite", "model_url": f"http://127.0.0.1:{sys.argv[2]}/v1", "api_key": "x"}], "max_workers_per_model": 2}}, open(sys.argv[1], "w"))
PY
python3 - experiments/fm_injection/gemini/${fw}_normal.yaml $S/_cfg_${fw}.yaml $port <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1])); c["llm_config"].update(model_name="gemini-2.5-flash-lite", model_url=f"http://127.0.0.1:{sys.argv[3]}/v1", api_key="x")
open(sys.argv[2], "w").write(yaml.safe_dump(c))
PY
out=$S/${fw}_replayed.jsonl; rm -f $out
env -u XIAOJINGAI_GEMINI_API_KEY python3 main.py --method_name $fw --experiment_config $S/_cfg_${fw}.yaml --model_api_config $S/${fw}_api.json --model_name gemini-2.5-flash-lite \
  --dataset_file ${DATASET:-datasets/data/pools_v1/eval.json} --test_dataset_name medxpertqa_text --output_path $out --limit $lim \
  --model_temperature 0.7 --model_max_tokens 4096 --max_workers 16 --num_runs 1 --run_index_start 0 --no_inject > $out.log 2>&1
kill $spid
python3 - $fw $log <<'PY'
import json,sys,collections
fw,log=sys.argv[1],sys.argv[2]
L=[json.loads(l) for l in open(log)]
print(fw,'requests',len(L),'hit',sum(bool(x.get('hit')) for x in L), collections.Counter(x.get('hit') for x in L))
PY
