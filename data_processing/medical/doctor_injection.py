#!/usr/bin/env python3
# file: data_processing/medical/doctor_injection.py
"""
Diagnose whether error injection actually had an effect, by inspecting one (or two)
raw result jsonl files produced by main.py.

Single-file diagnosis prints, for each record:
  - whether any turn was tagged injection_applied
  - whether the modified prompt actually differed from the original (prompt_modified)
  - whether the response was actually corrupted (response_corrupted)
  - whether the model's final response was correct (is_correct)
  - any injection_error captured during the run

Paired diagnosis (--clean clean.jsonl --inject inject.jsonl) additionally aligns
records by query and reports, per pair:
  - whether the inject run's response differs from the clean run's response
  - whether is_correct flipped (clean=True -> inject=False is the desired error case)

Aggregate stats are printed at the end so you can tell at a glance whether your
injection setup is working (e.g. "injection had no effect on 80% of samples" means
something is wrong — likely an RLHF refusal in llm_rewrite mode; switch to
injection_method: direct_prepend in the YAML).

Usage:
    python data_processing/medical/doctor_injection.py --inject inject.jsonl
    python data_processing/medical/doctor_injection.py --clean clean.jsonl --inject inject.jsonl
"""

import argparse
import json
from collections import Counter
from typing import List, Dict, Any


def _load(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _injection_stats(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Extract per-record injection diagnostics from a raw main.py jsonl record."""
    log = rec.get("injection_log", {}) or {}
    hist = log.get("conversation_history") or log.get("full_history") or []
    turns_with_metadata = [t for t in hist if isinstance(t, dict) and t.get("injection_applied")]
    ver = rec.get("verification", {}) or {}
    return {
        "id": rec.get("id"),
        "status": rec.get("status"),
        "is_correct": rec.get("is_correct"),
        "run_mode": rec.get("run_mode"),
        "num_turns": len(hist),
        "num_injected_turns": len(turns_with_metadata),
        "any_prompt_modified": any(t.get("prompt_modified") for t in turns_with_metadata),
        "any_response_corrupted": any(t.get("response_corrupted") for t in turns_with_metadata),
        "injection_errors": [t.get("injection_error") for t in turns_with_metadata if t.get("injection_error")],
        "fm_error_types": sorted({t.get("fm_error_type") for t in turns_with_metadata if t.get("fm_error_type")}),
        # Verification audit (added by main.py)
        "verification_path": ver.get("decision_path"),
        "llm_judge_called": ver.get("llm_judge_called"),
    }


def _print_single(rows: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    print(f"\n===== {label}: {len(rows)} records =====")
    stats = [_injection_stats(r) for r in rows]

    n_status_ok = sum(1 for s in stats if s["status"] == "success")
    n_status_api_fail = sum(1 for s in stats if s["status"] == "llm_api_failure")
    n_status_err = sum(1 for s in stats if s["status"] == "error")
    n_with_injection_meta = sum(1 for s in stats if s["num_injected_turns"] > 0)
    n_prompt_modified = sum(1 for s in stats if s["any_prompt_modified"])
    n_response_corrupted = sum(1 for s in stats if s["any_response_corrupted"])
    n_correct = sum(1 for s in stats if s["is_correct"] is True)
    n_errors = sum(1 for s in stats if s["injection_errors"])
    n_judge_called = sum(1 for s in stats if s["llm_judge_called"])
    paths = Counter(s["verification_path"] for s in stats if s["verification_path"])
    fm_counter = Counter()
    for s in stats:
        for t in s["fm_error_types"]:
            fm_counter[t] += 1

    print(f"  status==success                  : {n_status_ok} / {len(rows)}")
    if n_status_api_fail:
        print(f"  status==llm_api_failure          : {n_status_api_fail}  *** LLM API was unreachable; trajectories invalid ***")
    if n_status_err:
        print(f"  status==error                    : {n_status_err}")
    print(f"  records with any injected turn   : {n_with_injection_meta}")
    print(f"  records where prompt was modified: {n_prompt_modified}")
    print(f"  records where response corrupted : {n_response_corrupted}")
    print(f"  records with is_correct == True  : {n_correct}")
    print(f"  records with injection errors    : {n_errors}")
    print(f"  records where LLM judge was called: {n_judge_called}")
    if paths:
        print(f"  verification decision paths (top): {dict(paths.most_common(5))}")
    if fm_counter:
        print(f"  FM error types observed: {dict(fm_counter)}")
    if n_with_injection_meta and n_judge_called == 0 and len(rows) > 0:
        print("  *** NOTE: LLM judge was NEVER called on any record. Either")
        print("      use_llm_judge: false is set, the judge LLM is unreachable,")
        print("      or every record was decided by the deterministic parser.")
        print("      For long/free-form responses you almost certainly want the")
        print("      LLM judge: set use_llm_judge: true and judge_mode: llm_primary.")
    if n_with_injection_meta and not (n_prompt_modified or n_response_corrupted):
        print("  *** WARNING: injection was attempted but NEITHER prompt NOR response")
        print("      was actually modified on any record. This usually means the")
        print("      llm_rewrite path silently returned the original text (RLHF refusal).")
        print("      Set `injection_method: direct_prepend` in the experiment YAML.")
    return {
        "n": len(rows),
        "stats": stats,
        "n_correct": n_correct,
        "n_with_injection_meta": n_with_injection_meta,
        "n_prompt_modified": n_prompt_modified,
        "n_response_corrupted": n_response_corrupted,
    }


def _diagnose_pair(clean_rows: List[Dict[str, Any]], inj_rows: List[Dict[str, Any]]):
    print("\n===== PAIRED DIAGNOSIS =====")
    clean_by_q = {r.get("query", "").strip(): r for r in clean_rows}
    diffs = 0
    flips = 0
    same_resp = 0
    matched = 0
    for r in inj_rows:
        q = r.get("query", "").strip()
        c = clean_by_q.get(q)
        if c is None:
            continue
        matched += 1
        if r.get("response") != c.get("response"):
            diffs += 1
        else:
            same_resp += 1
        if c.get("is_correct") is True and r.get("is_correct") is False:
            flips += 1
    print(f"  matched query pairs: {matched}")
    print(f"  inject.response differs from clean.response: {diffs}")
    print(f"  identical responses (bad sign if many)     : {same_resp}")
    print(f"  desirable correctness flips (clean True -> inject False): {flips}")
    if matched and same_resp / matched > 0.5:
        print("  *** WARNING: >50% of paired records have identical responses in clean")
        print("      and inject runs. Injection is not having a behavioral effect.")
        print("      Switch to `injection_method: direct_prepend` and/or pick stronger")
        print("      FM error types (FM-2.3, FM-3.1) and target the Solver/Aggregator.")


def main():
    p = argparse.ArgumentParser(description="Diagnose injection effectiveness.")
    p.add_argument("--clean", help="raw clean-run jsonl from main.py --no_inject")
    p.add_argument("--inject", help="raw inject-run jsonl from main.py")
    args = p.parse_args()

    if not args.clean and not args.inject:
        p.error("provide at least --inject (and optionally --clean for paired diagnosis).")

    inj_rows = _load(args.inject) if args.inject else []
    cln_rows = _load(args.clean) if args.clean else []

    if cln_rows:
        _print_single(cln_rows, "CLEAN run")
    if inj_rows:
        _print_single(inj_rows, "INJECT run")
    if cln_rows and inj_rows:
        _diagnose_pair(cln_rows, inj_rows)


if __name__ == "__main__":
    main()
