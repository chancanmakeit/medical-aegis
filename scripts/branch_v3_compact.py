"""Compact archive of a v3 branching eval job (v11 r9).

Full branch outputs are ~9 GB (every record repeats the parent's replayed steps). The archive keeps, per
branch record: id, run_index, the `branch` identity block, the final response / extracted answer /
correctness, and the text of the REGENERATED steps only. Replayed steps are the parent's steps
(verified by the identity stamp: prefix sha1 and replay keys), so a full record is rebuilt from the frozen
parent (`<fw>__normal_*.jsonl.gz`) + the regenerated steps.
  branch_v3_compact.py --dir /home/claude/eval_v3/<job> --out data_runs/eval_v3_2026-11-04/<job>
"""
import argparse, glob, gzip, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from branch_pilot import final_answer, llm_steps  # noqa: E402

KEEP_STEP = ("step_id", "agent_name", "phase", "round", "content")

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
n = skipped = 0
with gzip.open(os.path.join(a.out, "branch_records_compact.jsonl.gz"), "wt", encoding="utf-8") as g:
    for f in sorted(glob.glob(os.path.join(a.dir, "runs", "*_out.jsonl"))):
        for l in open(f, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            b = r.get("branch")
            if b is None:            # interrupted batch, rerun later; not part of the eval set
                skipped += 1
                continue
            regen = set(b.get("regenerated_step_ids") or [])
            steps = [{k: s.get(k) for k in KEEP_STEP} for s in llm_steps(r) if s.get("step_id") in regen]
            g.write(json.dumps({"source_file": os.path.basename(f), "id": r["id"], "run_index": r.get("run_index"),
                                "framework": r.get("framework"), "model": r.get("model"), "status": r.get("status"),
                                "response": r.get("response"), "final_answer": final_answer(r) or "NONE",
                                "is_correct": r.get("is_correct"), "branch": b, "regenerated_steps": steps},
                               ensure_ascii=False) + "\n")
            n += 1
for pat in ("labels_v3.jsonl", "summary.md", "*_candidates.jsonl", "*_stage2_plan.txt", "PAUSED", "*_parents_*.json"):
    for f in glob.glob(os.path.join(a.dir, pat)):
        dst = os.path.join(a.out, os.path.basename(f))
        if f.endswith(".jsonl"):
            with open(f, "rb") as s, gzip.open(dst + ".gz", "wb") as d:
                shutil.copyfileobj(s, d)
        else:
            shutil.copy(f, dst)
print(f"{a.dir}: {n} records archived, {skipped} unstamped skipped")
