# file: aegis_core/agent_systems/fm_consensus_wrapper.py
"""
FM-injection wrapper for ConSensus (method `consensus`) and the multi-agent
baselines shipped in the same upstream repo (see methods/consensus_baselines).

Structural roles (ConSensus_Main):
  ModalityAgent(i)  i = position of the modality in info.json (agent_label = modality)
  SemanticFusion(0), StatisticalFusion(0), HybridFusion(0)
A JSON-retry turn reuses the agent's (role, role_index); with the default
first-invocation-only policy an injection never fires on the retry.

Agents answer in {"REASON","ANSWER"} JSON, so YAMLs use task_type
"classification": prompt injection uses label-oriented instructions and
response corruption rewrites the JSON with a different class (the class list
is handed to the factory per sample in before_run).
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMConSensusWrapper(StructuredFMWrapper):
    FRAMEWORK = "consensus"
    CONFIG_NAME_KEY = "consensus_config_name"
    DEFAULT_CONFIG_NAME = "config_sensing"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        # Same wrapper serves consensus and consensus_{debate,mad,reconcile,cmd};
        # log under the actual method name.
        self.FRAMEWORK = exp_config["system_under_test"]["name"]

    def build_sample(self, task: Any) -> Dict[str, Any]:
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        if "consensus" not in raw:
            raise ValueError("ConSensus sample is missing the 'consensus' field "
                             "(convert with data_processing/sensing/convert_consensus_datasets.py)")
        return {"query": task.query, "consensus": raw["consensus"]}

    def before_run(self, task: Any, sample: Dict[str, Any]) -> None:
        self.fm_factory.classification_labels = list(sample["consensus"]["info"]["class"].keys())

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {k: fo.get(k) for k in ("stage_answers", "modality_answers", "aborted_at")}
