"""Parent files for the v3 expansion (v11 r11): new natural runs (run_index >= 1) plus run-0 parents NOT used
by the first v3 batch (their qids are read from that batch's candidates), so no point is labelled twice.
  build_expansion_parents.py --out F --new R1.jsonl [--new R2.jsonl] [--old R0.jsonl --used_candidates C.jsonl]"""
import argparse, json
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True); ap.add_argument("--new", action="append", default=[])
ap.add_argument("--old"); ap.add_argument("--used_candidates")
a = ap.parse_args()
used = {(c["qid"], int(c.get("run_index", 0))) for c in map(json.loads, open(a.used_candidates))} if a.used_candidates else set()
n_old = n_new = 0
with open(a.out, "w", encoding="utf-8") as f:
    if a.old:
        for l in open(a.old, encoding="utf-8"):
            r = json.loads(l)
            if (r["id"], int(r.get("run_index", 0))) not in used:
                f.write(l if l.endswith("\n") else l + "\n"); n_old += 1
    for p in a.new:
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            assert int(r.get("run_index", 0)) >= 1, "new runs must have run_index >= 1"
            f.write(l if l.endswith("\n") else l + "\n"); n_new += 1
print(f"{a.out}: {n_old} unused run-0 records + {n_new} new records; excluded {len(used)} used parents")
