"""
Agent Systems Package

Provides wrappers for different Multi-Agent System frameworks.
"""

from .base_wrapper import SystemWrapper
from .fm_dylan_wrapper import FMDyLANWrapper
from .fm_agentverse_wrapper import FMAgentVerseWrapper
from .fm_debate_wrapper import FM_Debate_Wrapper
from .fm_macnet_wrapper import FMMacNetWrapper

# Aliases for backward compatibility
BaseMASWrapper = SystemWrapper
DylanMASWrapper = FMDyLANWrapper
AgentVerseMASWrapper = FMAgentVerseWrapper
DebateMASWrapper = FM_Debate_Wrapper
FMDebateWrapper = FM_Debate_Wrapper
MacNetMASWrapper = FMMacNetWrapper

# Registry of available MAS frameworks
MAS_REGISTRY = {
    "dylan": FMDyLANWrapper,
    "agentverse": FMAgentVerseWrapper,
    "llm_debate": FM_Debate_Wrapper,
    "macnet": FMMacNetWrapper,
}

def get_mas_wrapper(framework_name: str, config: dict):
    """
    Factory function to get the appropriate MAS wrapper.

    Args:
        framework_name: Name of the MAS framework
        config: Configuration dictionary

    Returns:
        Initialized MAS wrapper instance

    Raises:
        ValueError: If framework_name is not supported
    """
    if framework_name not in MAS_REGISTRY:
        available = list(MAS_REGISTRY.keys())
        raise ValueError(f"Unsupported MAS framework: {framework_name}. Available: {available}")

    wrapper_class = MAS_REGISTRY[framework_name]
    return wrapper_class(config=config)

__all__ = [
    "BaseMASWrapper",
    "SystemWrapper",
    "FMDyLANWrapper",
    "FMAgentVerseWrapper",
    "FM_Debate_Wrapper",
    "FMDebateWrapper",
    "FMMacNetWrapper",
    "DylanMASWrapper",
    "AgentVerseMASWrapper",
    "DebateMASWrapper",
    "MacNetMASWrapper",
    "get_mas_wrapper",
    "MAS_REGISTRY"
]