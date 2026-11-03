#!/usr/bin/env python3
"""Calibration of the branching eval set (protocol v2) on a new backbone: flip and confirmed-flip yield per
step type and per parent run. Joins on the embedded `branch` identity.

  python3 scripts/branch_eval_calibration.py --dir /home/claude/branch_gemini_cal [--rep1_plan] [--out FILE]
"""
import argparse
import glob
import json
import os
import random
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from branch_pilot import letter  # noqa: E402
import branch_identity as bi  # noqa: E402


def stype(c):
    ph = str(c.get("phase") or "").split("/")[0]
    return f"{ph}" + (f" r{c['round']}" if c.get("round") else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--rep1_plan", action="store_true")
    ap.add_argument("--share", type=float, default=0.10)
    ap.add_argument("--out")
    a = ap.parse_args()
    cands = {}
    for f in glob.glob(os.path.join(a.dir, "*_candidates.jsonl")):
        for l in open(f):
            c = json.loads(l)
            cands[(c["fw"], c["qid"], c["run_index"], c["t_step_id"])] = c
    recs = defaultdict(dict)
    blocks = []
    for f in glob.glob(os.path.join(a.dir, "runs", "*_out.jsonl")):
        fw = os.path.basename(f).split("_p")[0]
        for l in open(f):
            r = json.loads(l)
            b = r["branch"]
            blocks.append(b)
            recs[(fw, b["pair_id"])][(b["arm"], b["repetition"])] = r
    probs, summ = bi.validate(blocks)
    out = [f"identity {json.dumps(summ)}; problems {len(probs)}", ""]
    pts = []
    for (fw, pid), o in recs.items():
        if ("branch", 0) not in o or ("control", 0) not in o:
            continue
        r = o[("control", 0)]
        c = cands[(fw, r["id"], int(r["run_index"]), r["branch"]["candidate_step_id"])]
        bf = letter(o[("branch", 0)].get("response"))
        reps = [letter(v.get("response")) for (arm, k), v in sorted(o.items()) if arm == "control"]
        t_new = next((s for s in o[("branch", 0)]["injection_log"]["conversation_history"] if s.get("step_id") == c["t_step_id"]), {})
        pts.append(dict(c, pair_id=pid, flip=bf != reps[0], reps=reps, branch_final=bf,
                        confirmed=(bf != reps[0] and len(reps) > 1 and len(set(reps)) == 1),
                        to_right=(reps[0] != c["gold"] and bf == c["gold"]),
                        t_changed=letter(t_new.get("content")) != c["t_letter"],
                        ctl_vs_rec=reps[0] != c["recorded_final"]))
    for fw in sorted({p["fw"] for p in pts}):
        s = [p for p in pts if p["fw"] == fw]
        par = {(p["qid"], p["run_index"]) for p in s}
        out.append(f"## {fw}: {len(par)} parents, {len(s)} points, flips {sum(p['flip'] for p in s)}, "
                   f"confirmed {sum(p['confirmed'] for p in s)}, wrong->right {sum(p['to_right'] for p in s)}, "
                   f"control rep0 != recorded {sum(p['ctl_vs_rec'] for p in s)}")
        by = defaultdict(list)
        for p in s:
            by[stype(p)].append(p)
        for k in sorted(by):
            g = by[k]
            out.append(f"- {k}: flips {sum(p['flip'] for p in g)}/{len(g)}, confirmed {sum(p['confirmed'] for p in g)}, "
                       f"2nd control = branch {sum(p['flip'] and len(p['reps']) > 1 and p['reps'][-1] == p['branch_final'] and not p['confirmed'] for p in g)}, "
                       f"letter at t changed {sum(p['t_changed'] for p in g)}")
        rr = [p for p in s if len(p["reps"]) > 1]
        fl = [p for p in rr if p["flip"]]
        un = [p for p in rr if not p["flip"]]
        out.append(f"- control re-runs: flipped {sum(len(set(p['reps'])) > 1 for p in fl)}/{len(fl)} disagree, "
                   f"undetermined {sum(len(set(p['reps'])) > 1 for p in un)}/{len(un)} disagree")
        per = Counter((p["qid"], p["run_index"]) for p in s if p["confirmed"])
        out.append(f"- confirmed flips per parent: mean {sum(per.values()) / len(par):.2f}; parents with >= 1: {len(per)}/{len(par)}")
        out.append("")
    txt = "\n".join(out)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")
    if a.rep1_plan:
        rng = random.Random(0)
        for fw in sorted({p["fw"] for p in pts}):
            s = [p for p in pts if p["fw"] == fw]
            und = [p for p in s if not p["flip"]]
            pick = [p for p in s if p["flip"]] + rng.sample(und, max(1, round(a.share * len(und))))
            by = defaultdict(list)
            for p in pick:
                by[p["pass"]].append(p["qid"])
            with open(os.path.join(a.dir, f"{fw}_rep1_plan.txt"), "w") as f:
                for k in sorted(by):
                    f.write(f"{k} {','.join(sorted(by[k]))}\n")
            print(f"{fw}: rep1 plan {len(pick)} points ({sum(p['flip'] for p in pick)} flips)")


if __name__ == "__main__":
    main()
