#!/usr/bin/env python3
"""Token cost of raw main.py result files (llama-4-maverick list price by default).

Sums prompt/completion tokens over every distinct LLM call recorded in a run:
llm_meta dicts are collected anywhere in the record and de-duplicated by their
JSON form, because the same call meta appears in several history views. This
includes discarded length-match tries and clean reference calls.
Usage: python3 scripts/run_cost.py <results.jsonl>... [--in 0.27 --out 0.85]  ($ per 1M tokens)
"""
import argparse, json

def metas(o, acc):
    if isinstance(o, dict):
        if "prompt_tokens" in o and "completion_tokens" in o:
            acc.add(json.dumps(o, sort_keys=True))
        for v in o.values():
            metas(v, acc)
    elif isinstance(o, list):
        for v in o:
            metas(v, acc)

ap = argparse.ArgumentParser(); ap.add_argument("files", nargs="+")
ap.add_argument("--in", dest="pin", type=float, default=0.27); ap.add_argument("--out", type=float, default=0.85)
a = ap.parse_args()
tot = 0.0
for f in a.files:
    n = pt = ct = calls = 0
    for l in open(f):
        acc = set(); metas(json.loads(l), acc); n += 1; calls += len(acc)
        for m in map(json.loads, acc):
            pt += m.get("prompt_tokens") or 0; ct += m.get("completion_tokens") or 0
    c = pt / 1e6 * a.pin + ct / 1e6 * a.out; tot += c
    print(f"{f.split('/')[-1]:40s} runs={n:4d} calls={calls:5d} in={pt:9d} out={ct:8d}  ${c:.3f}  (${c / max(n, 1):.4f}/run)")
print(f"total ${tot:.3f}")
