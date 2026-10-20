# file: aegis_core/agent_systems/fm_cmas_structured_wrapper.py
"""
FM-injection wrapper for CMAS (method `cmas`, zero-shot NER) on the
structured contract (StructuredFMWrapper): clean `input_messages`, read sets,
stable agent ids, `llm_meta`, inject-once.

Replaces fm_cmas_wrapper.py (kept only to reproduce old data). Structural
roles unchanged: TRFExtractor(0), Discriminator(0), OverallPredictor(0). The
retrieved demonstrations are a task observation ("demonstrations").
task_type "ner" still falls back to the MCQ templates in the factory (user
decision: not handled for now).

YAML overrides kept: cmas_config_name, cmas_use_trf_extractor,
cmas_use_discriminator, cmas_few_shot_number, cmas_demo_pool_path,
cmas_demo_retrieval_mode.
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMCMASStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "cmas"
    CONFIG_NAME_KEY = "cmas_config_name"
    DEFAULT_CONFIG_NAME = "config_ner"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        for key, attr, cast in (("cmas_use_trf_extractor", "use_trf_extractor", bool),
                                ("cmas_use_discriminator", "use_discriminator", bool),
                                ("cmas_few_shot_number", "few_shot_number", int),
                                ("cmas_demo_pool_path", "demo_pool_path", str),
                                ("cmas_demo_retrieval_mode", "demo_retrieval_mode", str)):
            if exp_config.get(key) is not None:
                setattr(self.mas, attr, cast(exp_config[key]))
        if exp_config.get("cmas_demo_pool_path") is not None:
            self.mas._demo_pool = None      # reload from the new path

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {"trfs": fo.get("trfs"), "helpfulness": fo.get("helpfulness")}
