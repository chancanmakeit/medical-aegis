#!/usr/bin/env python3
# file: data_processing/medical/build_medical_dataset.py
"""
Build the AEGIS-format medical trajectory datasets from raw main.py output.

Inputs are the raw .jsonl files written by main.py (one record per task), produced by:
  * a CLEAN run  (--no_inject)   -> candidate NORMAL trajectories
  * an INJECT run                -> candidate ERROR  trajectories

This script:
  1. Reads normal-run and inject-run jsonl files.
  2. Keeps NORMAL records where is_correct == True   (task solved, no error).
  3. Keeps ERROR  records where is_correct == False  (injection changed the answer).
  4. Emits each set in the unified schema:
        {id, metadata, input, output, ground_truth}
     matching evaluation/data/aegis.jsonl.
  5. Optionally builds contrastive pairs (same query, normal vs error).

Usage:
  python data_processing/medical/build_medical_dataset.py \
      --normal results_inj/medqa/gpt-4o-mini/dylan_fm_clean_none_none.jsonl \
      --inject results_inj/medqa/gpt-4o-mini/dylan_fm_multi_*.jsonl \
      --framework dylan --benchmark medqa --model gpt-4o-mini \
      --out_dir datasets/medical_built
"""

import argparse
import glob
import hashlib
import json
import os
from typing import Any, Dict, List


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _expand(paths: List[str]) -> List[str]:
    out = []
    for p in paths:
        out.extend(sorted(glob.glob(p)) or [p])
    return out


def _infer_phase(framework: str, agent_name: str, step_idx: int) -> str:
    """Map an agent turn to one of the official phase labels.

    Official phases observed: initialization, reasoning, discussion, evaluation.
    """
    name = (agent_name or "").lower()
    if "roleassigner" in name:
        return "initialization"
    if "evaluator" in name or "critic" in name:
        return "evaluation"
    if "aggregator" in name or "ranker" in name:
        return "discussion"
    if framework in ("llm_debate", "macnet", "agentverse"):
        return "discussion" if step_idx > 0 else "reasoning"
    return "reasoning"


def _conv_history(rec: Dict[str, Any], framework: str,
                  injected_names: set) -> List[Dict[str, Any]]:
    log = rec.get("injection_log", {}) or {}
    # Prefer the normalized conversation_history; fall back to legacy full_history.
    hist = log.get("conversation_history") or log.get("full_history") or []
    norm = []
    for i, h in enumerate(hist):
        # Unified schema uses agent_name; legacy logs used role.
        agent_name = h.get("agent_name") or h.get("role") or f"agent_{i}"
        # Sequential 1-based step (use the normalized step if present).
        step = h.get("step") if isinstance(h.get("step"), int) else i + 1
        entry = {
            "step": step,
            "agent_name": agent_name,
            "content": h.get("content") or h.get("response") or "",
            "phase": h.get("phase") or _infer_phase(framework, agent_name, i),
        }
        # Preserve the exact LLM inputs when the framework captured them (AgentVerse).
        if h.get("input_messages") is not None:
            entry["input_messages"] = h["input_messages"]
        # Carry the round index when the framework exposes it (useful for multi-round MAS).
        if isinstance(h.get("round"), int):
            entry["round"] = h["round"]
        # Carry full injection-audit fields when this turn was injected.
        for k in ("injection_applied", "fm_error_type", "injection_strategy",
                  "original_input_messages", "injected_input_messages",
                  "prompt_modified",
                  "clean_response_before_corruption", "response_corrupted",
                  "injection_error", "injection_process",
                  "injection_description",
                  "is_input", "is_aggregator"):
            if k in h:
                entry[k] = h[k]
        # Only error records carry per-turn is_injected flags (matches official data).
        if injected_names:
            entry["is_injected"] = str(agent_name in injected_names)
        norm.append(entry)
    return norm


def _faulty_agents(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    log = rec.get("injection_log", {}) or {}
    info = log.get("multi_injection_info") or []
    faulty = []
    for it in info:
        faulty.append({
            "agent_name": it.get("injected_role"),
            "error_type": it.get("fm_error_type"),
            "injection_strategy": it.get("injection_strategy"),
        })
    # single-agent fallback
    if not faulty and rec.get("fm_error_type"):
        faulty.append({
            "agent_name": rec.get("injection_log", {}).get("injected_role"),
            "error_type": rec.get("fm_error_type"),
            "injection_strategy": rec.get("injection_strategy"),
        })
    return faulty


def _injected_agents(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ground_truth.injected_agents — like faulty_agents plus a description field.

    `malicious_action_description` prefers the LLM-generated, sample-specific
    description from conversation_history[*].injection_description (added by the
    describer in main.py) over the static, generic string from multi_injection_info.
    Matching is by (agent_name, fm_error_type) — falling back to positional order.
    """
    log = rec.get("injection_log", {}) or {}
    info = log.get("multi_injection_info") or []
    hist = log.get("conversation_history") or []

    # Build an index of LLM descriptions per injected turn.
    descs_by_key: Dict[tuple, List[str]] = {}
    descs_positional: List[str] = []
    for t in hist:
        if isinstance(t, dict) and t.get("injection_applied") and t.get("injection_description"):
            key = (t.get("agent_name"), t.get("fm_error_type"))
            descs_by_key.setdefault(key, []).append(t["injection_description"])
            descs_positional.append(t["injection_description"])

    def _pick_desc(role: str, fm: str, fallback: str, used_idx: List[int]) -> str:
        # Prefer keyed match (agent_name, fm_error_type) for accuracy when there
        # are multiple injected turns; pop from the bucket so each LLM description
        # is used at most once.
        bucket = descs_by_key.get((role, fm))
        if bucket:
            return bucket.pop(0)
        # Positional fallback
        if descs_positional and len(used_idx) < len(descs_positional):
            d = descs_positional[len(used_idx)]
            used_idx.append(len(used_idx))
            return d
        return fallback

    out = []
    used_idx: List[int] = []
    for it in info:
        desc = _pick_desc(
            it.get("injected_role"), it.get("fm_error_type"),
            it.get("malicious_action_description", ""), used_idx,
        )
        out.append({
            "agent_name": it.get("injected_role"),
            "error_type": it.get("fm_error_type"),
            "injection_strategy": it.get("injection_strategy"),
            "malicious_action_description": desc,
        })
    if not out and rec.get("fm_error_type"):
        out.append({
            "agent_name": log.get("injected_role"),
            "error_type": rec.get("fm_error_type"),
            "injection_strategy": rec.get("injection_strategy"),
            "malicious_action_description": descs_positional[0] if descs_positional else "",
        })
    return out


def _to_unified(rec: Dict[str, Any], framework: str, benchmark: str, model: str,
                label: str) -> Dict[str, Any]:
    query = rec.get("query") or rec.get("input", {}).get("query", "")
    uid = f"{benchmark}_{model}_{framework}_{label}_" + hashlib.md5(
        (query + label).encode("utf-8")).hexdigest()[:8]
    gt = rec.get("ground_truth")
    if not isinstance(gt, dict):
        gt = {"correct_answer": rec.get("answer") or gt}
    correct_answer = gt.get("correct_answer", rec.get("answer"))

    faulty = _faulty_agents(rec) if label == "error" else []
    injected = _injected_agents(rec) if label == "error" else []
    injected_names = {a.get("agent_name") for a in injected if a.get("agent_name")}

    num_agents = rec.get("num_agents") or (rec.get("injection_log", {}) or {}).get("num_agents")

    input_block = {
        "query": query,
        "conversation_history": _conv_history(rec, framework, injected_names),
    }
    # Official data omits final_output for dylan; include it when available otherwise.
    final_out = rec.get("response")
    if framework != "dylan" and final_out is not None:
        input_block["final_output"] = final_out

    out_rec = {
        "id": uid,
        "metadata": {
            "framework": framework,
            "benchmark": benchmark,
            "model": model,
            "num_agents": num_agents,
            "num_injected_agents": len(faulty),
            "task_type": "medical",
            # non-official extras (kept for your own filtering; harmless to downstream)
            "label": label,
            "is_correct": rec.get("is_correct"),
            # Full verification audit (judge_mode, decision_path, llm_judge_called,
            # llm_judge_raw_output, etc.) so the user can see how is_correct was decided.
            "verification": rec.get("verification"),
        },
        "input": input_block,
        "output": {"faulty_agents": faulty},
        "ground_truth": {
            "correct_answer": correct_answer,
            "injected_agents": injected,
            # normal trajectory: no successful injection; error trajectory: injection flipped answer
            "is_injection_successful": (label == "error"),
        },
    }
    # LLM-generated sample-level summary of how the injections affected this trajectory.
    if rec.get("injection_summary"):
        out_rec["injection_summary"] = rec["injection_summary"]
    return out_rec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--normal", nargs="*", default=[], help="Raw jsonl(s) from CLEAN run.")
    p.add_argument("--inject", nargs="*", default=[], help="Raw jsonl(s) from INJECT run.")
    p.add_argument("--framework", required=True)
    p.add_argument("--benchmark", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--out_dir", default="datasets/medical_built")
    p.add_argument("--make_pairs", action="store_true",
                   help="Also emit contrastive (normal,error) pairs matched by query.")
    p.add_argument("--strict_schema", action="store_true",
                   help="Drop non-official extras (metadata.label, metadata.is_correct) so "
                        "records are shape-identical to the official AEGIS release for merging.")
    args = p.parse_args()

    def _strip(rec):
        if args.strict_schema:
            rec["metadata"].pop("label", None)
            rec["metadata"].pop("is_correct", None)
            rec["metadata"].pop("verification", None)
            rec.pop("injection_summary", None)
            for e in rec["input"].get("conversation_history", []):
                e.pop("round", None)
                e.pop("input_messages", None)
                # Also drop injection-audit fields (not in official schema).
                for k in ("injection_applied", "fm_error_type", "injection_strategy",
                          "original_input_messages", "injected_input_messages",
                          "prompt_modified", "clean_response_before_corruption",
                          "response_corrupted", "injection_error", "injection_process",
                          "injection_description",
                          "is_input", "is_aggregator"):
                    e.pop(k, None)
        return rec

    os.makedirs(args.out_dir, exist_ok=True)

    normal_recs, error_recs = [], []
    for path in _expand(args.normal):
        for r in _load_jsonl(path):
            if r.get("status") == "success" and r.get("is_correct") is True:
                normal_recs.append(_strip(_to_unified(r, args.framework, args.benchmark, args.model, "normal")))
    for path in _expand(args.inject):
        for r in _load_jsonl(path):
            if r.get("status") == "success" and r.get("is_correct") is False:
                error_recs.append(_strip(_to_unified(r, args.framework, args.benchmark, args.model, "error")))

    tag = f"{args.benchmark}_{args.framework}_{args.model}"
    normal_path = os.path.join(args.out_dir, f"{tag}_normal.jsonl")
    error_path = os.path.join(args.out_dir, f"{tag}_error.jsonl")
    with open(normal_path, "w", encoding="utf-8") as f:
        for r in normal_recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(error_path, "w", encoding="utf-8") as f:
        for r in error_recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"NORMAL trajectories: {len(normal_recs)} -> {normal_path}")
    print(f"ERROR  trajectories: {len(error_recs)} -> {error_path}")

    if args.make_pairs:
        idx = {}
        for r in normal_recs:
            idx.setdefault(r["input"]["query"].strip(), {})["normal"] = r
        for r in error_recs:
            idx.setdefault(r["input"]["query"].strip(), {})["error"] = r
        pairs = [{"query": q, "normal": d["normal"], "error": d["error"]}
                 for q, d in idx.items() if "normal" in d and "error" in d]
        pairs_path = os.path.join(args.out_dir, f"{tag}_pairs.jsonl")
        with open(pairs_path, "w", encoding="utf-8") as f:
            for pr in pairs:
                f.write(json.dumps(pr, ensure_ascii=False) + "\n")
        print(f"CONTRASTIVE pairs:   {len(pairs)} -> {pairs_path}")


if __name__ == "__main__":
    main()
