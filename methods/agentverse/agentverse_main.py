import os
import re
from typing import List, Dict, Any, Set, Tuple

from methods.mas_base import MAS
from methods.answer_parsing import mcq_answer
from .prompt_main import *

# Define the NEWMAS class which inherits from MAS and implements the inference method
class AgentVerse_Main(MAS):
    """AgentVerse (role assignment -> vertical solver/critic loop -> evaluator).

    Step contract (StructuredFMWrapper, fm_agentverse_structured_wrapper.py,
    2026-10-20; prompts and control flow unchanged). Roles are set explicitly
    at each call site (the legacy wrapper guessed them from prompt keywords):
    RoleAssigner(0) [phase role_assignment], Solver(0) [solve / revise],
    Critic(j) j=0..cnt_agents-2 [criticism], Evaluator(0) [evaluation];
    `round` = outer turn (1..max_turn); critic/revise steps also carry
    `event_ids` ["turn<t>_crit<r>"]. Read sets are exact: every entry of the
    shared `self.history` is mapped (by object identity) to the step that
    produced it, so a call's sources are the producers of the history entries
    it was actually given, plus the role assignment / solution / advice
    inserted into its prompt.
    """
    def __init__(self, general_config, method_config_name = None):
        method_config_name = "config_main" if method_config_name is None else method_config_name
        super().__init__(general_config, method_config_name)
        
        self.max_turn = self.method_config['max_turn']
        self.cnt_agents = self.method_config['cnt_agents']
        self.max_criticizing_rounds = self.method_config['max_criticizing_rounds']
        
        self.dimensions: List[str] = ["Score", "Response"]
        # Optional steering for the RoleAssigner. For medical tasks, set
        # `role_assigner_advice` in the config to recruit medical experts
        # (e.g. physician, pharmacologist, pathologist) with named roles.
        self.advice = self.method_config.get("role_assigner_advice", "No advice yet.")
        self.history = []
        self.conversation_history = []
        self._hist_src = {}              # id(history entry dict) -> (step_id, how)
        self.current_role, self.current_role_index = None, 0
        self.current_phase, self.current_round = None, None
        self._turn = None
        self._advice_step = None         # evaluator step whose feedback is self.advice
        self._assign_step = None

    def _call(self, role, role_index, phase, agent_id, messages, extra_sources=(),
              extra_how=None, event_ids=()):
        """call_llm with structural context + one history entry with exact sources."""
        self.current_role, self.current_role_index = role, role_index
        self.current_phase, self.current_round = phase, self._turn
        resp = self.call_llm(messages=messages)
        srcs, how = [], dict(extra_how or {})
        for m in messages:
            hit = self._hist_src.get(id(m))
            if hit:
                srcs.append(hit[0]); how.setdefault(hit[0], hit[1])
        srcs = [x for x in dict.fromkeys(list(extra_sources) + srcs) if x]
        sid = f"s{len(self.conversation_history)}"
        entry = {"step_id": sid, "role": role, "role_index": role_index, "agent_id": agent_id,
                 "phase": phase, "round": self._turn, "event_ids": list(event_ids),
                 "sources": srcs, "observations": [], "content": resp if resp is not None else ""}
        how = {k: v for k, v in how.items() if k in srcs and v != "verbatim"}
        if how:
            entry["source_how"] = how
        self.conversation_history.append(entry)
        return resp, sid

    def _push_history(self, entry, step_id, how):
        self.history.append(entry)
        self._hist_src[id(entry)] = (step_id, how)
    
    def inference(self, sample):

        query = sample["query"]
        self.conversation_history, self._hist_src = [], {}
        self._advice_step = None

        for i in range(self.max_turn):
            self._turn = i + 1
            # Assign roles to agents
            role_descriptions = self.assign_roles(query)

            # Collaborate to solve the query
            solution = self.group_vertical_solver_first(query, role_descriptions)

            # Get evaluation and feedback
            score, feedback = self.evaluate(query, role_descriptions, solution)

            if score == 1:
                break
            else:
                self.advice = feedback
                self._advice_step = self._eval_step
        return {"response": solution, "history": list(self.conversation_history),
                "final_step_id": self._solution_step}

    def assign_roles(self, query: str):
        # Fetch prompts from config.yaml (assumed to be loaded earlier)
        prepend_prompt = ROLE_ASSIGNER_PREPEND_PROMPT.replace("${query}", query).replace("${cnt_agents}", str(self.cnt_agents)).replace("${advice}", self.advice)
        append_prompt = ROLE_ASSIGNER_APPEND_PROMPT.replace("${cnt_agents}", str(self.cnt_agents))
        
        # Call LLM to get the role assignments
        assigner_messages = self.construct_messages(prepend_prompt, [], append_prompt)
        role_assignment_response, self._assign_step = self._call(
            "RoleAssigner", 0, "role_assignment", "role_assigner", assigner_messages,
            extra_sources=[self._advice_step] if self._advice_step else [],
            extra_how={self._advice_step: "excerpt"} if self._advice_step else None)
        # Extract role descriptions using regex
        role_descriptions = self.extract_role_descriptions(role_assignment_response)
        self.conversation_history[-1]["structured"] = {"roles": list(role_descriptions)}
        return role_descriptions

    def extract_role_descriptions(self, response: str):
        """
        Extracts the role descriptions from the model's response using regex.
        Handles malicious injection cases with fallback role assignments.
        Assumes the response is formatted like:
        1. an electrical engineer specified in the field of xxx.
        2. an economist who is good at xxx.
        ...
        """
        role_pattern = r"\d+\.\s*([^.]+)"  # extract the content between the number and the period
        
        role_descriptions = re.findall(role_pattern, response)
        
        if len(role_descriptions) == self.cnt_agents:
            return role_descriptions
        else:
            print(f"[AgentVerse] Warning: Expected {self.cnt_agents} agents but found {len(role_descriptions)} role descriptions")
            print(f"[AgentVerse] RoleAssigner output: {response[:300]}...")
            
            # Handle malicious injection by providing fallback roles
            if len(role_descriptions) == 0:
                # Complete parsing failure - use generic roles
                fallback_roles = [f"a general problem solver (agent {i+1})" for i in range(self.cnt_agents)]
                print(f"[AgentVerse] Using fallback roles: {fallback_roles}")
                return fallback_roles
            elif len(role_descriptions) < self.cnt_agents:
                # Partial parsing - pad with generic roles
                while len(role_descriptions) < self.cnt_agents:
                    role_descriptions.append(f"a general problem solver (agent {len(role_descriptions)+1})")
                print(f"[AgentVerse] Padded roles to: {role_descriptions}")
                return role_descriptions
            else:
                # Too many roles - truncate to required number
                truncated_roles = role_descriptions[:self.cnt_agents]
                print(f"[AgentVerse] Truncated roles to: {truncated_roles}")
                return truncated_roles

    def group_vertical_solver_first(self, query: str, role_descriptions: List[str]):
        max_history_solver = 5
        max_history_critic = 3
        previous_plan = "No solution yet."
        # Initialize history and other variables
        nonempty_reviews = []
        history_solver = []
        history_critic = []
        consensus_reached = False
        
        if not self.advice == "No advice yet.":
            # Medical configs set role_assigner_advice, so turn 1 already has
            # a non-default advice string that no step produced.
            self._push_history(
                {
                    "role": "assistant",
                    "content": f"[Evaluator]: {self.advice}",
                }, self._advice_step, "excerpt")
            if len(self.history) > max_history_solver:
                history_solver = self.history[-max_history_solver:]
            else:
                history_solver = self.history
        # Step 1: Solver generates a solution
        solver_prepend_prompt = SOLVER_PREPEND_PROMPT.replace("${query}", query)
        solver_append_prompt = SOLVER_APPEND_PROMPT.replace("${role_description}", role_descriptions[0])
        # print(f"history_solver: {history_solver}")
        solver_message = self.construct_messages(solver_prepend_prompt, history_solver, solver_append_prompt)
        RA = {self._assign_step: "structured_field"}
        solver_response, s_sol = self._call("Solver", 0, "solve", "solver", solver_message,
                                            extra_sources=[self._assign_step], extra_how=RA)
        self.conversation_history[-1]["structured"] = {"answer": mcq_answer(solver_response or "")}
        self._push_history(
            {
                "role": "assistant",
                "content": f"[{role_descriptions[0]}]: {solver_response}",
            }, s_sol, "verbatim")
        self._solution_step = s_sol
        if len(self.history) > max_history_critic:
            history_critic = self.history[-max_history_critic:]
        else:
            history_critic = self.history
        previous_plan = solver_response  # Set the solution as previous_plan
        
        cnt_critic_agent = self.cnt_agents - 1
        
        for i in range(self.max_criticizing_rounds):
            
            #step 2: Critics review the solution
            reviews = []
            for j in range(cnt_critic_agent):
                critic_prepend_prompt = CRITIC_PREPEND_PROMPT.replace("${query}", query).replace("${role_description}", role_descriptions[j+1])
                critic_append_prompt = CRITIC_APPEND_PROMPT
                critic_message = self.construct_messages(critic_prepend_prompt, history_critic, critic_append_prompt)
                ev = [f"turn{self._turn}_crit{i + 1}"]
                critic_response, s_cr = self._call("Critic", j, "criticism", f"critic_{j}", critic_message,
                                                   extra_sources=[self._assign_step], extra_how=RA,
                                                   event_ids=ev)
                self.conversation_history[-1]["structured"] = {"agree": "[Agree]" in (critic_response or "")}
                if "[Agree]" not in critic_response:
                    self._push_history(
                        {
                            "role": "assistant",
                            "content": f"[{role_descriptions[j+1]}]: {self.parse_critic(critic_response)}",
                        }, s_cr, "excerpt")
                    if len(self.history) > max_history_solver:
                        history_solver = self.history[-max_history_solver:]
                    else:
                        history_solver = self.history
                reviews.append(critic_response)
            for review in reviews:
                if "[Agree]" not in review:
                    nonempty_reviews.append(review)
            if len(nonempty_reviews) == 0:
                # print("Consensus Reached!")
                break
            solver_message = self.construct_messages(solver_prepend_prompt, history_solver, solver_append_prompt)
            solver_response, s_sol = self._call("Solver", 0, "revise", "solver", solver_message,
                                                extra_sources=[self._assign_step], extra_how=RA,
                                                event_ids=[f"turn{self._turn}_crit{i + 1}"])
            self.conversation_history[-1]["structured"] = {"answer": mcq_answer(solver_response or "")}
            self._push_history(
                {
                    "role": "assistant",
                    "content": f"[{role_descriptions[0]}]: {solver_response}",
                }, s_sol, "verbatim")
            self._solution_step = s_sol
            if len(self.history) > max_history_critic:
                history_critic = self.history[-max_history_critic:]
            else:
                history_critic = self.history
            previous_plan = solver_response
        results = previous_plan
        return results
    
    def parse_critic(self, output) -> str:
        output = re.sub(r"\n+", "\n", output.strip())
        if "[Agree]" in output:
            return ""
        else:
            return output
            
    def evaluate(self, query: str, role_descriptions: List[str], Plan):
        evaluator_prepend_prompt = EVALUATOR_PREPEND_PROMPT.replace("${query}", query).replace("${all_role_description}", "\n".join(role_descriptions)).replace("${solution}", Plan)
        evaluator_append_prompt = EVALUATOR_APPEND_PROMPT
        evaluator_message = self.construct_messages(evaluator_prepend_prompt, [], evaluator_append_prompt)
        evaluator_response, self._eval_step = self._call(
            "Evaluator", 0, "evaluation", "evaluator", evaluator_message,
            extra_sources=[self._assign_step, self._solution_step],
            extra_how={self._assign_step: "structured_field"})
        score, advice = self.parse_evaluator(evaluator_response)
        self.conversation_history[-1]["structured"] = {"correctness": score}
        return score, advice
        
    def parse_evaluator(self, output) -> Tuple[List[int], str]:
        """
        Parse evaluator output with error handling for malicious injection cases.
        Returns (correctness, advice) where correctness defaults to 0 if parsing fails.
        """
        try:
            correctness_match = re.search(r"Correctness:\s*(\d)", output)
            if correctness_match:
                correctness = int(correctness_match.group(1))
            else:
                print(f"[AgentVerse] Warning: Correctness not found in evaluator output, defaulting to 0")
                print(f"[AgentVerse] Evaluator output: {output[:200]}...")
                correctness = 0  # Default to incorrect when parsing fails

            advice_match = re.search(r"Response:\s*(.+)", output, re.DOTALL)  
            if advice_match:
                advice = advice_match.group(1).strip()  
                clean_advice = re.sub(r"\n+", "\n", advice.strip())
            else:
                print(f"[AgentVerse] Warning: Response not found in evaluator output, using full output as advice")
                clean_advice = f"Parsing failed - Raw evaluator output: {output}"
 
            return correctness, clean_advice
            
        except Exception as e:
            print(f"[AgentVerse] Error parsing evaluator output: {e}")
            print(f"[AgentVerse] Raw output: {output}")
            # Return default values to allow execution to continue
            return 0, f"Evaluator parsing error: {str(e)} - Raw output: {output}"

    def construct_messages(self, prepend_prompt: str, history: List[Dict], append_prompt: str):
        messages = []
        if prepend_prompt:
            messages.append({"role": "system", "content": prepend_prompt})
        if len(history) > 0:
            messages += history
        if append_prompt:
            messages.append({"role": "user", "content": append_prompt})
        return messages
