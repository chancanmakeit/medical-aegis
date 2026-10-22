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
  * Every LLM step gets `llm_meta` (reasoning text, finish_reason, token usage,
    max_tokens; see mas_base._extract_call_meta). For a response-corrupted step
    it describes the clean call whose output was then corrupted.

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
from methods.mas_base.mas_base import pop_last_call_meta


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
            template_pool=exp_config.get("template_pool"),
            template_pool_model=exp_config.get("template_pool_model") or llm_config.get("model_name"),
            seed=exp_config.get("injection_seed", 0),
            rc_mode=exp_config.get("rc_mode", "append"),
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

    def before_injection(self, role, role_index, phase, round_) -> None:
        """Called right before a target fires (e.g. set the factory's answer
        field / class labels for this agent)."""

    # ---- entry points -------------------------------------------------- #
    def run_clean(self, task: Any) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, malicious_agents=[], injection_targets=[])

    def run_with_injection(self, task: Any, malicious_agent: FMMaliciousAgent,
                           injection_target: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
        return self.run_with_multi_injection(task, [malicious_agent], [injection_target])

    def _inject_into_call(self, args, kwargs, modified_text_fn):
        """Return (new_args, new_kwargs, original_text, modified_text)."""
        # call_llm(prompt, system_prompt, messages, ...): a positional
        # `messages` (e.g. AgentVerse's call_llm(None, None, msgs)) is moved to
        # kwargs first, otherwise the prompt branch below would pass `prompt`
        # twice.
        if kwargs.get("messages") is None and len(args) >= 3 and args[2] is not None:
            kwargs = dict(kwargs, messages=args[2])
            args = tuple(args[3:])
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

        # role_index "*" matches any agent of that role; "nth": k fires on the
        # k-th matching call (1-based), e.g. {role: Doctor, role_index: "*",
        # phase: discussion, nth: 2} = the second doctor turn, whoever speaks
        # (MAC's selector decides who speaks, so fixed roles often never fire).
        match_counts: Dict[int, int] = {}

        def _match(role, role_index, phase, round_):
            for ti, (_a, t) in enumerate(targets):
                if t["role"] != role:
                    continue
                if t.get("role_index", 0) != "*" and t.get("role_index", 0) != role_index:
                    continue
                if t.get("phase") is not None and t["phase"] != phase:
                    continue
                if t.get("round") is not None and t["round"] != round_:
                    continue
                if t.get("nth") is not None:
                    match_counts[ti] = match_counts.get(ti, 0) + 1
                    if match_counts[ti] != int(t["nth"]):
                        continue
                if self._inject_every or ti not in fired_targets:
                    return ti
            return None
        injection_meta_by_call: Dict[int, Dict[str, Any]] = {}
        clean_messages_by_call: Dict[int, List[Dict[str, Any]]] = {}
        llm_meta_by_call: Dict[int, Any] = {}

        def _call(turn_idx, where, *a, **kw):
            pop_last_call_meta(self.mas)          # drop any stale meta
            r = _llm_response_or_raise(original_llm_call(*a, **kw), where=where)
            llm_meta_by_call[turn_idx] = pop_last_call_meta(self.mas)
            return r
        call_counter = {"n": 0}

        sample = self.build_sample(task)
        # the factory reads MCQ option letters from the task text (RC wrong answer)
        self.fm_factory.task_text = getattr(task, "query", None) or str(sample.get("query", ""))
        gt = getattr(task, "ground_truth", None)
        if isinstance(gt, dict):
            gt = gt.get("correct_answer")
        self.fm_factory.gold_answer = gt if isinstance(gt, (str, int)) else None
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        self.fm_factory.distractor_counts = raw.get("screen_distractors")
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
                return _call(turn_idx, where, *args, **kwargs)

            fired_targets.add(ti)
            malicious_agent = targets[ti][0]
            self.before_injection(role, role_index, phase, round_)
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
            def _pi_call(ref_text):
                """Prompt-injected call. With exp_config `pi_length_match`
                ({min_ratio, max_ratio, max_tries}) and a clean reference reply,
                the injected reply is re-sampled until its length is within
                [min_ratio, max_ratio] x the reference (else the closest try
                is kept): injected replies were ~half as long as normal ones,
                a length signature (anchor gate, 2026-10-21). Only the kept
                try stays in the trajectory; the others are dropped from the
                capture and recorded in the labels."""
                cfg = self.exp_config.get("pi_length_match") or {}
                self.fm_factory.target_words = (len(ref_text.split()) if (ref_text and cfg.get("state_length"))
                                                else None)
                # format of the clean reference (state_format, fmt_v1): injected
                # notes otherwise suppressed markdown (MedHyperTrace r43)
                struct = bool(cfg.get("state_structure"))   # fmt_v1_1 (MHT r48)
                ref_fmt = (FMMaliciousFactory.ref_format_features(ref_text, struct)
                           if (ref_text and cfg.get("state_format")) else None)
                self.fm_factory.ref_format = ref_fmt
                _sh = (targets[ti][1].get("attack_spec") or {}).get("sham")
                self.fm_factory.sham_mode = "style" if _sh == "style" else bool(_sh)
                new_args, new_kwargs, orig_txt, mod_txt = self._inject_into_call(
                    args, kwargs,
                    lambda t: self.fm_factory.inject_prompt(t, malicious_agent.fm_error_type, agent_context))
                self.fm_factory.target_words = None
                self.fm_factory.ref_format = None
                self.fm_factory.sham_mode = False
                tries = int(cfg.get("max_tries", 3)) if (cfg and ref_text) else 1
                lo, hi = float(cfg.get("min_ratio", 0.6)), float(cfg.get("max_ratio", 1.5))
                # match_format: a try is accepted only if it also has markdown
                # exactly when the reference does (same '###'/'**' test as r43)
                ref_md = FMMaliciousFactory.has_markdown(ref_text) if ref_text else None
                ref_sig = FMMaliciousFactory.format_signature(ref_text, struct) if ref_text else None
                want_fmt = bool(cfg.get("match_format")) and ref_text is not None
                attempts = []

                def _ok(a):
                    len_ok = a["ratio"] is None or lo <= a["ratio"] <= hi
                    return len_ok and (not want_fmt or a["sig"] == ref_sig)
                for t in range(tries):
                    cap_i = len(llm_capture)
                    r = _call(turn_idx, f"{where}_inject" + (f"_try{t}" if t else ""), *new_args, **new_kwargs)
                    ratio = (len(r or "") / max(1, len(ref_text))) if ref_text else None
                    attempts.append({"resp": r, "meta": llm_meta_by_call.get(turn_idx),
                                     "cap": cap_i, "ratio": ratio,
                                     "md": FMMaliciousFactory.has_markdown(r),
                                     "sig": FMMaliciousFactory.format_signature(r, struct)})
                    if _ok(attempts[-1]):
                        break
                import math
                chosen = attempts[-1]
                if not _ok(chosen):
                    # no try passed: prefer a format match, then the closest length
                    chosen = min(attempts, key=lambda a: (
                        (want_fmt and a["sig"] != ref_sig),
                        abs(math.log(max(a["ratio"], 1e-6))) if a["ratio"] is not None else 0.0))
                for a in sorted((a for a in attempts if a is not chosen), key=lambda a: -a["cap"]):
                    if a["cap"] < len(llm_capture):
                        del llm_capture[a["cap"]]
                llm_meta_by_call[turn_idx] = chosen["meta"]
                info = {"prompt_modified": (mod_txt != orig_txt)}
                if ref_text is not None and cfg:
                    info["pi_length_match"] = {
                        "ref_len": len(ref_text), "ratios": [a["ratio"] for a in attempts],
                        "kept_try": attempts.index(chosen), "in_range": lo <= chosen["ratio"] <= hi,
                        "discarded_llm_meta": [a["meta"] for a in attempts if a is not chosen]}
                    if ref_fmt is not None or want_fmt:
                        info["pi_length_match"]["format"] = {
                            "ref_md": ref_md, "ref_features": ref_fmt,
                            "md": [a["md"] for a in attempts], "ref_sig": list(ref_sig or ()),
                            "sig": [list(a["sig"]) for a in attempts], "match_format": want_fmt}
                return chosen["resp"], info

            if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                ref = None
                if self.exp_config.get("pi_length_match"):
                    # clean reference reply for the length match (not a step)
                    n_cap = len(llm_capture)
                    ref = _call(turn_idx, f"{where}_length_ref", *args, **kwargs)
                    ref_meta = llm_meta_by_call.get(turn_idx)
                    if len(llm_capture) > n_cap:
                        del llm_capture[n_cap]
                    meta["length_ref_llm_meta"] = ref_meta
                resp, info = _pi_call(ref)
                meta.update(info)
                meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
                if meta["injection_process"].get("sham"):
                    meta["sham"] = meta["injection_process"]["sham"]
            elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                n_cap = len(llm_capture)
                clean = _call(turn_idx, f"{where}_clean_for_corruption", *args, **kwargs)
                resp = self.fm_factory.corrupt_response(
                    clean, malicious_agent.fm_error_type, agent_context)
                meta["clean_response_before_corruption"] = clean
                meta["response_corrupted"] = (resp != clean)
                meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
                # rc_mode "inplace" found no answer to change in this reply (e.g. an
                # analysis that names no option): with rc_fallback "pi" the step is
                # redone as a prompt injection instead of appending a template.
                if (self.fm_factory.last_injection_meta.get("inplace_applicable") is False
                        and self.exp_config.get("rc_fallback", "append") == "pi"):
                    discarded_meta = llm_meta_by_call.get(turn_idx)
                    # the clean reply is the length reference; drop its capture
                    # first so the PI tries are the only captures of this turn
                    if len(llm_capture) > n_cap:
                        del llm_capture[n_cap]
                    resp, info = _pi_call(clean)
                    meta["discarded_llm_meta"] = discarded_meta
                    meta["rc_fallback_to_pi"] = True
                    meta["injection_strategy"] = InjectionStrategy.PROMPT_INJECTION.value
                    meta.update(info)
                    meta["discarded_clean_response"] = meta.pop("clean_response_before_corruption")
                    meta.pop("response_corrupted", None)
                    meta["injection_process"] = dict(self.fm_factory.last_injection_meta,
                                                     rc_fallback_to_pi=True)
            else:
                resp = _call(turn_idx, f"{where}_unknown_strategy", *args, **kwargs)
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
        # Tool entries (`is_tool`, e.g. MAM's web search) are not LLM calls:
        # exclude them from the call <-> history alignment.
        llm_history = [h for h in raw_history if not h.get("is_tool")]
        alignment_ok = (len(llm_history) == len(clean_messages_by_call) == len(llm_capture))
        for i, h in enumerate(llm_history):
            received = llm_capture[i].get("input_messages") if i < len(llm_capture) else None
            clean = clean_messages_by_call.get(i)
            h["input_messages"] = clean if clean is not None else received
            h["llm_meta"] = llm_meta_by_call.get(i)
            if i in injection_meta_by_call:
                meta = injection_meta_by_call[i]
                if meta.get("injection_strategy") == InjectionStrategy.PROMPT_INJECTION.value:
                    meta["injected_input_messages"] = received
                h.update(meta)
            if "agent_name" not in h and "role" in h:
                h["agent_name"] = h["role"]
        if not alignment_ok:
            print(f"[{type(self).__name__}] WARNING: history/capture misalignment "
                  f"({len(llm_history)} LLM history entries, {len(clean_messages_by_call)} calls, "
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
        # Shared task observations a method registered (ConSensus feature blocks,
        # MAM audio); steps reference them via `observations: [<id>]`.
        if getattr(self.mas, "task_observations", None):
            log["task_observations"] = list(self.mas.task_observations)
        log.update(self.extra_log(final_output))
        out = {"response": final_output.get("response", "")} if isinstance(final_output, dict) \
            else {"response": str(final_output)}
        return out, log
