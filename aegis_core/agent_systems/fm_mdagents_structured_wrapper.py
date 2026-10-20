# file: aegis_core/agent_systems/fm_mdagents_structured_wrapper.py
"""
FM-injection wrapper for MDAgents (method `mdagents`) on the structured
contract (StructuredFMWrapper): clean `input_messages`, read sets, stable
agent ids, `llm_meta`, inject-once by default (scheme A).

Replaces fm_mdagents_wrapper.py (kept only to reproduce old data, whose
recorded inputs contain the injected text; MedHyperTrace issue #1 problem A).
Structural roles are unchanged: Recruiter(0), Expert(0..N-1), Aggregator(0);
adaptive mode adds Classifier(0); basic MedicalExpert(0); advanced
MDTMember(0..5) / TeamLead(0..1) / Aggregator(0).

YAML overrides kept from the legacy wrapper: mdagents_config_name,
mdagents_difficulty, mdagents_num_experts, mdagents_debate_rounds;
new: mdagents_text_model_name (text backbone for Recruiter / Classifier).
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMMDAgentsStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "mdagents"
    CONFIG_NAME_KEY = "mdagents_config_name"
    DEFAULT_CONFIG_NAME = "config_medical"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        if exp_config.get("mdagents_difficulty") is not None:
            self.mas.difficulty = exp_config["mdagents_difficulty"]
        if exp_config.get("mdagents_num_experts") is not None:
            self.mas.num_experts = int(exp_config["mdagents_num_experts"])
        if exp_config.get("mdagents_debate_rounds") is not None:
            self.mas.debate_rounds = int(exp_config["mdagents_debate_rounds"])
        if exp_config.get("mdagents_text_model_name") is not None:
            self.mas.text_model_name = exp_config["mdagents_text_model_name"]

    def build_sample(self, task: Any) -> Dict[str, Any]:
        # The method forwards these to every expert / aggregator call
        # (explicit images= wins over the wrapper's auto-attach layer).
        sample = {"query": task.query}
        if getattr(task, "image_paths", None):
            sample["image_paths"] = list(task.image_paths)
        return sample

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {"difficulty": fo.get("difficulty", getattr(self.mas, "difficulty", None))}
