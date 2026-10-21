#!/usr/bin/env python3
"""Difficulty screening of MCQ questions with a cheap single-agent setting.

MedHyperTrace r28: keep questions whose normal accuracy is neither ~0 nor ~1,
so that normal MAS runs also disagree / revise (removes the topology shortcut),
naturally paired success/failure runs exist, and injections have room to flip
the outcome. This script runs each question K times as ONE chain-of-thought
call (same query text the frameworks get, temperature 0.7) and records the
per-question accuracy; select_band() then keeps e.g. 0.25 <= acc <= 0.75.

Contamination check (MedHyperTrace r29): runs k >= --n_unshuffled (default 2
of K=4) see the options in a seeded random order, relabelled A, B, ...; the
reply's letter is mapped back to the original label before scoring. If the
shuffled accuracy is clearly lower, the model recalls answer letters rather
than reasoning. The report gives overall / unshuffled / shuffled accuracy and
in-band counts per question_type. Wrong answers of all runs (original labels)
become each kept question's `screen_distractors` ({letter: count}), which the
factory uses to draw corrupted answers from the natural error distribution.

Usage:
  python scripts/screen_difficulty.py --dataset datasets/data/medxpertqa_text.json \
      --model llama-4-maverick --base_url https://aihubmix.com/v1 --api_key_env AIHUBMIX_API_KEY \
      --n_questions 500 --k 4 --seed 20261021 --out screen_llama.jsonl [--workers 16]
  (resumable: questions/runs already in --out are skipped)
  python scripts/screen_difficulty.py --select screen_llama.jsonl [screen_mercury.jsonl] \
      --band 0.25 0.75 --dataset datasets/data/medxpertqa_text.json --out_dataset band.json
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from methods.answer_parsing import mcq_answer  # noqa: E402

SUFFIX = "\n\nThink step by step, then end with a line of the form 'Final answer: <letter>'."
LETTERS = "ABCDEFGHIJ"


def shuffled_query(q, k, seed):
    """The query with options in a seeded random order, relabelled A, B, ...;
    returns (query, new_label -> original_label)."""
    from methods.medagents_mc.medagents_mc_main import parse_mcq_query
    from data_processing.medical.convert_medical_datasets import _format_mcq_query
    stem, opts = parse_mcq_query(q["query"])
    orig = sorted(opts)
    perm = orig[:]
    random.Random(f"{seed}|{q['id']}|{k}").shuffle(perm)
    mapping = {LETTERS[i]: o for i, o in enumerate(perm)}
    return _format_mcq_query(stem, [opts[o] for o in perm]), mapping


def run_screen(a):
    from openai import OpenAI
    data = json.load(open(a.dataset))
    rng = random.Random(a.seed)
    qs = rng.sample(data, min(a.n_questions, len(data)))
    done = set()
    if os.path.exists(a.out):
        for l in open(a.out):
            r = json.loads(l)
            done.add((r["id"], r["k"]))
    jobs = [(q, k) for q in qs for k in range(a.k) if (q["id"], k) not in done]
    client = OpenAI(base_url=a.base_url, api_key=os.environ[a.api_key_env], max_retries=4)
    lock = threading.Lock()
    tot = {"in": 0, "out": 0, "n": 0, "fail": 0}

    def one(job):
        q, k = job
        shuffled = k >= a.n_unshuffled
        query, mapping = shuffled_query(q, k, a.seed) if shuffled else (q["query"], None)
        for attempt in range(3):
            try:
                r = client.chat.completions.create(
                    model=a.model, temperature=a.temperature, max_tokens=a.max_tokens,
                    messages=[{"role": "user", "content": query + SUFFIX}])
                text = r.choices[0].message.content or ""
                raw = mcq_answer(text)
                ans = mapping.get(raw) if (shuffled and raw) else raw
                rec = {"id": q["id"], "k": k, "model": a.model, "answer": ans, "shuffled": shuffled,
                       "raw_answer": raw, "question_type": q.get("question_type"),
                       "gold": q["answer"], "finish_reason": r.choices[0].finish_reason,
                       "prompt_tokens": r.usage.prompt_tokens,
                       "completion_tokens": r.usage.completion_tokens}
                rec["correct"] = rec["answer"] == q["answer"]
                with lock:
                    tot["in"] += rec["prompt_tokens"]; tot["out"] += rec["completion_tokens"]; tot["n"] += 1
                    with open(a.out, "a") as f:
                        f.write(json.dumps(rec) + "\n")
                return
            except Exception as e:
                print(f"[{q['id']} k={k}] attempt {attempt + 1}: {e}", file=sys.stderr)
                time.sleep(2)
        with lock:
            tot["fail"] += 1

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, jobs))
    print(json.dumps({"model": a.model, "calls": tot["n"], "failed": tot["fail"],
                      "prompt_tokens": tot["in"], "completion_tokens": tot["out"]}))


def select_band(a):
    per_model = defaultdict(lambda: defaultdict(list))
    shuf = defaultdict(lambda: {True: [], False: []})
    distract = defaultdict(lambda: defaultdict(int))
    qtype = {}
    for path in a.select:
        for l in open(path):
            r = json.loads(l)
            per_model[r["model"]][r["id"]].append(bool(r["correct"]))
            shuf[r["model"]][bool(r.get("shuffled"))].append(bool(r["correct"]))
            qtype[r["id"]] = r.get("question_type")
            if not r["correct"] and r.get("answer"):
                distract[r["id"]][r["answer"]] += 1
    data = {s["id"]: s for s in json.load(open(a.dataset))}
    for q in list(qtype):
        qtype[q] = qtype[q] or (data.get(q) or {}).get("question_type")
    lo, hi = a.band
    keep = set()
    report = {}
    for m, d in per_model.items():
        inband = {q for q, v in d.items() if lo <= sum(v) / len(v) <= hi}
        mean = lambda v: sum(v) / len(v) if v else float("nan")
        by_type = defaultdict(lambda: [0, 0])
        for q, v in d.items():
            by_type[qtype.get(q)][0] += 1
            by_type[qtype.get(q)][1] += q in inband
        rep = {"screened": len(d), "in_band": len(inband),
               "acc_overall": mean([x for v in d.values() for x in v]),
               "acc_unshuffled": mean(shuf[m][False]), "acc_shuffled": mean(shuf[m][True]),
               "in_band_by_question_type": {str(t): {"screened": n, "in_band": b}
                                            for t, (n, b) in by_type.items()}}
        report[m] = rep
        print(f"{m}: {json.dumps(rep)}")
        keep |= inband
    out = [dict(data[q], screen_accuracy={m: sum(per_model[m][q]) / len(per_model[m][q])
                                          for m in per_model if q in per_model[m]},
                screen_distractors=dict(distract.get(q, {})))
           for q in sorted(keep) if q in data]
    if a.report:
        json.dump(report, open(a.report, "w"), indent=1)
    json.dump(out, open(a.out_dataset, "w"), ensure_ascii=False, indent=1)
    print(f"kept {len(out)} questions (in band for at least one model) -> {a.out_dataset}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset")
    ap.add_argument("--model")
    ap.add_argument("--base_url")
    ap.add_argument("--api_key_env")
    ap.add_argument("--n_questions", type=int, default=500)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261021)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max_tokens", type=int, default=4096)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--out")
    ap.add_argument("--select", nargs="*")
    ap.add_argument("--band", nargs=2, type=float, default=(0.25, 0.75))
    ap.add_argument("--out_dataset")
    ap.add_argument("--n_unshuffled", type=int, default=2,
                    help="runs k < this see the original option order; the rest are shuffled")
    ap.add_argument("--report", help="write the selection report (JSON) here")
    a = ap.parse_args()
    if a.select:
        select_band(a)
    else:
        run_screen(a)


if __name__ == "__main__":
    main()
