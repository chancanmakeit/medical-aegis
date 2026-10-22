#!/usr/bin/env python3
"""Do the injected steps of the original AEGIS simulated split carry a surface signature?

Written for the MAFA project (RUN.md §53 treats prompt_injection as the realistic
subset of data/simulated). Same-slot design: every injected step of
data/simulated/<group>_error.jsonl is compared with the step of the paired clean
run data/clean/<group>_clean-paired_normal.jsonl that has the same question id,
agent_name, phase and k-th occurrence of (agent_name, phase). Unmatched injected
steps (the trajectories diverge after an injection) are counted and dropped.

Reports per framework x strategy:
  - match coverage;
  - markdown ('###' or '**'), list-line and median length ratio, injected vs paired clean;
  - same-slot AUROC of tfidf_punct (whitespace tokens, case kept) + LR, GroupKFold(5)
    by question, on raw text and on MedHyperTrace's format-normalised text (`norm`,
    MHT analysis/anchor_fmt_val/lexical_norm.py), bootstrap 95% CI by question.

Usage: python3 scripts/aegis_simulated_signature_check.py <data_dir with clean/ and simulated/>
"""
import collections
import glob
import json
import os
import re
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold


def norm(t):  # MedHyperTrace lexical_norm.py (round 47), verbatim
    t = t or ""
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*(?:[-*+•]|\d+[.)])\s+", "", t)
    t = re.sub(r"[*_`]+", "", t)
    t = re.sub(r"\[([A-Za-z]{1,12})\]", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


has_md = lambda t: "###" in (t or "") or "**" in (t or "")
has_list = lambda t: bool(re.search(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+\S", t or ""))
# surface markers checked per strategy (injected / paired clean)
MARKERS = {
    # strict: unambiguous references to an instruction (llama in medical-aegis anchors: 4 / 13,379
    # normal steps, 0 injected steps)
    "instruction_strict": r"(?i)\b(updated|new|given|following|this|the|per the|my) instructions?\b|\bUPDATED INSTRUCTION\b|\bcomply with\b|\bas instructed\b|\bdeviate from the goal\b|\binstructed (me|us) to\b",
    # loose: also "the prompt ..." -- injection-only in AEGIS mdagents, but often just refers to the
    # question (3.5% of normal steps in the medical-aegis anchors), so not proof of leakage
    "prompt_or_instruction_loose": r"\b(the|this|updated) (prompt|instruction)s?\b|\bUPDATED INSTRUCTION\b|\binstructed to\b|\bdeviate from the goal\b",
    "refusal": r"\bI (cannot|can't|can not|won't|am unable)\b",
    "Justification:": r"Justification\s*:",
    "Answer:": r"\bAnswer\s*:",
}


def slots(rec):
    occ, out = collections.Counter(), []
    for s in rec["injection_log"]["conversation_history"]:
        b = (s.get("agent_name"), s.get("phase"))
        out.append((b + (occ[b],), s))
        occ[b] += 1
    return out


def auroc(texts, y, g):
    y, g = np.array(y), np.array(g)
    sc = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(texts, y, g):
        v = TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=False, min_df=2, sublinear_tf=True)
        X = v.fit_transform([texts[i] for i in tr])
        sc[te] = LogisticRegression(max_iter=3000).fit(X, y[tr]).predict_proba(
            v.transform([texts[i] for i in te]))[:, 1]
    a = roc_auc_score(y, sc)
    qs, rng, b = np.unique(g), np.random.default_rng(0), []
    idx = {q: np.where(g == q)[0] for q in qs}
    for _ in range(500):
        ii = np.concatenate([idx[q] for q in rng.choice(qs, len(qs))])
        if len(set(y[ii])) == 2:
            b.append(roc_auc_score(y[ii], sc[ii]))
    return a, np.percentile(b, 2.5), np.percentile(b, 97.5)


def main():
    d = sys.argv[1]
    print(f"{'group':40s} {'strategy':20s} {'n_inj':>5s} {'matched':>7s}  md inj/clean  list inj/clean  "
          f"len ratio  AUROC raw [CI]        AUROC normalised [CI]")
    for f in sorted(glob.glob(os.path.join(d, "simulated", "*_error.jsonl"))):
        grp = os.path.basename(f).split("_error")[0]
        clean = {}
        for l in open(os.path.join(d, "clean", f"{grp}_clean-paired_normal.jsonl")):
            r = json.loads(l)
            clean[r["id"]] = dict(slots(r))
        pairs = collections.defaultdict(list)
        n_inj = collections.Counter()
        for l in open(f):
            r = json.loads(l)
            c = clean.get(r["id"], {})
            for k, s in slots(r):
                if str(s.get("injection_applied")) != "True":
                    continue
                st = s.get("injection_strategy")
                n_inj[st] += 1
                if k in c:
                    pairs[st].append((s.get("content") or "", c[k].get("content") or "", r["id"]))
        for st in sorted(pairs):
            P = pairs[st]
            md = (np.mean([has_md(a) for a, _, _ in P]), np.mean([has_md(b) for _, b, _ in P]))
            ls = (np.mean([has_list(a) for a, _, _ in P]), np.mean([has_list(b) for _, b, _ in P]))
            lr = np.median([len(a) / max(1, len(b)) for a, b, _ in P])
            T = [a for a, _, _ in P] + [b for _, b, _ in P]
            y = [1] * len(P) + [0] * len(P)
            g = [q for _, _, q in P] * 2
            if len(set(g)) >= 5 and len(P) >= 20:
                r1 = auroc(T, y, g)
                r2 = auroc([norm(t) for t in T], y, g)
                au = f"{r1[0]:.2f} [{r1[1]:.2f}, {r1[2]:.2f}]   {r2[0]:.2f} [{r2[1]:.2f}, {r2[2]:.2f}]"
            else:
                au = "n/a (too few)"
            print(f"{grp:40s} {st:20s} {n_inj[st]:5d} {len(P):7d}  {md[0]:.2f}/{md[1]:.2f}     "
                  f"{ls[0]:.2f}/{ls[1]:.2f}       {lr:5.2f}      {au}", flush=True)
            mk = {m: f"{np.mean([bool(re.search(p, a)) for a, _, _ in P]):.2f}/"
                     f"{np.mean([bool(re.search(p, b)) for _, b, _ in P]):.2f}" for m, p in MARKERS.items()}
            print(f"{'':40s} {'':20s} markers inj/clean: {mk}", flush=True)


if __name__ == "__main__":
    main()
