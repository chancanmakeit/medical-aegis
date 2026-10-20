# file: aegis_core/agent_systems/fm_medagents_mc_wrapper.py
"""
FM-injection wrapper for MedAgents (multi-disciplinary collaboration), method
name `medagents_mc` (see methods/medagents_mc/medagents_mc_main.py).

All injection / clean-input / read-set logic lives in StructuredFMWrapper
(fm_structured_wrapper.py). Structural roles set by MedAgentsMC_Main._ask:
  QuestionClassifier(0), OptionClassifier(0), QuestionAnalyst(0..4),
  OptionAnalyst(0..1), Synthesizer(0), Voter(0..6), Advisor(0..6),
  Reviser(0), Decider(0)
Voter / Advisor / Reviser can be invoked once per consultation round; Advisor
and Reviser only when some voter says NO.
"""

from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMMedAgentsMCWrapper(StructuredFMWrapper):
    FRAMEWORK = "medagents_mc"
    CONFIG_NAME_KEY = "medagents_config_name"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        if exp_config.get("medagents_max_attempt_vote") is not None:
            self.mas.max_attempt_vote = int(exp_config["medagents_max_attempt_vote"])
        if exp_config.get("medagents_use_original_max_tokens") is not None:
            self.mas.use_original_max_tokens = bool(exp_config["medagents_use_original_max_tokens"])

    def build_sample(self, task: Any) -> Dict[str, Any]:
        sample = {"query": task.query}
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        if raw.get("mcq_options"):
            sample["mcq_question"] = raw.get("mcq_question")
            sample["mcq_options"] = raw["mcq_options"]
        return sample

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {"num_consultation_rounds": fo.get("num_consultation_rounds"),
                "vote_history": fo.get("vote_history")}
