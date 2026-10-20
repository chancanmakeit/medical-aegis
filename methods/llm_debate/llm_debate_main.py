# The official implementation of LLM Debate https://github.com/composable-models/llm_multiagent_debate offen encounters errors.
# This is a modified version of the original implementation.
#
# Step contract (StructuredFMWrapper, fm_llm_debate_structured_wrapper.py,
# 2026-10-20): roles Agent(0..N-1) [phase "discussion", round 1..R] and
# Aggregator(0) [phase "aggregation"]; prompts unchanged. Each call records
# step_id, agent_id (agent_<i> / aggregator), cumulative sources and
# structured {"answer": <option letter>}.

import os
from ..mas_base import MAS
from ..answer_parsing import mcq_answer

class LLM_Debate_Main(MAS):
    def __init__(self, general_config, method_config_name=None):
        method_config_name = "config_main" if method_config_name is None else method_config_name
        super().__init__(general_config, method_config_name)

        self.agents_num = self.method_config["agents_num"]
        self.rounds_num = self.method_config["rounds_num"]
    
    def _ask_agent(self, role, role_index, agent_id, round_, sources, **call_kwargs):
        """One call_llm with structural context + one history entry (step contract
        of StructuredFMWrapper)."""
        self.current_role, self.current_role_index = role, role_index
        self.current_phase = "discussion" if role == "Agent" else "aggregation"
        self.current_round = round_
        response = self.call_llm(**call_kwargs)
        sid = f"s{len(self.conversation_history)}"
        self.conversation_history.append({
            "step_id": sid, "role": role, "role_index": role_index, "agent_id": agent_id,
            "phase": self.current_phase, "round": round_, "event_ids": [],
            "sources": list(dict.fromkeys(sources)), "observations": [],
            "content": response if response is not None else "",
            "structured": {"answer": mcq_answer(response or "")},
        })
        return response, sid

    def inference(self, sample):

        query = sample["query"]
        self.conversation_history = []

        agent_contexts = [[{"role": "user", "content": f"""{query} Make sure to state your answer at the end of the response."""}] for agent in range(self.agents_num)]
        # Read sets: every agent keeps ONE growing conversation, so a turn reads
        # its own earlier turns, everything those read, and (from round 2) the
        # other agents' previous-round answers embedded in the new message.
        own_steps = [[] for _ in range(self.agents_num)]     # per agent, in order
        reads = [[] for _ in range(self.agents_num)]         # accumulated read set
        prev_round = [None] * self.agents_num                # step of last round's answer

        for round in range(self.rounds_num):
            this_round = list(prev_round)
            for i, agent_context in enumerate(agent_contexts):
                if round != 0:
                    agent_contexts_other = agent_contexts[:i] + agent_contexts[i+1:]
                    message = self.construct_message(agent_contexts_other, query, 2*round - 1)
                    agent_context.append(message)
                    reads[i] += [prev_round[j] for j in range(self.agents_num) if j != i]

                response, sid = self._ask_agent("Agent", i, f"agent_{i}", round + 1,
                                                own_steps[i] + reads[i], messages=agent_context)
                agent_context.append({"role": "assistant", "content": response})
                own_steps[i].append(sid)
                this_round[i] = sid
            prev_round = this_round

        answers = [agent_context[-1]['content'] for agent_context in agent_contexts]

        final_answer = self.aggregate(query, answers, sources=list(prev_round))
        self.agent_contexts = agent_contexts  # 记录完整对话历史，供 wrapper 使用
        return {"response": final_answer, "history": list(self.conversation_history),
                "final_step_id": self.conversation_history[-1]["step_id"]}

    def construct_message(self, agents, question, idx):

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

    def aggregate(self, query, answers, sources=()):
        aggregate_instruction = f"Task:\n{query}\n\n"
        for i, answer in enumerate(answers):
            aggregate_instruction += f"Solution {i+1}:\n{answer}\n\n"
        aggregate_instruction += "Given all the above solutions, reason over them carefully and provide a final answer to the task."
        response, _ = self._ask_agent("Aggregator", 0, "aggregator", None, sources,
                                      prompt=aggregate_instruction)
        return response