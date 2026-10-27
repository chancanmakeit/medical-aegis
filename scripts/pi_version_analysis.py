#!/usr/bin/env python3
"""PI / sham across injection-note versions (MedHyperTrace round 55 requests).

Input: a validation export holding normal runs plus PI and plain-sham runs of several
note versions on the same questions (scripts/build_fmt_validation_export.py output).
Text is normalised with MedHyperTrace's `norm()` (lexical_norm.py, round 47) first.

Reports per framework x note version:
  pi_vs_normal / sham_vs_normal   same-slot AUROC (question, agent, phase, round, k-th)
  *_drop1                         the same after dropping every step's first sentence
  pi_vs_sham                      PI step vs sham step of the same (question, agent, phase,
                                  round, k-th) slot; falls back to (question, agent, phase)
  answer_change                   share of PI / sham steps whose structured answer differs
                                  from the majority answer of the same-slot normal steps
and, when two versions are given with --pair A B, the paired difference B - A of
pi_vs_normal and sham_vs_normal with a bootstrap CI over questions (both versions scored
on the same question resamples).
Features: tfidf_punct (\\S+ tokens, case kept) or char (char_wb 3-5), LR, GroupKFold(5).

Usage: python3 scripts/pi_version_analysis.py <export.jsonl> [--feat punct|char] [--pair fmt_v1 fmt_v1_1]
"""
import argparse
import collections
import json
import re

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


def drop_first_sentence(t):
    parts = re.split(r"(?<=[.!?:])\s+", t, maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def slot_keys(r):
    occ, out = collections.Counter(), {}
    for s in r["steps"]:
        b = (s.get("agent_id"), s.get("phase"), s.get("round"))
        out[s["step_id"]] = b + (occ[b],)
        occ[b] += 1
    return out


def answer(s):
    st = s.get("structured") or {}
    a = st.get("answer")
    return None if a is None else str(a).strip().upper()


def scores(texts, y, g, feat):
    y, g = np.array(y), np.array(g)
    sc = np.zeros(len(y))
    mk = (lambda: TfidfVectorizer(token_pattern=r"(?u)\S+", lowercase=False, min_df=2, sublinear_tf=True)) \
        if feat == "punct" else \
        (lambda: TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True))
    for tr, te in GroupKFold(min(5, len(set(g)))).split(texts, y, g):
        v = mk()
        X = v.fit_transform([texts[i] for i in tr])
        sc[te] = LogisticRegression(max_iter=3000).fit(X, y[tr]).predict_proba(
            v.transform([texts[i] for i in te]))[:, 1]
    return y, g, sc


def boot(y, g, sc, n=1000, seed=0):
    qs, rng = np.unique(g), np.random.default_rng(seed)
    idx = {q: np.where(g == q)[0] for q in qs}
    b = []
    for _ in range(n):
        ii = np.concatenate([idx[q] for q in rng.choice(qs, len(qs))])
        if len(set(y[ii])) == 2:
            b.append(roc_auc_score(y[ii], sc[ii]))
    return np.percentile(b, 2.5), np.percentile(b, 97.5)


def fmt(y, g, sc):
    lo, hi = boot(y, g, sc)
    return f"{roc_auc_score(y, sc):.2f} [{lo:.2f}, {hi:.2f}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--feat", default="punct", choices=["punct", "char"])
    ap.add_argument("--pair", nargs=2, default=None)
    a = ap.parse_args()
    runs = [json.loads(l) for l in open(a.export)]
    normal = collections.defaultdict(list)          # (fw, q, slot) -> [step]
    for r in runs:
        if r["run_mode"] == "normal":
            k = slot_keys(r)
            for s in r["steps"]:
                normal[(r["framework"], r["question_id"]) + k[s["step_id"]]].append(s)
    inj = collections.defaultdict(list)             # (fw, kind, ver) -> [(q, slot, step)]
    for r in runs:
        if r["run_mode"] != "inject":
            continue
        k = slot_keys(r)
        by = {s["step_id"]: s for s in r["steps"]}
        for i in r["labels"].get("injection") or []:
            st = i.get("effective_strategy")
            if st not in ("prompt_injection", "sham"):
                continue
            kind = "pi" if st == "prompt_injection" else "sham"
            inj[(r["framework"], kind, i.get("note_version") or "old")].append(
                (r["question_id"], k[i["step_id"]], by[i["step_id"]]))

    def vs_normal(fw, items, tf):
        T, y, g = [], [], []
        for q, sl, s in items:
            neg = normal.get((fw, q) + sl, [])
            if not neg:
                continue
            T.append(tf(norm(s.get("output")))); y.append(1); g.append(q)
            for n_ in neg:
                T.append(tf(norm(n_.get("output")))); y.append(0); g.append(q)
        return scores(T, y, g, a.feat)

    ident = lambda t: t
    vers = sorted({k[2] for k in inj})
    res = {}
    print(f"features: {a.feat} (normalised text)")
    for fw in sorted({k[0] for k in inj}):
        for ver in vers:
            pi, sh = inj.get((fw, "pi", ver), []), inj.get((fw, "sham", ver), [])
            if not pi and not sh:
                continue
            out = {}
            for name, items in (("pi", pi), ("sham", sh)):
                if not items:            # e.g. a sham-only re-run (mdagents match_opener, v10 round 16)
                    continue
                res[(fw, name, ver)] = vs_normal(fw, items, ident)
                out[f"{name}_vs_normal"] = fmt(*res[(fw, name, ver)])
                out[f"{name}_vs_normal_drop1"] = fmt(*vs_normal(fw, items, drop_first_sentence))
                ch = []
                for q, sl, s in items:
                    na = [answer(n_) for n_ in normal.get((fw, q) + sl, []) if answer(n_)]
                    if na and answer(s):
                        ch.append(answer(s) != collections.Counter(na).most_common(1)[0][0])
                out[f"{name}_answer_change"] = f"{np.mean(ch):.2f} (n={len(ch)})" if ch else "n/a"
            # PI vs sham in the same slot (fallback: same question, agent, phase)
            shk = {(q,) + sl: s for q, sl, s in sh}
            shk2 = collections.defaultdict(list)
            for q, sl, s in sh:
                shk2[(q, sl[0], sl[1])].append(s)
            T, y, g, exact = [], [], [], 0
            for q, sl, s in pi:
                m = shk.get((q,) + sl)
                if m is not None:
                    exact += 1
                    ms = [m]
                else:
                    ms = shk2.get((q, sl[0], sl[1]), [])
                if not ms:
                    continue
                T.append(norm(s.get("output"))); y.append(1); g.append(q)
                for m_ in ms:
                    T.append(norm(m_.get("output"))); y.append(0); g.append(q)
            if sum(y) >= 5 and len(set(g)) >= 3:
                out["pi_vs_sham"] = fmt(*scores(T, y, g, a.feat)) + f" (pairs={sum(y)}, exact slot={exact})"
            print(f"\n{fw} @{ver}")
            for k_, v in out.items():
                print(f"  {k_:24s} {v}")
    if a.pair:
        A, B = a.pair
        print(f"\npaired difference {B} - {A} (bootstrap over questions, same resamples)")
        rng = np.random.default_rng(1)
        for fw in sorted({k[0] for k in inj}):
            for name in ("pi", "sham"):
                if (fw, name, A) not in res or (fw, name, B) not in res:
                    continue
                (ya, ga, sa), (yb, gb, sb) = res[(fw, name, A)], res[(fw, name, B)]
                qs = sorted(set(ga) & set(gb))
                ia = {q: np.where(ga == q)[0] for q in qs}
                ib = {q: np.where(gb == q)[0] for q in qs}
                d0 = roc_auc_score(yb, sb) - roc_auc_score(ya, sa)
                ds = []
                for _ in range(1000):
                    pick = rng.choice(qs, len(qs))
                    ja = np.concatenate([ia[q] for q in pick]); jb = np.concatenate([ib[q] for q in pick])
                    if len(set(ya[ja])) == 2 and len(set(yb[jb])) == 2:
                        ds.append(roc_auc_score(yb[jb], sb[jb]) - roc_auc_score(ya[ja], sa[ja]))
                print(f"  {fw:12s} {name:5s} {d0:+.2f} [{np.percentile(ds, 2.5):+.2f}, {np.percentile(ds, 97.5):+.2f}]  (questions={len(qs)})")


if __name__ == "__main__":
    main()
