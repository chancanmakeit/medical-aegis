"""
MAD baseline of the ConSensus repo (moderated multi-agent debate) re-implemented
on the AEGIS `MAS` base class.

Reference:
  Yoon, Malekzadeh, Lee, Kawsar, Qendro. "ConSensus: Multi-Agent Collaboration
  for Multimodal Sensing", ACL 2026 Findings, arXiv:2601.06453 (baseline section).
  Source: https://github.com/nokia/multi-agent-collaboration-for-multimodal-sensing
          (baselines/mad/{run.py, agent_pool.py, modality_agent.py, judge_agent.py},
           core/agent.py)

Per-sample flow (upstream baselines/mad/run.py::run_sample, fixed schedule):
  1. Interpretation : one ModalityAgent per modality (info.json modality_data)
                      reads ONLY its own modality's features (+ the labelled
                      few-shot examples) and answers {"REASON","ANSWER"}.
                      Majority vote over modality answers (logged only).
  2. Judge 1        : a moderator (JudgeAgent) reads ALL modality responses and
                      answers {"REASON","ANSWER"} ("to break the tie, ...").
  3. Debate 1       : every modality agent reads the OTHER agents' last
                      responses plus the moderator's last response ("Moderator")
                      and answers again (its own earlier turns stay in its
                      conversation). All agents of a round read the same
                      snapshot taken before the round (upstream runs them in
                      parallel); memories are promoted after the whole round.
  4. Judge 2        : moderator reads all (post-debate-1) modality responses; its
                      own earlier turn stays in its conversation.
  5. Debate 2       : as 3, with the judge-2 response.
  6. Judge 3        : as 4. Its ANSWER is the method's final answer (the last
                      "Decision made" line of upstream).
  The sample is aborted (no final answer) if any agent's JSON cannot be parsed
  after one retry, or the judge's ANSWER is missing, exactly as upstream.
  Total LLM calls without retries: N + 1 + N + 1 + N + 1 = 3N + 3 (N = #modalities).

Faithfulness notes:
  - All prompts (modality / judge system messages, interpretation, debate and
    judge turns), `json.dumps(..., indent=2)` serialisation (no sort_keys, unlike
    ConSensus fusion) and the memory model (system msg + short-term turns promoted
    to long-term after a successful step; JSON-retry is a real extra turn in the
    same conversation) are copied from upstream. No volatile memory is used by
    this baseline (`invoke(content)` default), so `SensingAgent` (extended only in the
    read-set bookkeeping, see `_ConversationAgent`) is used.
  - Feature formatting and modality info assembly are the ConSensus-port helpers
    (verbatim copies of upstream).
  - Upstream runs agents of a stage concurrently with asyncio; here they run
    sequentially in info.json order. Within a round all prompts depend only on
    the pre-round snapshot, so trajectories are equivalent up to call order.
  - Temperature comes from the global config.

Deviations from upstream:
  - None in prompts / control flow. Upstream only logs to files; here the
    per-stage decisions are returned in `stage_answers`.
  - Upstream's run.py imports its classes from `baselines.judge.*` (a stale
    package name); the code actually shipped in `baselines/mad/*` is what is ported.
  - `modality_answers` are the interpretation-stage answers (as in ConSensus);
    post-debate answers are not duplicated (see `stage_answers`).

Injection contract (fm_consensus_wrapper.py):
  role "ModalityAgent", role_index = position of the modality in info.json
  (stable per dataset; `agent_label` carries the modality name), phases
  "interpretation" (round None) and "debate" (round 1..2, event_ids ["debate<k>"]);
  role "Judge", role_index 0, phase "judge" (round 1..3, event_ids ["judge<k>"]).
  A JSON-retry turn reuses the agent's (role, role_index, round). With the
  default first-invocation-only policy a target ModalityAgent(i) fires on its
  interpretation call and Judge(0) on judge round 1.

Read sets: each step records `sources` = step_ids whose outputs were inserted
into its input: modality responses serialised into the judge / debate prompt,
the moderator's last response in the debate prompt, plus the agent's own earlier
AI turns AND (via `_ConversationAgent`) the sources of its earlier calls: every call
re-sends the agent's whole conversation, so e.g. the judge in round 2 also "reads" the
interpretation outputs that were serialised into its round-1 prompt, and a debating
agent in round 2 re-reads the round-1 debate inputs.
"""

import json
from typing import Any, Dict

from methods.consensus.consensus_main import (
    SensingAgent, SensingMASBase, gen_feature_info, last_responses, modality_info_dict_from,
    task_info_from, vote,
)


class _ConversationAgent(SensingAgent):
    """SensingAgent whose read set also covers outputs of OTHER agents that sit in
    its own earlier user turns.

    In multi-turn agents (debate rounds, repeated judge calls) every call re-sends
    the agent's whole conversation, i.e. also the earlier prompts in which other
    agents' outputs were serialised. SensingAgent.invoke only adds the agent's own
    earlier AI turns, so those inherited reads are added here: a call's sources =
    own earlier AI turns + the sources of every earlier call of this agent + the
    explicitly passed `sources`. (Upstream memory semantics are unchanged.)"""

    def invoke(self, content, sources, round_=None, event_ids=None):
        prior = {h["step_id"]: h for h in self.mas.conversation_history}
        own = self.long_term_steps + self.short_term_steps
        inherited = [s for st in own for s in prior[st]["sources"]]
        return super().invoke(content, list(dict.fromkeys(inherited + list(sources))),
                              round_=round_, event_ids=event_ids)


class SensingMAD_Main(SensingMASBase):
    """ConSensus-repo MAD baseline: modality agents + a moderator (judge)."""

    FRAMEWORK_NAME = "ConSensus-MAD"

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        self._reset()
        cs = sample["consensus"]
        info, test, examples = cs["info"], cs["test"], cs.get("examples") or []
        task_info = task_info_from(info)
        classes_info = list(info["class"].keys())
        mod_info = modality_info_dict_from(info)
        modalities = list(info["modality_data"].keys())

        # ---- agents (upstream run_sample order: modality agents, then judge) ---- #
        agents: Dict[str, _ConversationAgent] = {}
        for i, modality in enumerate(modalities):
            a = _ConversationAgent(self, f"{modality}", "ModalityAgent", i, "interpretation")
            a.set_system_message(
                f"You are {modality} agent that solves a sensing task.\n"
                "You have the following information about the task:\n"
                f"{task_info}\n\n"
                f"You will receive sensor features from {modality} modality, "
                "and you have the following information about the modality:\n"
                f"{json.dumps(mod_info[modality], indent=2)}\n\n"
                "Your goal is to analyze the features and "
                "provide a reasoned answer using your knowledge.")
            agents[modality] = a

        judge = _ConversationAgent(self, "JudgeAgent", "Judge", 0, "judge")
        judge.set_system_message(
            "You are a moderator. "
            "There will be multiple sensing agents solving the same task. "
            "You have the following information about the task:\n"
            f"{task_info}\n\n"
            "You will receive reasonings and answers from multiple agents "
            "based on their interpretations of different modalities.\n"
            "Your goal is to provide a final reasoned answer for the task.")

        # ---- 1. interpretation (AgentPool.run_parallel_interpretation) ------- #
        results = {}
        for modality, a in agents.items():
            feature_info = gen_feature_info(modality, test, examples)
            content = (
                f"You have received sensor features from {modality} modality:\n"
                f"{feature_info}\n\n"
                f"Please provide your answer for the task among {classes_info} "
                "and the reasoning for your answer.\n"
                "Note that the sensor features might be wrong due to the data collection or processing.\n"
                "You can evaluate the quality of the features by checking the examples you have.\n"
                "Respond in the following strict JSON format:\n"
                "{\n"
                '  "REASON": "<Reasoning for the answer>",\n'
                f'  "ANSWER": "<Answer among {classes_info}>",\n'
                "}\n\n"
                "Do not include any additional text outside the JSON.")
            results[modality] = a.run_json_turn(content, sources=[])
        if any(r is None for r in results.values()):
            return self._abort("interpretation")
        for a in agents.values():
            a.update_memory()

        responses, _ = last_responses(agents)
        answers = {k: v.get("ANSWER", "") for k, v in responses.items()}
        stage_answers = {"interpretation": vote(answers)}
        modality_answers = dict(answers)

        # ---- fixed schedule: judge, debate, judge, debate, judge ------------- #
        schedule = [("judge", 1), ("debate", 1), ("judge", 2), ("debate", 2), ("judge", 3)]
        final = None
        for kind, k in schedule:
            stage = f"{kind}{k}"
            if kind == "judge":
                final = self._run_judge(judge, agents, classes_info, k)
                if final is None:
                    return self._abort(stage)
                stage_answers[stage] = final
            else:
                answers = self._run_debate(judge, agents, classes_info, k)
                if answers is None:
                    return self._abort(stage)
                stage_answers[stage] = vote(answers)

        raw = self.conversation_history[-1]["content"]      # judge-3 turn (or its retry)
        return {
            "response": f"{raw}\n\nFinal answer: {final}",
            "history": list(self.conversation_history),
            "final_step_id": judge.last_step,
            "stage_answers": stage_answers,
            "modality_answers": modality_answers,
            "aborted_at": None,
        }

    # ------------------------------------------------------------------ #
    def _run_judge(self, judge: _ConversationAgent, agents: Dict[str, _ConversationAgent],
                   classes_info, k: int):
        """AgentPool.run_parallel_judge + JudgeAgent.judge. Returns ANSWER or None."""
        responses, steps = last_responses(agents)
        responses_info = json.dumps(responses, indent=2)
        content = (
            "You have received responses from multiple sensing agents:\n"
            f"{responses_info}\n\n"
            "To break the tie, "
            "analyze the reasonings and answers and provide a final reasoned answer.\n"
            "Respond in the following strict JSON format:\n"
            "{\n"
            '  "REASON": "<Reasoning for the answer>",\n'
            f'  "ANSWER": "<Answer among {classes_info}>",\n'
            "}\n\n"
            "Do not include any additional text outside the JSON.")
        response = judge.run_json_turn(content, sources=steps, round_=k, event_ids=[f"judge{k}"])
        if response is None or response.get("ANSWER", None) is None:
            return None
        judge.update_memory()
        return response.get("ANSWER", None)

    def _run_debate(self, judge: _ConversationAgent, agents: Dict[str, _ConversationAgent],
                    classes_info, k: int):
        """AgentPool.run_parallel_debate + ModalityAgent.debate. Returns the
        post-round {agent: ANSWER} dict, or None on failure."""
        # Snapshot taken before the round (upstream: computed once, then agents
        # run in parallel; memories are only promoted after the whole round).
        all_responses, all_steps = last_responses(agents)
        step_of = dict(zip(all_responses.keys(), all_steps))
        judge_response = judge.get_last_response()
        judge_step = judge.last_step

        results = {}
        for name, a in agents.items():
            responses = {kk: v for kk, v in all_responses.items() if kk != name}
            moderator_response = {"Moderator": judge_response}
            content = (
                f"Other agents have provided their answers for the same task:\n"
                f"{json.dumps(responses, indent=2)}\n"
                f"{json.dumps(moderator_response, indent=2)}\n\n"
                f"Please debate with them and provide your answer for the task among {classes_info} "
                "and the reasoning for your answer.\n"
                "Respond in the following strict JSON format:\n"
                "{\n"
                '  "REASON": "<Reasoning for the answer>",\n'
                f'  "ANSWER": "<Answer among {classes_info}>",\n'
                "}\n\n"
                "Do not include any additional text outside the JSON.")
            sources = [step_of[kk] for kk in responses]
            if judge_response:
                sources.append(judge_step)
            a.phase = "debate"
            results[name] = a.run_json_turn(content, sources=sources, round_=k,
                                            event_ids=[f"debate{k}"])
        if any(r is None for r in results.values()):
            return None
        for a in agents.values():
            a.update_memory()

        responses, _ = last_responses(agents)
        return {kk: v.get("ANSWER", "") for kk, v in responses.items()}
