#!/bin/bash
# Rebuild the local (not-in-git) working data of medical-aegis in a fresh session. Free: no LLM API calls.
#   bash scripts/restore_workspace.sh [hf|all|anchor|branch|public|mht|aegis]      (default: hf)
#   hf = download the full snapshot from the private HF dataset UUUooUUU/medical-aegis-workspace (fastest, most
#        complete); all = rebuild the same data from the repo and public sources instead.
# env: ROOT (default /home/claude). Needs: HF token in $ROOT/.hf_token (read is enough) for the private
# AgentRx mirror; gh with access to chancanmakeit/Medhypertrace (MHT converters) and, for "aegis",
# chancanmakeit/nature-sub-record (add_repo first).
#
# What it rebuilds (v10 round 17 layout):
#   anchor  $ROOT/anchor_runs/*.jsonl         <- data_runs/anchor_llama_2026-10-21/*.jsonl.gz (+ anchor_all.jsonl export;
#           older derived exports such as gate7_export / fmt_val / mda50_val are rebuilt with the commands in
#           data_runs/anchor_llama_2026-10-21/README.md and scripts/build_*_export.py when needed)
#           $ROOT/anchor_runs_trial/          <- data_runs/workspace_2026-10-27/anchor_runs_trial.tar.gz
#   branch  $ROOT/branch_pilot/               <- data_runs/workspace_2026-10-27/branch_pilot.tar.gz (candidates + D(t),
#                                                 runs with call logs incl. texts); $ROOT/run16_logs, $ROOT/val16 (analysis txt)
#   public  $ROOT/public_mas/raw/<owner>__<name>/  raw public MAS datasets from HuggingFace (layouts MHT's converters read)
#   mht     $ROOT/mht_ref/p2m_r61 (MHT converters, current), $ROOT/mht_pkg_r61 (runnable package),
#           $ROOT/public_mas/mas_traj_r61/*.jsonl.gz (converted, 26,108 runs), $ROOT/mht_ref/lexical_norm.py, maa/
#   aegis   $ROOT/aegis_data/{clean,simulated}  (AEGIS original data, nature-sub-record; only for the MAFA check)
set -e
ROOT=${ROOT:-/home/claude}
REPO=$(cd "$(dirname "$0")/.." && pwd)
WS=$REPO/data_runs/workspace_2026-10-27
what=${1:-hf}
pip install -q --break-system-packages huggingface_hub pandas pyarrow pyyaml tiktoken 2>/dev/null || true

if [[ $what == hf ]]; then
  # full 2026-10-27 snapshot from the private HF dataset (1.6 GB): everything the other modes rebuild, PLUS the
  # derived anchor exports (gate7_export, fmt_val, mda50_val, anchor_all_*), val16 exports and aegis_data
  S=$ROOT/hf_workspace
  HF_TOKEN=$(cat $ROOT/.hf_token) S=$S python3 -I -c "
import os
from huggingface_hub import snapshot_download
snapshot_download('UUUooUUU/medical-aegis-workspace', repo_type='dataset', local_dir=os.environ['S'], token=os.environ['HF_TOKEN'])"
  mkdir -p $ROOT/anchor_runs $ROOT/public_mas
  for f in $S/anchor_runs/*; do
    b=$(basename $f)
    if [[ $b == *.jsonl.gz ]]; then gunzip -c $f > $ROOT/anchor_runs/${b%.gz}; else cp $f $ROOT/anchor_runs/; fi
  done
  cp -r $S/anchor_runs_trial $ROOT/
  for t in branch_pilot val16 run16_logs mht_ref; do tar xzf $S/$t.tar.gz -C $ROOT; done
  tar xf $S/aegis_data.tar -C $ROOT
  tar xf $S/public_mas/raw.tar -C $ROOT/public_mas
  tar xzf $S/public_mas/mas_traj_r61.tar.gz -C $ROOT/public_mas
  tar xzf $S/public_mas/mas_traj_r57.tar.gz -C $ROOT/public_mas
  echo "hf: restored from UUUooUUU/medical-aegis-workspace; snapshot kept in $S (delete it to free 1.6 GB)"
fi

if [[ $what == all || $what == anchor ]]; then
  mkdir -p $ROOT/anchor_runs
  for f in $REPO/data_runs/anchor_llama_2026-10-21/*.jsonl.gz; do
    b=$(basename $f .gz); [ -f $ROOT/anchor_runs/$b ] || gunzip -c $f > $ROOT/anchor_runs/$b
  done
  tar xzf $WS/anchor_runs_trial.tar.gz -C $ROOT
  tar xzf $WS/anchor_runs_txt_logs.tar.gz -C $ROOT       # gate outputs (*.txt) and run logs (*.log) of 2026-10-21..26
  (cd $REPO && python3 scripts/export_schema_v1.py $ROOT/anchor_runs/*__normal.jsonl $ROOT/anchor_runs/*__inject*.jsonl \
      --out $ROOT/anchor_runs/anchor_all.jsonl --maa_exclusion docs/requests/maa_exclusion_v1.json 2>&1 | tail -6)
  echo "anchor: $(ls $ROOT/anchor_runs/*.jsonl | wc -l) files"
fi

if [[ $what == all || $what == branch ]]; then
  tar xzf $WS/branch_pilot.tar.gz -C $ROOT
  tar xzf $WS/run16_logs.tar.gz -C $ROOT
  tar xzf $WS/val16_analysis.tar.gz -C $ROOT
  echo "branch: $(ls $ROOT/branch_pilot/runs | wc -l) files in branch_pilot/runs"
fi

if [[ $what == all || $what == public ]]; then
  HF_TOKEN=$(cat $ROOT/.hf_token 2>/dev/null || true) R=$ROOT/public_mas/raw python3 -I - <<'PY'
import os
from huggingface_hub import hf_hub_download
R = os.environ["R"]; tok = os.environ.get("HF_TOKEN") or None
jobs = [("Kevin355/Who_and_When", "refs/convert/parquet", ["Hand-Crafted/train/0000.parquet", "Algorithm-Generated/train/0000.parquet"], None),
        ("mcemri/MAST-Data", "refs/convert/parquet", ["default/train/0000.parquet"], None),
        ("Edlison/ARIA", None, ["data/train.parquet", "data/validation.parquet", "data/test.parquet"], None),
        ("ZBox008003/AFTraj", None, ["aftraj_safe.parquet", "aftraj_unsafe.parquet", "splits_test.json"], None),
        ("mascope/mascope-bench", None, ["LG-Ctrl.jsonl", "Inject-Mix.jsonl"], None),
        # user's private mirror of the gated microsoft/AgentRx (byte-identical, checked 2026-10-26)
        ("UUUooUUU/AgentRx", None, ["magentic_dataset.jsonl", "magentic_one.jsonl", "tau_retail.jsonl", "tau_retail_dataset.jsonl"], "microsoft__AgentRx"),
        ("TraceElephant/TraceElephant", None, ["data.zip"], None)]
for repo, rev, files, local in jobs:
    d = f"{R}/{local or repo.replace('/', '__')}"
    for f in files:
        if not os.path.exists(f"{d}/{f}"):
            hf_hub_download(repo, f, repo_type="dataset", revision=rev, local_dir=d, token=tok)
    print("ok", repo)
PY
  du -sh $ROOT/public_mas/raw
fi

if [[ $what == all || $what == mht ]]; then
  P=$ROOT/mht_ref/p2m_r61; mkdir -p $P $ROOT/mht_ref/maa
  D=MedHyperTrace-v2/data_tools/public_to_mas_traj
  for f in $(gh api "repos/chancanmakeit/Medhypertrace/contents/$D" --jq '.[] | select(.type=="file") | .name'); do
    gh api -H "Accept: application/vnd.github.raw" "repos/chancanmakeit/Medhypertrace/contents/$D/$f" > $P/$f
  done
  gh api -H "Accept: application/vnd.github.raw" "repos/chancanmakeit/Medhypertrace/contents/MedHyperTrace-v2/data_tools/maa_exclusion.py" > $ROOT/mht_ref/maa/maa_exclusion.py
  gh api -H "Accept: application/vnd.github.raw" "repos/chancanmakeit/Medhypertrace/contents/MedHyperTrace-v2/analysis/anchor_fmt_val/lexical_norm.py" > $ROOT/mht_ref/lexical_norm.py || true
  B=$ROOT/mht_pkg_r61; rm -rf $B; mkdir -p $B/data_tools/public_to_mas_traj $ROOT/public_mas/mas_traj_r61
  touch $B/data_tools/__init__.py; cp $ROOT/mht_ref/maa/maa_exclusion.py $B/data_tools/; cp $P/* $B/data_tools/public_to_mas_traj/
  # the converters import $REPO/scripts/{export_schema_v1,phase_canonical}.py from /home/claude/medical-aegis
  (cd $B && for m in whowhen:who_and_when traceelephant:traceelephant mast:mast_data aria:aria aftraj:aftraj mascope:mascope agentrx_tau:agentrx_tau; do
     mod=${m%%:*}; ds=${m##*:}
     (python3 -m data_tools.public_to_mas_traj.$mod --raw $ROOT/public_mas/raw --out $ROOT/public_mas/mas_traj_r61/$ds.jsonl.gz \
        > $ROOT/public_mas/mas_traj_r61/$ds.log 2>&1; echo "$ds exit=$?") &
   done; wait)
  grep -h "wrote" $ROOT/public_mas/mas_traj_r61/*.log | cut -c1-110
fi

if [[ $what == aegis ]]; then
  echo "aegis: add_repo chancanmakeit/nature-sub-record (read) first; take only the clean and simulated archives (34 MB),"
  echo "unpack to $ROOT/aegis_data/{clean,simulated}. Only needed to re-run scripts/aegis_simulated_signature_check.py."
fi
echo "restore ($what) done"
