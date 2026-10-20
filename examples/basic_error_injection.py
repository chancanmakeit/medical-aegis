#!/usr/bin/env python3
"""
Basic Error Injection Example

This script demonstrates how to use AEGIS to inject errors into a multi-agent system
and generate labeled failure trajectories for training error attribution models.

Usage:
    python examples/basic_error_injection.py

Note: This example requires proper API configuration. Please set up your
model_api_configs/model_api_config.json before running.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import asyncio
from pathlib import Path

from aegis_core.malicious_factory import (
    FMMaliciousFactory,
    FMErrorType,
    InjectionStrategy,
    AgentContext
)


def demonstrate_fm_error_types():
    """Demonstrate all available FM error types."""
    print("=" * 60)
    print("AEGIS FM Error Types")
    print("=" * 60)

    error_types = [
        ("FM-1.1", "Task specification deviation"),
        ("FM-1.2", "Role specification deviation"),
        ("FM-1.3", "Add redundant steps"),
        ("FM-1.4", "Remove conversation history"),
        ("FM-1.5", "Remove termination conditions"),
        ("FM-2.1", "Repeat handled tasks"),
        ("FM-2.2", "Make request ambiguous"),
        ("FM-2.3", "Deviate from main goal"),
        ("FM-2.4", "Hide important information"),
        ("FM-2.5", "Ignore other agents"),
        ("FM-2.6", "Inconsistent reasoning"),
        ("FM-3.1", "Premature termination"),
        ("FM-3.2", "Remove verification steps"),
        ("FM-3.3", "Incorrect verification"),
    ]

    for code, description in error_types:
        print(f"  {code}: {description}")

    print("\nInjection Strategies:")
    print("  - prompt_injection: Modify input prompts before processing")
    print("  - response_corruption: Corrupt output responses after processing")
    print("=" * 60)


def demonstrate_injection_instruction_generation():
    """Demonstrate how injection instructions are generated."""
    print("\n" + "=" * 60)
    print("Injection Instruction Generation Demo")
    print("=" * 60)

    # Create factory without LLM (for instruction generation only)
    factory = FMMaliciousFactory(llm=None)

    # Create sample agent context
    agent_context = AgentContext(
        role_name="MathSolver",
        role_type="Specialist Agent",
        agent_id="agent_001",
        system_message="You are a math problem solver that helps users solve complex equations.",
        tools=["calculator", "symbolic_solver"],
        external_tools=[],
        description="A specialized agent for solving mathematical problems",
        model_type="gpt-4"
    )

    # Sample task
    task_context = "Solve the equation: 2x + 5 = 17. What is the value of x?"

    print(f"\nAgent: {agent_context.role_name} ({agent_context.role_type})")
    print(f"Task: {task_context}")

    # Generate injection instructions for different error types
    test_cases = [
        (FMErrorType.FM_1_1, InjectionStrategy.PROMPT_INJECTION),
        (FMErrorType.FM_2_3, InjectionStrategy.PROMPT_INJECTION),
        (FMErrorType.FM_3_2, InjectionStrategy.RESPONSE_CORRUPTION),
    ]

    for fm_type, strategy in test_cases:
        print(f"\n--- {fm_type.value} via {strategy.value} ---")
        instruction = factory.get_injection_instruction(
            fm_type,
            agent_context,
            strategy,
            task_context
        )
        # Print first 300 characters of instruction
        print(instruction[:300] + "..." if len(instruction) > 300 else instruction)


async def demonstrate_malicious_agent_creation():
    """Demonstrate creating malicious agents."""
    print("\n" + "=" * 60)
    print("Malicious Agent Creation Demo")
    print("=" * 60)

    # Create factory without LLM
    factory = FMMaliciousFactory(llm=None)

    # Create malicious agents for different scenarios
    scenarios = [
        {
            "task_query": "Calculate the area of a triangle with base 10 and height 5",
            "target_role": "Calculator",
            "target_index": 0,
            "fm_type": "FM-1.1",
            "strategy": "prompt_injection"
        },
        {
            "task_query": "Review this code for bugs",
            "target_role": "CodeReviewer",
            "target_index": 1,
            "fm_type": "FM-2.5",
            "strategy": "response_corruption"
        },
    ]

    for scenario in scenarios:
        agent = await factory.create_agent(
            task_query=scenario["task_query"],
            target_agent_role=scenario["target_role"],
            target_agent_index=scenario["target_index"],
            fm_error_type=scenario["fm_type"],
            injection_strategy=scenario["strategy"]
        )

        print(f"\nCreated Malicious Agent:")
        print(f"  Target Role: {agent.target_agent_role}")
        print(f"  Target Index: {agent.target_agent_index}")
        print(f"  FM Error Type: {agent.fm_error_type.value}")
        print(f"  Strategy: {agent.injection_strategy.value}")
        print(f"  Description: {agent.description}")


def demonstrate_all_injection_methods():
    """List all 28 possible injection methods."""
    print("\n" + "=" * 60)
    print("All Available Injection Methods (28 combinations)")
    print("=" * 60)

    factory = FMMaliciousFactory(llm=None)
    methods = factory.get_all_injection_methods()

    for i, method in enumerate(methods, 1):
        print(f"{i:2d}. {method['method_id']}")
        print(f"    {method['description']}")


def main():
    """Main entry point."""
    print("AEGIS - Agent Error Generation and Injection System")
    print("Basic Usage Example")
    print()

    # 1. Show all FM error types
    demonstrate_fm_error_types()

    # 2. Demonstrate injection instruction generation
    demonstrate_injection_instruction_generation()

    # 3. Demonstrate malicious agent creation
    asyncio.run(demonstrate_malicious_agent_creation())

    # 4. List all injection methods
    demonstrate_all_injection_methods()

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print("\nFor full experiments, please use main.py with proper configuration:")
    print("  python main.py --experiment_config configs/your_config.yaml")
    print("\nFor Magnetic-One experiments:")
    print("  python magnetic_one/gaia.py --inject --target-agent WebSurfer --fm-type FM-2.3")


if __name__ == "__main__":
    main()
