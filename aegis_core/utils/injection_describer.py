# file: aegis_core/utils/injection_describer.py
"""
LLM-powered descriptions of how injection actually manifested in a trajectory.

The static `malicious_action_description` strings in the malicious_factory are
just one-liners like "Deviate from main goal via prompt injection". They tell
you the *category* but not what concretely changed in this particular sample.

This module asks an LLM to read the evidence (pre/post-injection prompts,
clean/corrupted responses, final answer) and write a concrete, sample-specific
description of how the FM error manifested.

Two granularities (both can be generated for the same sample):

  * per-turn description    (one description per injected turn)
  * sample-level summary    (one description summarizing the whole sample's
                             injection effect — how the injections combined,
                             how the system responded, whether the error
                             propagated to the final answer)

Per the user's configuration:
  - `description_llm_config` selects a dedicated LLM for describing.
  - Descriptions are generated for EVERY injected turn (regardless of whether
    the injection visibly succeeded), since the user wanted full coverage.
"""

from typing import Any, Dict, List, Optional


# Short, plain-English explanations of each FM error type, used to anchor the
# LLM's description so it doesn't have to know the taxonomy.
FM_GLOSSARY = {
    "FM-1.1": "Task specification deviation: the agent ignored details of the task spec.",
    "FM-1.2": "Role specification deviation: the agent strayed from its assigned role/persona.",
    "FM-1.3": "Redundant looping / re-stating instead of progressing the reasoning.",
    "FM-1.4": "Context omission / forgetting prior context.",
    "FM-1.5": "Multiple answers / refusal to commit to a single final choice.",
    "FM-2.1": "Restarting reasoning from scratch and discarding prior progress.",
    "FM-2.2": "Hedging and uncertainty, refusal to commit.",
    "FM-2.3": "Deviating from the main goal — producing a wrong answer on purpose.",
    "FM-2.4": "Withholding key information, giving a low-information answer.",
    "FM-2.5": "Ignoring or contradicting other agents in the discussion.",
    "FM-2.6": "Reasoning-conclusion mismatch: the reasoning supports one answer but the final letter is different.",
    "FM-3.1": "Premature termination: ending without analysis, often a bare letter.",
    "FM-3.2": "Skipping verification / committing without checking.",
    "FM-3.3": "Evaluator approval failure: rubber-stamping an answer instead of evaluating it.",
}


_PER_TURN_PROMPT = """You are auditing a multi-agent system trajectory in which a specific agent's behavior was deliberately injected with an error of type {fm} ({fm_meaning}).

Strategy used: {strategy}.

Below is the EVIDENCE for this specific turn. Describe, in 1-3 concrete sentences, WHAT changed in this turn because of the injection and HOW that change manifests the {fm} error. Be specific — reference exact phrases, missing details, contradictions, or shifted conclusions. Do NOT restate the FM-error definition; describe what actually happened.

--- AGENT BEING INJECTED ---
{agent_name} (role_index={role_index}), phase: {phase}

--- ORIGINAL INPUT MESSAGES (what the agent would have seen WITHOUT injection) ---
{original_input}

--- ACTUAL INPUT MESSAGES (what the agent saw WITH injection) ---
{injected_input}

--- CLEAN RESPONSE (only for response_corruption; null for prompt_injection) ---
{clean_response}

--- ACTUAL RESPONSE (what this agent produced; for response_corruption this is the corrupted version) ---
{actual_response}

Concrete description (1-3 sentences, no preamble):"""


_SAMPLE_PROMPT = """You are auditing a single multi-agent trajectory in which one or more agents were injected with errors.

Question the system was solving:
{query}

Ground truth answer: {gold}

Final system response: {response}
Final correctness: {is_correct}

Injected turns (in order):
{per_turn_block}

In 2-4 concrete sentences, summarize how the injections affected the trajectory as a whole: which injection had the biggest effect, whether downstream agents corrected or amplified it, and whether the error propagated to the final answer. Be specific to this sample — reference actual content, do not restate FM definitions."""


def _truncate(s: Any, n: int = 1500) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 25] + " ...[truncated]"


def _format_messages(msgs: Any) -> str:
    if not msgs:
        return "(none)"
    if isinstance(msgs, list):
        parts = []
        for m in msgs:
            if isinstance(m, dict):
                parts.append(f"[{m.get('role','?')}] {_truncate(m.get('content',''), 800)}")
            else:
                parts.append(_truncate(str(m), 800))
        return "\n".join(parts)
    return _truncate(msgs)


def _call_llm(llm, prompt: str) -> Optional[str]:
    """Invoke an LLM and return its text output (or None on error)."""
    if llm is None:
        return None
    try:
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
            else:
                return None
        if isinstance(out, dict):
            out = out.get("response") or out.get("content") or str(out)
        return (out or "").strip() if isinstance(out, str) else str(out).strip()
    except Exception as e:
        return f"<describer error: {e}>"


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def describe_per_turn(turn: Dict[str, Any], llm) -> Optional[str]:
    """Generate a sample-specific description for ONE injected turn.

    Expects `turn` to be a normalized conversation_history entry that carries
    injection metadata (injection_applied, fm_error_type, injection_strategy,
    original_input_messages, injected_input_messages, content/response,
    clean_response_before_corruption).
    """
    if not turn.get("injection_applied"):
        return None
    fm = turn.get("fm_error_type") or ""
    strategy = turn.get("injection_strategy") or ""
    prompt = _PER_TURN_PROMPT.format(
        fm=fm,
        fm_meaning=FM_GLOSSARY.get(fm, "(unknown error type)"),
        strategy=strategy,
        agent_name=turn.get("agent_name", "?"),
        role_index=turn.get("role_index"),
        phase=turn.get("phase", "?"),
        original_input=_format_messages(turn.get("original_input_messages")),
        injected_input=_format_messages(turn.get("injected_input_messages") or turn.get("input_messages")),
        clean_response=_truncate(turn.get("clean_response_before_corruption")) if turn.get("clean_response_before_corruption") is not None else "null",
        actual_response=_truncate(turn.get("content") or turn.get("response", "")),
    )
    return _call_llm(llm, prompt)


def describe_sample(record: Dict[str, Any], llm) -> Optional[str]:
    """Generate a single sample-level summary of the injection's net effect."""
    log = record.get("injection_log", {}) or {}
    hist = log.get("conversation_history") or []
    injected = [t for t in hist if isinstance(t, dict) and t.get("injection_applied")]
    if not injected:
        return None

    per_turn_lines = []
    for t in injected:
        per_turn_lines.append(
            f"- {t.get('agent_name','?')} [{t.get('fm_error_type','?')}/"
            f"{t.get('injection_strategy','?')}]: "
            f"{_truncate(t.get('content') or t.get('response',''), 250)}"
        )
    gt = record.get("ground_truth", {}) or {}
    _ca = str(gt.get("correct_answer", "")).strip()
    _at = str(gt.get("answer_text", "")).strip()
    gold = f"{_ca}. {_at}" if (_ca and _at) else (_ca or _at) or "(unknown)"
    prompt = _SAMPLE_PROMPT.format(
        query=_truncate(record.get("query", ""), 1200),
        gold=gold,
        response=_truncate(record.get("response", ""), 800),
        is_correct=record.get("is_correct"),
        per_turn_block="\n".join(per_turn_lines),
    )
    return _call_llm(llm, prompt)


def annotate_record(record: Dict[str, Any], llm,
                    per_turn: bool = True, sample_summary: bool = True) -> Dict[str, Any]:
    """Generate and attach LLM descriptions to a record IN PLACE.

    For each injected turn in `conversation_history`, sets
    `turn['injection_description']`. For the whole record, sets
    `record['injection_summary']`.

    Returns the same record (for chaining).
    """
    log = record.get("injection_log", {}) or {}
    hist = log.get("conversation_history") or []

    if per_turn:
        for t in hist:
            if isinstance(t, dict) and t.get("injection_applied"):
                desc = describe_per_turn(t, llm)
                if desc:
                    t["injection_description"] = desc

    if sample_summary:
        summary = describe_sample(record, llm)
        if summary:
            record["injection_summary"] = summary

    return record
