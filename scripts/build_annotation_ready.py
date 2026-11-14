"""Build the doctor-annotation-ready subset for MAFA-human-ai-annotation (v11 r14, 2026-11-14).

Source: the frozen natural (non-injected, non-branch) runs of the protocol-v3 eval set
(data_runs/eval_v3_2026-11-04/parents/*.jsonl.gz; gemini-2.5-flash-lite, temperature 0.7).
Output layout (what MAFA's loader expects, see its RUN.md / scripts/_common.py):
  <out>/data/faulty/<framework>__normal_<pool>.jsonl   runs whose final answer is wrong
  <out>/data/clean/<framework>__normal_<pool>.jsonl    runs whose final answer is right
  <out>/specs/*.json                                   MAFA MappingSpecs for these files
  <out>/images/<basename>                              images referenced by multimodal runs
  <out>/manifest.jsonl                                 one row per run: trace file + line, run ids,
                                                       v3 counterfactual labels (HIDDEN from annotators)
Records are the raw AEGIS-format records, unchanged except: duplicate (framework, id, run_index,
dataset) rows are dropped (the *_x expansion files repeat unused run-0 parents), a top-level
`images` list of basenames is added for multimodal runs (MAFA reads `images`), and the local
`image_paths` / task_observations[*].path are rewritten to `images/<basename>`.
MAM (audio) is left out: the MAFA review tool cannot play audio.
  build_annotation_ready.py --root data_runs/eval_v3_2026-11-04 --specs DIR --out DIR"""
import argparse, collections, glob, gzip, json, os, shutil

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--specs", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()

# v3 labels per parent run: positive / undetermined step ids (kept out of the trace files)
lab = collections.defaultdict(lambda: {"points": 0, "positive_steps": [], "positive_steps_pooled": []})
for f in glob.glob(os.path.join(a.root, "*", "labels_v3.jsonl.gz")):
    job = os.path.basename(os.path.dirname(f))
    for l in gzip.open(f, "rt", encoding="utf-8"):
        r = json.loads(l)
        rid = r["target"]["run_id"]
        d = lab[rid]
        d["points"] += 1
        d.setdefault("jobs", set()).add(job)
        st = r["statistics"]
        if r["judgment"] == "positive":
            d["positive_steps"].append(r["target"]["step_ids"][0])
        if st.get("stage") == 2 and (st.get("p_value_pooled") or 1) < 0.05:
            d["positive_steps_pooled"].append(r["target"]["step_ids"][0])

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from branch_identity import normal_run_id  # noqa: E402

os.makedirs(os.path.join(a.out, "images"), exist_ok=True)
for split in ("faulty", "clean"):
    os.makedirs(os.path.join(a.out, "data", split), exist_ok=True)
os.makedirs(os.path.join(a.out, "specs"), exist_ok=True)
for s in glob.glob(os.path.join(a.specs, "*.json")):
    shutil.copy(s, os.path.join(a.out, "specs"))

seen = set()
writers, lines = {}, collections.Counter()
manifest = open(os.path.join(a.out, "manifest.jsonl"), "w", encoding="utf-8")
stats = collections.Counter()
for f in sorted(glob.glob(os.path.join(a.root, "parents", "*.jsonl.gz"))):
    base = os.path.basename(f)[:-len(".jsonl.gz")]
    fw = base.split("__")[0]
    if fw == "mam":
        continue
    pool = base.split("__normal_")[1]
    for suf in ("_x", "_r123", "_r1"):
        pool = pool[:-len(suf)] if pool.endswith(suf) else pool
    for l in gzip.open(f, "rt", encoding="utf-8"):
        r = json.loads(l)
        key = (fw, r["id"], r.get("run_index", 0), r.get("dataset"))
        if key in seen or not r["injection_log"]["conversation_history"]:
            continue
        seen.add(key)
        imgs = []
        for p in r.get("image_paths") or []:
            b = os.path.basename(p)
            dst = os.path.join(a.out, "images", b)
            if not os.path.exists(dst):
                shutil.copy(p, dst)
            imgs.append(b)
        if imgs:
            r["images"] = imgs
            r["image_paths"] = [f"images/{b}" for b in imgs]
            for o in r["injection_log"].get("task_observations") or []:
                if o.get("path"):
                    o["path"] = "images/" + os.path.basename(o["path"])
        split = "clean" if r.get("is_correct") else "faulty"
        name = f"{fw}__normal_{pool}.jsonl"
        k = (split, name)
        if k not in writers:
            writers[k] = open(os.path.join(a.out, "data", split, name), "w", encoding="utf-8")
        writers[k].write(json.dumps(r, ensure_ascii=False) + "\n")
        lines[k] += 1
        rid = normal_run_id(r)
        L = lab.get(rid)
        manifest.write(json.dumps({
            "file": f"data/{split}/{name}", "line": lines[k], "framework": fw, "pool": pool,
            "dataset": r.get("dataset"), "id": r["id"], "run_index": r.get("run_index", 0),
            "run_id": rid, "is_correct": bool(r.get("is_correct")), "n_steps": len(r["injection_log"]["conversation_history"]),
            "v3_branch_parent": L is not None,
            "v3_points": L["points"] if L else 0,
            "v3_positive_steps": L["positive_steps"] if L else [],
            "v3_positive_steps_pooled": L["positive_steps_pooled"] if L else [],
        }, ensure_ascii=False) + "\n")
        stats[(fw, pool, split)] += 1
for w in writers.values():
    w.close()
manifest.close()
for k, v in sorted(stats.items()):
    print(k, v)
print("images", len(os.listdir(os.path.join(a.out, "images"))))
