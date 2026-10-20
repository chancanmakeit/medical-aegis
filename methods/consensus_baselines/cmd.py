"""
CMD baseline of the ConSensus repo (cross-group multi-agent debate with a
secretary tie-breaker) re-implemented on the AEGIS `MAS` base class.

Reference:
  Yoon, Malekzadeh, Lee, Kawsar, Qendro. "ConSensus: Multi-Agent Collaboration
  for Multimodal Sensing", ACL 2026 Findings, arXiv:2601.06453 (baseline section).
  Source: https://github.com/nokia/multi-agent-collaboration-for-multimodal-sensing
          (baselines/cmd/{run.py, agent_pool.py, modality_agent.py, secretary_agent.py},
           core/agent.py)

Per-sample flow (upstream baselines/cmd/run.py::run_sample):
  1. Interpretation : one ModalityAgent per modality (info.json modality_data)
                      reads ONLY its own modality's features (+ the labelled
                      few-shot examples) and answers {"REASON","ANSWER"}.
                      Majority vote over modality answers (logged only).
  2. Debate 1       : the agents are randomly split into 2 groups
                      (shuffle the agent list, group i = shuffled[i::2]). Every
                      agent reads (a) the full {"REASON","ANSWER"} responses of
                      the OTHER members of its own group (json.dumps indent=2)
                      and (b) a count summary "<n> agents think <ANSWER> is the
                      correct answer." of the other group, then answers again
                      (its own earlier turns stay in its conversation). All
                      agents of a round read the same snapshot taken before the
                      round (upstream runs them in parallel); memories are
                      promoted after the whole round.
  3. Debate 2       : new random grouping, same as 2.
  4. Decision       : majority vote over the debate-2 answers (first-seen key
                      among the max counts). If the maximum is shared (tie), a
                      SecretaryAgent reads ALL agents' last responses and its
                      ANSWER replaces the vote ("breaks the tie").
  The sample is aborted (no final answer) if any agent's JSON cannot be parsed
  after one retry, or the secretary's ANSWER is missing, exactly as upstream.
  LLM calls without retries: N + N + N (+ 1 on a tie), N = #modalities.

Faithfulness notes:
  - All prompts (modality / secretary system messages, interpretation, debate
    and tie-break turns), `json.dumps(..., indent=2)` serialisation (no
    sort_keys), the group split rule and the memory model (system msg +
    short-term turns promoted to long-term after a successful step; JSON-retry
    is a real extra turn in the same conversation) are copied from upstream. No
    volatile memory is used by this baseline; `SensingAgent` is used, extended only in the
    read-set bookkeeping (see `_ConversationAgent`).
  - Feature formatting and modality info assembly are the ConSensus-port helpers
    (verbatim copies of upstream).
  - Upstream runs agents of a stage concurrently with asyncio; here they run
    sequentially in info.json order. Within a round all prompts depend only on
    the pre-round snapshot, so trajectories are equivalent up to call order.
  - Temperature comes from the global config.

Deviations from upstream:
  - Group shuffling: upstream uses the process-global `np.random` stream seeded
    once with config `seed` (0), consumed by concurrently running samples, i.e.
    not reproducible per sample. Here every sample draws its two groupings from
    its own `random.Random(crc32(test sample JSON) ^ SEED)` (SEED = 0), so the
    grouping is deterministic per sample, independent of processing order,
    resume and parallelism, while still differing between samples. The
    algorithm (shuffle the agent list, split with stride 2) is identical; the
    concrete permutations differ from upstream's.
  - Upstream only logs to files; here the per-stage decisions are returned in
    `stage_answers` (answers, plus the realised "debate<k>_groups" and the boolean
    "debate2_tie" for the log) and the groups again in `debate_groups`.
  - When no tie occurs the final answer is a deterministic vote, so there is no
    single final LLM step: `final_step_id` is None and `final_source_step_ids`
    lists the debate-2 steps voted over; `response` carries a one-line summary
    of the vote instead of a model output.
  - `modality_answers` are the interpretation-stage answers (as in ConSensus).

Injection contract (fm_consensus_wrapper.py):
  role "ModalityAgent", role_index = position of the modality in info.json
  (stable per dataset; `agent_label` carries the modality name), phases
  "interpretation" (round None) and "debate" (round 1..2, event_ids ["debate<k>"]);
  role "Secretary", role_index 0, phase "tie_break" (only called on a tie, so a
  target on it stays un-fired on samples without a tie).
  A JSON-retry turn reuses the agent's (role, role_index, round).

Read sets: each step records `sources` = step_ids whose outputs were inserted
into its input. For a debate call these are the same-group members' last
responses (full text in the prompt) and - see OTHER_GROUP_COUNTS_ARE_READS -
the other group's last responses (only their ANSWER enters the prompt, as a
count line), plus the agent's own earlier AI turns AND (via `_ConversationAgent`) the
sources of its earlier calls: every call re-sends the agent's whole conversation, so
a debate-2 call also "reads" the other agents' outputs serialised into its debate-1
prompt. The secretary reads every agent's last response.
"""

import json
import random
import zlib
from typing import Any, Dict, List, Tuple

from methods.consensus.consensus_main import (
    SensingAgent, SensingMASBase, gen_feature_info, last_responses, modality_info_dict_from,
    task_info_from,
)


def vote_with_tie(answers: Dict[str, str]) -> Tuple[str, bool]:
    """Upstream cmd AgentPool.vote: (first-seen key among the max counts, is_tie)."""
    answer_cnt: Dict[str, int] = {}
    for _, answer in answers.items():
        if answer not in answer_cnt:
            answer_cnt[answer] = 0
        answer_cnt[answer] += 1
    max_val = max(answer_cnt.values())
    max_keys = [k for k, v in answer_cnt.items() if v == max_val]
    return max_keys[0], len(max_keys) > 1


class _ConversationAgent(SensingAgent):
    """SensingAgent whose read set also covers outputs of OTHER agents that sit in
    its own earlier user turns.

    In multi-turn agents (debate rounds, repeated judge calls) every call re-sends
    the agent's whole conversation, i.e. also the earlier prompts in which other
    agents' outputs were serialised. SensingAgent.invoke only adds the agent's own
    earlier AI turns, so those inherited reads are added here: a call's sources =
    own earlier AI turns + the sources of every earlier call of this agent + the
    explicitly passed `sources`. (Upstream memory semantics are unchanged.)"""


    # The cumulative read set (own earlier turns + everything they read) is now
    # implemented once in SensingAgent.invoke (methods/consensus/consensus_main.py),
    # so no override is needed here; the class is kept as a named alias.


class SensingCMD_Main(SensingMASBase):
    """ConSensus-repo CMD baseline: two-group cross debate + secretary tie-break."""

    FRAMEWORK_NAME = "ConSensus-CMD"
    SEED = 0                      # upstream config `seed`; mixed into the per-sample RNG seed
    NUM_GROUPS = 2                # AgentPool.group_agents default
    # The other group's *answers* (not their reasoning) are inserted into the debate prompt
    # as count lines. They are real information flow from those steps, so they are recorded
    # as sources. Set False to list only the same-group steps whose text is inserted verbatim
    # (scripts/check_trajectory_sources.py then stops reporting not_found for them).
    OTHER_GROUP_COUNTS_ARE_READS = True

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        self._reset()
        cs = sample["consensus"]
        info, test, examples = cs["info"], cs["test"], cs.get("examples") or []
        task_info = task_info_from(info)
        classes_info = list(info["class"].keys())
        mod_info = modality_info_dict_from(info)
        modalities = list(info["modality_data"].keys())
        rng = random.Random(zlib.crc32(json.dumps(test, sort_keys=True, default=str).encode("utf-8"))
                            ^ int(self.SEED))

        # ---- agents (upstream run_sample order: modality agents, then secretary) ---- #
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

        secretary = _ConversationAgent(self, "SecretaryAgent", "Secretary", 0, "tie_break")
        secretary.set_system_message(
            "Multiple agents are solving the same task. "
            "But they have ties in answers. "
            "You are a secretary agent that breaks the tie. "
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
        stage_answers = {"interpretation": vote_with_tie(answers)[0]}
        modality_answers = dict(answers)

        # ---- 2./3. two debate rounds, each with a fresh random grouping ------- #
        debate_groups: Dict[str, List[List[str]]] = {}
        result = None
        for k in (1, 2):
            groups = self._group_agents(agents, rng)
            debate_groups[f"debate{k}"] = groups
            stage_answers[f"debate{k}_groups"] = groups       # logged by the wrapper (extra_log)
            answers = self._run_debate(agents, groups, classes_info, k)
            if answers is None:
                return self._abort(f"debate{k}")
            result = vote_with_tie(answers)
            stage_answers[f"debate{k}"] = result[0]
        stage_answers["debate2_tie"] = result[1]

        # ---- 4. decision: vote, or secretary on a tie ------------------------ #
        if result[1]:
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
            r = secretary.run_json_turn(content, sources=steps)
            if r is None or r.get("ANSWER", None) is None:
                return self._abort("tie_break")
            final = r.get("ANSWER", None)
            stage_answers["tie_break"] = final
            raw = self.conversation_history[-1]["content"]      # secretary turn (or its retry)
            out = {"response": f"{raw}\n\nFinal answer: {final}",
                   "final_step_id": secretary.last_call_step}
        else:
            responses, steps = last_responses(agents)
            final = result[0]
            counts = {k_: v.get("ANSWER", "") for k_, v in responses.items()}
            out = {"response": ("No tie after the second debate; majority vote over "
                                f"{json.dumps(counts)}\n\nFinal answer: {final}"),
                   "final_step_id": None,
                   "final_source_step_ids": list(steps)}
        return {
            **out,
            "history": list(self.conversation_history),
            "stage_answers": stage_answers,
            "modality_answers": modality_answers,
            "debate_groups": debate_groups,
            "aborted_at": None,
        }

    # ------------------------------------------------------------------ #
    def _group_agents(self, agents: Dict[str, _ConversationAgent], rng: random.Random) -> List[List[str]]:
        """AgentPool.group_agents: shuffle the agent names, group i = shuffled[i::n]."""
        names = list(agents.keys())
        rng.shuffle(names)
        return [names[i::self.NUM_GROUPS] for i in range(self.NUM_GROUPS)]

    def _run_debate(self, agents: Dict[str, _ConversationAgent], groups: List[List[str]],
                    classes_info, k: int):
        """AgentPool.run_parallel_debate + ModalityAgent.debate. Returns the
        post-round {agent: ANSWER} dict, or None on failure."""
        # Snapshot taken before the round (upstream: computed once, then agents
        # run in parallel; memories are only promoted after the whole round).
        all_responses, all_steps = last_responses(agents)
        step_of = dict(zip(all_responses.keys(), all_steps))

        results = {}
        for name, a in agents.items():
            same_group_agents: List[str] = []
            other_group_agents: List[str] = []
            for group in groups:
                if name in group:
                    same_group_agents.extend(group)
                    same_group_agents.remove(name)
                else:
                    other_group_agents.extend(group)

            other_group_answer_cnts: Dict[str, int] = {}
            same_group_responses: Dict[str, Any] = {}
            sources: List[str] = []
            source_how: Dict[str, str] = {}
            for kk, v in all_responses.items():
                if kk in other_group_agents:
                    if v["ANSWER"] not in other_group_answer_cnts:
                        other_group_answer_cnts[v["ANSWER"]] = 0
                    other_group_answer_cnts[v["ANSWER"]] += 1
                    if self.OTHER_GROUP_COUNTS_ARE_READS:
                        sources.append(step_of[kk])
                        # Only the ANSWER enters the prompt (as a count line).
                        source_how[step_of[kk]] = "structured_field"
                elif kk in same_group_agents:
                    same_group_responses[kk] = v
                    sources.append(step_of[kk])

            other_group_summary = ""
            for ans, cnt in other_group_answer_cnts.items():
                other_group_summary += f"{cnt} agents think {ans} is the correct answer.\n"
            other_group_summary = other_group_summary.strip()
            same_group_summary = json.dumps(same_group_responses, indent=2)

            content = (
                f"There are {len(groups)} groups of agents solving the same task. "
                "I will provide you the detailed opinions and "
                "reasoning steps from your group member and opinions from other group members. "
                "Use these opinions and your previous opinion as additional advice, "
                "note that they maybe wrong. Do not copy other's entire answer, "
                "modify the part you believe is wrong.\n\n"
                "Other group members' opinions:\n"
                f"{other_group_summary}\n\n"
                "Your group's opinions:\n"
                f"{same_group_summary}\n\n"
                f"Please debate with them and provide your answer for the task among {classes_info} "
                "and the reasoning for your answer.\n"
                "Respond in the following strict JSON format:\n"
                "{\n"
                '  "REASON": "<Reasoning for the answer>",\n'
                f'  "ANSWER": "<Answer among {classes_info}>",\n'
                "}\n\n"
                "Do not include any additional text outside the JSON.")
            a.phase = "debate"
            results[name] = a.run_json_turn(content, sources=sources, round_=k,
                                            event_ids=[f"debate{k}"], source_how=source_how)
        if any(r is None for r in results.values()):
            return None
        for a in agents.values():
            a.update_memory()

        responses, _ = last_responses(agents)
        return {kk: v.get("ANSWER", "") for kk, v in responses.items()}
