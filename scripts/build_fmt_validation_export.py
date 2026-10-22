#!/usr/bin/env python3
"""Paired old-note vs fmt_v1 export for the format-fix validation (v10 round 5).

Keeps only the questions that have fmt_v1 runs, and on those questions: all
normal runs, plus PI and plain-sham inject runs of BOTH note versions (old =
length-matched PI `_pi4` / sham `_sham`; new = `note_version == fmt_v1`).
RC, sham_style and the pre-length-match PI are dropped, so quality_gate's
same_slot section compares the two notes on identical questions and slots.

Usage: python3 scripts/build_fmt_validation_export.py full_export.jsonl out.jsonl
"""
import json
import sys


def kind(r):
    """'normal', ('pi'|'sham', 'old'|'fmt_v1'), or None (dropped)."""
    if r["run_mode"] == "normal":
        return "normal"
    injs = r["labels"].get("injection") or []
    if not injs:
        return None                      # not fired
    i = injs[0]
    st = i.get("effective_strategy") or i.get("strategy")
    ver = i.get("note_version") or "old"            # fmt_v1, fmt_v1_1, ...
    if st == "prompt_injection" and i.get("pi_length_match"):
        return ("pi", ver)
    if st == "sham" and i.get("sham_variant", "plain_v1") == "plain_v1":
        return ("sham", ver)
    return None


def main():
    src, dst = sys.argv[1], sys.argv[2]
    runs = [json.loads(l) for l in open(src)]
    qs = {r["question_id"] for r in runs
          if any(i.get("note_version") for i in r["labels"].get("injection") or [])}
    keep, counts = [], {}
    for r in runs:
        if r["question_id"] not in qs:
            continue
        k = kind(r)
        if k is None:
            continue
        keep.append(r)
        counts[(r["framework"], str(k))] = counts.get((r["framework"], str(k)), 0) + 1
    with open(dst, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in keep)
    print(f"{len(qs)} questions, {len(keep)} runs -> {dst}")
    for k in sorted(counts):
        print(f"  {k[0]:14s} {k[1]:22s} {counts[k]}")


if __name__ == "__main__":
    main()
