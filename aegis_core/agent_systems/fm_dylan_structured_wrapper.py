# file: aegis_core/agent_systems/fm_dylan_structured_wrapper.py
"""
FM-injection wrapper for DyLAN (method `dylan`) on the structured contract
(StructuredFMWrapper): clean `input_messages`, read sets, stable agent ids,
`llm_meta`, inject-once by default (scheme A; the legacy fm_dylan_wrapper.py
is kept only to reproduce old data). `inject_every_invocation: true` = scheme B.

Roles unchanged from the legacy wrapper: the node role name (e.g. Physician,
Pharmacologist) with role_index = node_idx % num_agents [phase "answer",
round k; a target may pin `round`], and Ranker(num_agents) [phase "ranking"].
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMDyLANStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "dylan"
    CONFIG_NAME_KEY = "dylan_config_name"
    DEFAULT_CONFIG_NAME = "config_medical"

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {"final_source_step_ids": fo.get("final_source_step_ids") or []}
