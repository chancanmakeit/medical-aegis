#!/usr/bin/env python3
# file: scripts/build_paired_dataset.py
"""
Build a PAIRED contrastive dataset from clean (normal) trajectories and
error-injected trajectories.

Keep only sample IDs where BOTH conditions hold:
  - the clean file has a record with `is_valid_normal == True`, AND
  - at least one inject file has a record with `is_valid_error == True` for the same id.

For each paired id, emit:
  - the SINGLE clean record  -> <output_dir>/paired_normal.jsonl
  - ALL its valid error records (up to --max_errors_per_id, sorted by source
    config label for determinism) -> <output_dir>/paired_error.jsonl

This gives you, for contrastive learning, a fully-paired dataset:
  - every id in paired_error.jsonl has at least one matching record in paired_normal.jsonl
  - every id in paired_normal.jsonl has at least one matching record in paired_error.jsonl

Usage example
-------------
python scripts/build_paired_dataset.py \\
    --clean ./results_inj/medxpertqa-mm/gemini-2.5-flash-lite/mdagents_fm_clean_none_none.jsonl \\
    --inject_root ./results_diverse-medxpertqa-mm-100/results/mdagents \\
    --output_dir ./paired_dataset/medxpertqa-mm
"""
import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _read_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    """Yield records from a JSONL file. Tolerate blank / malformed lines."""
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[warn] {path}:{i} malformed JSON: {e}", file=sys.stderr)
                continue


def _scan_inject_files(inject_root: str, pattern: str) -> List[str]:
    """Return absolute paths to every inject jsonl under inject_root matching pattern."""
    root = Path(inject_root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"--inject_root does not exist: {root}")
    matches = sorted(str(p) for p in root.glob(pattern))
    if not matches:
        raise SystemExit(
            f"No inject jsonl files found under {root} matching '{pattern}'. "
            f"Did you mean `--inject_glob '*.jsonl'`?"
        )
    return matches


def _config_label_from_path(path: str, inject_root: str) -> str:
    """Derive a short, stable identifier for which inject config produced a file.

    For orchestrator-style layouts that put each config in its own subdirectory
    (`<inject_root>/<label>/trajectories.jsonl`), the label is the
    parent directory name. For flat layouts (everything in one dir), we fall
    back to the basename minus extension.
    """
    p = Path(path)
    parent = p.parent.name
    if parent and parent != Path(inject_root).resolve().name:
        return parent
    return p.stem


def _record_passes_strict(rec: Dict[str, Any]) -> bool:
    """When --strict is on, also require status=='success' on the record.
    This excludes `llm_api_failure` and `error` records even if their
    is_valid_normal / is_valid_error flag is mistakenly true.
    """
    return rec.get("status") == "success"


def build_paired(
    clean_path: str,
    inject_files: List[str],
    inject_root: str,
    strict: bool,
    max_errors_per_id: int = 0,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    """Return (clean_by_id, errors_by_id, stats).

    clean_by_id : {id: clean_record_with_is_valid_normal_True}
    errors_by_id: {id: [error_records_with_is_valid_error_True]}
    Only ids appearing in BOTH dicts are kept; this is the intersection.
    """
    stats: Dict[str, Any] = {
        "clean_file": clean_path,
        "n_inject_files": len(inject_files),
        "clean_total": 0,
        "clean_valid_normal": 0,
        "clean_kept": 0,
        "inject_total": 0,
        "inject_valid_error": 0,
        "inject_kept": 0,
        "paired_ids": 0,
        "per_id_error_count_histogram": {},
        "per_inject_file": {},
    }

    # --- pass 1: clean ---
    clean_candidates: Dict[str, Dict[str, Any]] = {}  # id -> first valid clean record
    for rec in _read_jsonl(clean_path):
        stats["clean_total"] += 1
        if not rec.get("is_valid_normal"):
            continue
        if strict and not _record_passes_strict(rec):
            continue
        stats["clean_valid_normal"] += 1
        rid = rec.get("id")
        if rid is None:
            continue
        # Keep the FIRST occurrence per id (a clean rerun shouldn't produce
        # duplicate ids; if it does, the first wins).
        if rid not in clean_candidates:
            rec.setdefault("_source_file", clean_path)
            clean_candidates[rid] = rec

    # --- pass 2: inject (across all files) ---
    error_candidates: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for ipath in inject_files:
        per_file = {"total": 0, "valid_error": 0, "kept": 0}
        config_label = _config_label_from_path(ipath, inject_root)
        for rec in _read_jsonl(ipath):
            per_file["total"] += 1
            stats["inject_total"] += 1
            if not rec.get("is_valid_error"):
                continue
            if strict and not _record_passes_strict(rec):
                continue
            per_file["valid_error"] += 1
            stats["inject_valid_error"] += 1
            rid = rec.get("id")
            if rid is None:
                continue
            # We only KEEP this error record if its id ALSO has a valid clean
            # counterpart. Skipping otherwise saves memory on large runs.
            if rid not in clean_candidates:
                continue
            rec.setdefault("_source_file", ipath)
            rec.setdefault("_source_config_label", config_label)
            error_candidates[rid].append(rec)
            per_file["kept"] += 1
            stats["inject_kept"] += 1
        stats["per_inject_file"][config_label] = per_file

    # --- intersection ---
    paired_ids = sorted(set(clean_candidates.keys()) & set(error_candidates.keys()))
    stats["paired_ids"] = len(paired_ids)

    # Filter clean_candidates to paired ids only
    clean_by_id = {rid: clean_candidates[rid] for rid in paired_ids}
    stats["clean_kept"] = len(clean_by_id)

    # Cap per-id error count if requested, and report histogram.
    errors_by_id: Dict[str, List[Dict[str, Any]]] = {}
    hist: Dict[int, int] = collections.Counter()
    for rid in paired_ids:
        recs = error_candidates[rid]
        # Sort by source_config_label so output is deterministic across runs.
        recs.sort(key=lambda r: r.get("_source_config_label", ""))
        if max_errors_per_id and len(recs) > max_errors_per_id:
            recs = recs[:max_errors_per_id]
        errors_by_id[rid] = recs
        hist[len(recs)] += 1
    stats["per_id_error_count_histogram"] = dict(sorted(hist.items()))

    return clean_by_id, errors_by_id, stats


def write_outputs(
    clean_by_id: Dict[str, Dict[str, Any]],
    errors_by_id: Dict[str, List[Dict[str, Any]]],
    output_dir: str,
    out_normal: str,
    out_error: str,
) -> Tuple[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    normal_path = os.path.join(output_dir, out_normal)
    error_path = os.path.join(output_dir, out_error)

    # Emit clean records in id order
    with open(normal_path, "w", encoding="utf-8") as f:
        for rid in sorted(clean_by_id.keys()):
            f.write(json.dumps(clean_by_id[rid], ensure_ascii=False) + "\n")
    # Emit error records grouped by id (id order outer; config_label inner)
    with open(error_path, "w", encoding="utf-8") as f:
        for rid in sorted(errors_by_id.keys()):
            for rec in errors_by_id[rid]:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return normal_path, error_path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--clean", required=True,
                    help="Path to the clean (normal) trajectories jsonl, "
                         "e.g. mdagents_fm_clean_none_none.jsonl")
    ap.add_argument("--inject_root", required=True,
                    help="Directory under which inject trajectory jsonl files live. "
                         "Recursively globbed.")
    ap.add_argument("--inject_glob", default="**/trajectories.jsonl",
                    help="Glob pattern under --inject_root. Default is the "
                         "orchestrator's layout `<config_label>/trajectories.jsonl`. "
                         "Use `*.jsonl` if all inject files are flat in one dir.")
    ap.add_argument("--output_dir", default="./paired_dataset",
                    help="Where to write paired_normal.jsonl + paired_error.jsonl + summary.json.")
    ap.add_argument("--output_normal", default="paired_normal.jsonl",
                    help="Name of the output normal jsonl file.")
    ap.add_argument("--output_error", default="paired_error.jsonl",
                    help="Name of the output error jsonl file.")
    ap.add_argument("--max_errors_per_id", type=int, default=0,
                    help="Cap on how many error records to keep per id (0 = unlimited). "
                         "Useful if you have 100 inject configs but only want a balanced "
                         "subset of error variants per clean record.")
    ap.add_argument("--strict", action="store_true",
                    help="Additionally require record['status'] == 'success' (rejects "
                         "records that succeeded structurally but came from a flaky "
                         "API call or had a downstream error).")
    args = ap.parse_args()

    if not os.path.exists(args.clean):
        raise SystemExit(f"--clean does not exist: {args.clean}")

    inject_files = _scan_inject_files(args.inject_root, args.inject_glob)
    print(f"[scan] clean file: {args.clean}")
    print(f"[scan] {len(inject_files)} inject files under {args.inject_root}")

    clean_by_id, errors_by_id, stats = build_paired(
        clean_path=args.clean,
        inject_files=inject_files,
        inject_root=args.inject_root,
        strict=args.strict,
        max_errors_per_id=args.max_errors_per_id,
    )

    normal_path, error_path = write_outputs(
        clean_by_id, errors_by_id,
        output_dir=args.output_dir,
        out_normal=args.output_normal,
        out_error=args.output_error,
    )

    # Add the final counts to stats and write a summary.
    stats["output_normal"] = normal_path
    stats["output_error"] = error_path
    stats["output_normal_records"] = len(clean_by_id)
    stats["output_error_records"] = sum(len(v) for v in errors_by_id.values())
    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Print a concise report
    print()
    print("=" * 70)
    print("PAIRING REPORT")
    print("=" * 70)
    print(f"  clean total records         : {stats['clean_total']}")
    print(f"  clean with is_valid_normal  : {stats['clean_valid_normal']}")
    print()
    print(f"  inject files scanned        : {stats['n_inject_files']}")
    print(f"  inject total records        : {stats['inject_total']}")
    print(f"  inject with is_valid_error  : {stats['inject_valid_error']}")
    print()
    print(f"  PAIRED ids (intersection)   : {stats['paired_ids']}")
    print(f"  normal records emitted      : {stats['output_normal_records']}")
    print(f"  error records emitted       : {stats['output_error_records']}")
    print()
    if stats["per_id_error_count_histogram"]:
        print("  per-id error count histogram (how many error variants each id got):")
        for k, v in stats["per_id_error_count_histogram"].items():
            print(f"    {k:>4} error variants -> {v} id(s)")
    print()
    print(f"  ->  {normal_path}")
    print(f"  ->  {error_path}")
    print(f"  ->  {summary_path}")

    if stats["paired_ids"] == 0:
        print()
        print("WARNING: no paired ids. Possible causes:")
        print("  - the clean run produced no is_valid_normal records (the MAS got too many wrong)")
        print("  - the inject runs produced no is_valid_error records (injection failed to flip answers)")
        print("  - id formats mismatch between clean and inject files")


if __name__ == "__main__":
    main()
