"""
Error Type to Feedback Mapping
将错误类型编号映射为给 agent 的自然语言反馈
"""

ERROR_TYPE_DESCRIPTIONS = {
    # Functional Mistakes - Task Execution Errors (FM-1.x)
    "FM-1.1": {
        "name": "Task specification deviation",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously deviated from the specified task requirements. Please ensure you:
- Carefully read and follow all task specifications
- Double-check that your approach aligns with the requirements
- If asked for a specific format or method, stick to it exactly
- Don't make assumptions about what the task wants beyond what's explicitly stated"""
    },

    "FM-1.2": {
        "name": "Role specification deviation",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously acted outside your designated role. Please ensure you:
- Stay within your assigned role and responsibilities
- Don't perform tasks that belong to other agents
- If you notice something that another role should handle, mention it but don't do it yourself
- Focus on your specific expertise and let other agents handle theirs"""
    },

    "FM-1.3": {
        "name": "Add redundant steps",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously added unnecessary or duplicate steps. Please ensure you:
- Check if a step has already been completed before doing it again
- Review the conversation history to avoid redundancy
- Keep your solution concise and avoid repetition
- Only add steps that bring new value to the solution"""
    },

    "FM-1.4": {
        "name": "Remove conversation history",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously ignored or removed important context from previous turns. Please ensure you:
- Carefully read the entire conversation history
- Take into account corrections, clarifications, or feedback from earlier messages
- Build upon previous work rather than starting from scratch
- Reference relevant information from the conversation when making decisions"""
    },

    "FM-1.5": {
        "name": "Remove termination conditions",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously failed to define proper stopping criteria. Please ensure you:
- Define clear termination conditions for any loops or recursive processes
- Include base cases for recursive functions
- Set appropriate limits to prevent infinite loops
- Make sure your solution can reach a definite conclusion"""
    },

    # Functional Mistakes - Communication & Coordination Errors (FM-2.x)
    "FM-2.1": {
        "name": "Repeat handled tasks",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously redundantly handled already completed tasks. Please ensure you:
- Check if a task has already been completed by another agent
- Read other agents' responses carefully to understand what's been done
- Don't re-do work that's already finished and approved
- If you think something needs improvement, suggest it rather than redoing it"""
    },

    "FM-2.2": {
        "name": "Make request ambiguous",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously provided unclear or confusing instructions to other agents. Please ensure you:
- Be specific and clear when communicating with other agents
- Provide all necessary details and context
- Use concrete examples when possible
- Avoid vague terms like "handle it" or "take care of this" - specify exactly what you mean"""
    },

    "FM-2.3": {
        "name": "Deviate from main goal",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously pursued objectives unrelated to the main task. Please ensure you:
- Stay focused on the primary goal
- Don't get sidetracked by tangential topics
- If something is interesting but not relevant, skip it
- Keep your contributions directly related to solving the given problem"""
    },

    "FM-2.4": {
        "name": "Hide important information",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously withheld crucial information needed by other agents. Please ensure you:
- Share all relevant information with the team
- If you discover important details, communicate them clearly
- Don't assume others already know what you know
- Be transparent about limitations, issues, or concerns you identify"""
    },

    "FM-2.5": {
        "name": "Ignore other agents",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously failed to consider input, corrections, or questions from other agents. Please ensure you:
- Read and acknowledge other agents' contributions
- Respond to questions or concerns raised by teammates
- Incorporate feedback and corrections from others
- Show that you've considered different perspectives before deciding"""
    },

    "FM-2.6": {
        "name": "Inconsistent reasoning",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
Your logic previously contradicted your own earlier statements. Please ensure you:
- Maintain logical consistency throughout your reasoning
- If you change your position, explicitly explain why based on new information
- Don't make contradictory claims without justification
- Review your previous statements before making new ones"""
    },

    # Functional Mistakes - Quality & Verification Errors (FM-3.x)
    "FM-3.1": {
        "name": "Premature termination",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously stopped or declared the task complete before all requirements were met. Please ensure you:
- Check all requirements before declaring completion
- Verify that every aspect of the task has been addressed
- Don't rush to finish - take time to ensure completeness
- Review the original task to confirm nothing is missing"""
    },

    "FM-3.2": {
        "name": "Remove verification steps",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously skipped necessary validation or testing steps. Please ensure you:
- Include verification steps to check your work
- Test your solution if applicable
- Validate that your answer makes sense
- Don't skip quality assurance steps to save time"""
    },

    "FM-3.3": {
        "name": "Incorrect verification",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously performed flawed or wrong verification. Please ensure you:
- Design verification steps that actually test what they're supposed to
- Make sure your validation logic is correct
- Test edge cases, not just the happy path
- Double-check that your verification approach is sound"""
    },

    # Additional Error Types for Mathematical/Reasoning Errors
    "FM-4.1": {
        "name": "Calculation error",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously made a mathematical calculation mistake. Please ensure you:
- Double-check all arithmetic operations
- Verify each step of your calculations
- Consider using a calculator or checking your work
- Pay attention to units and scales in the problem"""
    },

    "FM-4.2": {
        "name": "Logical reasoning error",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
Your reasoning was previously flawed. Please ensure you:
- Follow logical steps from premises to conclusions
- Avoid jumping to conclusions without proper justification
- Check that your reasoning is internally consistent
- Consider alternative interpretations before settling on one"""
    },

    "FM-4.3": {
        "name": "Misunderstanding the problem",
        "feedback": """⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You previously misinterpreted what the problem was asking for. Please ensure you:
- Read the entire problem statement carefully
- Identify exactly what is being asked
- Note all given information and constraints
- Don't make assumptions about what's included or excluded
- Pay attention to details like whether to count all entities or just a subset"""
    },
}


def get_error_feedback(error_type: str) -> str:
    """
    Get natural language feedback for a given error type.

    Args:
        error_type: Error type code (e.g., "FM-1.1")

    Returns:
        Natural language feedback string
    """
    error_info = ERROR_TYPE_DESCRIPTIONS.get(error_type)
    if error_info:
        return error_info["feedback"]
    else:
        # 默认反馈
        return f"""⚠️ FEEDBACK FROM PREVIOUS ATTEMPT:
You made an error (type: {error_type}) in the previous attempt. Please be more careful and:
- Review your work thoroughly
- Follow best practices
- Collaborate effectively with other agents
- Ensure quality and correctness"""


def get_error_name(error_type: str) -> str:
    """
    Get the short name for an error type.

    Args:
        error_type: Error type code (e.g., "FM-1.1")

    Returns:
        Short name string
    """
    error_info = ERROR_TYPE_DESCRIPTIONS.get(error_type)
    if error_info:
        return error_info["name"]
    else:
        return f"Unknown error type: {error_type}"


def list_all_error_types():
    """List all available error types."""
    print("Available Error Types:")
    print("=" * 80)
    for error_type, info in sorted(ERROR_TYPE_DESCRIPTIONS.items()):
        print(f"\n{error_type}: {info['name']}")
        print("-" * 80)


if __name__ == "__main__":
    # 测试
    list_all_error_types()
    print("\n\nExample feedback for FM-1.1:")
    print(get_error_feedback("FM-1.1"))
