"""
Multi-agent Debate baseline from the ConSensus repo, re-implemented on the
AEGIS `MAS` base class (via `SensingMASBase`, see methods/consensus/consensus_main.py).

Reference:
  Yoon, Malekzadeh, Lee, Kawsar, Qendro. "ConSensus: Multi-Agent Collaboration
  for Multimodal Sensing", ACL 2026 Findings, arXiv:2601.06453 (baseline section).
  Source: https://github.com/nokia/multi-agent-collaboration-for-multimodal-sensing
          (baselines/debate/{run.py,agent_pool.py,modality_agent.py}, core/agent.py)

Per-sample flow (upstream baselines/debate/run.py::run_sample):
  1. Interpretation : one ModalityAgent per modality (info.json modality_data)
                      reads ONLY its own modality's features (+ the labelled
                      few-shot examples) and answers {"REASON","ANSWER"}.
                      Majority vote over the answers ("Decision made" #1).
  2. Debate round 1 : a snapshot of every agent's last parsed response is
                      taken once; each agent then receives the snapshot MINUS
                      its own entry and re-answers {"REASON","ANSWER"} in its own
                      conversation (so it also sees its own earlier turns).
                      All agents update memory only after the whole round.
                      Majority vote ("Decision made" #2).
  3. Debate round 2 : same as round 1, reading the round-1 responses.
                      Majority vote ("Decision made" #3) = the method's answer.
  There is no aggregator agent: the final answer is the deterministic vote
  over the round-2 answers, so `final_step_id` is None and
  `final_source_step_ids` lists the round-2 steps voted over (`response` is a
  vote summary + "Final answer: <label>", not any single agent's output).
  A sample is aborted (no final answer) if any agent's JSON cannot be parsed
  after one retry in any stage, exactly as upstream (all agents of a stage
  still run before the abort is raised, as with asyncio.gather upstream).

Faithfulness notes:
  - Prompts, the JSON-validation retry ("Failed to parse the JSON ...") and the
    memory model (system msg + short-term turns promoted to long-term at the end
    of a stage) are copied from upstream; the retry is a real extra turn in the
    same conversation.  Upstream's debate/interpret never use `volatile` memory,
    so the shared SensingAgent memory model is sufficient.
  - The debate prompt embeds `json.dumps(responses, indent=2)` WITHOUT
    sort_keys (unlike ConSensus fusion agents); `responses` is the stage-start
    snapshot (agents whose last response is empty/unparsable are omitted).
  - Upstream runs the agents of a stage concurrently with asyncio; here they run
    sequentially in info.json order.  No prompt within a stage depends on
    another agent's output of the SAME stage (the snapshot is taken before the
    stage), so the trajectories are equivalent up to call order.
  - Temperature comes from the global config (upstream config default 0.0).

Deviations from upstream: none in prompts / control flow.  Extra bookkeeping
only (step recording, `sources`, `round`/`event_ids`).

Injection contract (fm_consensus_wrapper.py):
  role "ModalityAgent", role_index = position of the modality in info.json
  (stable per dataset; `agent_label` carries the modality name); phases
  "interpretation" (round None), "debate" (round 1, 2; event_ids ["debate1"],
  ["debate2"]).  A JSON-retry turn reuses the agent's (role, role_index, round).
  Later-round target: ModalityAgent(i) in "debate" with round 2.

Read sets: each step records `sources` = step_ids whose outputs are in its input:
the agent's own earlier turns (incl. a failed first attempt on a retry), the
stage-start last responses of the OTHER agents inserted into this round's prompt,
and (cumulatively) the other agents' responses embedded in the agent's earlier
debate prompts, which stay in its conversation memory (see DebateAgent).
"""

import json
from typing import Any, Dict, List

from methods.consensus.consensus_main import (
    SensingAgent,
    SensingMASBase,
    gen_feature_info,
    last_responses,
    modality_info_dict_from,
    task_info_from,
    vote,
)


class DebateAgent(SensingAgent):
    """SensingAgent whose recorded read set is cumulative.

    Upstream agents keep their whole conversation (long-term memory), so a
    round-2 call re-sends the round-1 prompt, which embedded the other agents'
    earlier responses.  Those texts are therefore still in the model's input and
    their step_ids must stay in `sources` (SensingAgent.invoke only adds the
    agent's own earlier AI turns)."""


    # The cumulative read set (own earlier turns + everything they read) is now
    # implemented once in SensingAgent.invoke (methods/consensus/consensus_main.py),
    # so no override is needed here; the class is kept as a named alias.


class SensingDebate_Main(SensingMASBase):
    """ConSensus-repo `debate` baseline: independent interpretation, then two
    all-to-all debate rounds, final answer = majority vote of round 2."""

    FRAMEWORK_NAME = "ConSensusDebate"
    N_DEBATE_ROUNDS = 2  # upstream run_sample hard-codes "debate (1)" and "debate (2)"

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        self._reset()
        cs = sample["consensus"]
        info, test, examples = cs["info"], cs["test"], cs.get("examples") or []
        task_info = task_info_from(info)
        classes_info = list(info["class"].keys())
        mod_info = modality_info_dict_from(info)
        modalities = list(info["modality_data"].keys())

        # ---- 1. modality interpretation --------------------------------- #
        agents: Dict[str, DebateAgent] = {}
        for i, modality in enumerate(modalities):
            a = DebateAgent(self, f"{modality}", "ModalityAgent", i, "interpretation")
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

        results = {}
        for modality, a in agents.items():
            feature_info = self._observe(modality, gen_feature_info(modality, test, examples))
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
            results[modality] = a.run_json_turn(content, sources=[], observations=[modality])
        if any(r is None for r in results.values()):
            return self._abort("interpretation")
        for a in agents.values():
            a.update_memory()

        responses, resp_steps = last_responses(agents)
        answers = {k: v.get("ANSWER", "") for k, v in responses.items()}
        stage_answers = {"interpretation": vote(answers)}
        round_answers: Dict[str, Dict[str, Any]] = {"interpretation": dict(answers)}
        final_steps = resp_steps

        # ---- 2./3. debate rounds ----------------------------------------- #
        for k in range(1, self.N_DEBATE_ROUNDS + 1):
            stage = f"debate{k}"
            # Snapshot taken once, before any agent of this round runs.
            responses, resp_steps = last_responses(agents)
            step_of = dict(zip(responses.keys(), resp_steps))
            results = {}
            for name, a in agents.items():
                a.phase = "debate"
                others = {n: v for n, v in responses.items() if n != name}
                content = (
                    "Other agents have provided their answers for the same task:\n"
                    f"{json.dumps(others, indent=2)}\n\n"
                    f"Please debate with them and provide your answer for the task among {classes_info} "
                    "and the reasoning for your answer.\n"
                    "Respond in the following strict JSON format:\n"
                    "{\n"
                    '  "REASON": "<Reasoning for the answer>",\n'
                    f'  "ANSWER": "<Answer among {classes_info}>",\n'
                    "}\n\n"
                    "Do not include any additional text outside the JSON.")
                results[name] = a.run_json_turn(
                    content, sources=[step_of[n] for n in others],
                    round_=k, event_ids=[stage])
            if any(r is None for r in results.values()):
                return self._abort(stage)
            for a in agents.values():
                a.update_memory()

            responses, resp_steps = last_responses(agents)
            answers = {n: v.get("ANSWER", "") for n, v in responses.items()}
            stage_answers[stage] = vote(answers)
            round_answers[stage] = dict(answers)
            final_steps = resp_steps

        final = stage_answers[f"debate{self.N_DEBATE_ROUNDS}"]
        summary = (f"Majority vote over the round-{self.N_DEBATE_ROUNDS} debate answers: "
                   f"{json.dumps(round_answers[f'debate{self.N_DEBATE_ROUNDS}'])}")
        return {
            "response": f"{summary}\n\nFinal answer: {final}",
            "history": list(self.conversation_history),
            "final_step_id": None,                    # deterministic vote, no single LLM step
            "final_source_step_ids": list(final_steps),
            "stage_answers": stage_answers,
            "modality_answers": round_answers["interpretation"],
            "round_answers": round_answers,
            "aborted_at": None,
        }
