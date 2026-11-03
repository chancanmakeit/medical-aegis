#!/usr/bin/env python3
"""Question pools for the gemini batch (v11 round 6; issue #1 r51, #3 r52).

MedXpertQA-Text (2,450) minus the 100 anchor questions (already in MedHyperTrace's TAPT corpus) minus MAA
overlaps (exact + probe, maa_exclusion_v1), then near-duplicate groups (question stem word-set Jaccard >= 0.3,
connected components) so that a whole group lands in one pool, and groups touching an anchor question are
dropped. The rest is split by group into
  eval    -- branching eval set / held-out frameworks; never enters any training corpus
  corpus  -- natural runs that may be used for (interaction) continued pre-training
task_group_id = "mxq-g<k>" (component id); singletons keep their own group.

  python3 scripts/build_question_pools.py [--eval_n 400] [--seed 0]
writes datasets/data/pools_v1/{eval,corpus}.json and pools_v1/manifest.json
"""
import argparse
import json
import os
import random
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from export_schema_v1 import load_maa_exclusion, maa_overlap  # noqa: E402

OPT = re.compile(r"\n\s*Options:|\nAnswer Choices|\n\(?A[\).:]", re.S)


def stem_words(q):
    s = OPT.split(q, maxsplit=1)[0].lower()
    return set(w for w in re.findall(r"[a-z0-9]+", s) if len(w) > 2)


def components(items, thr):
    """Union-find over Jaccard >= thr (inverted index on words; exact pairwise check)."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    inv = defaultdict(list)
    for i, w in enumerate(items):
        for t in w:
            inv[t].append(i)
    n_pairs = 0
    for i, w in enumerate(items):
        cand = defaultdict(int)
        for t in w:
            if len(inv[t]) > 400:          # very common words: no signal, skip for speed
                continue
            for j in inv[t]:
                if j > i:
                    cand[j] += 1
        for j, inter in cand.items():
            union = len(w) + len(items[j]) - inter
            if union and inter / union >= thr:
                parent[find(i)] = find(j)
                n_pairs += 1
    return [find(i) for i in range(len(items))], n_pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval_n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--thr", type=float, default=0.3)
    ap.add_argument("--out", default=os.path.join(REPO, "datasets/data/pools_v1"))
    a = ap.parse_args()
    allq = json.load(open(os.path.join(REPO, "datasets/data/medxpertqa_text.json")))
    anchor = {d["id"] for d in json.load(open(os.path.join(REPO, "datasets/data/anchor_medxpertqa100.json")))}
    ex = load_maa_exclusion(os.path.join(REPO, "docs/requests/maa_exclusion_v1.json"))
    maa = set()
    for d in allq:
        exact, probe = maa_overlap({"task": {"query": d["query"], "images": []}}, ex)
        if exact or probe:
            maa.add(d["id"])
    words = [stem_words(d["query"]) for d in allq]
    comp, n_pairs = components(words, a.thr)
    groups = defaultdict(list)
    for d, c in zip(allq, comp):
        groups[c].append(d["id"])
    gid = {}
    for k, (c, ids) in enumerate(sorted(groups.items(), key=lambda x: min(x[1]))):
        for i in ids:
            gid[i] = f"mxq-g{k}"
    bad_groups = {gid[i] for i in anchor | maa}
    usable_groups = sorted({gid[d["id"]] for d in allq} - bad_groups)
    rng = random.Random(a.seed)
    rng.shuffle(usable_groups)
    eval_g, n = set(), 0
    size = defaultdict(int)
    for d in allq:
        size[gid[d["id"]]] += 1
    for g in usable_groups:
        if n >= a.eval_n:
            break
        eval_g.add(g)
        n += size[g]
    os.makedirs(a.out, exist_ok=True)
    pools = {"eval": [], "corpus": []}
    order = {g: i for i, g in enumerate(usable_groups)}
    for d in allq:
        g = gid[d["id"]]
        if g in bad_groups:
            continue
        pools["eval" if g in eval_g else "corpus"].append(dict(d, task_group_id=g))
    for k in pools:
        pools[k].sort(key=lambda d: (order[d["task_group_id"]], d["id"]))   # seeded order: take the first N
        json.dump(pools[k], open(os.path.join(a.out, f"{k}.json"), "w"), ensure_ascii=False)
    multi = sum(1 for ids in groups.values() if len(ids) > 1)
    man = {"version": "pools_v1", "source": "datasets/data/medxpertqa_text.json", "n_source": len(allq),
           "excluded_anchor": len(anchor), "excluded_maa": len(maa - anchor),
           "excluded_by_group": sum(1 for d in allq if gid[d["id"]] in bad_groups) - len(anchor | maa),
           "near_dup_rule": f"question-stem word-set Jaccard >= {a.thr} (words > 2 chars, options cut), connected components",
           "n_groups_with_more_than_one_question": multi, "n_similar_pairs": n_pairs,
           "eval_n": len(pools["eval"]), "corpus_n": len(pools["corpus"]), "seed": a.seed,
           "rule": "eval questions never enter any training corpus; the split is by task_group_id; "
                   "files are in a seeded group order, take the first N for a batch",
           "review_status": "automatic (no manual review of near-duplicate groups yet)"}
    json.dump(man, open(os.path.join(a.out, "manifest.json"), "w"), indent=1)
    print(json.dumps(man, indent=1))


if __name__ == "__main__":
    main()
