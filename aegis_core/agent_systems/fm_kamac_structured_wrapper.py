# file: aegis_core/agent_systems/fm_kamac_structured_wrapper.py
"""
FM-injection wrapper for KAMAC (method `kamac`, methods/kamac/kamac_main.py)
on the structured contract (StructuredFMWrapper): clean `input_messages`,
exact read sets, stable agent ids, `llm_meta`, inject-once by default.

Structural roles (targets match role, role_index and optionally phase/round):
  Recruiter(0)  phases recruitment, gap_recruitment
  Expert(i)     initial panel, i = 0..num_agents-1
  Recruit(k)    k-th recruited expert (by recruitment order); a target on a
                recruit that never appears in a run does not fire (not_fired)
  Assistant(0)  gap_summary;  Moderator(0)  decision
  Expert / Recruit phases: initial_assessment, participate, choose_recipients,
  message, knowledge_gap, reanswer; `round` = debate turn (1-based).
Every agent call sends the agent's whole chat history; a prompt injection
rewrites only the newest user message.

YAML overrides: kamac_config_name, kamac_num_agents, kamac_num_turns,
kamac_num_rounds, kamac_auto_recruit, kamac_max_recruits,
kamac_max_turn_extensions, kamac_gap_prompt, kamac_message_delivery.
"""
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper

_OVERRIDES = (("kamac_num_agents", "num_agents", int), ("kamac_num_turns", "num_turns", int),
              ("kamac_num_rounds", "num_rounds", int), ("kamac_auto_recruit", "auto_recruit", bool),
              ("kamac_max_recruits", "max_recruits", int),
              ("kamac_max_turn_extensions", "max_turn_extensions", int),
              ("kamac_gap_prompt", "gap_prompt", str),
              ("kamac_message_delivery", "message_delivery", str))


class FMKAMACStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "kamac"
    CONFIG_NAME_KEY = "kamac_config_name"
    DEFAULT_CONFIG_NAME = "config_kamac"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        for key, attr, cast in _OVERRIDES:
            if exp_config.get(key) is not None:
                setattr(self.mas, attr, cast(exp_config[key]))

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {"kamac": fo.get("kamac")}
