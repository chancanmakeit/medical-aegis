# file: aegis_core/utils/trajectory_normalizer.py
"""
Normalize the per-framework injection_log into ONE unified trajectory schema.

Different MAS wrappers in this repo build their logs independently and therefore
use different field names and granularity:

  - DyLAN      : log["full_history"]          entries {role, role_index, content, node_id, round}
  - LLM-Debate : log["full_history"]          entries {role, role_index, content, msg_index}
  - AgentVerse : log["conversation_history"]  entries {phase, role, role_index, call_count,
                                                       input_messages, timestamp, response, parsed_roles}

This module rewrites any of them into a single canonical shape so that the saved
jsonl is structurally identical regardless of framework:

  log["conversation_history"] = [
      {
        "step":           <int>,          # 1-based global order across the whole trajectory
        "agent_name":     <str>,          # the agent/role name for this turn
        "role_index":     <int|None>,
        "phase":          <str>,          # initialization/reasoning/discussion/evaluation/...
        "input_messages": <list|None>,    # the exact messages sent to the LLM (AgentVerse only;
                                          #   None for frameworks that reconstruct history post-hoc)
        "content":        <str>,          # the agent's output text for this turn
        "response":       <str>,          # alias of content (kept for AgentVerse compatibility)
      },
      ...
  ]

The original framework-specific history is preserved untouched under
log["raw_history"] so no information is lost.

`input_messages` semantics: for AgentVerse, each LLM call is intercepted live, so we
keep the full message list that was actually sent to the model that step (the system +
user prompt, in OpenAI chat format). DyLAN and LLM-Debate reconstruct their history
from internal structures *after* the run and never captured the per-call inputs, so
their `input_messages` is None rather than a fabricated value.
"""

from typing import Any, Dict, List, Optional


CANONICAL_KEY = "conversation_history"


def _infer_phase(framework: str, agent_name: str, idx: int, total: int) -> str:
    name = (agent_name or "").lower()
    if "roleassigner" in name or "role_assign" in name:
        return "initialization"
    if "evaluator" in name or "critic" in name:
        return "evaluation"
    if "aggregator" in name or "ranker" in name:
        return "discussion"
    if framework in ("llm_debate", "macnet"):
        return "discussion" if idx > 0 else "reasoning"
    if framework == "agentverse":
        return "solving"
    return "reasoning"


def _normalize_entry(framework: str, e: Dict[str, Any], step: int,
                     total: int) -> Dict[str, Any]:
    agent_name = e.get("role") or e.get("agent_name") or f"agent_{step}"
    # content: DyLAN/Debate use "content"; AgentVerse uses "response".
    content = e.get("content")
    if content is None:
        content = e.get("response", "")
    phase = e.get("phase") or _infer_phase(framework, agent_name, step - 1, total)
    out = {
        "step": step,
        "agent_name": agent_name,
        "role_index": e.get("role_index"),
        "phase": phase,
        # input_messages only exists for live-intercepted frameworks (AgentVerse).
        "input_messages": e.get("input_messages"),
        "content": content,
        "response": e.get("response", content),
    }
    # Preserve injection metadata when present (added by wrappers in inject runs).
    for k in ("injection_applied", "fm_error_type", "injection_strategy",
              "original_input_messages", "injected_input_messages",
              "prompt_modified",
              "clean_response_before_corruption", "response_corrupted",
              "injection_error", "injection_process",
              "is_input", "is_aggregator"):
        if k in e:
            out[k] = e[k]
    # Read-set / event structure recorded at prompt-assembly time by wrappers
    # that support it (medagents_mc so far). Passed through unchanged.
    for k in ("step_id", "sources", "source_how", "round", "event_ids", "agent_label"):
        if k in e:
            out[k] = e[k]
    return out


def normalize_log(log: Any, framework: str, fold_user_inputs: bool = False) -> Any:
    """Rewrite `log` in place to use the unified conversation_history schema.

    Safe to call on any framework's log (and on clean-run logs). Returns the log.

    Args:
      fold_user_inputs: if True, User/is_input entries are FOLDED into the next
        assistant turn's input_messages (and dropped as standalone turns).
        Default False keeps User entries as separate turns tagged is_input=true
        (the current behavior). Mostly useful for LLM-Debate, which produces
        many alternating User/Agent turns.
    """
    if not isinstance(log, dict):
        return log

    # Locate whichever history key this framework used.
    raw_hist: Optional[List[Dict[str, Any]]] = None
    src_key = None
    for key in ("conversation_history", "full_history", "history"):
        if isinstance(log.get(key), list):
            raw_hist = log[key]
            src_key = key
            break
    if raw_hist is None:
        # Nothing to normalize; still guarantee the canonical key exists.
        log.setdefault(CANONICAL_KEY, [])
        return log

    total = len(raw_hist)
    unified = [
        _normalize_entry(framework, e if isinstance(e, dict) else {"content": str(e)},
                         step=i + 1, total=total)
        for i, e in enumerate(raw_hist)
    ]

    # Optional fold: drop User turns and merge their content into the next
    # assistant turn's input_messages (as the trailing user message).
    if fold_user_inputs:
        folded: List[Dict[str, Any]] = []
        pending_user_contents: List[str] = []
        for e in unified:
            if e.get("is_input") or e.get("agent_name") == "User":
                if e.get("content"):
                    pending_user_contents.append(str(e["content"]))
                continue
            if pending_user_contents:
                im = list(e.get("input_messages") or [])
                for txt in pending_user_contents:
                    im.append({"role": "user", "content": txt})
                e["input_messages"] = im
                pending_user_contents = []
            folded.append(e)
        # renumber steps
        for i, e in enumerate(folded):
            e["step"] = i + 1
        unified = folded

    # Preserve the original under raw_history (avoid clobbering if already present).
    if src_key != CANONICAL_KEY:
        log.setdefault("raw_history", raw_hist)
        log.pop(src_key, None)
    else:
        # AgentVerse already used the canonical key; keep a raw copy too.
        log.setdefault("raw_history", list(raw_hist))

    log[CANONICAL_KEY] = unified
    return log
