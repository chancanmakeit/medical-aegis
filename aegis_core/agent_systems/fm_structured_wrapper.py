# file: aegis_core/agent_systems/fm_structured_wrapper.py
"""
Shared FM-injection wrapper for frameworks re-implemented in this repo with the
"structured" contract (medagents_mc, consensus + its baselines, MAM, ...).

Method-side contract (the MAS class must):
  * route every LLM call through `self.call_llm(prompt=..., system_prompt=...)`
    or `self.call_llm(messages=[...])` (multi-turn agents);
  * set `current_role` / `current_role_index` / `current_phase` before each call;
  * append exactly ONE entry to `self.conversation_history` per call_llm, with
    `step_id`, `role`, `role_index`, `phase`, `content`, and ideally
    `sources` / `round` / `event_ids` / `agent_label`.

What this wrapper guarantees (MedHyperTrace issue #1, problems A and C):
  * `input_messages` on every step is the CLEAN, pre-injection input; for a
    prompt-injected step the received input goes to `injected_input_messages`.
    The log carries `input_messages_are_clean: true`.
  * Prompt injection works for both call styles: `prompt=` is rewritten, or
    for `messages=` the LAST user message is rewritten (earlier turns of a
    multi-turn agent are untouched).
  * A target matches (role, role_index) and optionally `phase` / `round`
    (from current_phase / current_round). It fires only on its FIRST matching
    call unless `inject_every_invocation: true`; each target reports `fired`.
  * `step_id` / `sources` / `round` / `event_ids` pass through untouched.

Subclasses set FRAMEWORK, CONFIG_NAME_KEY and may override `configure()`,
`build_sample()`, `before_run()` and `extra_log()`.
"""

from typing import Any, Dict, List, Tuple

from .base_wrapper import (
    SystemWrapper, _override_rounds, _llm_response_or_raise, LLMAPIFailure,
    _attach_task_images,
)
from malicious_factory import FMMaliciousFactory, FMMaliciousAgent, InjectionStrategy
from methods import get_method_class


def messages_from_call(args, kwargs) -> List[Dict[str, Any]]:
    """Rebuild the chat messages exactly as mas_base.call_llm would."""
    messages = kwargs.get("messages")
    if messages is None and len(args) >= 3:
        messages = args[2]
    if messages is not None:
        return [dict(m) for m in messages]
    prompt = kwargs.get("prompt")
    if prompt is None and len(args) >= 1:
        prompt = args[0]
    system_prompt = kwargs.get("system_prompt")
    if system_prompt is None and len(args) >= 2:
        system_prompt = args[1]
    msgs = []
    if system_prompt is not None:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.append({"role": "user", "content": prompt or ""})
    return msgs


class StructuredFMWrapper(SystemWrapper):
    FRAMEWORK = "structured"
    CONFIG_NAME_KEY = "method_config_name"   # experiment-YAML key naming the method config
    DEFAULT_CONFIG_NAME = "config_medical"

    def __init__(self, general_config: Dict[str, Any], method_config: Dict[str, Any]):
        from utils.async_llm import create_llm_instance

        exp_config = general_config.get("experiment_config", {})
        self.exp_config = exp_config
        llm_config = exp_config.get("llm_config", {})
        if not llm_config:
            raise ValueError("No LLM configuration found for the specified model name.")
        self.llm = create_llm_instance(llm_config)

        method_name = exp_config["system_under_test"]["name"]
        MAS_CLASS = get_method_class(method_name, exp_config.get("benchmark_name"))
        cfg_name = exp_config.get(self.CONFIG_NAME_KEY) \
            or (method_config.get(self.CONFIG_NAME_KEY) if isinstance(method_config, dict) else None) \
            or self.DEFAULT_CONFIG_NAME
        self.mas = MAS_CLASS(general_config, method_config_name=cfg_name)
        self.configure(exp_config)
        self._round_settings = _override_rounds(self.mas, exp_config, framework=method_name)
        self._inject_every = bool(exp_config.get("inject_every_invocation", False))

        factory_llm = self.llm
        if exp_config.get("factory_llm_config"):
            try:
                factory_llm = create_llm_instance(exp_config["factory_llm_config"])
            except Exception as _e:
                print(f"[{type(self).__name__}] could not build factory_llm_config ({_e}); reusing MAS LLM.")
        self.fm_factory = FMMaliciousFactory(
            llm=self.llm,
            injection_method=exp_config.get("injection_method", "direct_prepend"),
            task_type=exp_config.get("task_type", "mcq"),
            prompt_wrapper_style=exp_config.get("prompt_wrapper_style", "direct"),
            factory_llm=factory_llm,
        )
        print(f"{type(self).__name__} initialized (framework={self.FRAMEWORK}, "
              f"inject_every_invocation={self._inject_every}).")

    # ---- hooks --------------------------------------------------------- #
    def configure(self, exp_config: Dict[str, Any]) -> None:
        """Apply experiment-YAML overrides onto self.mas."""

    def build_sample(self, task: Any) -> Dict[str, Any]:
        return {"query": task.query}

    def before_run(self, task: Any, sample: Dict[str, Any]) -> None:
        """Per-sample setup (e.g. tell the factory the class labels)."""

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        return {}

    # ---- entry points -------------------------------------------------- #
    def run_clean(self, task: Any) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, malicious_agents=[], injection_targets=[])

    def run_with_injection(self, task: Any, malicious_agent: FMMaliciousAgent,
                           injection_target: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, [malicious_agent], [injection_target])

    def _inject_into_call(self, args, kwargs, modified_text_fn):
        """Return (new_args, new_kwargs, original_text, modified_text)."""
        new_kwargs = dict(kwargs)
        msgs = kwargs.get("messages")
        if msgs is not None:
            msgs = [dict(m) for m in msgs]
            idx = max(i for i, m in enumerate(msgs) if m.get("role") == "user")
            original = msgs[idx].get("content") or ""
            modified = modified_text_fn(original)
            msgs[idx]["content"] = modified
            new_kwargs["messages"] = msgs
            return args, new_kwargs, original, modified
        original = kwargs.get("prompt")
        if original is None and len(args) >= 1:
            original = args[0]
        original = original or ""
        modified = modified_text_fn(original)
        new_kwargs["prompt"] = modified
        new_args = args[1:] if (len(args) >= 1 and "prompt" not in kwargs) else args
        return new_args, new_kwargs, original, modified

    def run_with_multi_injection(self, task: Any, malicious_agents: list,
                                 injection_targets: list) -> Tuple[Any, Dict[str, Any]]:
        # A target matches a call on (role, role_index) and, when given, on
        # `phase` and/or `round` as well (lets a target hit e.g. debate round 2
        # of an agent instead of its first call).
        targets = list(zip(malicious_agents, injection_targets))
        fired_targets = set()  # indices into `targets`

        def _match(role, role_index, phase, round_):
            for ti, (_a, t) in enumerate(targets):
                if t["role"] != role or t.get("role_index", 0) != role_index:
                    continue
                if t.get("phase") is not None and t["phase"] != phase:
                    continue
                if t.get("round") is not None and t["round"] != round_:
                    continue
                if self._inject_every or ti not in fired_targets:
                    return ti
            return None
        injection_meta_by_call: Dict[int, Dict[str, Any]] = {}
        clean_messages_by_call: Dict[int, List[Dict[str, Any]]] = {}
        call_counter = {"n": 0}

        sample = self.build_sample(task)
        self.before_run(task, sample)
        _attach_task_images(self.mas, getattr(task, "image_paths", None))
        llm_capture = self._start_llm_capture(self.mas)     # what the model RECEIVED
        original_llm_call = self.mas.call_llm
        execution_error = None
        fw = self.FRAMEWORK

        def fm_call_llm(*args, **kwargs):
            inst = self.mas
            role = getattr(inst, "current_role", None)
            role_index = getattr(inst, "current_role_index", 0)
            phase = getattr(inst, "current_phase", None)
            round_ = getattr(inst, "current_round", None)
            turn_idx = call_counter["n"]
            call_counter["n"] += 1
            clean_messages_by_call[turn_idx] = messages_from_call(args, kwargs)

            ti = _match(role, role_index, phase, round_)
            where = f"{fw}:{role}_idx{role_index}_turn{turn_idx}"
            if ti is None:
                return _llm_response_or_raise(original_llm_call(*args, **kwargs), where=where)

            fired_targets.add(ti)
            malicious_agent = targets[ti][0]
            print(f"*** FM injection on {fw} '{role}' (idx {role_index}, phase '{phase}', "
                  f"turn {turn_idx}): {malicious_agent.fm_error_type.value} / "
                  f"{malicious_agent.injection_strategy.value} ***")
            sys_msg = next((m.get("content") for m in clean_messages_by_call[turn_idx]
                            if m.get("role") == "system"), "") or ""

            class _Mock:
                role_name = role or "agent"
                role_type = f"{fw} agent"
                agent_id = f"{fw}_{role}_{role_index}"
                system_message = sys_msg
                tool_dict = {}
                model_type = "LLM"
                chat_history = []
            agent_context = self.fm_factory.extract_agent_context(
                _Mock(), {"name": role, "description": f"{fw} {role} agent"})
            malicious_agent.agent_context = agent_context

            meta = {
                "injection_applied": True,
                "fm_error_type": malicious_agent.fm_error_type.value,
                "injection_strategy": malicious_agent.injection_strategy.value,
                "current_role": role,
                "current_role_index": role_index,
                "current_phase": phase,
                "current_round": round_,
                "target_index": ti,
            }
            if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                new_args, new_kwargs, orig_txt, mod_txt = self._inject_into_call(
                    args, kwargs,
                    lambda t: self.fm_factory.inject_prompt(t, malicious_agent.fm_error_type, agent_context))
                resp = _llm_response_or_raise(original_llm_call(*new_args, **new_kwargs),
                                              where=f"{where}_inject")
                meta["prompt_modified"] = (mod_txt != orig_txt)
                meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
            elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                clean = _llm_response_or_raise(original_llm_call(*args, **kwargs),
                                               where=f"{where}_clean_for_corruption")
                resp = self.fm_factory.corrupt_response(
                    clean, malicious_agent.fm_error_type, agent_context)
                meta["clean_response_before_corruption"] = clean
                meta["response_corrupted"] = (resp != clean)
                meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
            else:
                resp = _llm_response_or_raise(original_llm_call(*args, **kwargs),
                                              where=f"{where}_unknown_strategy")
            injection_meta_by_call[turn_idx] = meta
            return resp

        self.mas.call_llm = fm_call_llm
        try:
            final_output = self.mas.inference(sample)
        except LLMAPIFailure as e:
            execution_error = f"llm_api_failure: {e}"
            print(f"[{type(self).__name__}] LLM API FAILURE (not an injection effect): {e}")
            final_output = {"response": f"LLM API failure: {e}", "history": []}
        except Exception as e:
            execution_error = str(e)
            print(f"[{type(self).__name__}] Inference failed: {e}")
            final_output = {"response": f"{fw} execution disrupted: {e}", "history": []}
        finally:
            self._stop_llm_capture(self.mas)

        raw_history = list(getattr(self.mas, "conversation_history", []))
        alignment_ok = (len(raw_history) == len(clean_messages_by_call) == len(llm_capture))
        for i, h in enumerate(raw_history):
            received = llm_capture[i].get("input_messages") if i < len(llm_capture) else None
            clean = clean_messages_by_call.get(i)
            h["input_messages"] = clean if clean is not None else received
            if i in injection_meta_by_call:
                meta = injection_meta_by_call[i]
                if meta.get("injection_strategy") == InjectionStrategy.PROMPT_INJECTION.value:
                    meta["injected_input_messages"] = received
                h.update(meta)
            if "agent_name" not in h and "role" in h:
                h["agent_name"] = h["role"]
        if not alignment_ok:
            print(f"[{type(self).__name__}] WARNING: history/capture misalignment "
                  f"({len(raw_history)} history, {len(clean_messages_by_call)} calls, "
                  f"{len(llm_capture)} captures)")

        log = {
            "framework": fw,
            "conversation_history": raw_history,
            "input_messages_are_clean": True,
            "history_alignment_ok": alignment_ok,
            "multi_injection_info": [
                {"injected_role": t["role"], "injected_role_index": t.get("role_index", 0),
                 "injected_phase": t.get("phase"), "injected_round": t.get("round"),
                 "fm_error_type": a.fm_error_type.value,
                 "injection_strategy": a.injection_strategy.value,
                 "fired": ti in fired_targets}
                for ti, (a, t) in enumerate(targets)
            ],
            "num_injected_agents": len(malicious_agents),
            "agent_names": list(dict.fromkeys(h.get("role") for h in raw_history if h.get("role"))),
            "final_step_id": final_output.get("final_step_id") if isinstance(final_output, dict) else None,
            "execution_successful": execution_error is None,
            "execution_error": execution_error,
            "round_settings": self._round_settings,
        }
        log.update(self.extra_log(final_output))
        out = {"response": final_output.get("response", "")} if isinstance(final_output, dict) \
            else {"response": str(final_output)}
        return out, log
