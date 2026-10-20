"""
AEGIS Core Package

This package contains the core functionality for the AEGIS framework,
including error injection, MAS wrappers, and utilities.
"""

__version__ = "0.1.0"

from .malicious_factory import (
    FMMaliciousFactory,
    FMMaliciousAgent,
    AgentContext,
    FMErrorType,
    InjectionStrategy
)
from .agent_systems import get_mas_wrapper, BaseMASWrapper
from .utils import load_model_api_config, write_to_jsonl, reserve_unprocessed_queries

__all__ = [
    "FMMaliciousFactory",
    "FMMaliciousAgent",
    "AgentContext",
    "FMErrorType",
    "InjectionStrategy",
    "get_mas_wrapper",
    "BaseMASWrapper",
    "load_model_api_config",
    "write_to_jsonl",
    "reserve_unprocessed_queries"
]