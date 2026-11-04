"""Trivial baselines on the v3 eval set (v11 r12; replicates MHT #1 round 84 section 2 and extends it to
triage_agent / MAM / multimodal / expansion jobs). Offline, no API.

Within each parent run that has >= 1 positive, compare positive points with the other points of the same
run (all labelled points of that run): within-trajectory AUROC = share of (positive, other) pairs where the
positive scores higher (ties 0.5), pooled over runs; 95% CI by bootstrap over parent runs.
Scores: step length (characters of the parent's step-t output), relative position (t / (n_steps - 1)).
Final-call-only positives (declared D(t) empty and nothing after t regenerated) are excluded, as by MHT.
Judgment: positives under the job's own rule (column `rule`) and, separately, under the pooled reference.
  branch_v3_baselines.py --root data_runs/eval_v3_2026-11-04 [--group framework]"""
import argparse, glob, gzip, json, os, random, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from branch_pilot import llm_steps  # noqa: E402
from branch_identity import normal_run_id  # noqa: E402


def rows(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def auroc(groups):
    num = den = 0.0
    for pos, neg in groups:
        for a in pos:
            for b in neg:
                num += 1.0 if a > b else 0.5 if a == b else 0.0
                den += 1
    return num / den if den else float("nan")


def ci(groups, n=1000, seed=0):
    rng = random.Random(seed)
    vals = sorted(auroc([groups[rng.randrange(len(groups))] for _ in groups]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--group", choices=["job", "framework"], default="job")
a = ap.parse_args()

steps = {}   # run_id -> {step_id: (index, n_steps, length)}
for p in glob.glob(os.path.join(a.root, "parents", "*.jsonl.gz")):
    for r in rows(p):
        h = llm_steps(r)
        steps[normal_run_id(r)] = {s["step_id"]: (i, len(h), len(s.get("content") or "")) for i, s in enumerate(h)}

data = defaultdict(lambda: defaultdict(list))   # group -> run_id -> [(is_pos, is_pos_pooled, len, relpos)]
miss = 0
for d in sorted(glob.glob(os.path.join(a.root, "*", "labels_v3.jsonl.gz"))):
    job = os.path.basename(os.path.dirname(d))
    for l in rows(d):
        ctx, st = l["context"], l["statistics"]
        if l["judgment"] == "positive" and ctx.get("dt_empty") and not ctx.get("downstream_regenerated"):
            continue
        rid, sid = l["target"]["run_id"], l["target"]["step_ids"][0]
        info = steps.get(rid, {}).get(sid)
        if info is None:
            miss += 1
            continue
        i, n, ln = info
        g = job if a.group == "job" else l["framework"] + ("_mm" if job.startswith("mm_") else "")
        pooled = st.get("stage") == 2 and (st.get("p_value_pooled") or 1) < 0.05
        data[g][rid].append((l["judgment"] == "positive", pooled, ln, i / max(1, n - 1)))

print(f"(points without parent step: {miss})\n")
print("| group | rule | parents with ≥1 positive | positives | step length AUROC [95% CI] | relative position AUROC [95% CI] |")
print("|---|---|---|---|---|---|")
for g in sorted(data):
    for rule, k in (("own", 0), ("pooled", 1)):
        L, P = [], []
        npos = 0
        for rid, pts in data[g].items():
            pos = [x for x in pts if x[k]]
            neg = [x for x in pts if not x[k]]
            if not pos or not neg:
                continue
            npos += len(pos)
            L.append(([x[2] for x in pos], [x[2] for x in neg]))
            P.append(([x[3] for x in pos], [x[3] for x in neg]))
        if not L:
            continue
        lo, hi = ci(L); plo, phi = ci(P)
        print(f"| {g} | {rule} | {len(L)} | {npos} | {auroc(L):.3f} [{lo:.3f}, {hi:.3f}] | {auroc(P):.3f} [{plo:.3f}, {phi:.3f}] |")
