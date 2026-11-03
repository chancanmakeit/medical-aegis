#!/usr/bin/env python3
"""Analysis of plan A (docs/requests/samples/planA_2026-11-03/PLAN.md), fixed before the run.

Per point: flip = branch final letter != control final letter (rep 0). answer_changed == flip;
correctness_changed = (branch == gold) != (control == gold). Points are joined on the embedded `branch`
identity (pair_id), not on file names.

  python3 scripts/branch_planA_analysis.py --dir /home/claude/branch_planA [--rep1_plan] [--out FILE]
"""
import argparse
import glob
import json
import os
import random
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from branch_pilot import letter, P_IN, P_OUT  # noqa: E402
import branch_identity as bi  # noqa: E402


def load(d):
    cands = {}
    for l in open(os.path.join(d, "llm_debate_candidates.jsonl")):
        c = json.loads(l)
        cands[(c["qid"], c["run_index"], c["t_step_id"])] = c
    recs = defaultdict(dict)   # pair_id -> {(arm, rep): record}
    blocks = []
    for f in glob.glob(os.path.join(d, "runs", "*_out.jsonl")):
        for l in open(f):
            r = json.loads(l)
            b = r.get("branch")
            if b is None:
                sys.exit(f"{f}: record without branch identity")
            blocks.append(b)
            recs[b["pair_id"]][(b["arm"], b["repetition"])] = r
    cost = 0.0
    for f in glob.glob(os.path.join(d, "runs", "*_calls.jsonl")):
        for l in open(f):
            x = json.loads(l)
            if x.get("upstream"):
                u = x.get("usage") or {}
                cost += u.get("prompt_tokens", 0) * P_IN + u.get("completion_tokens", 0) * P_OUT
    return cands, recs, blocks, cost


def points(cands, recs):
    pts = []
    for pid, o in recs.items():
        if ("branch", 0) not in o or ("control", 0) not in o:
            continue
        r = o[("control", 0)]
        b = r["branch"]
        c = cands[(r["id"], int(r["run_index"]), b["candidate_step_id"])]
        bf, cf = letter(o[("branch", 0)].get("response")), letter(r.get("response"))
        g = c["gold"]
        t_new = next((s for s in o[("branch", 0)]["injection_log"]["conversation_history"]
                      if s.get("step_id") == c["t_step_id"]), {})
        pts.append(dict(c, pair_id=pid, branch_final=bf, control_final=cf, flip=bf != cf,
                        correctness_changed=(bf == g) != (cf == g), to_right=(cf != g and bf == g),
                        to_wrong=(cf == g and bf != g), t_letter_changed=letter(t_new.get("content")) != c["t_letter"],
                        control_vs_recorded=cf != c["recorded_final"],
                        reps=[letter(v.get("response")) for (arm, k), v in sorted(o.items()) if arm == "control"],
                        rep_reason=next(((v["branch"]["selection"] or {}).get("repetition_reason")
                                         for (arm, k), v in o.items() if k > 0), None)))
    return pts


def kind(p):
    return {("end_wrong", "wrong"): "main", ("end_wrong", "right"): "ctl1", ("end_right", "right"): "ctl2"}[
        (p["run_end"], p["letter_status"])]


def boot(pts, stat, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    qs = sorted({p["qid"] for p in pts})
    byq = defaultdict(list)
    for p in pts:
        byq[p["qid"]].append(p)
    vals = []
    for _ in range(n):
        s = [p for q in rng.choice(qs, len(qs), replace=True) for p in byq[q]]
        v = stat(s)
        if v is not None and not np.isnan(v):
            vals.append(v)
    if len(vals) < 0.9 * n:      # a stratum is empty in too many resamples: no interval
        return float("nan"), float("nan")
    return np.percentile(vals, 2.5), np.percentile(vals, 97.5)


def rate(s, pos=None, peer=None, key="flip"):
    s = [p for p in s if (pos is None or p["position"] == pos) and (peer is None or min(p["peers_right"], 1) == peer)]
    return float(np.mean([p[key] for p in s])) if s else float("nan")


def std_rate(s, pos, key="flip"):
    """Rate at one position standardized to equal weight on the two peer strata (the design's balance)."""
    r = [rate(s, pos, k, key) for k in (0, 1)]
    return float(np.mean(r)) if not any(np.isnan(r)) else float("nan")


def slope(s, key="flip"):
    r = [std_rate(s, k, key) for k in range(3)]
    return float(np.polyfit([0, 1, 2], r, 1)[0]) if not any(np.isnan(r)) else float("nan")


def fmt(k, n):
    return f"{k}/{n}" + (f" = {k / n:.2f}" if n else "")


def report(d):
    cands, recs, blocks, cost = load(d)
    probs, summ = bi.validate(blocks)
    pts = points(cands, recs)
    out = [f"# Plan A results ({len(pts)} points with both arms; upstream cost ${cost:.3f})", "",
           f"identity: {json.dumps(summ)}; problems {len(probs)} {probs[:3]}", ""]
    main = [p for p in pts if kind(p) == "main"]
    out.append("## Primary: main points (wrong letter, run ends wrong), flip by speaker position")
    out.append("| position | peers right 0 | peers right >= 1 | standardized [95% CI, question bootstrap] |")
    out.append("|---|---|---|---|")
    for k in range(3):
        cells = []
        for peer in (0, 1):
            s = [p for p in main if p["position"] == k and min(p["peers_right"], 1) == peer]
            cells.append(fmt(sum(p["flip"] for p in s), len(s)))
        lo, hi = boot(main, lambda s, k=k: std_rate(s, k))
        out.append(f"| {k} | {cells[0]} | {cells[1]} | {std_rate(main, k):.2f} [{lo:.2f}, {hi:.2f}] |")
    d20 = lambda s: std_rate(s, 2) - std_rate(s, 0)
    lo, hi = boot(main, d20)
    out.append(f"\n- pos 2 - pos 0: {d20(main):+.2f} [{lo:+.2f}, {hi:+.2f}]")
    lo, hi = boot(main, slope)
    out.append(f"- linear trend per position: {slope(main):+.3f} [{lo:+.3f}, {hi:+.3f}]")
    best = max(range(3), key=lambda k: std_rate(main, k))
    out.append(f"- prediction pos 2 > 1 > 0: observed order {sorted(range(3), key=lambda k: -std_rate(main, k))}; "
               f"pos 2 highest: {best == 2}")
    pe = lambda s: rate(s, peer=1) - rate(s, peer=0)
    lo, hi = boot(main, pe)
    out.append(f"- peer support (>= 1 minus 0), pooled over positions: {pe(main):+.2f} [{lo:+.2f}, {hi:+.2f}] "
               f"({fmt(sum(p['flip'] for p in main if p['peers_right'] >= 1), sum(p['peers_right'] >= 1 for p in main))} vs "
               f"{fmt(sum(p['flip'] for p in main if p['peers_right'] == 0), sum(p['peers_right'] == 0 for p in main))})")
    out.append(f"- flips wrong -> right: {sum(p['to_right'] for p in main)}; wrong -> other wrong: "
               f"{sum(p['flip'] and not p['to_right'] for p in main)}")
    out.append(f"- step-t letter changed by the resample: {sum(p['t_letter_changed'] for p in main)}/{len(main)}; flips among "
               f"them {sum(p['flip'] for p in main if p['t_letter_changed'])}, among unchanged "
               f"{sum(p['flip'] for p in main if not p['t_letter_changed'])}")
    out.append("")
    out.append("## Control candidates (right letter at t)")
    for name, lab in (("ctl1", "run ends wrong (right letter in a wrong run)"), ("ctl2", "run ends right (right -> wrong direction)")):
        s = [p for p in pts if kind(p) == name]
        out.append(f"- {lab}: flips {fmt(sum(p['flip'] for p in s), len(s))}; to wrong {sum(p['to_wrong'] for p in s)}, "
                   f"to right {sum(p['to_right'] for p in s)}; by position "
                   + ", ".join(f"{k}: {fmt(sum(p['flip'] for p in s if p['position'] == k), sum(p['position'] == k for p in s))}" for k in range(3))
                   + "; by peers 0 / >= 1: "
                   + " / ".join(fmt(sum(p['flip'] for p in s if min(p['peers_right'], 1) == k), sum(min(p['peers_right'], 1) == k for p in s)) for k in (0, 1)))
    out.append("")
    out.append("## Determinism")
    out.append(f"- control rep 0 final != recorded final: {sum(p['control_vs_recorded'] for p in pts)}/{len(pts)}")
    rr = defaultdict(lambda: [0, 0])
    for p in pts:
        if len(p["reps"]) > 1:
            rr[p["rep_reason"]][1] += 1
            rr[p["rep_reason"]][0] += len(set(p["reps"])) > 1
    for k, (a, n) in sorted(rr.items(), key=str):
        out.append(f"- control re-runs ({k}): disagree {a}/{n}")
    # post hoc (not pre-registered): temperature 0 turned out not to be deterministic with this provider, so a
    # flip can be downstream noise. Noise baseline = control-vs-control disagreement, reweighted to all points.
    n_all = len(pts)
    fl = [p for p in pts if p["flip"] and len(p["reps"]) > 1]
    un = [p for p in pts if not p["flip"] and len(p["reps"]) > 1]
    nf, nu = sum(p["flip"] for p in pts), n_all - sum(p["flip"] for p in pts)
    if fl and un:
        d_f = sum(len(set(p["reps"])) > 1 for p in fl) / len(fl)
        d_u = sum(len(set(p["reps"])) > 1 for p in un) / len(un)
        out.append(f"- control-vs-control disagreement reweighted to all {n_all} points (post hoc noise baseline): "
                   f"{(d_f * nf + d_u * nu) / n_all:.3f} (flipped share {d_f:.2f}, undetermined share {d_u:.2f} of "
                   f"{len(un)}, upper bound for the latter ~{min(1, 3 / len(un)):.2f})")
    out.append("")
    out.append("## Post hoc: flips confirmed by the second control (control rep 1 == control rep 0)")
    for name in ("main", "ctl1", "ctl2"):
        s = [p for p in pts if kind(p) == name]
        cells = []
        for k in range(3):
            sk = [p for p in s if p["position"] == k]
            conf = sum(p["flip"] and len(p["reps"]) > 1 and len(set(p["reps"])) == 1 for p in sk)
            rb = sum(p["flip"] and len(p["reps"]) > 1 and p["reps"][-1] == p["branch_final"] and len(set(p["reps"])) > 1 for p in sk)
            cells.append(f"pos {k}: flips {sum(p['flip'] for p in sk)}, confirmed {conf}, 2nd control = branch {rb} (of {len(sk)})")
        out.append(f"- {name}: " + "; ".join(cells))
        for peer in (0, 1):
            sp = [p for p in s if min(p["peers_right"], 1) == peer]
            conf = sum(p["flip"] and len(p["reps"]) > 1 and len(set(p["reps"])) == 1 for p in sp)
            out.append(f"  - peers right {'0' if peer == 0 else '>= 1'}: flips {sum(p['flip'] for p in sp)}/{len(sp)}, confirmed {conf}")
    return pts, "\n".join(out)


def rep1_plan(pts, d, share=0.10, seed=0):
    rng = random.Random(seed)
    und = [p for p in pts if not p["flip"]]
    pick = [p for p in pts if p["flip"]] + rng.sample(und, max(1, round(share * len(und))))
    by = defaultdict(list)
    for p in pick:
        by[p["pass"]].append(p["qid"])
    path = os.path.join(d, "rep1_plan.txt")
    with open(path, "w") as f:
        for k in sorted(by):
            f.write(f"{k} {','.join(sorted(by[k]))}\n")
    print(f"rep1 plan: {len(pick)} points ({sum(p['flip'] for p in pick)} flips) -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/home/claude/branch_planA")
    ap.add_argument("--rep1_plan", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    pts, txt = report(a.dir)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")
    if a.rep1_plan:
        rep1_plan(pts, a.dir)


if __name__ == "__main__":
    main()
