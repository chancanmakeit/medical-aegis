"""Aggregate table of the protocol-v3 eval set (v11 r9): one row per job from labels_v3.jsonl + candidates.
  branch_v3_report.py --root data_runs/eval_v3_2026-11-04 > table.md
Columns: parents / points; noise floor (stage-1 control rep0 != rep1); share of points that went to stage 2;
positives (Fisher one-sided p < 0.05); positives at points with empty D(t) (final / aggregator step: they only
measure resampling of the last call); correctness_changed; wrong -> right among positives."""
import argparse, glob, gzip, json, os
from collections import Counter

ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True)
a = ap.parse_args()


def rows(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


print("| job | framework | parents | points | noise floor | to stage 2 | positives | of which D(t) empty | "
      "positives, D(t) non-empty | correctness changed | wrong → right | undetermined | still needs stage 2 |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
tot = Counter()
for d in sorted(glob.glob(os.path.join(a.root, "*", "labels_v3.jsonl.gz"))):
    job = os.path.basename(os.path.dirname(d))
    L = rows(d)
    cands = {}
    for cf in glob.glob(os.path.join(os.path.dirname(d), "*_candidates.jsonl.gz")):
        for c in rows(cf):
            cands[(c["qid"], int(c.get("run_index", 0)), c["t_step_id"])] = c
    fw = L[0]["framework"]
    J = Counter(l["judgment"] for l in L)
    noise = sum(1 for l in L if (l["statistics"].get("control_finals") or [None, None])[0]
                != (l["statistics"].get("control_finals") or [None, None])[1])
    st2 = sum(1 for l in L if l["statistics"].get("stage") == 2)
    pos = [l for l in L if l["judgment"] == "positive"]

    def empty_dt(l):
        t = l["target"]
        qid = t["run_id"].split("|")[3]
        ri = int(t["run_id"].split("|")[-1].lstrip("r"))
        c = cands.get((qid, ri, t["step_ids"][0]))
        return c is not None and not c.get("force_step_ids")
    pe = sum(1 for l in pos if empty_dt(l))
    cc = sum(1 for l in pos if l["endpoints"].get("correctness_changed"))
    wr = sum(1 for l in pos if l["endpoints"].get("branch_majority_correct"))
    parents = len({l["target"]["run_id"] for l in L})
    print(f"| {job} | {fw} | {parents} | {len(L)} | {noise / len(L):.3f} | {st2 / len(L):.2f} | {len(pos)} | {pe} | "
          f"{len(pos) - pe} | {cc} | {wr} | {J['undetermined']} | {J['needs_stage2']} |")
    tot.update(points=len(L), positives=len(pos), empty=pe, needs=J["needs_stage2"])
print(f"\nTotal: {tot['points']} points, {tot['positives']} positives ({tot['empty']} at empty D(t)), "
      f"{tot['needs']} points still need stage 2.")
