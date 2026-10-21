# file: aegis_core/agent_systems/fm_mac_structured_wrapper.py
"""
FM-injection wrapper for MAC (method `mac_groupchat`,
methods/mac_groupchat/mac_groupchat_main.py) on the structured contract
(StructuredFMWrapper): clean `input_messages`, exact read sets, stable agent
ids, `llm_meta`, inject-once by default.

Structural roles (set by MAC_Main before every call):
  Selector(0)   phase "select_speaker"   (one step per selection attempt)
  Doctor(0..N-1) phase "discussion"
  Supervisor(0) phase "supervision"
  Consultant(0) phase "specialist_recruit" (use_specialist only)
`round` = speaker turn (1..n_round-1). Who speaks when is decided by the
selector, so a Doctor / Supervisor target fires only if that agent is
selected at least once (the log records `fired`).

Two MAC-specific injection details:
  * Prompt injection appends to the LAST message of the call when it is a
    user or system message (the selector's last message is the system-role
    selection prompt), and otherwise appends a new user message carrying the
    injection block (e.g. a repeat speaker, whose last message is its own
    assistant turn). The base wrapper would rewrite the last USER message,
    i.e. some other agent's utterance in the middle of the context.
  * Response corruption of a Supervisor step with rc_mode "inplace" changes the
    letter in the summary JSON ("Most Likely Answer"), which is what the final
    answer and structured.answer are read from, plus every commitment to the
    same letter in the free text; the factory's generic in-place corruption
    only knows free-text commitments. A Supervisor reply without a JSON letter
    goes through the factory as usual (incl. rc_fallback).

YAML overrides: mac_config_name, mac_num_doctors, mac_n_round (or the generic
max_rounds), mac_use_specialist, mac_supervisor_prompt_bug,
mac_select_speaker_role, mac_speaker_name_in_content,
mac_max_retries_for_selecting_speaker.
"""
import re
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMMACStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "mac_groupchat"
    CONFIG_NAME_KEY = "mac_config_name"
    DEFAULT_CONFIG_NAME = "config_mac"

    def __init__(self, general_config: Dict[str, Any], method_config: Dict[str, Any]):
        super().__init__(general_config, method_config)
        orig = self.fm_factory.corrupt_response

        def corrupt_response(response, fm_error_type, agent_context, task_context=""):
            if getattr(self.mas, "current_role", None) == "Supervisor":
                out = self._corrupt_supervisor_json(response, fm_error_type)
                if out is not None:
                    return out
            return orig(response, fm_error_type, agent_context, task_context)
        self.fm_factory.corrupt_response = corrupt_response

    def configure(self, exp_config: Dict[str, Any]) -> None:
        m = self.mas
        if exp_config.get("max_rounds") is not None:
            m.n_round = int(exp_config["max_rounds"])
        for key, attr, typ in (("mac_num_doctors", "num_doctors", int),
                               ("mac_n_round", "n_round", int),
                               ("mac_use_specialist", "use_specialist", bool),
                               ("mac_supervisor_prompt_bug", "supervisor_prompt_bug", str),
                               ("mac_select_speaker_role", "select_speaker_role", str),
                               ("mac_speaker_name_in_content", "speaker_name_in_content", bool),
                               ("mac_max_retries_for_selecting_speaker",
                                "max_retries_for_selecting_speaker", int)):
            if exp_config.get(key) is not None:
                setattr(m, attr, typ(exp_config[key]))

    def build_sample(self, task: Any) -> Dict[str, Any]:
        sample = {"query": task.query}
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        if raw.get("mcq_options"):
            sample["mcq_question"] = raw.get("mcq_question")
            sample["mcq_options"] = raw["mcq_options"]
        return sample

    # ---- injection details -------------------------------------------- #
    def _inject_into_call(self, args, kwargs, modified_text_fn):
        if kwargs.get("messages") is None and len(args) >= 3 and args[2] is not None:
            kwargs = dict(kwargs, messages=args[2])
            args = tuple(args[3:])
        msgs = kwargs.get("messages")
        if msgs is None:
            return super()._inject_into_call(args, kwargs, modified_text_fn)
        msgs = [dict(m) for m in msgs]
        new_kwargs = dict(kwargs)
        if msgs and msgs[-1].get("role") in ("user", "system"):
            original = msgs[-1].get("content") or ""
            modified = modified_text_fn(original)
            msgs[-1]["content"] = modified
        else:
            original = ""
            modified = modified_text_fn("").lstrip()
            msgs.append({"role": "user", "content": modified})
        new_kwargs["messages"] = msgs
        return args, new_kwargs, original, modified

    def _corrupt_supervisor_json(self, response, fm_error_type):
        f = self.fm_factory
        if not (f.injection_method == "direct_prepend" and f.rc_mode == "inplace"
                and f.task_type == "mcq"):
            return None
        from methods.mac_groupchat.mac_groupchat_main import SUMMARY_KEY, letter_from_value
        from methods.answer_parsing import _COMMIT
        opts = getattr(self.mas, "options", None) or f._task_options()
        text = response or ""
        rx = re.compile(r'("' + SUMMARY_KEY + r'"\s*:\s*")([^"]*)(")')
        hits = list(rx.finditer(text))
        clean = letter_from_value(hits[-1].group(2), opts) if hits else None
        if clean is None:
            return None
        letters = sorted(opts) or list("ABCD")
        pool = f._not_gold([l for l in letters if l != clean] or letters)
        f.last_injection_meta = {
            "kind": "response_corruption",
            "fm_error_type": getattr(fm_error_type, "value", str(fm_error_type)),
            "injection_method": f.injection_method, "task_type": f.task_type,
        }
        wrong = f._draw_wrong_letter(pool, fm_error_type, text)
        n_sites = 0

        def _json(m):
            nonlocal n_sites
            if letter_from_value(m.group(2), opts) != clean:
                return m.group(0)
            n_sites += 1
            v = re.sub(r"(?<![A-Za-z])" + clean + r"(?![A-Za-z])", wrong, m.group(2), count=1)
            if opts.get(clean) and opts.get(wrong):
                v = v.replace(opts[clean], opts[wrong])
            return m.group(1) + v + m.group(3)
        out = rx.sub(_json, text)

        def _commit(m):
            nonlocal n_sites
            if m.group(1).upper() != clean:
                return m.group(0)
            n_sites += 1
            a, b = m.span(1)
            g = m.group(0)
            return g[:a - m.start()] + wrong + g[b - m.start():]
        out = _COMMIT.sub(_commit, out)
        f.last_injection_meta.update(
            rc_mode="inplace", clean_answer=clean, endorsed_option=clean,
            inplace_applicable=True, corrupted_answer=wrong, option_letters="".join(letters),
            inplace_sites=n_sites, inplace_site_kind="supervisor_json",
            corruption_template=None, template_table=None)
        return out

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        m = self.mas
        return {
            "final_source": fo.get("final_source"),
            "final_source_step_ids": fo.get("final_source_step_ids") or [],
            "terminated_by": fo.get("terminated_by"),
            "speaker_order": fo.get("speaker_order"),
            "num_speaker_turns": fo.get("num_speaker_turns"),
            "mac_agent_names": fo.get("agent_names"),
            "mac_settings": {
                "num_doctors": m.num_doctors, "n_round": m.n_round,
                "max_attempts_per_selection": m._max_attempts(),
                "use_specialist": m.use_specialist,
                "supervisor_prompt_bug": m.supervisor_prompt_bug,
                "select_speaker_role": m.select_speaker_role,
                "speaker_name_in_content": m.speaker_name_in_content,
            },
        }
