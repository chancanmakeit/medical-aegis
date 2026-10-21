#!/usr/bin/env python3
"""Difficulty screening of MCQ questions with a cheap single-agent setting.

MedHyperTrace r28: keep questions whose normal accuracy is neither ~0 nor ~1,
so that normal MAS runs also disagree / revise (removes the topology shortcut),
naturally paired success/failure runs exist, and injections have room to flip
the outcome. This script runs each question K times as ONE chain-of-thought
call (same query text the frameworks get, temperature 0.7) and records the
per-question accuracy; select_band() then keeps e.g. 0.25 <= acc <= 0.75.

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
        for attempt in range(3):
            try:
                r = client.chat.completions.create(
                    model=a.model, temperature=a.temperature, max_tokens=a.max_tokens,
                    messages=[{"role": "user", "content": q["query"] + SUFFIX}])
                text = r.choices[0].message.content or ""
                rec = {"id": q["id"], "k": k, "model": a.model, "answer": mcq_answer(text),
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
    acc = defaultdict(list)
    per_model = defaultdict(lambda: defaultdict(list))
    for path in a.select:
        for l in open(path):
            r = json.loads(l)
            per_model[r["model"]][r["id"]].append(bool(r["correct"]))
    lo, hi = a.band
    keep = set()
    for m, d in per_model.items():
        inband = {q for q, v in d.items() if lo <= sum(v) / len(v) <= hi}
        print(f"{m}: {len(d)} screened, {len(inband)} in [{lo}, {hi}], "
              f"mean acc {sum(sum(v) / len(v) for v in d.values()) / max(1, len(d)):.3f}")
        keep |= inband
    for m, d in per_model.items():
        for q, v in d.items():
            acc[q].append(sum(v) / len(v))
    data = {s["id"]: s for s in json.load(open(a.dataset))}
    out = [dict(data[q], screen_accuracy={m: sum(per_model[m][q]) / len(per_model[m][q])
                                          for m in per_model if q in per_model[m]})
           for q in sorted(keep) if q in data]
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
    a = ap.parse_args()
    if a.select:
        select_band(a)
    else:
        run_screen(a)


if __name__ == "__main__":
    main()
