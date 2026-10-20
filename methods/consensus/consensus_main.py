"""
ConSensus (multi-agent collaboration for multimodal sensing) re-implemented on
the AEGIS `MAS` base class.

Reference:
  Yoon, Malekzadeh, Lee, Kawsar, Qendro. "ConSensus: Multi-Agent Collaboration
  for Multimodal Sensing", ACL 2026 Findings, arXiv:2601.06453.
  Source: https://github.com/nokia/multi-agent-collaboration-for-multimodal-sensing
          (core/agent.py, core/modality_agent.py, core/*_fusion_agent.py,
           core/agent_pool.py, run_consensus.py)

Per-sample flow (upstream run_sample):
  1. Interpretation : one ModalityAgent per modality (info.json modality_data)
                      reads ONLY its own modality's features (+ the user's
                      labelled few-shot examples) and answers {"REASON","ANSWER"}.
                      Majority vote over modality answers (deterministic).
  2. Semantic fusion: reads all modality responses, answers freely.
  3. Statistical fusion: reads all modality responses + the majority answer,
                      and is instructed to side with the majority.
  4. Hybrid fusion  : reads modality responses + semantic + statistical
                      responses; its ANSWER is ConSensus's final answer.
  A sample is aborted (no final answer) if any agent's JSON cannot be parsed
  after one retry, exactly as upstream.

Faithfulness notes:
  - Prompts, JSON-validation retry ("Failed to parse the JSON ...") and the
    memory model (system msg + short-term turns promoted to long-term after a
    successful step) are copied from upstream; the retry is a real extra turn
    in the same conversation.
  - Feature formatting (format_feature) and modality info assembly
    (DataLoader.get_modality_info_dict) are copied verbatim.
  - Upstream runs modality agents concurrently with asyncio; here they run
    sequentially in info.json order (no prompt depends on another modality
    agent, so the trajectories are equivalent up to call order).
  - Temperature comes from the global config (upstream config default 0.0).

Injection contract (fm_consensus_wrapper.py):
  role "ModalityAgent", role_index = position of the modality in info.json
  (stable per dataset; `agent_label` carries the modality name),
  "SemanticFusion"(0), "StatisticalFusion"(0), "HybridFusion"(0).
  A JSON-retry turn reuses the agent's (role, role_index).

Read sets: each step records `sources` = step_ids whose outputs were inserted
into its input, including the agent's own earlier turn on a retry.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from methods.mas_base import MAS


# --------------------------------------------------------------------------- #
# Upstream helpers (core/agent.py) - verbatim logic
# --------------------------------------------------------------------------- #
def clean_json_text(text):
    text = text.strip()
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", "'").replace("”", "'")
    text = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*]", "]", text)
    text = "".join(ch for ch in text if ch.isprintable())
    text = text.replace("][", ",")
    return text


def safe_parse_json(text):
    if not text:
        return None
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(clean_json_text(match.group(0)))
        except json.JSONDecodeError:
            return None
    elif not text.endswith("}"):
        text += "}"
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(clean_json_text(match.group(0)))
            except json.JSONDecodeError:
                return None
    return None


def format_feature(value):
    if isinstance(value, float):
        if abs(value) >= 1e4 or abs(value) < 1e-2:
            return f"{value:.2e}"
        return f"{value:.2f}"
    return value


def task_info_from(info) -> str:
    task_info = f"**Task**:\n{info['task']}\n\n"
    classes_info = "\n".join(f"  - {k}: {v}" for k, v in info["class"].items())
    return task_info + f"**Classes**:\n{classes_info}"


def modality_info_dict_from(info) -> Dict[str, Dict[str, str]]:
    out = {}
    for modality in info["modality_data"].keys():
        out[modality] = {
            "Data collection": info["modality_data"][modality].strip(),
            "Feature extraction": info["feature"][modality.split("_")[-1]].strip(),
        }
    return out


def vote(answers: Dict[str, str]) -> str:
    """Upstream AgentPool.vote: first-seen key among the max counts."""
    answer_cnt = {}
    for _, answer in answers.items():
        answer_cnt[answer] = answer_cnt.get(answer, 0) + 1
    max_val = max(answer_cnt.values())
    return [k for k, v in answer_cnt.items() if v == max_val][0]


def gen_feature_info(name, sample, examples) -> str:
    """Upstream ModalityAgent.gen_feature_info (+ gen_example_info), verbatim.

    `name` may join several modalities with "+" (upstream convention)."""
    modalities = name.split("+")
    feature_info = f"{name} features:\n"
    if len(examples) > 0:
        ex = ("**Examples**\n"
              "Sensor values might not always align with your inherent "
              "knowledge due to differences in data collection or processing. "
              "So, we included a few labeled examples to help your interpretation:\n")
        for example in examples:
            ex += f"*Example of {example['label']}*:\n"
            for k, v in example["features"].items():
                for m in modalities:
                    if m in k:
                        ex += f"  - {k}: {format_feature(v)}\n"
            ex += "\n"
        feature_info += f"{ex.strip()}\n\n"
    feature_info += "**Current sample features**:\n"
    for k, v in sample["features"].items():
        for m in modalities:
            if m in k:
                feature_info += f"  - {k}: {format_feature(v)}\n"
    return feature_info.strip()


def last_responses(agents):
    """Upstream AgentPool.get_last_responses -> (responses, step_ids read)."""
    responses, steps = {}, []
    for name, a in agents.items():
        r = a.get_last_response()
        if r:
            responses[name] = r
            steps.append(a.last_step)
    return responses, steps


# --------------------------------------------------------------------------- #
# Agent with upstream memory semantics, but calls routed through the MAS.
# --------------------------------------------------------------------------- #
class _Agent:
    def __init__(self, mas: "ConSensus_Main", name: str, role: str, role_index: int, phase: str):
        self.mas, self.name, self.role, self.role_index, self.phase = mas, name, role, role_index, phase
        self.long_term: List[Dict[str, str]] = []
        self.short_term: List[Dict[str, str]] = []
        self.long_term_steps: List[str] = []    # step_ids of AI turns in long-term memory
        self.short_term_steps: List[str] = []
        self.last_step: Optional[str] = None    # step whose output get_last_response() parses

    def set_system_message(self, content):
        self.long_term.append({"role": "system", "content": content})

    def invoke(self, content: str, sources: List[str], round_=None, event_ids=None,
               source_how: Optional[Dict[str, str]] = None) -> str:
        messages = self.long_term + self.short_term + [{"role": "user", "content": content}]
        # Read set = this agent's own earlier AI turns (still in `messages`)
        # + everything those earlier turns read (their prompts are still in
        # `messages` too) + the outputs inserted into the new prompt.
        own = self.long_term_steps + self.short_term_steps
        prior = {h["step_id"]: h for h in self.mas.conversation_history}
        inherited, how = [], {}
        for st in own:
            inherited += prior[st].get("sources", [])
            how.update(prior[st].get("source_how", {}))
        how.update(source_how or {})
        all_sources = list(dict.fromkeys(own + inherited + list(sources)))
        resp, sid = self.mas._ask(self.role, self.role_index, self.phase, self.name,
                                  messages, sources=all_sources,
                                  round_=round_, event_ids=event_ids,
                                  source_how={k: v for k, v in how.items() if k in all_sources})
        self._last_round, self._last_events = round_, event_ids
        self.short_term += [{"role": "user", "content": content},
                            {"role": "assistant", "content": resp}]
        self.short_term_steps.append(sid)
        self.last_call_step = sid
        return resp.strip()

    def validate_response(self, response, fields):
        if not response or not isinstance(response, dict) or not all(f in response for f in fields):
            retry = self.invoke("Failed to parse the JSON from the previous response. Please try again.", [],
                                round_=getattr(self, "_last_round", None),
                                event_ids=getattr(self, "_last_events", None))
            response = safe_parse_json(retry)
        if not response or not isinstance(response, dict) or not all(f in response for f in fields):
            return None
        return response

    def update_memory(self):
        self.long_term += self.short_term
        self.long_term_steps += self.short_term_steps
        self.short_term, self.short_term_steps = [], []
        self.last_step = self.long_term_steps[-1] if self.long_term_steps else None

    def get_last_response(self):
        if len(self.long_term) >= 2 and self.long_term[-1]["role"] == "assistant":
            return safe_parse_json(self.long_term[-1]["content"])
        return None

    def run_json_turn(self, content: str, sources: List[str], round_=None, event_ids=None,
                      fields=("REASON", "ANSWER"), source_how: Optional[Dict[str, str]] = None):
        parsed = safe_parse_json(self.invoke(content, sources, round_=round_, event_ids=event_ids,
                                             source_how=source_how))
        return self.validate_response(parsed, list(fields))


# Public name for reuse by the ConSensus-repo baselines.
SensingAgent = _Agent


class SensingMASBase(MAS):
    """Shared plumbing for ConSensus and the ConSensus-repo baselines:
    structural role pointers, per-call step recording (step_id / sources /
    round / event_ids / agent_label) and the upstream abort convention."""

    FRAMEWORK_NAME = "sensing"

    def __init__(self, general_config, method_config_name="config_sensing"):
        super().__init__(general_config, method_config_name=method_config_name)
        self.conversation_history: List[Dict[str, Any]] = []
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None
        self.current_round: Optional[int] = None
        self._step_counter = 0

    def _reset(self):
        self.conversation_history, self._step_counter = [], 0

    def _ask(self, role, role_index, phase, agent_label, messages, sources,
             round_=None, event_ids=None, source_how=None) -> Tuple[str, str]:
        """One LLM call = one history entry.

        `source_how` maps a source step_id to how its output entered the prompt
        when that is NOT a verbatim/serialised copy, e.g. "structured_field"
        (only a derived field such as an ANSWER count). Unlisted = verbatim."""
        self.current_role, self.current_role_index, self.current_phase = role, role_index, phase
        self.current_round = round_
        resp = self.call_llm(messages=messages)
        resp = resp if resp is not None else ""
        sid = f"s{self._step_counter}"
        self._step_counter += 1
        entry = {
            "step_id": sid, "role": role, "role_index": role_index, "phase": phase,
            "agent_label": agent_label, "round": round_, "event_ids": list(event_ids or []),
            "sources": list(sources), "content": resp,
        }
        if source_how:
            entry["source_how"] = dict(source_how)
        self.conversation_history.append(entry)
        return resp, sid

    def _abort(self, stage: str) -> Dict[str, Any]:
        return {"response": f"{self.FRAMEWORK_NAME} aborted: JSON could not be parsed at {stage}.",
                "history": list(self.conversation_history), "final_step_id": None,
                "stage_answers": None, "modality_answers": None, "aborted_at": stage}


class ConSensus_Main(SensingMASBase):
    """ConSensus: modality agents + semantic / statistical / hybrid fusion."""

    FRAMEWORK_NAME = "ConSensus"

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
        agents: Dict[str, _Agent] = {}
        for i, modality in enumerate(modalities):
            a = _Agent(self, f"{modality}", "ModalityAgent", i, "interpretation")
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
            feature_info = self._gen_feature_info(modality, test, examples)
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

        responses, resp_steps = self._last_responses(agents)
        answers = {k: v.get("ANSWER", "") for k, v in responses.items()}
        interp_answer = vote(answers)

        # ---- 2. semantic fusion ------------------------------------------- #
        sem = _Agent(self, "SemanticFusionAgent", "SemanticFusion", 0, "semantic_fusion")
        sem.set_system_message(
            "You are a fusion agent that solves a multimodal sensing task "
            "based on interpretations from multiple sensing agents.\n"
            "You have the following information about the task:\n"
            f"{task_info}\n\n"
            "You will receive reasonings and answers from multiple agents "
            "based on their interpretations of different modalities.\n"
            "Your goal is to provide a final reasoned answer for the task.")
        responses_info = json.dumps(responses, indent=2, sort_keys=True)
        r = sem.run_json_turn(
            "You have received responses from multiple sensing agents:\n"
            f"{responses_info}\n\n"
            "Using your own knowledge and expertise, "
            "analyze the reasonings and answers and provide a final reasoned answer.\n"
            "Respond in the following strict JSON format:\n"
            "{\n"
            '  "REASON": "<Reasoning for the answer>",\n'
            f'  "ANSWER": "<Answer among {classes_info}>",\n'
            "}\n\n"
            "Do not include any additional text outside the JSON.",
            sources=resp_steps)
        if r is None:
            return self._abort("semantic_fusion")
        semantic_answer = r.get("ANSWER", "")
        sem.update_memory()

        # ---- 3. statistical fusion ---------------------------------------- #
        responses, resp_steps = self._last_responses(agents)
        majority = vote({k: v.get("ANSWER", "") for k, v in responses.items()})
        stat = _Agent(self, "StatisticalFusionAgent", "StatisticalFusion", 0, "statistical_fusion")
        stat.set_system_message(
            "You are a fusion agent that solves a multimodal sensing task "
            "based on interpretations from multiple sensing agents.\n"
            "You have the following information about the task:\n"
            f"{task_info}\n\n"
            "You will receive reasonings and answers from multiple agents "
            "based on their interpretations of different modalities.\n"
            "Your goal is to provide a final reasoned answer for the task.")
        responses_info = json.dumps(responses, indent=2, sort_keys=True)
        r = stat.run_json_turn(
            "You have received responses from multiple sensing agents:\n"
            f"{responses_info}\n\n"
            f"You are on the side that the correct answer is {majority} which is the majority answer.\n"
            "Based on the given reasonings and answers, provide a final reasoned answer for the task.\n"
            f"For agents who provided different answers from {majority}, "
            "explain why their reasoning is likely affected by noise or unreliable signal interpretation.\n"
            f"Stay consistent with the position that the correct answer is likely {majority}.\n"
            "Respond in the following strict JSON format:\n"
            "{\n"
            '  "REASON": "<Reasoning for the answer>",\n'
            f'  "ANSWER": "{majority}",\n'
            "}\n\n"
            "Do not include any additional text outside the JSON.",
            sources=resp_steps)
        if r is None:
            return self._abort("statistical_fusion")
        statistical_answer = r.get("ANSWER", "")
        stat.update_memory()

        # ---- 4. hybrid fusion --------------------------------------------- #
        responses, resp_steps = self._last_responses(agents)
        hyb = _Agent(self, "HybridFusionAgent", "HybridFusion", 0, "hybrid_fusion")
        hyb.set_system_message(
            "You are a coordinator agent that solves a multimodal sensing task "
            "based on interpretations from multiple sensing agents.\n"
            "You have the following information about the task:\n"
            f"{task_info}\n\n"
            "You will receive reasonings and answers from multiple agents, "
            "each interpreting different modalities, "
            "as well as two fusion agents that have already aggregated these responses in different ways.\n"
            "Your goal is to coordinate the responses from the fusion agents "
            "and provide a final reasoned answer for the task.")
        r = hyb.run_json_turn(
            "You have received the following information.\n"
            "1. Original responses from individual modality agents:\n"
            f"{json.dumps(responses, indent=2, sort_keys=True)}\n\n"
            "2. Responses from fusion agents:\n"
            f"{json.dumps(sem.get_last_response(), indent=2, sort_keys=True)}\n\n"
            f"{json.dumps(stat.get_last_response(), indent=2, sort_keys=True)}\n\n"
            "Your task is to determine the responses from the fusion agents "
            "and provide a final reasoned answer for the task.\n"
            "Respond in the following strict JSON format:\n"
            "{\n"
            '  "REASON": "<Reasoning for the answer>",\n'
            f'  "ANSWER": "<Answer among {classes_info}>",\n'
            "}\n\n"
            "Do not include any additional text outside the JSON.",
            sources=resp_steps + [sem.last_step, stat.last_step])
        if r is None:
            return self._abort("hybrid_fusion")
        hyb.update_memory()
        final = r.get("ANSWER", "")
        raw = self.conversation_history[-1]["content"]
        return {
            "response": f"{raw}\n\nFinal answer: {final}",
            "history": list(self.conversation_history),
            "final_step_id": hyb.last_step,
            "stage_answers": {"interpretation_vote": interp_answer, "semantic": semantic_answer,
                              "statistical": statistical_answer, "hybrid": final},
            "modality_answers": answers,
            "aborted_at": None,
        }

    # ------------------------------------------------------------------ #
    def _gen_feature_info(self, name, sample, examples) -> str:
        return gen_feature_info(name, sample, examples)

    @staticmethod
    def _last_responses(agents: Dict[str, "_Agent"]):
        responses, steps = {}, []
        for name, a in agents.items():
            r = a.get_last_response()
            if r:
                responses[name] = r
                steps.append(a.last_step)
        return responses, steps
