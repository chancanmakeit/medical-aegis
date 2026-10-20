#!/usr/bin/env python3
# file: scripts/recompute_trial_success_verdicts.py
"""
Offline re-scorer for ClinicalAgent / trial_success result files.

WHY THIS EXISTS
---------------
An earlier verifier bug let the LLM judge OVERRIDE the exact deterministic
threshold comparison for the `trial_success` (binary-via-probability) task,
in `judge_mode: llm_primary`. Because a general-purpose LLM judge does not
apply the 0.5 threshold, it wrongly marked many correct probability answers as
INCORRECT. The verifier is now fixed (trial_success is in
DETERMINISTIC_AUTHORITATIVE, so the deterministic verdict wins whenever it is
decisive), but result files produced BEFORE the fix carry wrong values in:

  - is_correct
  - is_valid_normal   (clean runs;  == is_correct)
  - is_valid_error    (inject runs; == not is_correct)
  - verification.deterministic_verdict
  - verification.final_verdict
  - verification.decision_path
  - verification.llm_judge_called / llm_judge_verdict / llm_judge_raw_output
    (these are cleared when the deterministic verdict is now authoritative and
     the judge is no longer consulted)

This script recomputes those fields IN PLACE using the SAME probability
extraction + thresholding logic as the fixed verifier, WITHOUT calling any LLM.
It uses the probability already stored at injection_log.predicted_probability
when present, otherwise re-extracts it from the `response` text.

It only rewrites records whose dataset is trial_success (detected via
ground_truth.predict_target == "failure_probability", or an explicit
--assume_trial_success flag). Records from other datasets are passed through
untouched, so it's safe to run on mixed trees.

USAGE
-----
# a single clean file
python scripts/recompute_trial_success_verdicts.py \
    --paths ./results_inj/.../clinical_agent_fm_clean_none_none.jsonl

# a whole diverse-run tree of inject files (recursive)
python scripts/recompute_trial_success_verdicts.py \
    --paths ./results_diverse/grok-4-1-fast-reasoning/results/clinical_agent \
    --glob "**/trajectories.jsonl"

# preview without writing (prints the diff summary only)
python scripts/recompute_trial_success_verdicts.py --paths ... --dry_run

By default the original file is backed up to <file>.bak before rewriting
(disable with --no_backup).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Probability extraction — copied verbatim (in behavior) from the fixed
# aegis_core/utils/medical_verifier.py so this script is self-contained and
# will produce identical verdicts to a fresh run.
# --------------------------------------------------------------------------- #
_PROB_TAG_RE = re.compile(r"<final_result>\s*([^<>]+?)\s*</final_result>", re.IGNORECASE | re.DOTALL)
_PROB_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+")


def _extract_probability(response: str) -> Optional[float]:
    if not response:
        return None
    inner = None
    m = _PROB_TAG_RE.search(response)
    if m:
        inner = m.group(1)
    else:
        alt = re.search(r"final[_\s]?result[:\s]*([-+]?\d*\.?\d+%?)", response, re.IGNORECASE)
        if not alt:
            return None
        inner = alt.group(1)
    nums = _PROB_FLOAT_RE.findall(inner)
    if not nums:
        return None
    try:
        val = float(nums[0])
    except ValueError:
        return None
    if "%" in inner:
        val = val / 100.0
    if val < 0.0:
        val = 0.0
    if val > 1.0:
        val = 1.0
    return val


def _verify_probability(prob: Optional[float], gt: Dict[str, Any]) -> Optional[bool]:
    """Same logic as the fixed verifier's _verify_probability, but takes an
    already-extracted probability (or None)."""
    if prob is None:
        return None
    threshold = float(gt.get("threshold", 0.5))
    pred_binary = 1 if prob >= threshold else 0
    gold_raw = gt.get("correct_answer", None)
    if gold_raw is None:
        return None
    try:
        gold_binary = int(str(gold_raw).strip())
    except ValueError:
        return None
    if gold_binary not in (0, 1):
        return None
    return pred_binary == gold_binary


def _is_trial_success(rec: Dict[str, Any], assume: bool) -> bool:
    if assume:
        return True
    gt = rec.get("ground_truth") or {}
    if isinstance(gt, dict) and gt.get("predict_target") == "failure_probability":
        return True
    # Fallback: detect the response's tag + a binary gold.
    return False


def recompute_record(rec: Dict[str, Any], assume_trial_success: bool) -> Tuple[bool, Dict[str, Any]]:
    """Return (changed, rec). Mutates rec in place for trial_success records."""
    if not _is_trial_success(rec, assume_trial_success):
        return False, rec
    # Skip records that never produced a usable trajectory.
    if rec.get("status") not in (None, "success"):
        # e.g. 'error' or 'llm_api_failure' — leave as-is (their is_correct=False stands)
        return False, rec

    gt = rec.get("ground_truth") or {}

    # Prefer the already-stored probability; else re-extract from response.
    prob = None
    ilog = rec.get("injection_log") or {}
    if isinstance(ilog, dict) and ilog.get("predicted_probability") is not None:
        prob = ilog.get("predicted_probability")
    if prob is None:
        prob = _extract_probability(rec.get("response", ""))

    det = _verify_probability(prob, gt)

    # Build the new verification audit consistent with the fixed verifier's
    # authoritative-deterministic path.
    old_ver = rec.get("verification") or {}
    new_ver = dict(old_ver)  # keep unrelated fields (judge_mode, gold, etc.)
    new_ver["deterministic_verdict"] = det
    # regex_extracted stays None for trial_success (it's an MCQ-only field).

    if det is not None:
        new_verdict = det
        new_ver["decision_path"] = "authoritative_deterministic/decisive"
        # The judge is no longer consulted for a decisive deterministic verdict.
        new_ver["llm_judge_called"] = False
        new_ver["llm_judge_verdict"] = None
        new_ver["llm_judge_raw_output"] = None
    else:
        # Deterministic couldn't decide. We CANNOT re-run the LLM judge offline,
        # so we preserve whatever the original judge said if it was called;
        # otherwise default False (matches verifier's undecidable path).
        if old_ver.get("llm_judge_called") and old_ver.get("llm_judge_verdict") is not None:
            new_verdict = bool(old_ver.get("llm_judge_verdict"))
            new_ver["decision_path"] = "authoritative_deterministic/llm_judge_fallback(offline_preserved)"
        else:
            new_verdict = False
            new_ver["decision_path"] = "authoritative_deterministic/undecidable_default_false"
    new_ver["final_verdict"] = new_verdict

    old_correct = rec.get("is_correct")
    changed = (old_correct != new_verdict) or (old_ver != new_ver)

    rec["verification"] = new_ver
    rec["is_correct"] = bool(new_verdict)
    # Derive the split-validity flags exactly like main.py does.
    run_mode = rec.get("run_mode")
    if run_mode == "clean" or ("is_valid_normal" in rec and "is_valid_error" not in rec):
        rec["is_valid_normal"] = bool(new_verdict)
    elif run_mode == "inject" or ("is_valid_error" in rec and "is_valid_normal" not in rec):
        rec["is_valid_error"] = (not bool(new_verdict))
    else:
        # run_mode missing and ambiguous — update whichever flag(s) exist.
        if "is_valid_normal" in rec:
            rec["is_valid_normal"] = bool(new_verdict)
        if "is_valid_error" in rec:
            rec["is_valid_error"] = (not bool(new_verdict))

    return changed, rec


def process_file(path: str, dry_run: bool, backup: bool,
                 assume_trial_success: bool) -> Dict[str, Any]:
    recs: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            recs.append(json.loads(line))

    stats = {"file": path, "total": len(recs), "trial_success": 0,
             "changed": 0, "flip_true_to_false": 0, "flip_false_to_true": 0,
             "valid_before": 0, "valid_after": 0}

    for rec in recs:
        is_ts = _is_trial_success(rec, assume_trial_success)
        # Count validity before
        vb = rec.get("is_valid_normal")
        if vb is None:
            vb = rec.get("is_valid_error")
            vb = (vb is True)  # for error files, "valid" means is_valid_error True
        else:
            vb = (vb is True)
        old_correct = rec.get("is_correct")

        if is_ts:
            stats["trial_success"] += 1
        changed, _ = recompute_record(rec, assume_trial_success)
        if changed:
            stats["changed"] += 1
            new_correct = rec.get("is_correct")
            if old_correct is True and new_correct is False:
                stats["flip_true_to_false"] += 1
            elif old_correct is False and new_correct is True:
                stats["flip_false_to_true"] += 1

        # Count "valid for its split" after
        if "is_valid_normal" in rec:
            stats["valid_after"] += 1 if rec.get("is_valid_normal") else 0
            stats["valid_before"] += 1 if vb else 0
        elif "is_valid_error" in rec:
            stats["valid_after"] += 1 if rec.get("is_valid_error") else 0
            stats["valid_before"] += 1 if vb else 0

    if not dry_run and stats["changed"] > 0:
        if backup:
            bak = path + ".bak"
            if not os.path.exists(bak):
                os.rename(path, bak)
                # rename moves the original; rewrite from bak content
                with open(bak, "r", encoding="utf-8") as _src:
                    pass  # (we already have recs in memory)
        with open(path, "w", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return stats


def gather_paths(paths: List[str], glob: str) -> List[str]:
    out = []
    for p in paths:
        pth = Path(p)
        if pth.is_file():
            out.append(str(pth))
        elif pth.is_dir():
            out.extend(sorted(str(x) for x in pth.glob(glob)))
        else:
            print(f"[warn] path not found: {p}", file=sys.stderr)
    # dedup preserve order
    seen = set(); uniq = []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paths", nargs="+", required=True,
                    help="One or more result .jsonl files, and/or directories to search.")
    ap.add_argument("--glob", default="**/trajectories.jsonl",
                    help="Glob used for any directory in --paths (default: "
                         "'**/trajectories.jsonl'; use '*.jsonl' for a flat dir "
                         "of clean files).")
    ap.add_argument("--assume_trial_success", action="store_true",
                    help="Treat EVERY record as trial_success (use only if your "
                         "ground_truth lacks predict_target but you know the file "
                         "is a trial_success run).")
    ap.add_argument("--dry_run", action="store_true",
                    help="Report what would change without writing files.")
    ap.add_argument("--no_backup", action="store_true",
                    help="Do not create <file>.bak backups before rewriting.")
    args = ap.parse_args()

    files = gather_paths(args.paths, args.glob)
    if not files:
        raise SystemExit("No files matched. Check --paths / --glob.")

    print(f"[recompute] {len(files)} file(s) to process"
          f"{' (DRY RUN — no writes)' if args.dry_run else ''}\n")

    grand = {"total": 0, "trial_success": 0, "changed": 0,
             "flip_true_to_false": 0, "flip_false_to_true": 0,
             "valid_before": 0, "valid_after": 0}
    for path in files:
        st = process_file(path, dry_run=args.dry_run,
                          backup=not args.no_backup,
                          assume_trial_success=args.assume_trial_success)
        for k in grand:
            grand[k] += st.get(k, 0)
        short = path if len(path) < 80 else "..." + path[-77:]
        print(f"  {short}")
        print(f"    records={st['total']:<5} trial_success={st['trial_success']:<5} "
              f"changed={st['changed']:<5} "
              f"T->F={st['flip_true_to_false']:<4} F->T={st['flip_false_to_true']:<4} "
              f"valid(for split): {st['valid_before']} -> {st['valid_after']}")

    print("\n" + "=" * 70)
    print("TOTALS")
    print("=" * 70)
    print(f"  files:                 {len(files)}")
    print(f"  records:               {grand['total']}")
    print(f"  trial_success records: {grand['trial_success']}")
    print(f"  records changed:       {grand['changed']}")
    print(f"  flips True->False:     {grand['flip_true_to_false']}")
    print(f"  flips False->True:     {grand['flip_false_to_true']}")
    print(f"  valid-for-split:       {grand['valid_before']} -> {grand['valid_after']}")
    if args.dry_run:
        print("\n  (dry run — no files were modified)")
    else:
        print(f"\n  backups: {'disabled' if args.no_backup else 'written as <file>.bak'}")


if __name__ == "__main__":
    main()
