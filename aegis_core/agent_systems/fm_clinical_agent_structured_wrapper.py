# file: aegis_core/agent_systems/fm_clinical_agent_structured_wrapper.py
"""
FM-injection wrapper for ClinicalAgent (method `clinical_agent`, the paper's
5-agent version) on the structured contract (StructuredFMWrapper): clean
`input_messages`, read sets, stable agent ids, `llm_meta`, inject-once.

Replaces fm_clinical_agent_wrapper.py (kept only to reproduce old data).
Structural roles unchanged: Planner(0), SafetyAgent(0), EfficacyAgent(0),
EnrollmentAgent(0), Reasoner(0) (+ ToolSynth(0) with tools_mode: llm_synth).
Placeholder tools are `is_tool` steps (agent_id tool:<name>, stub: true) that
the lane agents read. YAMLs use task_type "probability".

YAML overrides kept: clinical_agent_config_name, ca_use_planner,
ca_planner_subproblems, ca_tools_mode.
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMClinicalAgentStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "clinical_agent"
    CONFIG_NAME_KEY = "clinical_agent_config_name"
    DEFAULT_CONFIG_NAME = "config_medical"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        if exp_config.get("ca_use_planner") is not None:
            self.mas.use_planner = bool(exp_config["ca_use_planner"])
        if exp_config.get("ca_planner_subproblems") is not None:
            self.mas.planner_subproblems = int(exp_config["ca_planner_subproblems"])
        if exp_config.get("ca_tools_mode") is not None:
            self.mas.tools_mode = str(exp_config["ca_tools_mode"])

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {"use_planner": getattr(self.mas, "use_planner", None),
                "tools_mode": getattr(self.mas, "tools_mode", None),
                "predicted_probability": fo.get("prob"),
                "lane_scores": fo.get("lane_scores")}
