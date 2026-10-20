# file: aegis_core/agent_systems/fm_agentverse_structured_wrapper.py
"""
FM-injection wrapper for AgentVerse (method `agentverse`) on the structured
contract (StructuredFMWrapper): clean `input_messages`, exact read sets,
stable agent ids, `llm_meta`, inject-once by default (scheme A; the legacy
fm_agentverse_wrapper.py guessed roles from prompt keywords and is kept only
to reproduce old data). `inject_every_invocation: true` = scheme B.

Roles (set at each call site): RoleAssigner(0), Solver(0) [phases solve /
revise], Critic(0..cnt_agents-2), Evaluator(0); `round` = outer turn.
"""
from .fm_structured_wrapper import StructuredFMWrapper


class FMAgentVerseStructuredWrapper(StructuredFMWrapper):
    FRAMEWORK = "agentverse"
    CONFIG_NAME_KEY = "agentverse_config_name"
    DEFAULT_CONFIG_NAME = "config_medical"
