"""Re-stamp branch identity in finished v3 batches whose blocks have problems (v11 r9).
Used once for MAM: batches whose only upstream calls were answer-judge requests were stamped with
sample-blind keys, so the control arm's step t was not found (t_step_id_in_run None). Re-stamping is
deterministic from the out/calls files; the API is not called.
  branch_restamp.py --dir D --fw FW --recorded F [--dataset F] [--sample_keys]"""
import argparse, glob, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import branch_pilot as bp
import branch_identity as bi
from replay_openai_server import step_key as replay_key

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True); ap.add_argument("--fw", required=True)
ap.add_argument("--recorded", required=True); ap.add_argument("--sample_keys", action="store_true")
a = ap.parse_args()
bp.RECORDED = a.recorded; bp.SAMPLE_KEYS = a.sample_keys
bi.PROTOCOL_ID = bi.PROTOCOL_ID_V3
cands = [json.loads(l) for l in open(os.path.join(a.dir, f"{a.fw}_candidates.jsonl"))]
allrec = bp.recorded_all(a.fw)
fixed = left = 0
for out in sorted(glob.glob(os.path.join(a.dir, "runs", f"{a.fw}_p*_out.jsonl"))):
    recs = [json.loads(l) for l in open(out) if l.strip()]
    if not any(r.get("branch") and bi.block_problems(r["branch"]) for r in recs):
        continue
    m = re.search(r"_p(\d+)_(branch|control)_rep(\d+)_out", out)
    p, arm, rep = int(m.group(1)), m.group(2), int(m.group(3))
    ids = {r["id"] for r in recs}
    cp = [c for c in cands if c["pass"] == p and c["qid"] in ids]
    for c in cp:
        ph = bp.llm_steps(bp.rec_of(allrec, c))
        c["parent_step_ids"] = [s["step_id"] for s in ph]
        n_pre = c["t"] + (0 if arm == "branch" else 1)
        c["parent_prefix_sha1"] = [bi.sha1(s.get("content")) for s in ph[:n_pre]]
        c["parent_keys"] = [(s["step_id"], replay_key(bp.rec_of(allrec, c), s, a.sample_keys)) for s in ph]
    old = {r["id"]: r["branch"] for r in recs if r.get("branch")}
    exp = next(iter(old.values()))["experiment_id"]
    reasons = {q: (b.get("selection") or {}).get("repetition_reason") for q, b in old.items()} if rep > 0 else None
    bad = bi.stamp_file(out, cp, arm, rep, out.replace("_out.jsonl", "_calls.jsonl"), exp, reasons, a.fw)
    fixed += 1; left += len(bad)
    if bad:
        print(os.path.basename(out), bad[:2])
print(f"restamped {fixed} files; problems left {left}")
