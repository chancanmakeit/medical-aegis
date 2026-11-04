#!/bin/bash
# v3 eval set, all frameworks one after another (resumable: finished batches are skipped). v11 r8.
# Memory: 7 GB / 2 CPUs in this container; 8+ parallel lanes OOM-killed lanes and crashed the session.
cd "$(dirname "$0")/../.."
F=/home/claude/gemini_frozen
R="--recorded $F/{fw}__normal_eval.jsonl"
B=scripts/runners/branch_v3.sh
L=/home/claude/eval_v3/master.log
echo "$(date +%T) start" >> $L
bash $B llm_debate /home/claude/eval_v3/llm_debate 19000 300 $R
bash $B mdagents /home/claude/eval_v3/mdagents 19010 425 $R
bash $B agentverse /home/claude/eval_v3/agentverse 19020 250 $R
bash $B dylan /home/claude/eval_v3/dylan 19030 170 $R
bash $B medagents_mc /home/claude/eval_v3/medagents_mc 19040 40 $R
bash $B mac_groupchat /home/claude/eval_v3/mac_groupchat 19050 40 $R
# multimodal (mdagents): finish the Kvasir natural runs first, then freeze
if [ ! -f $F/mdagents__normal_mm_kvasir_vqa_x1.jsonl ]; then
  OUT=/home/claude/gemini_runs DATASET=datasets/data/mm_v1/kvasir_vqa_x1_eval.json bash scripts/runners/gemini_run.sh mdagents mm_kvasir_vqa_x1 125 1
  cp /home/claude/gemini_runs/mdagents__normal_mm_kvasir_vqa_x1.jsonl $F/
fi
p=19060
for d in medxpertqa_mm pathvqa slake kvasir_vqa_x1; do
  bash $B mdagents /home/claude/eval_v3/mm_$d $p 50 --recorded $F/mdagents__normal_mm_$d.jsonl --dataset datasets/data/mm_v1/${d}_eval.json
  p=$((p+10))
done
echo "$(date +%T) ALL_DONE" >> $L
