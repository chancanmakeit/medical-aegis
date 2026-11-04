#!/bin/bash
# Watchdog for the v3 eval set (v11 r8): prints the status of every job and restarts unfinished jobs that are
# not running (the drivers are resumable: finished batches are skipped). The cloud container is reclaimed when
# the session is idle, which kills background runs; scheduled check-ins call this script.
#   eval_v3_watchdog.sh [--restart]
cd "$(dirname "$0")/../.."
E=/home/claude/eval_v3
R="--recorded /home/claude/gemini_frozen/{fw}__normal_eval.jsonl"
declare -A PORT=([agentverse]=19020 [dylan]=19030 [mac_groupchat]=19050 [triage_agent]=19110
                [mam_heartbeat_a]=19120 [mam_heartbeat_b]=19130 [mam_sounddr]=19140)
declare -A NPAR=([agentverse]=250 [dylan]=170 [mac_groupchat]=40 [triage_agent]=100
                [mam_heartbeat_a]=${MAM_NPAR:-25} [mam_heartbeat_b]=${MAM_NPAR:-25} [mam_sounddr]=${MAM_NPAR:-25})
declare -A ARGS=([triage_agent]="--recorded /home/claude/gemini_frozen/triage_agent__normal_triage.jsonl --dataset datasets/data/triage_esi.json")
declare -A NEED=([triage_agent]=/home/claude/gemini_frozen/triage_agent__normal_triage.jsonl)
for d in heartbeat_a heartbeat_b sounddr; do   # MAM: audio, per-dataset dirs, sample-aware replay keys
  ARGS[mam_$d]="--sample_keys --recorded /home/claude/gemini_frozen/mam__normal_audio_$d.jsonl --dataset datasets/data/$d.json"
  NEED[mam_$d]=/home/claude/gemini_frozen/mam__normal_audio_$d.jsonl
done
# MAM natural runs (resumable; local script /home/claude/posts/run_mam_nat.sh)
if [ ! -f /home/claude/gemini_frozen/mam__normal_audio_sounddr.jsonl ] && [ -f /home/claude/posts/run_mam_nat.sh ]; then
  if ps -eo args | grep -q "^bash /home/claude/posts/[r]un_mam_nat"; then echo "mam natural: running"
  elif [ "${1:-}" = "--restart" ]; then setsid nohup bash /home/claude/posts/run_mam_nat.sh >> /home/claude/posts/run_mam_nat.log 2>&1 < /dev/null & echo "mam natural: restarted"
  fi
fi
# v11 r11 expansion (user-approved ~¥5): triage_agent run_index 1-3; MAM heartbeat a/b unused r0 parents + run_index 1
declare -A FWOF=([triage_agent_x]=triage_agent [mam_heartbeat_a_x]=mam [mam_heartbeat_b_x]=mam)
PORT[triage_agent_x]=19150; PORT[mam_heartbeat_a_x]=19160; PORT[mam_heartbeat_b_x]=19170
NPAR[triage_agent_x]=400; NPAR[mam_heartbeat_a_x]=40; NPAR[mam_heartbeat_b_x]=200
ARGS[triage_agent_x]="--recorded /home/claude/gemini_frozen/x/triage_agent__normal_triage_x.jsonl --dataset datasets/data/triage_esi.json"
NEED[triage_agent_x]=/home/claude/gemini_frozen/x/triage_agent__normal_triage_x.jsonl
for d in heartbeat_a heartbeat_b; do
  ARGS[mam_${d}_x]="--sample_keys --recorded /home/claude/gemini_frozen/x/mam__normal_audio_${d}_x.jsonl --dataset datasets/data/$d.json"
  NEED[mam_${d}_x]=/home/claude/gemini_frozen/x/mam__normal_audio_${d}_x.jsonl
done
pending=0
for job in llm_debate mdagents medagents_mc agentverse dylan mac_groupchat triage_agent mam_heartbeat_a mam_heartbeat_b mam_sounddr triage_agent_x mam_heartbeat_a_x mam_heartbeat_b_x; do
  fw=${job%%_heartbeat_*}; fw=${fw%_sounddr}; fw=${FWOF[$job]:-$fw}
  log=$E/$job/driver_$fw.log
  if [ -f "$log" ] && tail -1 "$log" | grep -q " done$"; then
    echo "$job: done"
    continue
  fi
  pending=1
  if [ -f $E/$job/PAUSED ]; then echo "$job: PAUSED ($(cat $E/$job/PAUSED | cut -c1-100))"; continue; fi
  if ps -eo args | grep -q "[b]ranch_v3.sh $fw $E/$job "; then
    echo "$job: running ($( [ -f "$log" ] && tail -1 "$log" | cut -c1-40))"
  elif [ "${1:-}" = "--restart" ] && [ -n "${PORT[$job]:-}" ]; then
    # DyLAN waits for AgentVerse (one heavy framework at a time besides MAC; 7 GB / 2 CPUs)
    if [ "$job" = dylan ] && ! { [ -f $E/agentverse/driver_agentverse.log ] && tail -1 $E/agentverse/driver_agentverse.log | grep -q " done$"; }; then
      echo "$job: waiting for agentverse"; continue
    fi
    if [ -n "${NEED[$job]:-}" ] && [ ! -f "${NEED[$job]}" ]; then
      echo "$job: parents not frozen yet (natural runs first)"; continue
    fi
    setsid nohup bash scripts/runners/branch_v3.sh $fw $E/$job ${PORT[$job]} ${NPAR[$job]} ${ARGS[$job]:-$R} > /dev/null 2>&1 < /dev/null &
    echo "$job: restarted"
  else
    echo "$job: not running"
  fi
done
for d in medxpertqa_mm pathvqa slake kvasir_vqa_x1; do
  tail -1 $E/mm_$d/driver_mdagents.log 2>/dev/null | grep -q " done$" && echo "mm_$d: done" || { echo "mm_$d: NOT done"; pending=1; }
done
[ $pending = 0 ] && echo "ALL_DONE"
true
