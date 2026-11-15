"""Choose the first MAFA doctor-annotation batch from annotation_ready/ (v11 r15, 2026-11-15).

8 groups: agentverse, mdagents (MedXpertQA-Text), mdagents-MM (the 4 image datasets pooled), llm_debate,
medagents_mc, mac_groupchat, triage_agent, dylan. Per group N wrong + N right runs (default 20 + 20):
  wrong: first runs whose v3 counterfactual labels have >= 1 positive step, then other v3 parents, then other
         wrong runs (random order, fixed seed);
  right: for triage_agent, right runs of the same cases as the chosen wrong ones first (each case has 4 runs);
         otherwise random right runs.
Writes the MAFA trace ids (`<fw>::<file stem>#<0-based line, 5 digits>#<id>`) and an organiser-only manifest.
  select_mafa_batch.py --manifest .../manifest.jsonl --out_ids ids.txt --out_manifest sel.jsonl [--n 20]"""
import argparse, collections, json, os, random

ap = argparse.ArgumentParser()
ap.add_argument("--manifest", required=True)
ap.add_argument("--out_ids", required=True)
ap.add_argument("--out_manifest", required=True)
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--seed", type=int, default=20261115)
a = ap.parse_args()

rows = [json.loads(l) for l in open(a.manifest, encoding="utf-8")]
groups = collections.defaultdict(list)
for r in rows:
    g = r["framework"] + ("_mm" if r["pool"].startswith("mm_") else "")
    groups[g].append(r)


def tid(r):
    stem = os.path.basename(r["file"])[:-len(".jsonl")]
    return f'{r["framework"]}::{stem}#{r["line"] - 1:05d}#{r["id"]}'


rng = random.Random(a.seed)
chosen = []
for g in sorted(groups):
    rs = groups[g][:]
    rng.shuffle(rs)
    wrong = [r for r in rs if not r["is_correct"]]
    right = [r for r in rs if r["is_correct"]]
    tier = lambda r: 0 if r["v3_positive_steps"] else 1 if r["v3_branch_parent"] else 2  # noqa: E731
    w = sorted(wrong, key=tier)[:a.n]
    if g == "triage_agent":
        ids = {r["id"] for r in w}
        right = sorted(right, key=lambda r: 0 if r["id"] in ids else 1)
    c = right[:a.n]
    for r in w + c:
        chosen.append(dict(r, group=g, trace_id=tid(r)))
    print(f"{g:16s} wrong {len(w)} (with positives {sum(1 for r in w if r['v3_positive_steps'])}) right {len(c)}")
with open(a.out_ids, "w") as f:
    f.write("\n".join(r["trace_id"] for r in chosen) + "\n")
with open(a.out_manifest, "w", encoding="utf-8") as f:
    for r in chosen:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("total", len(chosen))
