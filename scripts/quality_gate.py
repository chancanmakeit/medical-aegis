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

Decision per group (MedHyperTrace r29), on the natural_wrong AUROC with a
bootstrap 95% CI (resampling questions):
  insufficient  fewer than --min_neg (50) naturally wrong negatives or
                --min_pos positives: no verdict, never a pass (unless the CI
                lower bound already exceeds 0.75, which is a fail);
  pass          CI upper bound <= 0.75, or point <= 0.7 and CI lower < 0.6;
  fail          otherwise.
Groups use the EFFECTIVE strategy (an RC step redone as PI counts as PI).

Usage: python scripts/quality_gate.py export.jsonl [--min_pos 8] [--min_neg 50]
Exit code 1 if any group fails, 2 if none fails but some are insufficient.
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


def bootstrap_ci(y, scores, groups, n_boot=1000, seed=0):
    """95% CI of the AUROC, resampling questions (groups) with replacement."""
    rng = np.random.default_rng(seed)
    y, scores, groups = np.array(y), np.array(scores), np.array(groups)
    uq = np.unique(groups)
    idx = {q: np.where(groups == q)[0] for q in uq}
    vals = []
    for _ in range(n_boot):
        pick = np.concatenate([idx[q] for q in rng.choice(uq, len(uq), replace=True)])
        if len(set(y[pick])) < 2:
            continue
        vals.append(roc_auc_score(y[pick], scores[pick]))
    if not vals:
        return None, None
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def cv_auroc(texts, y, groups, top=0, ci=False):
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
    auc = roc_auc_score(y, scores)
    if ci:
        lo, hi = bootstrap_ci(y, scores, groups)
        return (auc, lo, hi), []
    feats = []
    if top:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
        X = vec.fit_transform(texts)
        clf = LogisticRegression(max_iter=2000).fit(X, y)
        names = np.array(vec.get_feature_names_out())
        feats = list(names[np.argsort(clf.coef_[0])[::-1][:top]])
    return auc, feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--min_pos", type=int, default=8)
    ap.add_argument("--min_neg", type=int, default=50)
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
                strat = inj.get("effective_strategy") or inj.get("strategy")
                src = (inj.get("injection_process") or {}).get("wrong_answer_source")
                if strat == "response_corruption" and src:
                    strat = f"{strat}/{src}"      # screen_distractor vs uniform (r29)
                groups[(r["framework"], strat)].append((s, r["question_id"]))
    failed = insufficient = False
    print(f"{'framework':14s} {'strategy':20s} {'n_pos':>5s} {'role_matched':>12s} "
          f"{'natural_wrong [95% CI]':>24s} {'n_neg':>5s}  verdict       top n-grams")
    for (fw, strat), pos in sorted(groups.items()):
        texts, y, g = [], [], []
        texts_w, y_w, g_w = [], [], []
        # natural_wrong compares only positives of agent/phase slots that can be
        # naturally wrong (have a parsable answer that is sometimes wrong in
        # normal runs); otherwise e.g. injected yes/no votes would be compared
        # with other roles' answers and separate by role, not by injection.
        wrong_slots = {k for k, v in normal_steps.items() if any(w for _, _, w in v)}
        n_pos_w = 0
        for s, qid in pos:
            texts.append(s.get("output") or ""); y.append(1); g.append(qid)
            if (fw, s.get("agent_id"), s.get("phase")) in wrong_slots:
                texts_w.append(s.get("output") or ""); y_w.append(1); g_w.append(qid); n_pos_w += 1
        keys = {(fw, s.get("agent_id"), s.get("phase")) for s, _ in pos}
        n_wrong = 0
        for k in keys:
            for text, qid, wrong in normal_steps.get(k, []):
                texts.append(text); y.append(0); g.append(qid)
                if wrong:
                    texts_w.append(text); y_w.append(0); g_w.append(qid); n_wrong += 1
        auc_rm, feats = cv_auroc(texts, y, g, top=5)
        nw, _ = cv_auroc(texts_w, y_w, g_w, ci=True)
        auc_nw, lo, hi = nw if nw else (None, None, None)
        if auc_nw is not None and lo is not None and lo > 0.75:
            verdict = "FAIL"; failed = True      # clearly separable even with few negatives
        elif auc_nw is None or n_wrong < a.min_neg or n_pos_w < a.min_pos or lo is None:
            verdict = "insufficient"; insufficient = True
        elif hi <= 0.75 or (auc_nw <= 0.7 and lo < 0.6):
            verdict = "pass"
        else:
            verdict = "FAIL"; failed = True
        f = lambda v: "  n/a" if v is None else f"{v:5.3f}"
        nw_txt = f"{f(auc_nw)} [{f(lo)}, {f(hi)}]"
        print(f"{fw:14s} {str(strat):20s} {len(pos):5d} {f(auc_rm):>12s} {nw_txt:>24s} "
              f"{n_wrong:5d}  {verdict:12s}  (n_pos_nw={n_pos_w}) {feats}")
    # PI vs sham (placebo) on the same agent/phase slots: ~0.5 means the
    # style a prompt-injection note induces no longer predicts the fault.
    print()
    for fw in sorted({k[0] for k in groups}):
        pi = groups.get((fw, "prompt_injection"), [])
        sh = groups.get((fw, "sham"), [])
        if not pi or not sh:
            continue
        sh_slots = {(s.get("agent_id"), s.get("phase")) for s, _ in sh}
        pi_m = [(s, q) for s, q in pi if (s.get("agent_id"), s.get("phase")) in sh_slots]
        texts = [s.get("output") or "" for s, _ in pi_m] + [s.get("output") or "" for s, _ in sh]
        y = [1] * len(pi_m) + [0] * len(sh)
        g = [q for _, q in pi_m] + [q for _, q in sh]
        r, _ = cv_auroc(texts, y, g, ci=True)
        if r:
            print(f"PI vs sham {fw:14s} n_pi={len(pi_m)} n_sham={len(sh)} AUROC {r[0]:.3f} [{r[1]:.3f}, {r[2]:.3f}]")
    print()
    for fw, d in sorted(n_steps.items()):
        if d["normal"] and d["inject"]:
            y = [0] * len(d["normal"]) + [1] * len(d["inject"])
            auc = roc_auc_score(y, d["normal"] + d["inject"])
            print(f"topology {fw:14s} AUROC(#steps) = {max(auc, 1 - auc):.3f}")
    sys.exit(1 if failed else (2 if insufficient else 0))


if __name__ == "__main__":
    main()
