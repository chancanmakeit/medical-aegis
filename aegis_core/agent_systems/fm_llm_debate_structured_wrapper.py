# file: aegis_core/agent_systems/fm_llm_debate_structured_wrapper.py
"""
FM-injection wrapper for LLM-Debate (method `llm_debate`) on the structured
contract (StructuredFMWrapper): clean `input_messages`, cumulative read sets,
stable agent ids, `llm_meta`, and inject-once by default (scheme A; the legacy
fm_debate_wrapper.py injected EVERY matching call and is kept only to
reproduce old data). Set `inject_every_invocation: true` for scheme B.

Roles unchanged: Agent(0..N-1) [phase "discussion", round 1..R; a target may
pin `round`], Aggregator(0) [phase "aggregation"].
"""
from .fm_structured_wrapper import StructuredFMWrapper


class FMLLMDebateStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "llm_debate"
    CONFIG_NAME_KEY = "llm_debate_config_name"
    DEFAULT_CONFIG_NAME = "config_medical"   # same values as config_main (3 agents, 2 rounds)
