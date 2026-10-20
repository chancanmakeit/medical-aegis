# file: aegis_core/agent_systems/fm_medagents_mc_wrapper.py
"""
FM-injection wrapper for MedAgents (multi-disciplinary collaboration), method
name `medagents_mc` (see methods/medagents_mc/medagents_mc_main.py).

Same monkey-patching approach as fm_mdagents_wrapper.py, with two changes that
address the label-leak findings from MedHyperTrace (issue #1, problem A):

  1. CLEAN INPUT. The capture layer sits below the injection layer, so what it
     records for a prompt-injected call is the INJECTED input. This wrapper
     additionally builds the clean (pre-injection) messages inside the
     injection layer and, when assembling the log, writes:
        input_messages           <- clean, pre-injection messages (always)
        injected_input_messages  <- what the model actually received
                                    (only on prompt-injected steps)
     so a consumer that reads `input_messages` never sees injection text.
     The log carries `input_messages_are_clean: true` to mark the convention.

  2. READ SETS. The method records `step_id` / `sources` / `round` /
     `event_ids` per step at prompt-assembly time; this wrapper passes them
     through untouched.

Structural roles (set by MedAgentsMC_Main._ask before each call):
  QuestionClassifier(0), OptionClassifier(0), QuestionAnalyst(0..4),
  OptionAnalyst(0..1), Synthesizer(0), Voter(0..6), Advisor(0..6),
  Reviser(0), Decider(0)
Voter / Advisor / Reviser can be invoked once per consultation round. By
default an injection fires only on the FIRST matching call (consistent with
mdagents / clinical_agent / cmas); set `inject_every_invocation: true` in the
experiment YAML to inject on every matching call.
"""

from typing import Any, Dict, List, Optional, Tuple

from .base_wrapper import (
    SystemWrapper, _override_rounds, _llm_response_or_raise, LLMAPIFailure,
    _attach_task_images,
)
from malicious_factory import FMMaliciousFactory, FMMaliciousAgent, InjectionStrategy
from methods import get_method_class


def _messages_from_call(args, kwargs) -> List[Dict[str, Any]]:
    """Rebuild the chat messages exactly as mas_base.call_llm would."""
    messages = kwargs.get("messages")
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


class FMMedAgentsMCWrapper(SystemWrapper):
    """Inject FM errors into MedAgents (MC) trajectories."""

    def __init__(self, general_config: Dict[str, Any], method_config: Dict[str, Any]):
        from utils.async_llm import create_llm_instance

        exp_config = general_config.get("experiment_config", {})
        llm_config = exp_config.get("llm_config", {})
        if not llm_config:
            raise ValueError("No LLM configuration found for the specified model name.")
        self.llm = create_llm_instance(llm_config)

        method_name = exp_config["system_under_test"]["name"]  # "medagents_mc"
        dataset_name = exp_config.get("benchmark_name", None)
        MAS_CLASS = get_method_class(method_name, dataset_name)
        cfg_name = exp_config.get("medagents_config_name") \
            or (method_config.get("medagents_config_name") if isinstance(method_config, dict) else None) \
            or "config_medical"
        self.mas = MAS_CLASS(general_config, method_config_name=cfg_name)

        if exp_config.get("medagents_max_attempt_vote") is not None:
            self.mas.max_attempt_vote = int(exp_config["medagents_max_attempt_vote"])
        if exp_config.get("medagents_use_original_max_tokens") is not None:
            self.mas.use_original_max_tokens = bool(exp_config["medagents_use_original_max_tokens"])

        self._round_settings = _override_rounds(self.mas, exp_config, framework=method_name)
        self._inject_every = bool(exp_config.get("inject_every_invocation", False))

        factory_llm = self.llm
        if exp_config.get("factory_llm_config"):
            try:
                factory_llm = create_llm_instance(exp_config["factory_llm_config"])
            except Exception as _e:
                print(f"[FMMedAgentsMCWrapper] could not build factory_llm_config ({_e}); reusing MAS LLM.")
        self.fm_factory = FMMaliciousFactory(
            llm=self.llm,
            injection_method=exp_config.get("injection_method", "direct_prepend"),
            task_type=exp_config.get("task_type", "mcq"),
            prompt_wrapper_style=exp_config.get("prompt_wrapper_style", "direct"),
            factory_llm=factory_llm,
        )
        print(f"FMMedAgentsMCWrapper initialized (max_attempt_vote={self.mas.max_attempt_vote}, "
              f"use_original_max_tokens={self.mas.use_original_max_tokens}, "
              f"inject_every_invocation={self._inject_every}).")

    # ------------------------------------------------------------------ #
    def run_clean(self, task: Any) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, malicious_agents=[], injection_targets=[])

    def run_with_injection(self, task: Any, malicious_agent: FMMaliciousAgent,
                           injection_target: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, [malicious_agent], [injection_target])

    # ------------------------------------------------------------------ #
    def run_with_multi_injection(self, task: Any, malicious_agents: list,
                                 injection_targets: list) -> Tuple[Any, Dict[str, Any]]:
        injection_map = {}
        for agent, target in zip(malicious_agents, injection_targets):
            injection_map[(target["role"], target.get("role_index", 0))] = {
                "agent": agent, "target": target}

        fired_keys = set()
        injection_meta_by_call: Dict[int, Dict[str, Any]] = {}
        clean_messages_by_call: Dict[int, List[Dict[str, Any]]] = {}
        call_counter = {"n": 0}

        _attach_task_images(self.mas, getattr(task, "image_paths", None))
        llm_capture = self._start_llm_capture(self.mas)   # records what the model RECEIVED
        original_llm_call = self.mas.call_llm             # = capturing call
        execution_error = None

        def fm_call_llm(*args, **kwargs):
            inst = self.mas
            role = getattr(inst, "current_role", None)
            role_index = getattr(inst, "current_role_index", 0)
            phase = getattr(inst, "current_phase", None)
            turn_idx = call_counter["n"]
            call_counter["n"] += 1
            # Clean messages, built BEFORE any injection touches the prompt.
            clean_messages_by_call[turn_idx] = _messages_from_call(args, kwargs)

            key = (role, role_index)
            should_inject = key in injection_map and (self._inject_every or key not in fired_keys)
            where = f"medagents_mc:{role}_idx{role_index}_turn{turn_idx}"
            if not should_inject:
                return _llm_response_or_raise(original_llm_call(*args, **kwargs), where=where)

            fired_keys.add(key)
            malicious_agent = injection_map[key]["agent"]
            print(f"*** FM injection on MedAgents '{role}' (idx {role_index}, phase '{phase}', "
                  f"turn {turn_idx}): {malicious_agent.fm_error_type.value} / "
                  f"{malicious_agent.injection_strategy.value} ***")

            class _Mock:
                role_name = role or "agent"
                role_type = "MedAgents Agent"
                agent_id = f"medagents_mc_{role}_{role_index}"
                system_message = kwargs.get("system_prompt") or ""
                tool_dict = {}
                model_type = "LLM"
                chat_history = []
            agent_context = self.fm_factory.extract_agent_context(
                _Mock(), {"name": role, "description": f"MedAgents {role} agent"})
            malicious_agent.agent_context = agent_context

            user_prompt = kwargs.get("prompt")
            if user_prompt is None and len(args) >= 1:
                user_prompt = args[0]
            user_prompt = user_prompt or ""

            meta = {
                "injection_applied": True,
                "fm_error_type": malicious_agent.fm_error_type.value,
                "injection_strategy": malicious_agent.injection_strategy.value,
                "current_role": role,
                "current_role_index": role_index,
                "current_phase": phase,
            }
            if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                modified_prompt = self.fm_factory.inject_prompt(
                    user_prompt, malicious_agent.fm_error_type, agent_context)
                new_kwargs = dict(kwargs)
                new_kwargs["prompt"] = modified_prompt
                new_args = args[1:] if (len(args) >= 1 and "prompt" not in kwargs) else args
                resp = _llm_response_or_raise(original_llm_call(*new_args, **new_kwargs),
                                              where=f"{where}_inject")
                meta["prompt_modified"] = (modified_prompt != user_prompt)
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
            # Overwrite the method's recorded output? No: the method records
            # whatever call_llm returns, i.e. the (possibly corrupted) resp.
            return resp

        self.mas.call_llm = fm_call_llm
        sample = {"query": task.query}
        md = getattr(task, "metadata", None) or {}
        if md.get("mcq_options"):
            sample["mcq_question"] = md.get("mcq_question")
            sample["mcq_options"] = md["mcq_options"]
        try:
            final_output = self.mas.inference(sample)
        except LLMAPIFailure as e:
            execution_error = f"llm_api_failure: {e}"
            print(f"[FMMedAgentsMCWrapper] LLM API FAILURE (not an injection effect): {e}")
            final_output = {"response": f"LLM API failure: {e}", "history": []}
        except Exception as e:
            execution_error = str(e)
            print(f"[FMMedAgentsMCWrapper] Inference failed: {e}")
            final_output = {"response": f"MedAgents execution disrupted: {e}", "history": []}
        finally:
            self._stop_llm_capture(self.mas)

        # --- Assemble the per-step log ------------------------------------ #
        # The method records exactly one history entry per call_llm (also on
        # injected calls; response_corruption makes ONE capture-layer call),
        # so entries align by position with clean_messages_by_call and
        # llm_capture.
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

        log = {
            "framework": "medagents_mc",
            "conversation_history": raw_history,
            "input_messages_are_clean": True,
            "history_alignment_ok": alignment_ok,
            "multi_injection_info": [
                {
                    "injected_role": t["role"],
                    "injected_role_index": t.get("role_index", 0),
                    "fm_error_type": a.fm_error_type.value,
                    "injection_strategy": a.injection_strategy.value,
                    "fired": (t["role"], t.get("role_index", 0)) in fired_keys,
                }
                for a, t in zip(malicious_agents, injection_targets)
            ],
            "num_injected_agents": len(malicious_agents),
            "agent_names": list(dict.fromkeys(h.get("role") for h in raw_history if h.get("role"))),
            "num_consultation_rounds": (final_output or {}).get("num_consultation_rounds")
                if isinstance(final_output, dict) else None,
            "vote_history": (final_output or {}).get("vote_history")
                if isinstance(final_output, dict) else None,
            "final_step_id": (final_output or {}).get("final_step_id")
                if isinstance(final_output, dict) else None,
            "execution_successful": execution_error is None,
            "execution_error": execution_error,
            "round_settings": self._round_settings,
        }
        if not alignment_ok:
            print(f"[FMMedAgentsMCWrapper] WARNING: history/capture misalignment "
                  f"({len(raw_history)} history, {len(clean_messages_by_call)} calls, "
                  f"{len(llm_capture)} captures)")

        out = {"response": final_output.get("response", "")} if isinstance(final_output, dict) \
            else {"response": str(final_output)}
        return out, log
