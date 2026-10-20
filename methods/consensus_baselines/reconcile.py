"""
ReConcile-style baseline from the ConSensus repo (confidence-weighted round-table
discussion), re-implemented on the AEGIS `MAS` base class (via `SensingMASBase`,
see methods/consensus/consensus_main.py).

Reference:
  Yoon, Malekzadeh, Lee, Kawsar, Qendro. "ConSensus: Multi-Agent Collaboration
  for Multimodal Sensing", ACL 2026 Findings, arXiv:2601.06453 (baseline section).
  Source: https://github.com/nokia/multi-agent-collaboration-for-multimodal-sensing
          (baselines/reconcile/{run.py,agent_pool.py,modality_agent.py}, core/agent.py)
  Original method: Chen et al., "ReConcile: Round-Table Conference Improves
  Reasoning via Consensus among Diverse LLMs" (the ConSensus repo's adaptation,
  not the original multi-model implementation, is what is ported here).

Per-sample flow (upstream baselines/reconcile/run.py::run_sample):
  1. Interpretation : one ModalityAgent per modality (info.json modality_data)
                      reads ONLY its own modality's features (+ the labelled
                      few-shot examples) and answers
                      {"REASON","ANSWER","CONFIDENCE"} (CONFIDENCE in [0,1]).
                      Confidence-weighted vote ("Decision made" #1).
  2. Debate round 1 : a snapshot of every agent's last parsed response (incl.
                      its CONFIDENCE) is taken once; each agent then receives the
                      snapshot MINUS its own entry and re-answers
                      {"REASON","ANSWER","CONFIDENCE"} in its own conversation
                      (so it also sees its own earlier turns).  All agents update
                      memory only after the whole round.  Confidence-weighted
                      vote ("Decision made" #2).
  3. Debate round 2 : same, reading the round-1 responses.  Confidence-weighted
                      vote ("Decision made" #3) = the method's answer.
  Voting (agent_pool.py): confidence = float(CONFIDENCE) (0.0 if unparsable),
  then recalibrate_confidences (>=0.9&<1.0 -> 0.8; >=0.8&<0.9 -> 0.5;
  >0.6&<0.8 -> 0.3; everything else, including exactly 1.0, -> 0.1 - copied
  verbatim, quirk included); each agent adds its recalibrated confidence to its
  ANSWER (non-str answers are skipped); the first-seen answer among the maxima
  wins.  There is no aggregator agent, so `final_step_id` is None and
  `final_source_step_ids` lists the round-2 steps whose answers were voted over
  (`response` is a vote summary + "Final answer: <label>").
  A sample is aborted (no final answer) if any agent's JSON (all three fields)
  cannot be parsed after one retry in any stage, exactly as upstream (all agents
  of a stage still run before the abort, as with asyncio.gather upstream).

Faithfulness notes:
  - Prompts, the JSON-validation retry ("Failed to parse the JSON ...") and the
    memory model (system msg + short-term turns promoted to long-term at the end
    of a stage) are copied from upstream; the retry is a real extra turn in the
    same conversation.  Upstream never uses `volatile` memory here.
  - The debate prompt embeds `json.dumps(responses, indent=2)` WITHOUT
    sort_keys; `responses` is the stage-start snapshot (agents whose last
    response is empty/unparsable are omitted).
  - Upstream runs the agents of a stage concurrently with asyncio; here they run
    sequentially in info.json order (no prompt in a stage depends on another
    agent's output of the SAME stage).
  - Temperature comes from the global config (upstream config default 0.0).

Deviations from upstream: (a) if no agent's ANSWER is a string, upstream's
`vote` raises ValueError (max() of an empty dict) and kills the sample; here the
sample is aborted via `_abort(stage)` instead.  Otherwise only bookkeeping
(step recording, `sources`, `round`/`event_ids`, extra `round_confidences`).

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
debate prompts, which stay in its conversation memory (see debate.DebateAgent).
"""

import json
from typing import Any, Dict, List, Optional

from methods.consensus.consensus_main import (
    SensingMASBase,
    gen_feature_info,
    last_responses,
    modality_info_dict_from,
    task_info_from,
)

from methods.consensus_baselines.debate import DebateAgent  # cumulative read-set agent

FIELDS = ("REASON", "ANSWER", "CONFIDENCE")


# --------------------------------------------------------------------------- #
# Upstream baselines/reconcile/agent_pool.py helpers - verbatim logic
# --------------------------------------------------------------------------- #
def _safe_float(value, default=0.0):
    """Safely convert value to float, returning default if conversion fails."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def recalibrate_confidences(confidences):
    for k, v in confidences.items():
        if v >= 0.9 and v < 1.0:
            confidences[k] = 0.8
        elif v >= 0.8 and v < 0.9:
            confidences[k] = 0.5
        elif v > 0.6 and v < 0.8:
            confidences[k] = 0.3
        else:
            confidences[k] = 0.1
    return confidences


def confidence_vote(answers, confidences) -> Optional[str]:
    """Upstream AgentPool.vote (reconcile): confidence-weighted, first-seen key
    among the maxima.  Returns None where upstream would raise (no str answer)."""
    answer_cnt = {}
    for k, answer in answers.items():
        confidence = confidences[k]
        if not isinstance(answer, str):
            continue
        if answer not in answer_cnt:
            answer_cnt[answer] = 0
        answer_cnt[answer] += confidence
    if not answer_cnt:
        return None
    max_val = max(answer_cnt.values())
    return [k for k, v in answer_cnt.items() if v == max_val][0]


class SensingReconcile_Main(SensingMASBase):
    """ConSensus-repo `reconcile` baseline: confidence-reporting interpretation,
    then two all-to-all debate rounds, final answer = confidence-weighted vote
    of round 2."""

    FRAMEWORK_NAME = "ConSensusReconcile"
    N_DEBATE_ROUNDS = 2  # upstream run_sample hard-codes "debate (1)" and "debate (2)"

    # ------------------------------------------------------------------ #
    def _tally(self, agents: Dict[str, DebateAgent]):
        """Upstream post-stage block: answers, raw + recalibrated confidences,
        weighted vote.  Returns (decision, answers, raw_conf, recal_conf, step_ids)."""
        responses, resp_steps = last_responses(agents)
        answers = {k: v.get("ANSWER", "") for k, v in responses.items()}
        confidences = {k: _safe_float(v.get("CONFIDENCE", 0.0)) for k, v in responses.items()}
        raw_conf = dict(confidences)
        recal = recalibrate_confidences(confidences)
        decision = confidence_vote(answers, recal)
        voted_steps = [s for (k, s) in zip(responses.keys(), resp_steps)
                       if isinstance(answers[k], str)]
        return decision, answers, raw_conf, dict(recal), voted_steps

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
            feature_info = gen_feature_info(modality, test, examples)
            content = (
                f"You have received sensor features from {modality} modality:\n"
                f"{feature_info}\n\n"
                f"Please provide your answer for the task among {classes_info} "
                "and the reasoning for your answer.\n"
                "Note that the sensor features might be wrong due to the data collection or processing.\n"
                "You can evaluate the quality of the features by checking the examples you have.\n"
                "Also, evaluate your confidence level (between 0.0 and 1.0) to indicate the "
                "possibility of your answer being right.\n"
                "Respond in the following strict JSON format:\n"
                "{\n"
                '  "REASON": "<Reasoning for the answer>",\n'
                f'  "ANSWER": "<Answer among {classes_info}>",\n'
                '  "CONFIDENCE": "<Confidence level (between 0.0 and 1.0)>",\n'
                "}\n\n"
                "Do not include any additional text outside the JSON.")
            results[modality] = a.run_json_turn(content, sources=[], fields=FIELDS)
        if any(r is None for r in results.values()):
            return self._abort("interpretation")
        for a in agents.values():
            a.update_memory()

        decision, answers, raw_conf, recal, final_steps = self._tally(agents)
        if decision is None:
            return self._abort("interpretation")
        stage_answers = {"interpretation": decision}
        round_answers: Dict[str, Dict[str, Any]] = {"interpretation": dict(answers)}
        round_confidences: Dict[str, Dict[str, Any]] = {
            "interpretation": {"raw": raw_conf, "recalibrated": recal}}

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
                    "Also, evaluate your confidence level (between 0.0 and 1.0) to indicate the "
                    "possibility of your answer being right.\n"
                    "Respond in the following strict JSON format:\n"
                    "{\n"
                    '  "REASON": "<Reasoning for the answer>",\n'
                    f'  "ANSWER": "<Answer among {classes_info}>",\n'
                    '  "CONFIDENCE": "<Confidence level (between 0.0 and 1.0)>",\n'
                    "}\n\n"
                    "Do not include any additional text outside the JSON.")
                results[name] = a.run_json_turn(
                    content, sources=[step_of[n] for n in others],
                    round_=k, event_ids=[stage], fields=FIELDS)
            if any(r is None for r in results.values()):
                return self._abort(stage)
            for a in agents.values():
                a.update_memory()

            decision, answers, raw_conf, recal, final_steps = self._tally(agents)
            if decision is None:
                return self._abort(stage)
            stage_answers[stage] = decision
            round_answers[stage] = dict(answers)
            round_confidences[stage] = {"raw": raw_conf, "recalibrated": recal}

        last = f"debate{self.N_DEBATE_ROUNDS}"
        final = stage_answers[last]
        summary = (f"Confidence-weighted vote over the round-{self.N_DEBATE_ROUNDS} debate answers: "
                   f"{json.dumps(round_answers[last])} with recalibrated confidences "
                   f"{json.dumps(round_confidences[last]['recalibrated'])}")
        return {
            "response": f"{summary}\n\nFinal answer: {final}",
            "history": list(self.conversation_history),
            "final_step_id": None,                    # deterministic vote, no single LLM step
            "final_source_step_ids": list(final_steps),
            "stage_answers": stage_answers,
            "modality_answers": round_answers["interpretation"],
            "round_answers": round_answers,
            "round_confidences": round_confidences,
            "aborted_at": None,
        }
