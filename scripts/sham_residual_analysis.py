#!/usr/bin/env python3
"""What is left of the sham signature after format normalisation? (MHT round 47 request)

Same-slot comparison: each injected step vs the normal steps of the same question,
agent_id, phase, round and k-th occurrence. Text is normalised with MedHyperTrace's
`norm()` (analysis/anchor_fmt_val/lexical_norm.py: headings, list markers, *_` marks,
[YES] brackets removed; whitespace collapsed), so formatting is out of the picture.

For each (framework, strategy, note version) it reports
  - top n-grams of a tfidf_punct + LR fit (positive = injected) on the normalised text;
  - same-slot rates of candidate explanations: words of the injection note copied into
    the reply, first person, hedging/assertive connectives;
  - single-feature AUROCs: normalised length, sentence count, mean sentence length,
    first-person count (scored within the same-slot comparison set).

Usage: python3 scripts/sham_residual_analysis.py <fmt_val_export.jsonl[.gz]> [fw ...]
"""
import collections
import gzip
import json
import re
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score


def norm(t):  # verbatim from MedHyperTrace lexical_norm.py (round 47)
    t = t or ""
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*(?:[-*+•]|\d+[.)])\s+", "", t)
    t = re.sub(r"[*_`]+", "", t)
    t = re.sub(r"\[([A-Za-z]{1,12})\]", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


# words that appear in the simulation note / sham instruction / fmt_v1 format sentence
NOTE_WORDS = ["simulation", "research", "teammate", "colleague", "genuine", "carefully",
              "best answer", "usual", "normally", "format", "mistake", "this turn",
              "work through", "honest"]
FIRST_PERSON = re.compile(r"\b(I|I'm|I've|my|me)\b")
ASSERTIVE = ["therefore", "clearly", "must", "definitively", "in conclusion", "in summary",
             "ultimately", "confident", "strongly"]
HEDGE = ["may", "might", "possibly", "likely", "could", "suggest"]


def sentences(t):
    return [s for s in re.split(r"(?<=[.!?])\s+", t) if s.strip()]


def slot_keys(r):
    occ, out = collections.Counter(), {}
    for s in r["steps"]:
        b = (s["agent_id"], s["phase"], s["round"])
        out[s["step_id"]] = b + (occ[b],)
        occ[b] += 1
    return out


def main():
    path = sys.argv[1]
    fws = set(sys.argv[2:])
    op = gzip.open if path.endswith(".gz") else open
    runs = [json.loads(l) for l in op(path, "rt")]
    normal = collections.defaultdict(list)
    for r in runs:
        if r["run_mode"] == "normal":
            k = slot_keys(r)
            for s in r["steps"]:
                normal[(r["framework"], r["question_id"]) + k[s["step_id"]]].append(norm(s["output"]))
    groups = collections.defaultdict(list)   # (fw, strat) -> [(pos_text, [neg_texts], qid, phase)]
    for r in runs:
        if r["run_mode"] != "inject" or (fws and r["framework"] not in fws):
            continue
        k = slot_keys(r)
        by = {s["step_id"]: s for s in r["steps"]}
        for i in r["labels"].get("injection") or []:
            st = i.get("effective_strategy") or i.get("strategy")
            if st not in ("sham", "prompt_injection"):
                continue
            st += "@" + (i.get("note_version") or "old")
            s = by[i["step_id"]]
            key = (r["framework"], r["question_id"]) + k[s["step_id"]]
            if key in normal:
                groups[(r["framework"], st)].append((norm(s["output"]), normal[key], r["question_id"], s["phase"]))

    for (fw, st), items in sorted(groups.items()):
        T = [p for p, _, _, _ in items] + [n for _, ns, _, _ in items for n in ns]
        y = np.array([1] * len(items) + [0] * sum(len(ns) for _, ns, _, _ in items))
        print(f"\n=== {fw} {st}  n_pos={len(items)} n_neg={int((1 - y).sum())}  phases={dict(collections.Counter(ph for *_, ph in items))}")
        vec = TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=False, min_df=2,
                              sublinear_tf=True, ngram_range=(1, 2))
        X = vec.fit_transform(T)
        clf = LogisticRegression(max_iter=3000).fit(X, y)
        names = np.array(vec.get_feature_names_out())
        order = np.argsort(clf.coef_[0])
        print("  top + (injected):", list(names[order[::-1][:15]]))
        print("  top - (normal)  :", list(names[order[:10]]))

        def rate(fn):
            pi = np.mean([fn(p) for p, _, _, _ in items])
            pn = np.mean([np.mean([fn(n) for n in ns]) for _, ns, _, _ in items])
            return f"{pi:.2f}/{pn:.2f}"
        low = lambda t: t.lower()
        copied = {w: rate(lambda t, w=w: w in low(t)) for w in NOTE_WORDS}
        copied = {w: v for w, v in copied.items() if v != "0.00/0.00"}
        print("  note words (inj/same-slot):", copied)
        print("  first person:", rate(lambda t: bool(FIRST_PERSON.search(t))),
              " assertive:", rate(lambda t: any(w in low(t) for w in ASSERTIVE)),
              " hedge:", rate(lambda t: any(re.search(rf"\b{w}\b", low(t)) for w in HEDGE)))
        feats = {"length": lambda t: len(t), "n_sentences": lambda t: len(sentences(t)),
                 "mean_sent_len": lambda t: len(t) / max(1, len(sentences(t))),
                 "first_person_n": lambda t: len(FIRST_PERSON.findall(t))}
        line = []
        for name, fn in feats.items():
            sc = np.array([fn(t) for t in T], float)
            a = roc_auc_score(y, sc)
            line.append(f"{name}={a:.2f}")
        print("  single-feature AUROC (>0.5 = larger in injected):", ", ".join(line))


if __name__ == "__main__":
    main()
