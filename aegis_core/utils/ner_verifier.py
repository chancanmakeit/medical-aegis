# file: aegis_core/utils/ner_verifier.py
"""
NER answer verifier for the CMAS / wikigold zero-shot NER task.

The MAS response is expected to contain a JSON list of single-key dicts:
    [{"Entity Name": "Entity Label"}, ...]
(matching CMAS's output convention). We parse the predicted (entity, type)
pairs, compare them to the gold pairs, and compute entity-level micro-F1 with
EXACT matching (both the entity span text and the type must match, following
the paper's "complete matching" evaluation).

Because AEGIS's is_correct is a BOOLEAN per sample, we threshold the per-sample
F1: a sample counts as "correct" when its F1 >= `f1_threshold` (default 1.0,
i.e. the prediction must be perfect). The raw F1 and the tp/fp/fn counts are
returned in the audit dict so a downstream aggregator can compute corpus-level
micro-F1 across samples if desired.

Entry points:
    verify_ner(response, ground_truth, f1_threshold=1.0) -> bool
    verify_ner_with_details(response, ground_truth, ...) -> (bool, audit)
    score_ner(response, ground_truth) -> dict with precision/recall/f1/tp/fp/fn
"""
import ast
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple


# --------------------------------------------------------------------------- #
# Parsing predicted entities out of a free-form model response.
# --------------------------------------------------------------------------- #
def _normalize_entity(text: str) -> str:
    """Normalize an entity span for matching: collapse whitespace, strip."""
    return re.sub(r"\s+", " ", str(text)).strip()


def _normalize_type(text: str) -> str:
    return str(text).strip()


def _extract_json_blob(response: str) -> Optional[str]:
    """Find the most likely JSON list in the response.

    CMAS answers look like [{"Ent": "Type"}, ...]. Models sometimes wrap the
    JSON in prose or code fences, so we search for the first '[' ... matching
    ']' span. Returns the raw substring or None.
    """
    if not response:
        return None
    # Strip code fences.
    cleaned = re.sub(r"```(?:json)?", "", response)
    # Find the first '[' and the last ']' — greedy but robust for a single list.
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        return cleaned[start:end + 1]
    # Fall back to a brace-delimited object list without outer brackets.
    return None


def parse_predicted_entities(response: str) -> Dict[str, str]:
    """Parse the predicted {entity: type} mapping from a model response.

    Robust to:
      - JSON list of single-key dicts: [{"UK":"Location"}, ...]
      - a single dict: {"UK":"Location", ...}
      - python-style quotes (ast.literal_eval fallback)
    Returns {} if nothing parseable is found (an empty prediction, which is a
    valid answer for sentences with no entities).
    """
    blob = _extract_json_blob(response)
    parsed = None
    if blob is not None:
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(blob)
                break
            except (ValueError, SyntaxError):
                continue
    if parsed is None:
        # Try to parse a bare object like {"UK": "Location"}
        obj_start = response.find("{") if response else -1
        obj_end = response.rfind("}") if response else -1
        if obj_start != -1 and obj_end > obj_start:
            frag = response[obj_start:obj_end + 1]
            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(frag)
                    break
                except (ValueError, SyntaxError):
                    continue
    if parsed is None:
        return {}

    out: Dict[str, str] = {}
    if isinstance(parsed, dict):
        for k, v in parsed.items():
            out[_normalize_entity(k)] = _normalize_type(v)
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                for k, v in item.items():
                    out[_normalize_entity(k)] = _normalize_type(v)
    return out


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _pair_set(mapping: Dict[str, str]) -> Set[Tuple[str, str]]:
    return {(_normalize_entity(k), _normalize_type(v)) for k, v in mapping.items()}


def score_ner(response: str, ground_truth: Dict[str, Any]) -> Dict[str, Any]:
    """Compute per-sample precision / recall / F1 with exact (span, type) match."""
    gold_map = (ground_truth or {}).get("entities", {}) or {}
    gold = _pair_set(gold_map)
    pred = _pair_set(parse_predicted_entities(response))

    tp = len(gold & pred)
    fp = len(pred - gold)
    fn = len(gold - pred)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Special case: gold empty AND pred empty -> perfect (F1 = 1.0), because the
    # correct answer for a no-entity sentence is an empty list.
    if len(gold) == 0 and len(pred) == 0:
        precision = recall = f1 = 1.0

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "n_gold": len(gold), "n_pred": len(pred),
        "gold_pairs": sorted(gold), "pred_pairs": sorted(pred),
    }


def verify_ner(response: str, ground_truth: Dict[str, Any],
               f1_threshold: float = 1.0) -> bool:
    """Boolean verdict: True iff per-sample F1 >= f1_threshold."""
    s = score_ner(response, ground_truth)
    return s["f1"] >= f1_threshold


def verify_ner_with_details(response: str, ground_truth: Dict[str, Any],
                            f1_threshold: float = 1.0,
                            **kwargs) -> Tuple[bool, Dict[str, Any]]:
    """Return (verdict, audit). Audit mirrors the medical verifier's shape as
    closely as makes sense for NER, plus the F1 breakdown."""
    s = score_ner(response, ground_truth)
    verdict = s["f1"] >= f1_threshold
    audit = {
        "task": "ner_micro_f1",
        "f1_threshold": f1_threshold,
        "precision": s["precision"],
        "recall": s["recall"],
        "f1": s["f1"],
        "tp": s["tp"], "fp": s["fp"], "fn": s["fn"],
        "n_gold": s["n_gold"], "n_pred": s["n_pred"],
        "gold_pairs": s["gold_pairs"],
        "pred_pairs": s["pred_pairs"],
        "deterministic_verdict": verdict,
        "decision_path": "ner_micro_f1/exact_match_threshold",
        "final_verdict": verdict,
    }
    return verdict, audit


# Datasets handled by this verifier.
NER_DATASETS = {"wikigold", "cmas", "cmas-wikigold"}
