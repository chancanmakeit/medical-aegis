"""Aggregate table of the protocol-v3 eval set (v11 r9, r11): one row per job from labels_v3.jsonl(.gz).
  branch_v3_report.py --root data_runs/eval_v3_2026-11-04 > table.md
Columns: parents / points; noise floor (stage-1 control rep0 != rep1); share of points that went to stage 2;
positives under the job's reference rule; positives with the pooled (symmetric) reference; E0 = expected
positives if t had no effect (permutation null of the full procedure) and FDR ~ E0 / positives (MHT #1 r84);
final-call-only positives (declared D(t) empty and no step after t regenerated: they only measure resampling
of the last call); positives that change correctness; wrong -> right."""
import argparse, glob, gzip, json, os
from collections import Counter

ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True)
a = ap.parse_args()


def rows(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


print("| job | framework | rule | parents | points | noise floor | to stage 2 | positives | pooled-ref positives | "
      "E0 | FDR ≈ | final-call-only | correctness changed | wrong → right | needs stage 2 |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
tot = Counter()
for d in sorted(glob.glob(os.path.join(a.root, "*", "labels_v3.jsonl*"))):
    job = os.path.basename(os.path.dirname(d))
    L = rows(d)
    S = [l["statistics"] for l in L]
    fw = L[0]["framework"]
    rule = next((s.get("reference_rule") for s in S if s.get("reference_rule")), "control")
    J = Counter(l["judgment"] for l in L)
    noise = sum(1 for s in S if (s.get("control_finals") or [None, None])[:2] and
                len(s.get("control_finals") or []) >= 2 and s["control_finals"][0] != s["control_finals"][1])
    st2 = [s for s in S if s.get("stage") == 2]
    pos = [l for l in L if l["judgment"] == "positive"]
    npool = sum(1 for s in st2 if (s.get("p_value_pooled") or 1) < 0.05)
    e0 = sum(s.get("p_null_positive") or 0 for s in st2)
    fco = sum(1 for l in pos if l["context"].get("dt_empty") and not l["context"].get("downstream_regenerated"))
    cc = sum(1 for l in pos if l["endpoints"].get("correctness_changed"))
    wr = sum(1 for l in pos if l["endpoints"].get("branch_majority_correct"))
    parents = len({l["target"]["run_id"] for l in L})
    print(f"| {job} | {fw} | {rule} | {parents} | {len(L)} | {noise / len(L):.3f} | {len(st2) / len(L):.2f} | {len(pos)} | "
          f"{npool} | {e0:.1f} | {e0 / max(1, len(pos)):.2f} | {fco} | {cc} | {wr} | {J['needs_stage2']} |")
    tot.update(points=len(L), positives=len(pos), pooled=npool, e0=e0, fco=fco, needs=J["needs_stage2"])
print(f"\nTotal: {tot['points']} points, {tot['positives']} positives (pooled reference: {tot['pooled']}), "
      f"E0 {tot['e0']:.1f}, {tot['fco']} final-call-only positives, {tot['needs']} points still need stage 2.")
