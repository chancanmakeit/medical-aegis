"""
Malicious Factory Package

Contains the core error injection and manipulation system.
"""

from .fm_malicious_system import (
    FMMaliciousFactory,
    FMMaliciousAgent,
    AgentContext,
    FMErrorType,
    InjectionStrategy
)
from .factory import MaliciousAgentFactory
from .enhanced_factory import EnhancedMaliciousFactory

__all__ = [
    "FMMaliciousFactory",
    "FMMaliciousAgent",
    "AgentContext",
    "FMErrorType",
    "InjectionStrategy",
    "MaliciousAgentFactory",
    "EnhancedMaliciousFactory"
]