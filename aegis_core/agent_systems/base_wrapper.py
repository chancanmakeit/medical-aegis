# file: agent_systems/base_wrapper.py

from abc import ABC, abstractmethod
from typing import Any, Tuple, Dict

# To prevent circular imports while allowing type hinting, we can
# use string-based hints or a simple forward declaration.
# This makes the code cleaner and more maintainable.
class Task:
    pass

class MaliciousAgent:
    pass


# --------------------------------------------------------------------------- #
# Round / turn override helper
# --------------------------------------------------------------------------- #
# Different MAS frameworks call their loop-bound differently:
#   DyLAN       -> instance.num_rounds         (must be > 2)
#   LLM-Debate  -> instance.rounds_num
#   AgentVerse  -> instance.max_turn (outer)   + instance.max_criticizing_rounds (inner)
#   MacNet      -> graph structure, no single round field
# This helper lets the experiment YAML override any of them from a SINGLE place
# without editing the per-framework method config files. Supported YAML keys:
#   max_rounds         : framework-agnostic "primary" round count
#   num_rounds         : DyLAN-specific
#   rounds_num         : LLM-Debate-specific
#   max_turn           : AgentVerse outer loop
#   max_criticizing_rounds : AgentVerse Critic->Solver inner loop
# When `max_rounds` is set, it is mapped to the framework's primary round field.

_PRIMARY_ROUND_FIELD = {
    "dylan": "num_rounds",
    "dylan_math": "num_rounds",
    "dylan_mmlu": "num_rounds",
    "llm_debate": "rounds_num",
    "agentverse": "max_turn",
    # macnet intentionally absent
}


def _override_rounds(instance, exp_config: Dict[str, Any], framework: str) -> Dict[str, Any]:
    """Apply round-count overrides from exp_config to `instance`. Returns the
    final round settings, so wrappers can record them on the trajectory."""
    applied = {}
    fw = (framework or "").lower()

    def _set(attr, val):
        if val is None or not hasattr(instance, attr):
            return
        try:
            setattr(instance, attr, int(val))
            applied[attr] = int(val)
        except (TypeError, ValueError):
            pass

    # Framework-agnostic "max_rounds" -> the primary loop bound for this MAS.
    primary = _PRIMARY_ROUND_FIELD.get(fw)
    if primary and exp_config.get("max_rounds") is not None:
        _set(primary, exp_config["max_rounds"])

    # Framework-specific keys (override the above if both are set).
    _set("num_rounds", exp_config.get("num_rounds"))
    _set("rounds_num", exp_config.get("rounds_num"))
    _set("max_turn", exp_config.get("max_turn"))
    _set("max_criticizing_rounds", exp_config.get("max_criticizing_rounds"))

    # Also collect the FINAL values from the instance for trajectory recording.
    final = {}
    for attr in ("num_rounds", "rounds_num", "max_turn", "max_criticizing_rounds"):
        if hasattr(instance, attr):
            final[attr] = getattr(instance, attr)
    if applied:
        print(f"[_override_rounds] {fw}: applied overrides {applied}; final state {final}")
    return final


class LLMAPIFailure(RuntimeError):
    """Raised when the underlying LLM API exhausted all retries and the framework
    returned None. Lets wrappers / main.py distinguish API failures from real
    injection effects, and surface a clean `status: 'llm_api_failure'` to users.
    """
    pass


def _llm_response_or_raise(response, *, where: str = "call_llm"):
    """Wrap a (possibly None) LLM response.

    When the underlying tenacity retry exhausts (5 attempts in mas_base), it
    calls `handle_retry_error` which returns None. That None then flows into
    framework code that does `re.findall(pattern, None)` -> TypeError
    'expected string or bytes-like object'. We catch the None at the boundary
    instead, raising a clear LLMAPIFailure so wrappers' try/except sees the
    real cause.
    """
    if response is None:
        raise LLMAPIFailure(
            f"LLM API call '{where}' returned None after retries exhausted. "
            f"This is an API-side failure (timeout, rate limit, network), NOT an "
            f"injection effect. Check provider availability."
        )
    return response


def _attach_task_images(instance, image_paths):
    """Install a thin layer on `instance.call_llm` that auto-forwards
    `images=image_paths` on every LLM call (unless the call site explicitly
    set `images=` itself).

    Layering: a wrapper typically composes layers as follows ::

        original  ->  attach_task_images  ->  capture  ->  injection

    so install this FIRST (before _start_llm_capture). When `image_paths` is
    None / empty, this is a no-op (returns the original function unchanged).

    Returns the original `call_llm` reference (so the caller can restore it
    after the run, or it's restored automatically by _stop_llm_capture if the
    capture layer is installed on top).
    """
    if not image_paths:
        return getattr(instance, "call_llm", None)
    original = instance.call_llm

    def _attaching_call(*args, **kwargs):
        # Respect EXPLICIT caller intent:
        #   - kwargs has no "images" key at all -> auto-inject task images
        #   - kwargs has "images" set to a truthy value -> caller-provided wins
        #   - kwargs has "images" set to None / [] -> caller is EXPLICITLY
        #     opting out of multimodal for THIS call (e.g. MDAgents Recruiter /
        #     Classifier turns). Do NOT override.
        if "images" not in kwargs:
            kwargs["images"] = list(image_paths)
        return original(*args, **kwargs)

    instance.call_llm = _attaching_call
    return original


class SystemWrapper(ABC):
    """
    An abstract base class for all multi-agent system wrappers.

    This class defines a standard interface for running experiments on different
    agent frameworks. Each specific framework (e.g., AFlow, Magentic-One) should
    have its own concrete implementation inheriting from this class.

    The main goal is to abstract away the specific details of how each
    framework is initialized and executed, allowing the main experiment
    runner to treat them uniformly.
    """

    @abstractmethod
    def __init__(self, *args, **kwargs):
        """
        The constructor should handle the specific setup for the wrapped
        agent system, such as loading configurations or initializing clients.
        
        This is an abstract method because each system will have a unique
        initialization process.
        """
        pass

    @abstractmethod
    def run_with_injection(
        self,
        task: Task,
        malicious_agent: MaliciousAgent,
        injection_target: dict
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        The core method to run an experiment with a malicious agent injected.

        This method must be implemented by all subclasses. It encapsulates the
        entire logic of executing a task within the target agent system while
        ensuring the malicious agent's behavior is correctly inserted.

        Args:
            task (Task): The task object containing the problem description and
                         ground truth criteria.
            malicious_agent (MaliciousAgent): The malicious agent object containing
                                              its prompt and role.
            injection_target (dict): The target specification for injection.

        Returns:
            A tuple containing:
                - final_output (Any): The final result produced by the agent system.
                - conversation_log (Dict[str, Any]): A dictionary or string
                  containing the log of the interaction for later evaluation.
        """
        pass
    
    def run_with_multi_injection(
        self,
        task: Task,
        malicious_agents: list,
        injection_targets: list
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Run an experiment with multiple malicious agents injected.
        
        Default implementation falls back to single injection if only one target.
        Subclasses should override this method for better multi-agent support.

        Args:
            task (Task): The task object containing the problem description and
                         ground truth criteria.
            malicious_agents (list): List of malicious agent objects.
            injection_targets (list): List of target specifications for injections.

        Returns:
            A tuple containing:
                - final_output (Any): The final result produced by the agent system.
                - conversation_log (Dict[str, Any]): A dictionary or string
                  containing the log of the interaction for later evaluation.
        """
        if len(malicious_agents) == 1 and len(injection_targets) == 1:
            # Fall back to single injection for backward compatibility
            return self.run_with_injection(task, malicious_agents[0], injection_targets[0])
        elif len(malicious_agents) == 0 and len(injection_targets) == 0:
            # No injection requested -> clean run (normal trajectory).
            return self.run_clean(task)
        else:
            # Default multi-injection implementation - subclasses should override
            raise NotImplementedError("Multi-agent injection not implemented for this wrapper")

    def run_clean(self, task: Task) -> Tuple[Any, Dict[str, Any]]:
        """
        Run the wrapped MAS with NO error injection (normal trajectory).

        Delegates to this wrapper's own `run_with_multi_injection` with empty
        injection lists. Each wrapper's multi-injection body builds an EMPTY
        injection map (so no error is ever injected) while still running the MAS
        and collecting the full conversation/trajectory history exactly the same
        way it does for error runs. This guarantees clean runs produce the same
        rich `full_history` / `conversation_history` as injection runs.
        """
        return self.run_with_multi_injection(
            task=task,
            malicious_agents=[],
            injection_targets=[]
        )

    # ------------------------------------------------------------------ #
    # LLM-call capture: records the EXACT input messages + output of every
    # call_llm invocation, so frameworks that reconstruct history post-hoc
    # (DyLAN, LLM-Debate) can still report real `input_messages` instead of None.
    # ------------------------------------------------------------------ #

    def _start_llm_capture(self, instance) -> list:
        """Wrap instance.call_llm to log (input_messages, response) per call.

        Returns the capture list (also stored on the wrapper as self._llm_capture).
        Call _stop_llm_capture(instance) to restore the original method.
        """
        capture = []
        self._llm_capture = capture
        original = instance.call_llm
        self._llm_capture_original = original

        def _resolve_messages(args, kwargs):
            # call_llm(self, prompt=None, system_prompt=None, messages=None, ...)
            messages = kwargs.get("messages")
            prompt = kwargs.get("prompt")
            system_prompt = kwargs.get("system_prompt")
            # positional fallback (rare): (prompt, system_prompt, messages, ...)
            if messages is None and len(args) >= 3:
                messages = args[2]
            if messages is None and prompt is None and len(args) >= 1:
                prompt = args[0]
            if messages is not None:
                return [dict(m) for m in messages] if isinstance(messages, list) else messages
            msgs = []
            if system_prompt:
                msgs.append({"role": "system", "content": system_prompt})
            if prompt is not None:
                msgs.append({"role": "user", "content": prompt})
            return msgs

        def capturing_call(*args, **kwargs):
            input_messages = _resolve_messages(args, kwargs)
            # role/round context at call time (DyLAN exposes these; others may not)
            role = None
            role_index = None
            node_idx = getattr(instance, "current_node_idx", None)
            num_agents = getattr(instance, "num_agents", None)
            if node_idx is not None and hasattr(instance, "nodes"):
                try:
                    role = instance.nodes[node_idx].get("role")
                    role_index = node_idx % num_agents if num_agents else None
                except Exception:
                    pass
            response = original(*args, **kwargs)
            capture.append({
                "input_messages": input_messages,
                "response": response,
                "role": role,
                "role_index": role_index,
            })
            return response

        instance.call_llm = capturing_call
        return capture

    def _stop_llm_capture(self, instance):
        """Restore the original call_llm (if capture was started)."""
        original = getattr(self, "_llm_capture_original", None)
        if original is not None:
            instance.call_llm = original
            self._llm_capture_original = None

    @staticmethod
    def _attach_input_messages(history: list, capture: list) -> list:
        """Fill each history entry's `input_messages` from captured LLM calls.

        Matches by exact response/content text first (most reliable across
        reordering), then falls back to positional order for any unmatched
        entries. Entries with no match keep input_messages=None.
        """
        if not history or not capture:
            return history
        # index captures by their response text for O(1) matching
        by_text = {}
        for c in capture:
            key = (c.get("response") or "").strip()
            if key:
                by_text.setdefault(key, []).append(c)

        used = set()
        for h in history:
            content = (h.get("content") or "").strip()
            matched = None
            bucket = by_text.get(content)
            if bucket:
                for c in bucket:
                    if id(c) not in used:
                        matched = c
                        used.add(id(c))
                        break
            if matched is not None:
                h["input_messages"] = matched.get("input_messages")

        # positional fallback for entries still missing input_messages.
        # Skip User/is_input entries: they are inputs themselves, not LLM calls,
        # so they must NOT consume a capture slot (otherwise the next assistant
        # turn's capture leaks onto them — most visibly Aggregator inputs ending
        # up on a User turn in LLM-Debate).
        remaining = [c for c in capture if id(c) not in used]
        ri = 0
        for h in history:
            if h.get("is_input") or h.get("agent_name") == "User" or h.get("role") == "User":
                continue
            if h.get("input_messages") is None and ri < len(remaining):
                h["input_messages"] = remaining[ri].get("input_messages")
                ri += 1
        return history