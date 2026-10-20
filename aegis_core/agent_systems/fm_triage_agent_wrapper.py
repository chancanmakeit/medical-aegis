# file: aegis_core/agent_systems/fm_triage_agent_wrapper.py
"""
FM-injection wrapper for TriageAgent (method `triage_agent`,
methods/triage_agent/triage_agent_main.py).

Structural roles: Doctor(0) = Doctor A, Doctor(1) = Doctor B, Doctor(2) =
Doctor C [phases "classify" and "discuss" (round k)], Summarizer(0) [phase
"summarize"], Coordinator(0) [phase "consensus"]. Targets may pin `phase` and
`round` (e.g. Doctor 2, phase discuss, round 1).

Agents answer in a labeled-field format, so YAMLs use task_type
"classification_field": response corruption rewrites the field value (next
label, cyclic) and the prompt-injection instructions use domain-neutral
wording. The field and labels depend on the agent hit:
  Doctor A classify -> "Coarse class" in {HIGH, LOW}
  Summarizer        -> "Suggested ESI level" in {1..5}
  everyone else     -> "ESI level" in {1..5}
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper

_ESI = ["1", "2", "3", "4", "5"]


class FMTriageAgentWrapper(StructuredFMWrapper):
    FRAMEWORK = "triage_agent"
    CONFIG_NAME_KEY = "triage_config_name"
    DEFAULT_CONFIG_NAME = "config_triage"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        for key, attr in (("triage_max_discuss_rounds", "max_discuss_rounds"),
                          ("triage_high_conf_threshold", "high_conf_threshold"),
                          ("triage_use_original_max_tokens", "use_original_max_tokens")):
            if exp_config.get(key) is not None:
                setattr(self.mas, attr, exp_config[key])

    def build_sample(self, task: Any) -> Dict[str, Any]:
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        tri = raw.get("triage") or {}
        if not tri.get("vignette") or "hits" not in (tri.get("retrieval") or {}):
            raise ValueError("triage sample lacks triage.vignette / triage.retrieval.hits "
                             "(build it with data_processing/triage/convert_triage_dataset.py)")
        return {"query": task.query, "vignette": tri["vignette"],
                "retrieval_hits": tri["retrieval"]["hits"]}

    def before_injection(self, role, role_index, phase, round_) -> None:
        f = self.fm_factory
        if role == "Doctor" and role_index == 0 and phase == "classify":
            f.classification_labels = ["HIGH", "LOW"]
            f.classification_field_label = "Coarse class"
            f.classification_field_regex = r"(Coarse\s*class\s*:\s*)(HIGH|LOW)"
        elif role == "Summarizer":
            f.classification_labels = list(_ESI)
            f.classification_field_label = "Suggested ESI level"
            f.classification_field_regex = r"(Suggested\s*ESI\s*level\s*:\s*)([1-5])"
        else:
            f.classification_labels = list(_ESI)
            f.classification_field_label = "ESI level"
            f.classification_field_regex = r"(ESI\s*level\s*:\s*)([1-5])"

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {k: fo.get(k) for k in ("final_source", "final_level", "final_confidence",
                                        "discussion", "retrieval")}
