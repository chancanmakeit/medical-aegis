#!/usr/bin/env python3
"""Protocol v3 (repeated sampling) for the medical branching eval set: stage-2 plan, labels, summary.

Per point (pair_id): finals of branch reps and control reps.
  stage 1: reps 0-1 of both arms. All 4 finals equal -> "undetermined" (stage 1), no stage 2.
  stage 2: otherwise reps 2-5 of both arms. Reference = modal control answer (tie: control rep 0's answer).
  Fisher exact, one-sided: branch finals equal the reference less often than control finals.
  p < 0.05 -> judgment "positive" for claim outcome_sensitive_under_protocol; otherwise "undetermined".
  Never "negative". Endpoints kept separately: answer_changed (branch modal != control modal) and
  correctness_changed (branch-majority correctness != control-majority correctness).

  python3 scripts/branch_v3_analysis.py plan  --dir D            # writes <fw>_stage2_plan.txt (pass qids)
  python3 scripts/branch_v3_analysis.py label --dir D [--out_labels F] [--out_summary F] [--reference pooled]

v11 r11 (MHT #1 round 84 audit): the control-modal reference is chosen from the arm tested as "high", which
biases towards positives (their null calibration: FDR ~0.14 over the set). Every stage-2 point now also gets
  - pooled reference: modal answer of all 12 finals (tie: lexicographically first), symmetric in the two arms;
    Fisher one-sided with it (p_value_pooled);
  - perm_p: exact permutation p-value of (control matches - branch matches) w.r.t. the pooled reference over
    all 924 6/6 splits of the 12 finals (the reference is invariant under these splits);
  - p_null_positive: probability that the FULL procedure (stage-1 screen, stage 2, the chosen reference rule)
    calls the point positive when the 12 finals are randomly reassigned to the 12 slots (Monte Carlo); its
    sum over a framework is the expected number of positives under "t has no effect" (E0), E0 / positives
    estimates the FDR (conservative: the observed finals include real effects).
--reference pooled makes the judgment use the pooled reference (default "control" keeps the labels of the
first v3 batch unchanged). context.dt_empty: the declared D(t) (from `sources`) is empty; context.is_last_llm_step;
context.downstream_regenerated: some branch run of the point regenerated a step after t (declared D(t) or a
dependency `sources` misses: AgentVerse criticism steps). "Final-call-only" points = not downstream_regenerated.
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

import itertools
import zlib
import random

from scipy.stats import fisher_exact

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from branch_pilot import letter, final_answer  # noqa: E402
import branch_identity as bi  # noqa: E402

ALPHA = 0.05
REFERENCE = "control"
N_NULL = 2000
_FISHER = {}


def fisher_p(a, n_c, b, n_b):
    k = (a, n_c, b, n_b)
    if k not in _FISHER:
        _FISHER[k] = fisher_exact([[a, n_c - a], [b, n_b - b]], alternative="greater")[1]
    return _FISHER[k]


def pooled_ref(finals):
    cnt = Counter(finals)
    top = max(cnt.values())
    return sorted(k for k, v in cnt.items() if v == top)[0]


def control_ref(ct):
    cnt = Counter(ct)
    top = max(cnt.values())
    return ct[0] if cnt[ct[0]] == top else sorted(k for k, v in cnt.items() if v == top)[0]


def decide(br, ct, rule):
    """the v3 procedure on full 6+6 finals (rep order kept): positive?"""
    if len({br[0], br[1], ct[0], ct[1]}) == 1:
        return False
    ref = control_ref(ct) if rule == "control" else pooled_ref(br + ct)
    a, b = sum(x == ref for x in ct), sum(x == ref for x in br)
    return fisher_p(a, len(ct), b, len(br)) < ALPHA


def perm_stats(br, ct, rule, seed):
    allf = br + ct
    ref = pooled_ref(allf)
    obs = sum(x == ref for x in ct) - sum(x == ref for x in br)
    hits = tot = 0
    for idx in itertools.combinations(range(len(allf)), len(ct)):
        s = set(idx)
        d = sum(allf[i] == ref for i in idx) - sum(allf[i] == ref for i in range(len(allf)) if i not in s)
        hits += d >= obs
        tot += 1
    rng = random.Random(seed)
    pos = 0
    for _ in range(N_NULL):
        x = allf[:]
        rng.shuffle(x)
        pos += decide(x[:len(br)], x[len(br):], rule)
    return hits / tot, pos / N_NULL


def load(d):
    cands = {}
    for f in glob.glob(os.path.join(d, "*_candidates.jsonl")):
        for l in open(f):
            c = json.loads(l)
            cands[(c["fw"], c["qid"], int(c["run_index"]), c["t_step_id"])] = c
    pts = defaultdict(lambda: {"branch": {}, "control": {}, "run_ids": []})
    blocks = []
    for f in glob.glob(os.path.join(d, "runs", "*_out.jsonl")):
        fw = os.path.basename(f).split("_p")[0]
        for l in open(f):
            r = json.loads(l)
            b = r.get("branch")
            if b is None:          # a batch interrupted before stamping: it is rerun, ignore here
                continue
            blocks.append(b)
            p = pts[(fw, b["pair_id"])]
            # a final without an option letter is its own outcome, not missing data
            p["branch" if b["arm"] == "branch" else "control"][b["repetition"]] = final_answer(r) or "NONE"
            p["run_ids"].append(bi.branch_run_id(b))
            if b["arm"] == "branch":   # steps after t that this branch run regenerated (declared D(t) or hidden)
                t_run = b.get("t_step_id_in_run", b["candidate_step_id"])
                p.setdefault("downstream", set()).update(x for x in (b.get("regenerated_step_ids") or []) if x != t_run)
            if b["arm"] == "control" and b["repetition"] == 0:
                p["cand"] = cands[(fw, r["id"], int(r["run_index"]), b["candidate_step_id"])]
                p["block"] = b
    return pts, blocks


def judge(p):
    br = [p["branch"][k] for k in sorted(p["branch"])]
    ct = [p["control"][k] for k in sorted(p["control"])]
    s1 = [p["branch"].get(0), p["branch"].get(1), p["control"].get(0), p["control"].get(1)]
    out = {"n_branch": len(br), "n_control": len(ct), "branch_finals": br, "control_finals": ct}
    if None in s1:
        out.update(judgment="incomplete", stage=1)
        return out
    if len(set(s1)) == 1:
        out.update(judgment="undetermined", stage=1, p_value=None)
        return out
    if len(br) < 6 or len(ct) < 6:
        out.update(judgment="needs_stage2", stage=1)
        return out
    ref = control_ref(ct)
    a, b = sum(x == ref for x in ct), sum(x == ref for x in br)
    pv = fisher_p(a, len(ct), b, len(br))
    pref = pooled_ref(br + ct)
    pa, pb = sum(x == pref for x in ct), sum(x == pref for x in br)
    ppv = fisher_p(pa, len(ct), pb, len(br))
    perm_p, p_null = perm_stats(br, ct, REFERENCE, zlib.crc32(p["block"]["pair_id"].encode())) if "block" in p else (None, None)
    bm = Counter(br).most_common(1)[0][0]
    g = p["cand"]["gold"]
    use = pv if REFERENCE == "control" else ppv
    out.update(stage=2, reference=ref, control_ref=a, branch_ref=b, p_value=pv,
               pooled_reference=pref, control_pooled_ref=pa, branch_pooled_ref=pb, p_value_pooled=ppv,
               perm_p=perm_p, p_null_positive=p_null, reference_rule=REFERENCE,
               judgment="positive" if use < ALPHA else "undetermined",
               answer_changed=bm != ref,
               correctness_changed=(sum(x == g for x in br) * 2 > len(br)) != (sum(x == g for x in ct) * 2 > len(ct)),
               branch_majority_correct=sum(x == g for x in br) * 2 > len(br))
    return out


def stype(c):
    ph = str(c.get("phase") or "").split("/")[0]
    return ph + (f" r{c['round']}" if c.get("round") else "")


def cmd_plan(a):
    pts, _ = load(a.dir)
    by = defaultdict(lambda: defaultdict(list))
    n = Counter()
    for (fw, pid), p in pts.items():
        j = judge(p)
        n[(fw, j["judgment"])] += 1
        if j["judgment"] == "needs_stage2":
            by[fw][p["cand"]["pass"]].append(p["cand"]["qid"])
    for fw, d in by.items():
        with open(os.path.join(a.dir, f"{fw}_stage2_plan.txt"), "w") as f:
            for k in sorted(d):
                f.write(f"{k} {','.join(sorted(d[k]))}\n")
    print(dict(n))


def cmd_label(a):
    pts, blocks = load(a.dir)
    probs, summ = bi.validate(blocks)
    rows = []
    for (fw, pid), p in sorted(pts.items()):
        if "cand" not in p:
            continue
        c, b = p["cand"], p["block"]
        j = judge(p)
        rows.append({
            "annotation_id": f"{pid}|v3", "framework": fw, "dataset": c.get("dataset_tag"),
            "layer": "responsibility", "granularity": "step", "taxonomy": "branch-outcome-sensitivity",
            "taxonomy_version": "v3", "claim": "outcome_sensitive_under_protocol",
            "target": {"run_id": b["parent_run_id"], "step_ids": [c["t_step_id"]], "agent": c.get("agent"),
                       "phase": c.get("phase"), "round": c.get("round"), "t_index": c["t"]},
            "judgment": j["judgment"], "annotator": {"kind": "program", "version": "branch_v3_analysis"},
            "evidence_method": ["counterfactual_replay"], "protocol_id": b["protocol_id"], "alpha": ALPHA,
            "evidence_refs": sorted(p["run_ids"]), "pair_id": pid,
            "endpoints": {k: j.get(k) for k in ("answer_changed", "correctness_changed", "branch_majority_correct")},
            "statistics": {k: j.get(k) for k in ("stage", "n_branch", "n_control", "branch_finals", "control_finals",
                                                 "reference", "control_ref", "branch_ref", "p_value",
                                                 "pooled_reference", "control_pooled_ref", "branch_pooled_ref",
                                                 "p_value_pooled", "perm_p", "p_null_positive", "reference_rule")},
            "context": {"gold": c["gold"], "t_letter": c.get("t_letter"), "letter_status": c.get("letter_status"),
                        "recorded_final": c.get("recorded_final"), "step_type": stype(c),
                        "dt_empty": not c.get("force_step_ids"), "is_last_llm_step": c["t"] == c["n_steps"] - 1,
                        "downstream_regenerated": bool(p.get("downstream"))},
        })
    out = [f"identity {json.dumps(summ)}; problems {len(probs)} {probs[:3]}", ""]
    for fw in sorted({r["framework"] for r in rows}):
        s = [r for r in rows if r["framework"] == fw]
        jc = Counter(r["judgment"] for r in s)
        par = {r["target"]["run_id"] for r in s}
        pos = [r for r in s if r["judgment"] == "positive"]
        st1 = [r for r in s if r["statistics"]["n_control"] >= 2]
        cc = sum(r["statistics"]["control_finals"][0] != r["statistics"]["control_finals"][1] for r in st1)
        bb = sum(len(r["statistics"]["branch_finals"]) >= 2 and r["statistics"]["branch_finals"][0] != r["statistics"]["branch_finals"][1] for r in st1)
        out.append(f"## {fw}: {len(par)} parents, {len(s)} points; {dict(jc)}; positives per parent {len(pos) / max(1, len(par)):.2f}; "
                   f"parents with >= 1 positive {len({r['target']['run_id'] for r in pos})}")
        out.append(f"- noise floor (stage 1, all points): control rep0 != rep1 {cc}/{len(st1)} = {cc / max(1, len(st1)):.3f}; "
                   f"branch rep0 != rep1 {bb}/{len(st1)}")
        out.append(f"- positives: answer_changed {sum(bool(r['endpoints']['answer_changed']) for r in pos)}, "
                   f"correctness_changed {sum(bool(r['endpoints']['correctness_changed']) for r in pos)}, "
                   f"of which branch majority correct (wrong -> right) {sum(bool(r['endpoints']['branch_majority_correct']) for r in pos)}")
        st2 = [r for r in s if r["statistics"]["stage"] == 2]
        e0 = sum(r["statistics"]["p_null_positive"] or 0 for r in st2)
        npool = sum(1 for r in st2 if r["statistics"]["p_value_pooled"] < ALPHA)
        out.append(f"- reference rule '{REFERENCE}': E0 (expected positives if t had no effect) {e0:.1f}, "
                   f"FDR ~ {e0 / max(1, len(pos)):.2f}; positives with the pooled reference {npool}; "
                   f"positives with perm_p < 0.05 {sum(1 for r in pos if (r['statistics']['perm_p'] or 1) < ALPHA)}; "
                   f"positives at empty declared D(t) {sum(1 for r in pos if r['context']['dt_empty'])}, "
                   f"of which no step after t regenerated (final-call only) {sum(1 for r in pos if not r['context']['downstream_regenerated'])}")
        by = defaultdict(list)
        for r in s:
            by[r["context"]["step_type"]].append(r)
        for k in sorted(by):
            g = by[k]
            out.append(f"  - {k}: positive {sum(r['judgment'] == 'positive' for r in g)}/{len(g)}, stage-2 {sum(r['statistics']['stage'] == 2 for r in g)}")
        out.append("")
    txt = "\n".join(out)
    print(txt)
    if a.out_summary:
        open(a.out_summary, "w").write(txt + "\n")
    if a.out_labels:
        with open(a.out_labels, "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "label"])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out_labels")
    ap.add_argument("--out_summary")
    ap.add_argument("--reference", choices=["control", "pooled"], default="control")
    a = ap.parse_args()
    global REFERENCE
    REFERENCE = a.reference
    {"plan": cmd_plan, "label": cmd_label}[a.cmd](a)


if __name__ == "__main__":
    main()
