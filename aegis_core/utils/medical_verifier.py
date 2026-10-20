# file: aegis_core/utils/medical_verifier.py
"""
Medical answer verification for AEGIS medical-trajectory data generation.

Decides whether a MAS final response is CORRECT with respect to the
dataset's ground_truth. This is the single source of truth for the
"normal (correct) vs error (incorrect)" split:

    normal trajectory  := response matches correct_answer  (is_correct == True)
    error  trajectory  := response differs from correct_answer (is_correct == False)

Strictness level (configurable): regex/exact match first, with an optional
LLM-judge fallback invoked ONLY when the deterministic parser cannot decide.

Each dataset has its own verifier because the answer space differs:
  - MCQ   (MedQA / MedMCQA / MMLU-medical) : single option letter (A-E)
  - PubMedQA                               : yes / no / maybe
  - MedCalc-Bench                          : numeric value within a tolerance range
  - MEDEC-MS                               : error flag + corrected sentence

Usage:
    from aegis_core.utils.medical_verifier import verify_answer
    is_correct = verify_answer(dataset_name, response, ground_truth, llm=optional_llm)
"""

import re
from typing import Any, Dict, Optional


# --------------------------------------------------------------------------- #
# Low-level extraction helpers
# --------------------------------------------------------------------------- #

# Answer-phrase patterns grouped by RELIABILITY tier (higher = stronger signal).
# Within the chosen tier, the LAST match wins (final answer appears at the end).
# Letter range is A-J to cover MedXpertQA (up to 10 choices) and the typical
# 4-5-choice MCQ datasets (MedQA, MedMCQA, MMLU). Letters past E are rare in
# random-text false matches, so widening doesn't increase noise.
_STRONG_PATTERNS = [
    r"final\s+answer\s*(?:is|:)?\s*\**\s*\(?\s*([A-J])\b",   # "final answer is **D"
    r"\banswer\s*(?:is|:)\s*\**\s*\(?\s*([A-J])\b",          # "answer: D" / "answer is D"
    r"\\boxed\{\s*\(?\s*([A-J])\b",                            # \boxed{D}
    r"\*\*\s*\(?\s*([A-J])\s*[\).:\-]",                       # "**D. Cross-linking**"
    r"\boption\s*:\s*\**\s*\(?\s*([A-J])\b",                  # "Option: D" (MedAgents decider format)
]
_WEAK_PATTERNS = [
    r"\boption\s+\(?\s*([A-J])\b",      # "option D"  (require a space -> avoids 'opti(o)n')
    r"\bchoice\s+\(?\s*([A-J])\b",      # "choice D"
    r"\(\s*([A-J])\s*\)",                # a bare "(D)"
]

# Kept for backward compatibility (other code/tests may import it).
_OPTION_PATTERNS = _STRONG_PATTERNS + _WEAK_PATTERNS


def _last_match(patterns, s):
    best = None
    for pat in patterns:
        for m in re.finditer(pat, s, flags=re.IGNORECASE):
            best = m.group(1).upper()
    return best


def extract_option_letter(text: str) -> Optional[str]:
    """Extract a single MCQ option letter (A-E) from free-form model output.

    Reliability-tiered: strong final-answer signals (an explicit "final answer is X",
    "answer: X", \\boxed{X}, or a bold "**X.**") beat weak ones ("option X", a bare
    "(X)"). Within a tier the LAST occurrence wins, because the final answer comes at
    the end after the reasoning. This prevents a stray letter early in a long response
    (e.g. inside "...mechanism of action...") from overriding the real final answer.
    Returns None if undecidable.
    """
    if not text:
        return None
    s = text.strip()

    # 1) strong final-answer signals
    strong = _last_match(_STRONG_PATTERNS, s)
    if strong:
        return strong

    # 2) a lone letter on the LAST non-empty line (answer printed alone)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if lines:
        m = re.fullmatch(r"\**\s*\(?\s*([A-J])\s*\)?\.?\**", lines[-1])
        if m:
            return m.group(1).upper()

    # 3) weak signals
    weak = _last_match(_WEAK_PATTERNS, s)
    if weak:
        return weak

    # 4) LAST resort: a SHORT response that starts with a bare choice "X. text".
    if len(s) < 80:
        lead = re.match(r"\(?\s*([A-J])\s*[\).:\-]\s+\S", s)
        if lead:
            return lead.group(1).upper()
    return None


def extract_yesno(text: str) -> Optional[str]:
    """Extract yes/no/maybe for PubMedQA-style answers."""
    if not text:
        return None
    t = text.lower()
    # look near explicit answer markers first
    m = re.search(r"answer\s*(?:is|:)?\s*\"?(yes|no|maybe)\"?", t)
    if m:
        return m.group(1)
    # otherwise take the last standalone occurrence
    found = re.findall(r"\b(yes|no|maybe)\b", t)
    return found[-1] if found else None


def extract_number(text: str) -> Optional[float]:
    """Extract the most likely final numeric answer from text."""
    if not text:
        return None
    # Prefer a number that follows an answer marker.
    m = re.search(
        r"(?:answer|result|value)\s*(?:is|:|=)?\s*\$?\s*(-?\d[\d,]*\.?\d*)",
        text,
        flags=re.IGNORECASE,
    )
    candidates = []
    if m:
        candidates.append(m.group(1))
    # boxed number
    for bm in re.finditer(r"\\boxed\{\s*\$?(-?\d[\d,]*\.?\d*)", text):
        candidates.append(bm.group(1))
    # else all numbers, take the last
    if not candidates:
        candidates = re.findall(r"-?\d[\d,]*\.?\d*", text)
    if not candidates:
        return None
    try:
        return float(candidates[-1].replace(",", ""))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Per-dataset verifiers (deterministic). Return True / False / None.
# None means "undecidable deterministically" -> caller may use LLM fallback.
# --------------------------------------------------------------------------- #

# datasets treated as multiple-choice
MCQ_DATASETS = {
    "medqa", "medmcqa",
    "mmlu_clinical_knowledge", "mmlu_medical_genetics", "mmlu_anatomy",
    "mmlu_professional_medicine", "mmlu_college_biology", "mmlu_college_medicine",
    "mmlu_pro_health", "mmlu_pro_medical",
    # MedXpertQA Text and MM are both MCQ-style (gold letter A-J).
    "medxpertqa", "medxpertqa-text", "medxpertqa_text",
    "medxpertqa-mm", "medxpertqa_mm",
    # MedConceptsQA: pure 4-choice (A-D) medical-coding MCQ. We list the
    # umbrella name plus every (vocab, level) variant the converter exposes,
    # so the verifier resolves whatever benchmark_name the user set.
    "medconceptsqa", "medconceptsqa-all", "medconceptsqa_all",
}
for _vocab in ("atc", "icd9cm", "icd9proc", "icd10cm", "icd10proc"):
    for _level in ("easy", "medium", "hard"):
        MCQ_DATASETS.add(f"medconceptsqa-{_vocab}-{_level}")
        MCQ_DATASETS.add(f"medconceptsqa_{_vocab}_{_level}")
del _vocab, _level


def _verify_mcq(response: str, gt: Dict[str, Any]) -> Optional[bool]:
    gold = str(gt.get("correct_answer", "")).strip()
    # gold may be a letter ("A"-"J") or the full option text.
    gold_letter = None
    m = re.fullmatch(r"\(?\s*([A-J])\s*\)?\.?", gold)
    if m:
        gold_letter = m.group(1).upper()
    elif "answer_idx" in gt:
        idx = gt.get("answer_idx")
        if isinstance(idx, int) and 0 <= idx < 5:
            gold_letter = "ABCDE"[idx]

    pred_letter = extract_option_letter(response)
    if gold_letter and pred_letter:
        return pred_letter == gold_letter
    # If gold is given as full text, compare normalized text containment.
    if gold and not gold_letter:
        norm_resp = re.sub(r"\s+", " ", (response or "").lower())
        norm_gold = re.sub(r"\s+", " ", gold.lower())
        if norm_gold and norm_gold in norm_resp:
            return True
    return None  # undecidable -> LLM fallback


def _verify_pubmedqa(response: str, gt: Dict[str, Any]) -> Optional[bool]:
    gold = str(gt.get("correct_answer", "")).strip().lower()
    pred = extract_yesno(response)
    if gold in {"yes", "no", "maybe"} and pred:
        return pred == gold
    return None


def _verify_medcalc(response: str, gt: Dict[str, Any]) -> Optional[bool]:
    """MedCalc-Bench-Verified carries an acceptable [lower, upper] range."""
    pred = extract_number(response)
    if pred is None:
        return None
    lower = gt.get("lower_limit", gt.get("Lower Limit"))
    upper = gt.get("upper_limit", gt.get("Upper Limit"))
    try:
        if lower is not None and upper is not None:
            return float(lower) <= pred <= float(upper)
    except (TypeError, ValueError):
        pass
    # fall back to exact/relative-tolerance match on correct_answer
    gold = gt.get("correct_answer")
    try:
        gold_val = float(str(gold).replace(",", ""))
        tol = max(abs(gold_val) * 0.01, 1e-6)  # 1% relative tolerance
        return abs(pred - gold_val) <= tol
    except (TypeError, ValueError):
        return None


def _verify_medec(response: str, gt: Dict[str, Any]) -> Optional[bool]:
    """MEDEC-MS: the system must detect the erroneous sentence id and/or correct it.

    ground_truth schema (normalized by our converter):
        correct_answer : the corrected sentence text (or "CORRECT" if no error)
        error_sentence_id : int index of the flagged sentence (-1 if none)
    """
    gold_id = gt.get("error_sentence_id", None)
    gold_text = str(gt.get("correct_answer", "")).strip()
    resp = (response or "")

    # No-error case: the system should say the text is correct / no error.
    if gold_id in (-1, "-1", None) and gold_text.upper() in {"CORRECT", "NO ERROR", ""}:
        if re.search(r"\b(no error|correct|no mistake)\b", resp, re.IGNORECASE):
            return True
        # if it flagged some sentence id, it's wrong
        if re.search(r"\bsentence\s*\d+", resp, re.IGNORECASE):
            return False
        return None

    # Error case: check the flagged sentence id matches.
    if gold_id not in (-1, "-1", None):
        m = re.search(r"sentence\s*(?:id|#)?\s*[:=]?\s*(\d+)", resp, re.IGNORECASE)
        pred_id = int(m.group(1)) if m else None
        if pred_id is not None:
            return pred_id == int(gold_id)
    return None  # undecidable -> LLM fallback (compare corrected text)


# --------------------------------------------------------------------------- #
# Probability / binary-classification verifier
# (used by ClinicalAgent trial-outcome prediction: framework output is
#  free-form text ending with `<final_result>0.X</final_result>` tag.)
# --------------------------------------------------------------------------- #
_PROB_TAG_RE = re.compile(r"<final_result>\s*([^<>]+?)\s*</final_result>", re.IGNORECASE | re.DOTALL)
_PROB_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+")


def _extract_probability(response: str) -> Optional[float]:
    """Pull the failure-probability value out of a `<final_result>` tag.

    Handles a few common variants:
      "<final_result>0.8</final_result>"           -> 0.8
      "<final_result>0.85 (high)</final_result>"   -> 0.85 (first number)
      "<final_result>85%</final_result>"           -> 0.85 (% present -> auto-scaled)
      "<final_result>The probability is 0.3</final_result>" -> 0.3

    Returns None if nothing usable is found (verifier caller can then either
    fall back to the LLM judge or mark undecidable).
    """
    if not response:
        return None
    inner = None
    m = _PROB_TAG_RE.search(response)
    if m:
        inner = m.group(1)
    else:
        # last-ditch: look for "final_result: 0.7" style without tags
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

    # Percentage only when '%' is explicitly present. Otherwise treat as a
    # raw fraction and just clamp to [0, 1] (defensively handles model garbage
    # like "1.5" without wrongly converting it into 0.015).
    if "%" in inner:
        val = val / 100.0
    if val < 0.0:
        val = 0.0
    if val > 1.0:
        val = 1.0
    return val


def _verify_probability(response: str, gt: Dict[str, Any]) -> Optional[bool]:
    """Verify a binary classification result expressed as a probability.

    Compares thresholded prediction to the gold binary label (0/1).
      - Extract the probability from the response (see _extract_probability).
      - If threshold-comparison-side gold is available, threshold both and
        compare; return True if they agree.
      - If we could not extract a probability at all, return None (undecidable
        -> LLM-judge fallback). This is important because an injected response
        might not contain a `<final_result>` tag at all.
    """
    prob = _extract_probability(response)
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


def extract_class_label(text: str) -> Optional[str]:
    """Pull a class label out of a sensing-framework response.

    Priority: the LAST "Final answer: <label>" line (frameworks append it),
    then the "ANSWER" field of the LAST JSON object in the text.
    """
    if not text:
        return None
    m = re.findall(r"Final answer:\s*([^\n]+)", text)
    if m:
        return m[-1].strip().strip('"\'.').strip()
    m = re.findall(r'"ANSWER"\s*:\s*"([^"]*)"', text)
    if m:
        return m[-1].strip()
    return None


def _label_lookup(gt: Dict[str, Any]) -> Dict[str, str]:
    """surface form (lowercase) -> canonical class, from gt['classes'] + gt['aliases']."""
    table = {}
    for c in gt.get("classes") or []:
        table[str(c).lower()] = str(c)
    for c, al in (gt.get("aliases") or {}).items():
        for a in al or []:
            table[str(a).lower()] = str(c)
    return table


def extract_free_text_label(text: str, gt: Dict[str, Any]) -> Optional[str]:
    """Class label from a free-text answer (e.g. a MAM diagnosis), or None.

    Order: explicit marker ("Final answer:" / "answer|diagnosis|category|label
    is|:" / a bold **label**; the LAST one wins) -> the only class mentioned in
    the text. Binary yes/no tasks only accept explicit markers or a reply that
    starts with yes/no, since "no" occurs in ordinary prose.
    """
    if not text:
        return None
    table = _label_lookup(gt)
    if not table:
        return None
    forms = sorted(table, key=len, reverse=True)
    alt = "|".join(re.escape(f) for f in forms)
    explicit = []
    for pat in (rf"final answer\s*[:：]\s*\**\s*({alt})\b",
                rf"\b(?:answer|diagnosis|classification|category|label)\s*(?:is|:|：)\s*\**\s*[\"'“]?({alt})\b",
                rf"\*\*\s*({alt})\s*\*\*"):
        for m in re.finditer(pat, text, re.IGNORECASE):
            explicit.append((m.start(), table[m.group(1).lower()]))
    if explicit:
        return sorted(explicit)[-1][1]
    binary = set(v.lower() for v in table.values()) <= {"yes", "no"}
    if binary:
        m = re.match(r"\s*\**\s*(yes|no)\b", text, re.IGNORECASE)
        return table.get(m.group(1).lower()) if m else None
    found = {table[m.group(1).lower()] for m in re.finditer(rf"\b({alt})\b", text, re.IGNORECASE)}
    return found.pop() if len(found) == 1 else None


def _verify_label(response: str, gt: Dict[str, Any]) -> Optional[bool]:
    """Class-label match (case-insensitive), e.g. WESAD 'stress', SleepEDF 'N2',
    Heartbeat 'murmur'. JSON/"Final answer" first; free-text fallback when the
    ground truth carries the class list (MAM)."""
    gold = str(gt.get("correct_answer", "")).strip()
    if not gold:
        return None
    pred = extract_class_label(response)
    if pred is not None and gt.get("classes"):
        # an explicit answer that is not a valid class is no answer at all
        pred = _label_lookup(gt).get(pred.lower())
    if pred is None and gt.get("classes"):
        pred = extract_free_text_label(response, gt)
    if pred is None:
        return None
    return pred.lower() == gold.lower()


_DETERMINISTIC = {
    "pubmedqa": _verify_pubmedqa,
    "medcalc-bench": _verify_medcalc,
    "medcalc": _verify_medcalc,
    "medec-ms": _verify_medec,
    "medec": _verify_medec,
    # ConSensus multimodal-sensing classification (class-label answers).
    "wesad": _verify_label,
    "sleepedf": _verify_label,
    # MAM audio diagnosis (free-text answers; class list in ground_truth).
    "heartbeat_a": _verify_label,
    "heartbeat_b": _verify_label,
    "sounddr": _verify_label,
    "sleep-edf": _verify_label,
    # ClinicalAgent trial-outcome-prediction dataset (binary via probability).
    "trial_success": _verify_probability,
    "trial-success": _verify_probability,
    "clinical_trial_outcome": _verify_probability,
    "clinical-trial-outcome": _verify_probability,
    "clinicalagent": _verify_probability,
}


# Datasets whose deterministic verdict is EXACT and should therefore OVERRIDE
# the LLM judge, even in llm_primary / llm_only modes. This matters for tasks
# where the correctness rule is a precise numeric/threshold comparison that a
# general-purpose LLM judge (whose prompt is tuned for MCQ / open-ended答案
# matching) tends to get wrong.
#
# Example: trial_success is binary-via-probability. If the model outputs
# <final_result>0.72</final_result> and the threshold is 0.5, the correct
# binary prediction is unambiguously 1 -- but an LLM judge shown "gold=1,
# response=...0.72..." may not apply the 0.5 threshold and can wrongly call it
# INCORRECT. For these datasets we trust the deterministic verdict whenever it
# is decisive (not None), and only fall back to the LLM judge when the
# deterministic parser could not extract an answer at all.
DETERMINISTIC_AUTHORITATIVE = {
    "wesad", "sleepedf", "sleep-edf", "heartbeat_a", "heartbeat_b", "sounddr",
    "trial_success", "trial-success",
    "clinical_trial_outcome", "clinical-trial-outcome",
    "clinicalagent",
}


# --------------------------------------------------------------------------- #
# LLM-judge fallback
# --------------------------------------------------------------------------- #

_JUDGE_PROMPT = """You are a strict grader for a medical question-answering system.
Decide whether the SYSTEM RESPONSE gives the same final answer as the GROUND TRUTH.
Ignore reasoning, formatting, and wording. Judge only the final answer.

QUESTION:
{query}

GROUND TRUTH ANSWER:
{gold}

SYSTEM RESPONSE:
{response}

Reply with exactly one word: CORRECT or INCORRECT."""


def _llm_judge(llm, query: str, response: str, gold: str) -> Optional[bool]:
    """Backward-compatible wrapper that returns only the verdict bool."""
    verdict, _ = _llm_judge_with_raw(llm, query, response, gold)
    return verdict


def _llm_judge_with_raw(llm, query: str, response: str, gold: str):
    """Use an LLM to grade. Returns (verdict_or_None, raw_text_or_None).

    raw_text is the model's literal CORRECT/INCORRECT reply (truncated to a
    sensible length), so callers can save the judge's reasoning trail.
    """
    if llm is None:
        return None, None
    prompt = _JUDGE_PROMPT.format(query=query or "", gold=gold or "", response=response or "")
    try:
        out = None
        if hasattr(llm, "call") and callable(llm.call):
            out = llm.call(prompt)
        else:
            for attr in ("generate", "chat", "__call__"):
                fn = getattr(llm, attr, None)
                if callable(fn):
                    try:
                        out = fn(prompt)
                    except TypeError:
                        out = fn([{"role": "user", "content": prompt}])
                    break
        if out is None:
            return None, None
        text = out if isinstance(out, str) else (
            out.get("response") if isinstance(out, dict) else str(out))
        raw = (text or "")[:500]
        verdict_str = (text or "").strip().upper()
        if "INCORRECT" in verdict_str:
            return False, raw
        if "CORRECT" in verdict_str:
            return True, raw
        return None, raw  # raw recorded even when verdict couldn't be parsed
    except Exception as e:
        return None, f"<exception: {e}>"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def verify_answer(
    dataset_name: str,
    response: str,
    ground_truth: Any,
    query: str = "",
    llm: Optional[object] = None,
    use_llm_fallback: bool = True,
    judge_mode: str = "llm_primary",
) -> bool:
    """Return True if `response` is correct w.r.t. `ground_truth`.

    Thin wrapper around `verify_answer_with_details`. Kept for backward
    compatibility — use the `_with_details` variant when you also want the
    audit dict (decision_path, regex letter, LLM judge raw output, etc.).
    """
    verdict, _ = verify_answer_with_details(
        dataset_name, response, ground_truth, query=query, llm=llm,
        use_llm_fallback=use_llm_fallback, judge_mode=judge_mode)
    return verdict


def verify_answer_with_details(
    dataset_name: str,
    response: str,
    ground_truth: Any,
    query: str = "",
    llm: Optional[object] = None,
    use_llm_fallback: bool = True,
    judge_mode: str = "llm_primary",
):
    """Verify correctness AND return a full audit trail.

    Returns (verdict: bool, details: dict). The `details` dict captures:
      - judge_mode               : the mode requested
      - llm_available            : whether an LLM judge was usable this call
      - gold                     : the combined "letter + answer_text" given to the judge
      - regex_extracted          : letter extracted from the response (MCQ) / None
      - deterministic_verdict    : True / False / None (parser's call)
      - llm_judge_called         : whether the LLM was actually invoked
      - llm_judge_raw_output     : the literal CORRECT/INCORRECT text the judge returned
      - llm_judge_verdict        : True / False / None (parsed verdict)
      - decision_path            : human-readable string explaining which path decided
      - final_verdict            : the returned bool

    This is what `main.py` saves under `injection_log.verification` so users can SEE
    exactly how `is_correct` was determined and audit/dispute it.
    """
    name = (dataset_name or "").strip().lower()
    gt = ground_truth if isinstance(ground_truth, dict) else {"correct_answer": ground_truth}
    response = response if isinstance(response, str) else str(response)
    _ca = str(gt.get("correct_answer", "")).strip()
    _at = str(gt.get("answer_text", "")).strip()
    gold = f"{_ca}. {_at}" if (_ca and _at) else (_ca or _at)

    details: Dict[str, Any] = {
        "judge_mode": judge_mode,
        "use_llm_fallback": use_llm_fallback,
        "llm_available": bool(use_llm_fallback and llm is not None),
        "gold": gold,
        "regex_extracted": None,
        "deterministic_verdict": None,
        "llm_judge_called": False,
        "llm_judge_raw_output": None,
        "llm_judge_verdict": None,
        "decision_path": None,
        "final_verdict": None,
    }

    # Record what regex picked out (MCQ datasets) so the user can sanity-check.
    if name in MCQ_DATASETS or name.startswith("mmlu"):
        details["regex_extracted"] = extract_option_letter(response)

    def _det() -> Optional[bool]:
        if name in MCQ_DATASETS or name.startswith("mmlu"):
            return _verify_mcq(response, gt)
        if name in _DETERMINISTIC:
            return _DETERMINISTIC[name](response, gt)
        v = _verify_mcq(response, gt)
        return v if v is not None else _verify_medcalc(response, gt)

    def _run_judge() -> Optional[bool]:
        if not (use_llm_fallback and llm is not None):
            return None
        details["llm_judge_called"] = True
        v, raw = _llm_judge_with_raw(llm, query, response, gold)
        details["llm_judge_verdict"] = v
        details["llm_judge_raw_output"] = raw
        return v

    # --- Authoritative-deterministic short-circuit ---------------------------
    # For datasets whose deterministic verdict is EXACT (see
    # DETERMINISTIC_AUTHORITATIVE), trust the deterministic result whenever it
    # is decisive, REGARDLESS of judge_mode. Only consult the LLM judge if the
    # deterministic parser could not extract an answer (verdict is None), e.g.
    # the model never emitted a <final_result> tag.
    if name in DETERMINISTIC_AUTHORITATIVE:
        det = _det(); details["deterministic_verdict"] = det
        if det is not None:
            details["decision_path"] = "authoritative_deterministic/decisive"
            details["final_verdict"] = det
            return det, details
        # Deterministic parser failed to extract -> try the LLM judge as a
        # last resort (e.g. injected response with no final_result tag).
        if details["llm_available"]:
            j = _run_judge()
            if j is not None:
                details["decision_path"] = "authoritative_deterministic/llm_judge_fallback"
                details["final_verdict"] = j
                return j, details
        details["decision_path"] = "authoritative_deterministic/undecidable_default_false"
        details["final_verdict"] = False
        return False, details

    if judge_mode == "regex_first":
        det = _det(); details["deterministic_verdict"] = det
        if det is not None:
            details["decision_path"] = "regex_first/deterministic_decisive"
            details["final_verdict"] = det
            return det, details
        j = _run_judge()
        if j is not None:
            details["decision_path"] = "regex_first/llm_judge"
            details["final_verdict"] = j
            return j, details
        details["decision_path"] = "regex_first/default_false"
        details["final_verdict"] = False
        return False, details

    if judge_mode == "llm_only":
        j = _run_judge()
        if j is not None:
            details["decision_path"] = "llm_only/llm_judge"
            details["final_verdict"] = j
            return j, details
        det = _det(); details["deterministic_verdict"] = det
        if det is not None:
            details["decision_path"] = "llm_only/llm_unavailable_fallback_to_deterministic"
            details["final_verdict"] = det
            return det, details
        details["decision_path"] = "llm_only/default_false"
        details["final_verdict"] = False
        return False, details

    # judge_mode == "llm_primary" (default)
    det = _det(); details["deterministic_verdict"] = det
    if details["llm_available"]:
        j = _run_judge()
        if j is not None:
            details["decision_path"] = "llm_primary/llm_judge_decisive"
            details["final_verdict"] = j
            return j, details
        # judge errored or could not parse verdict -> fall back to deterministic
        if det is not None:
            details["decision_path"] = "llm_primary/llm_unparseable_fallback_to_deterministic"
            details["final_verdict"] = det
            return det, details
        details["decision_path"] = "llm_primary/both_failed_default_false"
        details["final_verdict"] = False
        return False, details
    # No LLM available
    if det is not None:
        details["decision_path"] = "llm_primary/no_llm_used_deterministic"
        details["final_verdict"] = det
        return det, details
    details["decision_path"] = "llm_primary/no_llm_default_false"
    details["final_verdict"] = False
    return False, details
