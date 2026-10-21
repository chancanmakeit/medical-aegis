#!/usr/bin/env python3
"""Injection-signature quality gate for exported mas-traj/1 data.

MedHyperTrace r28: before a new injection configuration goes into formal
generation, check that an injected step cannot be told apart from ordinary
steps by its output text alone. Otherwise an attribution model trained on the
data learns "spot the injection" instead of "spot the error".

For every (framework, strategy) group this reports the AUROC of TF-IDF (word
1-2-grams) + logistic regression, 5-fold GroupKFold by question, for:
  role_matched   positives: injected steps; negatives: steps of the same
                 agent_id and phase in normal runs.
  natural_wrong  negatives: only those normal-run steps of the same agent_id
                 and phase whose structured answer is wrong (a natural error).
                 This is the comparison that matters: ~0.5-0.7 is acceptable,
                 clearly higher means the injection still leaves a signature.
  topology       AUROC of the run's step count alone (inject vs normal runs).
It also prints the strongest n-grams for the positive class.

Usage: python scripts/quality_gate.py export.jsonl [--min_pos 8] [--threshold 0.7]
Exit code 1 if any natural_wrong AUROC with enough data exceeds --threshold.
"""
import argparse
import json
import sys
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

ANSWER_KEYS = ("answer", "esi_level", "final_answer")


def step_answer(s):
    st = s.get("structured") or {}
    for k in ANSWER_KEYS:
        if st.get(k) is not None:
            return str(st[k]).strip().lower()
    return None


def cv_auroc(texts, y, groups, top=0):
    y = np.array(y)
    if y.sum() < 2 or (1 - y).sum() < 2:
        return None, []
    n_splits = min(5, len(set(groups)))
    if n_splits < 2:
        return None, []
    scores = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=n_splits).split(texts, y, groups):
        if len(set(y[tr])) < 2:
            scores[te] = 0.5
            continue
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        Xtr = vec.fit_transform([texts[i] for i in tr])
        clf = LogisticRegression(max_iter=2000, C=1.0).fit(Xtr, y[tr])
        scores[te] = clf.predict_proba(vec.transform([texts[i] for i in te]))[:, 1]
    if len(set(y)) < 2:
        return None, []
    feats = []
    if top:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        X = vec.fit_transform(texts)
        clf = LogisticRegression(max_iter=2000).fit(X, y)
        names = np.array(vec.get_feature_names_out())
        feats = list(names[np.argsort(clf.coef_[0])[::-1][:top]])
    return roc_auc_score(y, scores), feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--min_pos", type=int, default=8)
    ap.add_argument("--threshold", type=float, default=0.7)
    a = ap.parse_args()
    runs = [json.loads(l) for l in open(a.export)]
    normal_steps = defaultdict(list)       # (fw, agent_id, phase) -> [(text, qid, wrong)]
    n_steps = defaultdict(lambda: {"normal": [], "inject": []})
    for r in runs:
        n_steps[r["framework"]][r["run_mode"]].append(len(r["steps"]))
        if r["run_mode"] != "normal":
            continue
        gold = str(r["labels"].get("gold")).strip().lower()
        for s in r["steps"]:
            if s.get("kind") != "llm":
                continue
            ans = step_answer(s)
            normal_steps[(r["framework"], s.get("agent_id"), s.get("phase"))].append(
                (s.get("output") or "", r["question_id"], ans is not None and ans != gold))
    groups = defaultdict(list)             # (fw, strategy) -> [(step, qid)]
    for r in runs:
        if r["run_mode"] != "inject":
            continue
        by_id = {s["step_id"]: s for s in r["steps"]}
        for inj in r["labels"].get("injection") or []:
            s = by_id.get(inj["step_id"])
            if s is not None:
                groups[(r["framework"], inj.get("strategy"))].append((s, r["question_id"]))
    failed = False
    print(f"{'framework':14s} {'strategy':20s} {'n_pos':>5s} {'role_matched':>12s} {'natural_wrong':>13s}  top n-grams")
    for (fw, strat), pos in sorted(groups.items()):
        texts, y, g = [], [], []
        texts_w, y_w, g_w = [], [], []
        for s, qid in pos:
            for T, Y, G in ((texts, y, g), (texts_w, y_w, g_w)):
                T.append(s.get("output") or ""); Y.append(1); G.append(qid)
        keys = {(fw, s.get("agent_id"), s.get("phase")) for s, _ in pos}
        n_wrong = 0
        for k in keys:
            for text, qid, wrong in normal_steps.get(k, []):
                texts.append(text); y.append(0); g.append(qid)
                if wrong:
                    texts_w.append(text); y_w.append(0); g_w.append(qid); n_wrong += 1
        auc_rm, feats = cv_auroc(texts, y, g, top=5)
        auc_nw, _ = cv_auroc(texts_w, y_w, g_w)
        f = lambda v: "   n/a" if v is None else f"{v:6.3f}"
        print(f"{fw:14s} {str(strat):20s} {len(pos):5d} {f(auc_rm):>12s} {f(auc_nw):>9s} (n_neg={n_wrong})  {feats}")
        if auc_nw is not None and len(pos) >= a.min_pos and auc_nw > a.threshold:
            failed = True
    print()
    for fw, d in sorted(n_steps.items()):
        if d["normal"] and d["inject"]:
            y = [0] * len(d["normal"]) + [1] * len(d["inject"])
            auc = roc_auc_score(y, d["normal"] + d["inject"])
            print(f"topology {fw:14s} AUROC(#steps) = {max(auc, 1 - auc):.3f}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
