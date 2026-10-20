"""
Enhanced LLM Debate with Error Attribution Feedback Support
支持错误归因反馈的增强版LLM Debate
"""

import os
from ..mas_base import MAS

class LLM_Debate_Enhanced(MAS):
    """
    Enhanced version of LLM Debate that supports error feedback injection.
    This class allows providing specific error feedback to agents that made mistakes
    in a previous attempt, enabling them to improve in the retry.
    """
    
    def __init__(self, general_config, method_config_name=None):
        method_config_name = "config_main" if method_config_name is None else method_config_name
        super().__init__(general_config, method_config_name)

        self.agents_num = self.method_config["agents_num"]
        self.rounds_num = self.method_config["rounds_num"]
        
        # Store error feedback for each agent
        self.agent_error_feedback = {}  # {agent_index: feedback_text}
    
    def set_agent_error_feedback(self, agent_name: str, feedback: str):
        """
        Set error feedback for a specific agent.
        
        Args:
            agent_name: Name of the agent (e.g., "Assistant 1", "Assistant 2")
            feedback: Error feedback text to inject into the agent's prompt
        """
        # Extract agent index from name (e.g., "Assistant 1" -> 0)
        try:
            if "Assistant" in agent_name or "assistant" in agent_name:
                agent_index = int(agent_name.split()[-1]) - 1
                self.agent_error_feedback[agent_index] = feedback
                print(f"✓ Set error feedback for agent {agent_index}: {agent_name}")
            else:
                print(f"⚠️ Warning: Could not parse agent name '{agent_name}'")
        except (ValueError, IndexError) as e:
            print(f"⚠️ Warning: Could not extract agent index from '{agent_name}': {e}")
    
    def clear_error_feedback(self):
        """Clear all error feedback."""
        self.agent_error_feedback = {}
    
    def inference(self, sample):
        """
        Run inference with optional error feedback injection.
        
        Args:
            sample: The input sample with 'query' field
            
        Returns:
            Dict with 'response' field containing the final answer
        """
        query = sample["query"]

        # Initialize agent contexts with error feedback if available
        agent_contexts = []
        for agent_idx in range(self.agents_num):
            # Build initial prompt
            initial_prompt = f"{query} Make sure to state your answer at the end of the response."
            
            # Add error feedback if available for this agent
            if agent_idx in self.agent_error_feedback:
                feedback = self.agent_error_feedback[agent_idx]
                initial_prompt = f"{feedback}\n\n{initial_prompt}"
                print(f"→ Injected error feedback for Agent {agent_idx + 1}")
            
            agent_contexts.append([{"role": "user", "content": initial_prompt}])

        # Run the debate rounds
        for round in range(self.rounds_num):
            for i, agent_context in enumerate(agent_contexts):
                if round != 0:
                    agent_contexts_other = agent_contexts[:i] + agent_contexts[i+1:]
                    message = self.construct_message(agent_contexts_other, query, 2*round - 1)
                    agent_context.append(message)

                response = self.call_llm(messages=agent_context)
                agent_context.append({"role": "assistant", "content": response})
        
        answers = [agent_context[-1]['content'] for agent_context in agent_contexts]
        
        final_answer = self.aggregate(query, answers)
        self.agent_contexts = agent_contexts  # Save full conversation history
        return {"response": final_answer}
    
    def construct_message(self, agents, question, idx):
        """Construct message for agents to see each other's responses."""
        # Use introspection in the case in which there are no other agents.
        if len(agents) == 0:
            return {"role": "user", "content": "Can you verify that your answer is correct. Please reiterate your answer, making sure to state your answer at the end of the response."}

        prefix_string = "These are the recent/updated opinions from other agents: "

        for agent in agents:
            agent_response = agent[idx]["content"]
            response = "\n\n One agent response: ```{}```".format(agent_response)

            prefix_string = prefix_string + response

        prefix_string = prefix_string + "\n\n Use these opinions carefully as additional advice, can you provide an updated answer? Make sure to state your answer at the end of the response. \n The original problem is {}.".format(question)
        return {"role": "user", "content": prefix_string}

    def aggregate(self, query, answers):
        """Aggregate all agent answers into a final response."""
        aggregate_instruction = f"Task:\n{query}\n\n"
        for i, answer in enumerate(answers):
            aggregate_instruction += f"Solution {i+1}:\n{answer}\n\n"
        aggregate_instruction += "Given all the above solutions, reason over them carefully and provide a final answer to the task."
        response = self.call_llm(prompt=aggregate_instruction)
        return response


