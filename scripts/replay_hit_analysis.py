#!/usr/bin/env python3
"""Hit-rate report for replay_openai_server.py runs (v10 round 15).

For each (framework, run_index): requests served from the record vs. misses, the share of runs replayed
with zero misses, whether the replayed run reproduces the recorded final answer and step outputs, and
the miss diagnoses grouped by (agent, phase, reason).

  python scripts/replay_hit_analysis.py --calls_dir <dir with <fw>_r<k>_calls.jsonl and <fw>_r<k>_replayed.jsonl> \
      --recorded_dir /home/claude/anchor_runs
"""
import argparse
import glob
import json
import os
import re
from collections import Counter, defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls_dir", required=True)
    ap.add_argument("--recorded_dir", required=True)
    a = ap.parse_args()
    tot = Counter()
    for calls in sorted(glob.glob(os.path.join(a.calls_dir, "*_calls.jsonl"))):
        m = re.match(r"(.+)_r(\d+)_calls\.jsonl", os.path.basename(calls))
        fw, ri = m.group(1), int(m.group(2))
        L = [json.loads(l) for l in open(calls)]
        rec = {}
        for l in open(os.path.join(a.recorded_dir, f"{fw}__normal.jsonl")):
            r = json.loads(l)
            if int(r["run_index"]) == ri:
                rec[r["id"]] = r
        rep = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.calls_dir, f"{fw}_r{ri}_replayed.jsonl"))}
        hits = sum(x["hit"] for x in L)
        miss = [x for x in L if not x["hit"]]
        # attribute misses to questions via the nearest recorded step
        miss_q = Counter((x["diag"].get("nearest") or {}).get("qid") for x in miss)
        n_rec_steps = sum(sum(isinstance(s.get("input_messages"), list) for s in r["injection_log"]["conversation_history"]) for r in rec.values())
        unused = n_rec_steps - hits
        same_ans = same_steps = 0
        for qid, r in rep.items():
            o = rec.get(qid)
            if o is None:
                continue
            same_ans += str(r.get("answer")) == str(o.get("answer"))
            a1 = [s.get("content") for s in r["injection_log"]["conversation_history"]]
            a2 = [s.get("content") for s in o["injection_log"]["conversation_history"]]
            same_steps += a1 == a2
        print(f"== {fw} run_index={ri}: requests={len(L)} hits={hits} ({hits / max(len(L), 1):.3f}) misses={len(miss)} "
              f"recorded_steps={n_rec_steps} recorded_unused={unused}")
        print(f"   runs={len(rep)} runs_with_miss={len([q for q in miss_q if q])} "
              f"same_final_answer={same_ans}/{len(rep)} identical_step_outputs={same_steps}/{len(rep)}")
        why = Counter()
        ex = {}
        for x in miss:
            d = x["diag"]
            nm = d.get("nearest") or {}
            reason = d.get("note") or (f"msg{d.get('first_diff_msg')}:{d.get('role')}" if "first_diff_msg" in d else "no_nearest")
            k = (nm.get("agent"), nm.get("phase"), reason)
            why[k] += 1
            ex.setdefault(k, d)
        for k, v in why.most_common(8):
            d = ex[k]
            print(f"   miss {v:4d} {k}  req/rec msgs={d.get('req_msgs')}/{d.get('rec_msgs')} common={d.get('common_prefix_msgs')} "
                  f"diff_char={d.get('diff_char')} len={d.get('req_len')}/{d.get('rec_len')}")
            if d.get("req_snip") is not None:
                print(f"        req: {d['req_snip'][:180]!r}")
                print(f"        rec: {d['rec_snip'][:180]!r}")
        tot["req"] += len(L)
        tot["hit"] += hits
    print(f"TOTAL requests={tot['req']} hits={tot['hit']} ({tot['hit'] / max(tot['req'], 1):.4f})")


if __name__ == "__main__":
    main()
