# DEPRECATED (2026-10-20): superseded by aegis_core.agent_systems.fm_cmas_structured_wrapper.FMCMASStructuredWrapper
# (structured contract: clean input_messages, read sets, agent ids, llm_meta,
# inject-once). Kept only to reproduce data generated before the migration.
# file: aegis_core/agent_systems/fm_cmas_wrapper.py
"""
FM-injection wrapper for the CMAS zero-shot NER multi-agent system.

Same overall architecture as fm_dylan_wrapper.py / fm_agentverse_wrapper.py /
fm_debate_wrapper.py / fm_mdagents_wrapper.py / fm_clinical_agent_wrapper.py: we
monkey-patch the framework instance's `call_llm` so that each LLM call is
evaluated against the active `injection_plan.targets`. A call is injected if its
(role, role_index) matches.

Role/role_index conventions (set by `cmas_main.CMAS_Main._ask`):
  - "TRFExtractor"     (idx 0): type-related-feature identification (Prompt 2)
                                (skipped when method_config.use_trf_extractor=false)
  - "Discriminator"    (idx 0): demonstration helpfulness scoring / self-reflection
                                (Prompt 3; skipped when use_discriminator=false or
                                 there are no demonstrations)
  - "OverallPredictor" (idx 0): final NER prediction, JSON [{Entity: Type}] (Prompt 4)

The self-annotator (Prompt 1) is an OFFLINE corpus-annotation step and is not a
per-test-sample agent, so it is not part of the injectable trajectory.

These 3 core roles are STABLE across every sample -- there is NO LLM-decided role
naming. That property makes CMAS a clean AEGIS integration for cooperative
multi-agent error attribution studies on the NER task.
"""

import asyncio
from typing import Any, Dict, Tuple

from .base_wrapper import (
    SystemWrapper, _override_rounds, _llm_response_or_raise, LLMAPIFailure, _attach_task_images
)
from malicious_factory import (
    FMMaliciousFactory, FMMaliciousAgent, FMErrorType, InjectionStrategy
)
from methods import get_method_class


class FMCMASWrapper(SystemWrapper):
    """Inject FM errors into ClinicalAgent trajectories.

    Note: ClinicalAgent lacks the "round" notion DyLAN has; injections fire once
    when their (role, role_index) is encountered. If a role is invoked
    multiple times (e.g. the same Expert participates in two debate rounds),
    only the FIRST matching call is injected by default — this keeps the
    injection's effect easy to attribute. Set `inject_every_invocation: true`
    in the experiment YAML to inject on every matching call.
    """

    def __init__(self, general_config: Dict[str, Any], method_config: Dict[str, Any]):
        from utils.async_llm import create_llm_instance

        exp_config = general_config.get('experiment_config', {})
        llm_config = exp_config.get('llm_config', {})
        if not llm_config:
            raise ValueError("No LLM configuration found for the specified model name.")
        self.llm = create_llm_instance(llm_config)

        method_name = exp_config['system_under_test']['name']  # "cmas"
        dataset_name = exp_config.get('benchmark_name', None)
        MAS_CLASS = get_method_class(method_name, dataset_name)

        # Allow the experiment config to choose an mdagents config file
        # (loaded from methods/mdagents/configs/<name>.yaml). Default: "config_ner".
        md_config_name = exp_config.get('cmas_config_name') \
            or (method_config.get('cmas_config_name') if isinstance(method_config, dict) else None) \
            or "config_ner"
        self.cmas_instance = MAS_CLASS(general_config, method_config_name=md_config_name)

        # Allow YAML to override use_trf_extractor / use_discriminator /
        # few_shot_number / demo_pool_path directly on the instance (handy for
        # ablations without editing the method config file).
        if exp_config.get('cmas_use_trf_extractor') is not None:
            self.cmas_instance.use_trf_extractor = bool(exp_config['cmas_use_trf_extractor'])
        if exp_config.get('cmas_use_discriminator') is not None:
            self.cmas_instance.use_discriminator = bool(exp_config['cmas_use_discriminator'])
        if exp_config.get('cmas_few_shot_number') is not None:
            self.cmas_instance.few_shot_number = int(exp_config['cmas_few_shot_number'])
        if exp_config.get('cmas_demo_pool_path') is not None:
            self.cmas_instance.demo_pool_path = str(exp_config['cmas_demo_pool_path'])
        if exp_config.get('cmas_demo_retrieval_mode') is not None:
            self.cmas_instance.demo_retrieval_mode = str(exp_config['cmas_demo_retrieval_mode'])

        self._round_settings = _override_rounds(
            self.cmas_instance, exp_config, framework=method_name
        )

        # Inject on every matching call (default: only first)
        self._inject_every = bool(exp_config.get('inject_every_invocation', False))

        # FM factory: same as the other wrappers
        factory_llm = self.llm
        if exp_config.get('factory_llm_config'):
            try:
                from utils.async_llm import create_llm_instance as _cli
                factory_llm = _cli(exp_config['factory_llm_config'])
            except Exception as _e:
                print(f"[FMCMASWrapper] could not build factory_llm_config ({_e}); reusing MAS LLM.")
        self.fm_factory = FMMaliciousFactory(
            llm=self.llm,
            injection_method=exp_config.get('injection_method', 'direct_prepend'),
            task_type=exp_config.get('task_type', 'mcq'),
            prompt_wrapper_style=exp_config.get('prompt_wrapper_style', 'direct'),
            factory_llm=factory_llm,
        )
        print(f"FMCMASWrapper initialized (use_trf_extractor="
              f"{self.cmas_instance.use_trf_extractor}, use_discriminator="
              f"{self.cmas_instance.use_discriminator}, few_shot_number="
              f"{self.cmas_instance.few_shot_number}).")

    # ------------------------------------------------------------------ #
    # Clean run (no injection) — required by SystemWrapper.run_clean
    # ------------------------------------------------------------------ #
    def run_clean(self, task: Any) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, malicious_agents=[], injection_targets=[])

    def run_with_injection(self, task: Any, malicious_agent: FMMaliciousAgent,
                            injection_target: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, [malicious_agent], [injection_target])

    # ------------------------------------------------------------------ #
    # Multi-injection run (the workhorse)
    # ------------------------------------------------------------------ #
    def run_with_multi_injection(
        self, task: Any, malicious_agents: list, injection_targets: list
    ) -> Tuple[Any, Dict[str, Any]]:

        # Build (role, role_index) -> injection_info
        injection_map = {}
        for agent, target in zip(malicious_agents, injection_targets):
            key = (target['role'], target.get('role_index', 0))
            injection_map[key] = {'agent': agent, 'target': target}

        # Track which injection_keys have already fired (only-first-call mode).
        fired_keys = set()
        # Per-call meta we accumulate, indexed by a running counter so the
        # later log assembly can attach it to the right turn.
        injection_meta_by_call = {}
        # Counter mirrors len(self.cmas_instance.conversation_history)
        # at the time the call resolves (i.e. the index of THIS turn).
        call_counter = {"n": 0}

        # Start capturing real input_messages around every call_llm.
        # _start_llm_capture wraps `self.cmas_instance.call_llm`. The
        # injection patch below wraps THAT capturing function so input_messages
        # are still recorded even for injected calls.
        # Multimodal: install image-auto-attach layer FIRST (before capture & injection)
        # so every LLM call this instance makes during inference carries the task's
        # image(s). No-op for text-only tasks (image_paths is None or []).
        _attach_task_images(self.cmas_instance, getattr(task, 'image_paths', None))
        llm_capture = self._start_llm_capture(self.cmas_instance)
        original_llm_call = self.cmas_instance.call_llm  # = capturing_call

        execution_error = None

        def fm_cmas_call_llm(*args, **kwargs):
            instance = self.cmas_instance
            current_role = getattr(instance, "current_role", None)
            current_role_index = getattr(instance, "current_role_index", 0)
            current_phase = getattr(instance, "current_phase", None)

            # This is the turn that THIS call is about to produce.
            turn_idx = call_counter["n"]
            call_counter["n"] += 1

            injection_key = (current_role, current_role_index)
            should_inject = (
                injection_key in injection_map
                and (self._inject_every or injection_key not in fired_keys)
            )

            if not should_inject:
                # Passthrough — but still detect LLM API failure cleanly.
                return _llm_response_or_raise(
                    original_llm_call(*args, **kwargs),
                    where=f"cmas:{current_role}_idx{current_role_index}_turn{turn_idx}"
                )

            # ---- This call IS an injection target. ----
            fired_keys.add(injection_key)
            inj = injection_map[injection_key]
            malicious_agent = inj['agent']
            print(f"*** FM Multi-Malicious Agent Activated on ClinicalAgent '{current_role}' "
                  f"(idx {current_role_index}, phase '{current_phase}', turn {turn_idx}) ***")
            print(f"    Error Type: {malicious_agent.fm_error_type.value}, "
                  f"Strategy: {malicious_agent.injection_strategy.value}")

            # Build a mock agent context so the factory templates can use it.
            class _Mock:
                role_name = current_role or "agent"
                role_type = "ClinicalAgent Agent"
                agent_id = f"mdagents_{current_role}_{current_role_index}"
                system_message = kwargs.get("system_prompt") or ""
                tool_dict = {}
                model_type = "LLM"
                chat_history = []
            agent_context = self.fm_factory.extract_agent_context(
                _Mock(),
                {"name": current_role, "description": f"ClinicalAgent {current_role} agent"}
            )
            malicious_agent.agent_context = agent_context

            # Pull the user prompt out of args/kwargs.
            user_prompt = kwargs.get("prompt")
            if user_prompt is None and len(args) >= 1:
                user_prompt = args[0]
            user_prompt = user_prompt or ""

            meta = {
                "injection_applied": True,
                "fm_error_type": malicious_agent.fm_error_type.value,
                "injection_strategy": malicious_agent.injection_strategy.value,
                "original_prompt": user_prompt,
                "current_role": current_role,
                "current_role_index": current_role_index,
                "current_phase": current_phase,
            }

            if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                modified_prompt = self.fm_factory.inject_prompt(
                    user_prompt, malicious_agent.fm_error_type, agent_context
                )
                new_kwargs = dict(kwargs)
                new_kwargs["prompt"] = modified_prompt
                # Drop a positional prompt if one was supplied (avoid duplicate
                # arg error from call_llm); call_llm accepts kwargs-only here.
                new_args = args[1:] if (len(args) >= 1 and "prompt" not in kwargs) else args
                resp = _llm_response_or_raise(
                    original_llm_call(*new_args, **new_kwargs),
                    where=f"cmas:{current_role}_inject"
                )
                meta["prompt_modified"] = (modified_prompt != user_prompt)
                meta["modified_prompt"] = modified_prompt
                meta["injection_process"] = dict(self.fm_factory.last_injection_meta)

            elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                clean = _llm_response_or_raise(
                    original_llm_call(*args, **kwargs),
                    where=f"cmas:{current_role}_clean_for_corruption"
                )
                resp = self.fm_factory.corrupt_response(
                    clean, malicious_agent.fm_error_type, agent_context
                )
                meta["clean_response_before_corruption"] = clean
                meta["response_corrupted"] = (resp != clean)
                meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
            else:
                resp = _llm_response_or_raise(
                    original_llm_call(*args, **kwargs),
                    where=f"cmas:{current_role}_unknown_strategy"
                )

            injection_meta_by_call[turn_idx] = meta
            return resp

        # Install injection layer on top of the capture layer.
        self.cmas_instance.call_llm = fm_cmas_call_llm
        print(f"[FMCMASWrapper] Multi-injection monkey-patch applied "
              f"for {len(malicious_agents)} targets.")

        # Execute
        sample = {"query": task.query}
        # Forward multimodal attachments from the Task to ClinicalAgent_Main.inference,
        # which propagates them to every Expert/Aggregator LLM call.
        if getattr(task, "image_paths", None):
            sample["image_paths"] = list(task.image_paths)
        try:
            final_output = self.cmas_instance.inference(sample)
        except LLMAPIFailure as e:
            execution_error = f"llm_api_failure: {e}"
            print(f"[FMCMASWrapper] LLM API FAILURE (not an injection effect): {e}")
            final_output = {"response": f"LLM API failure: {e}", "history": []}
        except Exception as e:
            execution_error = str(e)
            print(f"[FMCMASWrapper] Inference failed during multi-injection: {e}")
            final_output = {"response": f"ClinicalAgent execution disrupted: {e}", "history": []}
        finally:
            # Restore
            self._stop_llm_capture(self.cmas_instance)
            print("[FMCMASWrapper] Original call_llm restored.")

        # --- Build the unified conversation_history ---
        # ClinicalAgent_Main records each turn into its own conversation_history
        # (role / role_index / phase / content). We attach input_messages
        # captured by _start_llm_capture and merge injection metadata.
        raw_history = list(getattr(self.cmas_instance, "conversation_history", []))
        # Attach input_messages from the capture (position-aligned: MDAgents
        # records EXACTLY one history entry per call_llm call).
        for i, h in enumerate(raw_history):
            if i < len(llm_capture):
                h["input_messages"] = llm_capture[i].get("input_messages")
            # Attach injection meta if this turn was injected.
            if i in injection_meta_by_call:
                h.update(injection_meta_by_call[i])
            # Standardize keys: most other wrappers use "agent_name" not "role".
            # Trajectory normalizer handles renames, but we set it here too for
            # backwards-compat with downstream filters that key on agent_name.
            if "agent_name" not in h and "role" in h:
                h["agent_name"] = h["role"]

        # Log dict mirroring the other wrappers' shape
        log = {
            "framework": "cmas",
            "use_trf_extractor": getattr(self.cmas_instance, "use_trf_extractor", None),
            "use_discriminator": getattr(self.cmas_instance, "use_discriminator", None),
            "trfs": (final_output or {}).get("trfs"),
            "helpfulness": (final_output or {}).get("helpfulness"),
            "conversation_history": raw_history,
            "multi_injection_info": [
                {
                    "injected_role": target['role'],
                    "injected_role_index": target.get('role_index', 0),
                    "fm_error_type": agent.fm_error_type.value,
                    "injection_strategy": agent.injection_strategy.value,
                }
                for agent, target in zip(malicious_agents, injection_targets)
            ],
            "num_injected_agents": len(malicious_agents),
            # Distinct structural speakers seen this run (in first-seen order),
            # excluding any orchestration helpers that aren't task-solving.
            "agent_names": list(dict.fromkeys(
                h.get("role") for h in raw_history if h.get("role")
            )),
            "execution_successful": execution_error is None,
            "execution_error": execution_error,
            "round_settings": self._round_settings,
        }

        # Normalize final_output into the {"response": "..."} shape main.py expects
        if isinstance(final_output, dict):
            out = {"response": final_output.get("response", "")}
        else:
            out = {"response": str(final_output)}

        return out, log
