"""
KAMAC (Knowledge-driven Adaptive Multi-Agent Collaboration) re-implemented on
the AEGIS `MAS` base class.

Reference:
  "A Knowledge-driven Adaptive Collaboration of LLMs for Enhancing Medical
  Decision-making", EMNLP 2025. Source: https://github.com/XiaoMinghan/KAMAC
  (main_kamac.py, agent/client.py). Upstream is GPL-3.0: NO upstream code is
  copied here. The control flow was re-implemented from a read of the code and
  every prompt was RE-WRITTEN (paraphrased, same content and intent) for
  licensing reasons, so wording differs from upstream while each prompt asks
  the model for the same thing in the same output format.

Flow (MDAgents "intermediate" pipeline + knowledge-gap-driven recruitment;
upstream line refs in brackets):
  1. Recruiter proposes `num_agents` experts ("N. Role - description -
     Hierarchy: ..."); the hierarchy is parsed but has no effect upstream
     (only printed) and none here [262-366, 165].
  2. Each expert answers the question independently [201-259].
  3. Debate turns (num_rounds rounds, each up to num_turns turns) [526-667]:
     for every panel agent in order
       a. participate (yes/no) [984]: turn 1 shows all current opinions --
          "role: letter" when all agree, else every full answer; later turns
          show the directed comments addressed to this agent (see
          `message_delivery`);
       b. if the reply contains "yes": pick recipients by number [993], then
          one message-writing call per recipient [1007];
       c. knowledge-gap question (yes/no + specialty) [669-740]; a reply
          containing the substring "yes" counts as a gap [737].
     Then [1044]: nobody talks and no gap -> stop. Gap -> an assistant
     de-duplicates the gap statements, the recruiter adds new experts or
     answers "<skip recruitment>" [742-782]. Skip: every agent's last reply
     (its gap answer) is overwritten with the recruiter's text in its history
     [784-786] and the turn cap grows by one [943]. Recruit: each new expert
     answers with the current opinions as context, then runs the participate /
     message step for this turn; if anyone wanted to talk, all agents re-answer
     [888-925]; recruiting on the last turn grows the cap by one [938].
     No gap but someone talked -> all agents re-answer [1069-1097].
     After a turn: stop if nobody wanted to talk, or at the turn cap.
  4. Moderator: majority vote over every agent's final full answer [1309-1322].
  Every agent (experts, recruiter, assistant) keeps ONE chat history for the
  case (client.py 556-572, 628, 782): each call sends the whole history.

Deviations from upstream (and why):
  * Per-patient JSON cache (forced on upstream, main_kamac.py 1741/1760) is
    not ported: every call is a live call.
  * Temperature: the run's model_temperature (upstream fixes 0.0) so normal
    runs can be sampled repeatedly. Recruiter / assistant / moderator use the
    run's model (upstream hard-codes gpt-4.1-mini for them).
  * Few-shot examplers (`--add_examplers`, MedQA train set) and the RADCURE
    CoT / vision prompts are not ported (no train split; text MCQ only).
    Options are not shuffled (upstream shuffles MedQA options per question).
  * Answer templates: upstream formats a 1-tuple ("('Answer: ',)") into the
    prompt; here "Answer: <option letter>" (moderator: "Answer: <letter>)
    <option text>", upstream's example "Answer: C) ..."). Answers are parsed
    with methods/answer_parsing.mcq_leaning (upstream: first "answer:(x)").
  * Upstream bugs made safe: recipient numbers outside 1..N are dropped
    (upstream IndexError / negative indexing) and duplicates removed; an
    unparsable recruiter reply recruits nobody (upstream crashes); if the
    initial recruitment parses no expert, one generalist is used.
  * After a recruitment SKIP upstream leaves the next turn's opinion table
    empty (turn_comments not carried forward) and at the turn cap it hands the
    moderator the opinions from the START of the last turn (dropping that
    turn's re-answers). Here the moderator always reads every agent's LATEST
    answer.
  * Caps (upstream unbounded): the turn cap can grow by at most
    `max_turn_extensions`; at most `max_recruits` experts are recruited in
    total (extra recruits proposed by the recruiter are ignored).
  * System prompts are plain text (upstream json.dumps()es them, adding
    quotes).
  * Knowledge-gap prompt: upstream uses a free-form wording for gpt models
    and a structured "Answer: yes/no / Reason:" wording for others;
    `gap_prompt: auto` reproduces that choice from the run's model name.
  * `message_delivery: upstream` (default) reproduces upstream exactly: a
    comment is shown to its recipient only in a later-than-first turn and only
    if the sender came earlier in the same turn's order (turn-1 comments are
    never shown to anyone). `inbox` instead shows each recipient every comment
    addressed to it that it has not seen yet (option for a variant).

Step contract (StructuredFMWrapper, fm_kamac_structured_wrapper.py): one
history entry per call with step_id, role/agent_name, role_index, phase,
round (debate turn, 1-based across rounds; None before the debate and for the
moderator), agent_id, agent_label (specialty), sources + source_how (exact
read set: the agent's whole chat history -- its earlier replies verbatim and
everything earlier prompts carried -- plus what the new prompt carries),
event_ids and structured.
  Roles / ids:  Recruiter(0) "recruiter"; Expert(i) "expert_<i>" (initial
  panel); Recruit(k) "recruit_<k>" (k by recruitment order); Assistant(0)
  "assistant" (gap de-duplication); Moderator(0) "moderator".
  Phases: recruitment, gap_recruitment (Recruiter); initial_assessment,
  participate, choose_recipients, message, knowledge_gap, reanswer (Expert /
  Recruit); gap_summary (Assistant); decision (Moderator).
  structured: recruits=[{agent_id, specialty}] + knowledge_gap (+ skip) on
  recruiter steps; answer on assessments / re-answers / messages / moderator
  (+ final_answer); participate / gap booleans; chosen=[agent_id] on the
  recipient choice; to=[agent_id] on each message. A recruited (or initial)
  expert's first step lists the recruiting step with how "control".
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from methods.mas_base import MAS
from methods.answer_parsing import mcq_leaning
from methods.medagents_mc.medagents_mc_main import parse_mcq_query

_HOW_RANK = {"control": 0, "structured_field": 1, "excerpt": 2, "summary": 3, "verbatim": 4}

# --------------------------------------------------------------------------- #
# Prompts -- re-written from upstream (GPL-3.0), same content and intent.
# --------------------------------------------------------------------------- #
RECRUITER_SYSTEM = ("You are a senior medical expert. Your job is to assemble a group of experts "
                    "with diverse backgrounds and have them discuss and solve a medical question.")


def recruit_prompt(question: str, n: int) -> str:
    return (
        f"Question: {question}\n"
        f"You may recruit {n} expert(s) with different medical specialties. Given the question and "
        "its answer options, which kind(s) of expert would you recruit to reach an accurate answer?\n"
        "Also state how the experts communicate (for example: Hepatologist == Nephrologist > "
        "Intensivist), or say that they work independently.\n\n"
        "Example answer when recruiting three experts:\n"
        "1. Hepatologist - Focuses on diseases of the liver and biliary tract. - Hierarchy: Independent\n"
        "2. Nephrologist - Treats disorders of kidney function and electrolytes. - Hierarchy: Hepatologist > Nephrologist\n"
        "3. Intensivist - Manages critically ill patients and organ support. - Hierarchy: Independent\n\n"
        "Answer in exactly this format and do not give reasons."
    )


def expert_system(role: str, description: str) -> str:
    return (f"You are a {role} who {description}. You work together with other medical experts "
            "as a team.")


ANSWER_TEMPLATE = "Answer: <option letter>"
FINAL_ANSWER_TEMPLATE = "Answer: <option letter>) <option text>"


def assessment_prompt(role: str, question: str, context: str) -> str:
    return (
        f"Using the reference material below (if any), answer the medical question as a {role}, "
        "choosing among the given options. Do not switch to a different medical specialty.\n\n"
        f"{context}\n\nQuestion: {question}\n\nGive your answer in this format:\n\n{ANSWER_TEMPLATE}"
    )


def participate_prompt(opinions: str) -> str:
    return (
        "Earlier in this conversation you were shown opinions from other medical experts on your "
        "team; keep those in mind. New opinions are given below. Considering the earlier and the "
        "new opinions together, say whether you want to talk to any other expert (yes/no). "
        f"Opinions:\n{opinions}"
    )


def talk_prompt(agent_list: str) -> str:
    return (
        f"Give the number of the expert you want to talk to:\n{agent_list}\n"
        "For example, to talk with Agent 1 (a pediatrician), return just 1. "
        "To talk with several experts, return their numbers separated by commas, e.g. 1,2, "
        "without any reasons."
    )


def comment_prompt(num: int, role: str) -> str:
    return (
        "Recall your medical expertise, then leave your opinion for the expert you chose "
        f"(Agent {num}. {role}). Share it once you are confident, and try to convince that "
        "expert with a brief reason."
    )


def gap_prompt_freeform(agent_list: str) -> str:
    return (
        f"You are a member of this team: {agent_list}. Earlier in this conversation you were given "
        "discussion opinions from one or more experts on the team; review them carefully now.\n\n"
        "Within your professional scope, decide whether a knowledge limitation or a missing "
        "perspective calls for help from another specialist. Answer yes or no.\n"
        "If yes, name the kind of specialist needed and give a short reason.\n"
        "Be concrete and consider the multidisciplinary needs of the case (for example imaging, "
        "supportive care, pathology review or other medical expertise). You may acknowledge "
        f"expertise that team members already cover (e.g. {agent_list}). Do not recommend a "
        "specialist whose expertise is already on the team."
    )


def gap_prompt_structured(agent_list: str) -> str:
    return (
        f"You are a member of this team: {agent_list}.\n"
        "Earlier in this conversation the team's expert opinions were shared. Based strictly on "
        "your professional scope, decide whether any additional type of specialist is needed to "
        "close a knowledge gap or a limitation in the decision.\n"
        "Reply in exactly this structure:\n---\nAnswer: yes or no\nReason: a short reason\n---\n"
        "Rules:\n- Do not propose specialties the team already has.\n"
        "- Do not explain, debate or show internal reasoning.\n"
        "- Do not argue that the current team is sufficient; only judge whether new expertise is needed.\n"
        "- Write nothing outside the structure."
    )


ASSISTANT_SYSTEM = ("You are a professional medical assistant who helps analyse a discussion "
                    "among several medical experts.")


def gap_summary_prompt(all_gaps: str, question: str, agent_list: str) -> str:
    return (
        f"Knowledge-gap statements: {all_gaps} for the question:\n {question}\n\n"
        "Given the medical question, the discussion options and the current expert team "
        f"{agent_list}, the text above holds several experts' recommendations for further "
        "consultation. Extract only the **unique, useful and specific** recommendations of an "
        "expert type, and **leave out**:\n"
        "- duplicates (if several experts ask for the same kind of specialist, keep it once);\n"
        "- recommendations that do not clearly name the type of expert needed;\n"
        "- recommendations that are only about psychological or emotional support, unless they "
        "add insight directly relevant to clinical decisions."
    )


def gap_recruit_prompt(gap: str, question: str, agent_list: str) -> str:
    return (
        "Rules:\n- Do **not** propose removing, replacing or duplicating current experts. Add "
        "**new** experts only when necessary.\n\n"
        f"Identified knowledge gap: {gap}\n\n"
        f"Medical question:\n {question}\n\n"
        f"Current expert team (DO NOT DUPLICATE): {agent_list}\n\n"
        "Task:\nGiven the medical question, the discussion options and the current team "
        f"{agent_list}, decide whether **new kinds of experts** must be recruited for an accurate "
        f"decision (excluding {agent_list}).\n\n"
        "Also state how the experts communicate (e.g. Hematologist -> Oncologist, Oncologist == "
        "Radiologist) or that the new expert(s) work independently.\n\n"
        "Do **not** propose removing, replacing or duplicating current experts. Add **new** "
        "experts only when necessary.\n"
        "Example format when recruiting:\n"
        "1. Hematologist - Your expertise is limited to disorders of blood and coagulation. - Hierarchy: Independent\n"
        "2. Other medical experts.\n\n"
        "Follow the format exactly. If the current team already covers the expertise needed for "
        "an accurate decision, answer: <skip recruitment>"
    )


def reanswer_prompt(question: str) -> str:
    return (
        "Now that you have interacted with other medical experts, recall your expertise and the "
        "other experts' comments, and give your final answer to the question:\n"
        f"{question}\n{ANSWER_TEMPLATE}"
    )


MODERATOR_SYSTEM = ("You are the final medical decision maker: you review the opinions of the "
                    "different medical experts and make the final decision.")


def moderator_prompt(final_answers: str, question: str) -> str:
    return (
        "Given each agent's final answer, review every agent's opinion and decide the final answer "
        "to the question by majority vote. Output only your final answer, in this format:\n"
        f"{FINAL_ANSWER_TEMPLATE}\n{final_answers} \n\nQuestion: {question}"
    )


# --------------------------------------------------------------------------- #
_RECRUIT_LINE = re.compile(r"^\s*\**\s*\d+\s*\.\s*\**\s*(?P<role>[^-\n*]+?)\s*\**\s*-\s*(?P<desc>[^-\n]*)")


def parse_recruits(text: str) -> List[Tuple[str, str]]:
    """(role, description) per "N. Role - description - Hierarchy: ..." line.
    Like upstream, the description ends at the next hyphen and both are
    lower-cased; lines without "N. X - Y" are skipped."""
    out = []
    for line in (text or "").splitlines():
        m = _RECRUIT_LINE.match(line)
        if not m:
            continue
        role = m.group("role").strip().lower()
        desc = m.group("desc").strip().rstrip(".").lower()
        if role:
            out.append((role, desc or "practises general medicine"))
    return out


def parse_numbers(text: str) -> List[int]:
    """Upstream recipient parsing: '.' -> ',', split on ',', keep pure digits."""
    return [int(x) for x in (text or "").replace(".", ",").split(",") if x.strip().isdigit()]


class _Agent:
    """One LLM agent with its own persistent chat history for the case."""

    def __init__(self, agent_id: str, role: str, role_index: int, system: str,
                 specialty: Optional[str] = None, description: Optional[str] = None,
                 origin: Optional[Dict[str, str]] = None):
        self.agent_id, self.role, self.role_index = agent_id, role, role_index
        self.specialty, self.description = specialty, description
        self.messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        self.msg_steps: List[Optional[str]] = [None]     # step behind each assistant message
        self.read: Dict[str, str] = dict(origin or {})   # step_id -> how, for all text in history


def _merge(dst: Dict[str, str], src: Dict[str, str]) -> None:
    for k, v in src.items():
        if k not in dst or _HOW_RANK[v] > _HOW_RANK[dst[k]]:
            dst[k] = v


class KAMAC_Main(MAS):
    def __init__(self, general_config, method_config_name="config_kamac"):
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.num_agents = int(mc.get("num_agents", 1))
        self.num_turns = int(mc.get("num_turns", 3))
        self.num_rounds = int(mc.get("num_rounds", 1))
        self.auto_recruit = bool(mc.get("auto_recruit", True))
        self.max_recruits = int(mc.get("max_recruits", 4))
        self.max_turn_extensions = int(mc.get("max_turn_extensions", 3))
        self.gap_prompt = mc.get("gap_prompt", "auto")
        self.message_delivery = mc.get("message_delivery", "upstream")
        self.conversation_history: List[Dict[str, Any]] = []
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None
        self.current_round: Optional[int] = None

    # ------------------------------------------------------------------ #
    def _call(self, agent: _Agent, phase: str, prompt: str, prompt_src: Dict[str, str] = None,
              round_: Optional[int] = None, event_ids=(), structured=None) -> Tuple[str, str]:
        """Send agent history + prompt; record one step; return (reply, step_id)."""
        msgs = [dict(m) for m in agent.messages] + [{"role": "user", "content": prompt}]
        read = dict(agent.read)
        _merge(read, prompt_src or {})
        self.current_role, self.current_role_index = agent.role, agent.role_index
        self.current_phase, self.current_round = phase, round_
        resp = self.call_llm(messages=msgs)
        resp = resp if resp is not None else ""
        sid = f"s{len(self.conversation_history)}"
        entry = {
            "step_id": sid, "role": agent.role, "agent_name": agent.role,
            "role_index": agent.role_index, "phase": phase, "round": round_,
            "agent_id": agent.agent_id, "agent_label": agent.specialty,
            "event_ids": list(event_ids), "content": resp,
            "sources": list(read.keys()), "source_how": dict(read),
            "structured": structured(resp) if callable(structured) else (structured or {}),
        }
        self.conversation_history.append(entry)
        agent.messages = msgs + [{"role": "assistant", "content": resp}]
        agent.msg_steps = agent.msg_steps + [None, sid]
        read[sid] = "verbatim"
        agent.read = read
        return resp, sid

    def _answer(self, text: str) -> Optional[str]:
        return mcq_leaning(text or "", self._options)

    def _agent_list(self) -> Tuple[str, Dict[str, str]]:
        lines = "".join(f"Agent {i+1}: {a.specialty} - {a.description}\n"
                        for i, a in enumerate(self.panel))
        return lines, {s: "structured_field" for s in self._persona_src.values()}

    def _opinions_block(self, full: bool = None) -> Tuple[str, Dict[str, str], bool]:
        """Upstream `assessment`: 'role: letter' list if all agree, else every
        full answer as '(role): text'. full=True forces the full form."""
        items = [(self._by_id[aid], txt, sid) for aid, (txt, sid) in self.opinions.items()]
        letters = {self._answer(t) for _, t, _ in items}
        agree = len(letters) == 1 and not full
        if agree:
            body = "[" + ", ".join(f"'{a.specialty}: {(self._answer(t) or 'none').lower()}'"
                                   for a, t, _ in items) + "]"
            return body, {sid: "structured_field" for _, _, sid in items}, True
        body = "".join(f"({a.specialty}): {t}\n" for a, t, _ in items)
        return body, {sid: "verbatim" for _, _, sid in items}, False

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        question = sample["query"] if isinstance(sample, dict) else str(sample)
        self.conversation_history = []
        _, self._options = parse_mcq_query(question)
        self.question = question
        self.panel: List[_Agent] = []
        self._by_id: Dict[str, _Agent] = {}
        self._persona_src: Dict[str, str] = {}     # agent_id -> recruiting step
        self.opinions: Dict[str, Tuple[str, str]] = {}   # agent_id -> (latest answer, step)
        self.recruit_log: List[Dict[str, Any]] = []
        self.n_recruited = 0
        self.gap_events = 0
        self.turn_counter = 0
        self.inbox: Dict[str, List[Tuple[int, str, str]]] = {}   # recipient -> [(sender pos, text, step)]

        # 1. initial recruitment ------------------------------------------
        self.recruiter = _Agent("recruiter", "Recruiter", 0, RECRUITER_SYSTEM)
        rec_txt, s_rec = self._call(self.recruiter, "recruitment",
                                    recruit_prompt(question, self.num_agents))
        parsed = parse_recruits(rec_txt)[: self.num_agents]
        if not parsed:
            parsed = [("general physician", "practises general internal medicine")]
        for i, (role, desc) in enumerate(parsed):
            self._add_agent(f"expert_{i}", "Expert", i, role, desc, s_rec)
        self.conversation_history[-1]["structured"] = {
            "recruits": [{"agent_id": a.agent_id, "specialty": a.specialty} for a in self.panel],
            "knowledge_gap": None}

        # 2. independent assessments --------------------------------------
        for a in list(self.panel):
            txt, sid = self._call(a, "initial_assessment", assessment_prompt(a.specialty, question, ""),
                                  structured=lambda r: {"answer": self._answer(r)})
            self.opinions[a.agent_id] = (txt, sid)

        # 3. participatory debate -----------------------------------------
        self.stop_reason = None
        for r in range(1, self.num_rounds + 1):
            talked = self._run_round(r)
            if not talked:
                break

        # 4. moderator ----------------------------------------------------
        final_answers, src, _ = self._opinions_block(full=True)
        self.moderator = _Agent("moderator", "Moderator", 0, MODERATOR_SYSTEM)
        final, s_fin = self._call(self.moderator, "decision", moderator_prompt(final_answers, question),
                                  prompt_src=src)
        ans = self._answer(final)
        self.conversation_history[-1]["structured"] = {"answer": ans, "final_answer": ans}
        return {"response": final, "history": list(self.conversation_history),
                "final_step_id": s_fin,
                "kamac": {"agents": [{"agent_id": a.agent_id, "specialty": a.specialty} for a in self.panel],
                          "recruit_events": self.recruit_log, "turns": self.turn_counter,
                          "stop_reason": self.stop_reason}}

    def _add_agent(self, agent_id, role, role_index, specialty, desc, rec_step) -> _Agent:
        a = _Agent(agent_id, role, role_index, expert_system(specialty, desc),
                   specialty=specialty, description=desc, origin={rec_step: "control"})
        self.panel.append(a)
        self._by_id[agent_id] = a
        self._persona_src[agent_id] = rec_step
        return a

    # ------------------------------------------------------------------ #
    def _run_round(self, rnd: int) -> bool:
        cap = self.num_turns
        extensions = 0
        turn = 0
        num_yes = 0
        while True:
            self.turn_counter += 1
            t = self.turn_counter
            ev = [f"round{rnd}_turn{turn+1}"]
            self.turn_msgs: Dict[Tuple[str, str], Tuple[str, str]] = {}   # (sender, recipient) -> (text, step)
            num_yes = num_gap = 0
            gap_replies: List[Tuple[_Agent, str, str]] = []
            opinions_txt, op_src, _ = self._opinions_block()
            # turn-start opinions in full form (upstream `options`, handed to recruits)
            full_txt, full_src, _ = self._opinions_block(full=True)
            for a in list(self.panel):
                num_yes += self._discuss(a, turn, t, ev, opinions_txt, op_src)
                if self.auto_recruit:
                    agent_list, al_src = self._agent_list()
                    style = self.gap_prompt
                    if style == "auto":
                        style = "freeform" if "gpt" in str(self.model_name).lower() else "structured"
                    p = gap_prompt_freeform(agent_list) if style == "freeform" else gap_prompt_structured(agent_list)
                    rep, sid = self._call(a, "knowledge_gap", p, prompt_src=al_src, round_=t, event_ids=ev,
                                          structured=lambda r: {"gap": "yes" in (r or "").lower().strip()})
                    gap_replies.append((a, rep, sid))
                    if "yes" in rep.lower().strip():
                        num_gap += 1
            # consensus step
            if num_yes == 0 and num_gap == 0:
                self.stop_reason = "no_talk_no_gap"
                return False
            if num_gap:
                num_yes, extend = self._respond_gap(num_yes, gap_replies, full_txt, full_src,
                                                    turn, cap, t, ev)
                if extend and extensions < self.max_turn_extensions:
                    cap += 1
                    extensions += 1
            else:
                self._reanswer_all(t, ev)
            turn += 1
            if num_yes == 0:
                self.stop_reason = "no_talk_after_gap"
                return False
            if turn >= cap:
                self.stop_reason = "turn_cap"
                return True

    def _discuss(self, a: _Agent, turn: int, t: int, ev, opinions_txt, op_src) -> int:
        pos = self.panel.index(a) + 1
        if turn == 0:
            shown, src = opinions_txt, dict(op_src)
        elif self.message_delivery == "inbox":
            pending = self.inbox.pop(a.agent_id, [])
            shown = "".join(f"Agent {k} -> Agent {pos}: {txt}\n" for k, txt, _ in pending) or "None\n"
            src = {sid: "verbatim" for _, _, sid in pending}
        else:   # upstream: this turn's comments to me from agents earlier in the order
            lines, src = [], {}
            for k, other in enumerate(self.panel, start=1):
                m = self.turn_msgs.get((other.agent_id, a.agent_id))
                lines.append(f"Agent {k} -> Agent {pos}: {m[0] if m else None}\n")
                if m:
                    src[m[1]] = "verbatim"
            shown = "".join(lines)
        rep, _ = self._call(a, "participate", participate_prompt(shown), prompt_src=src, round_=t,
                            event_ids=ev,
                            structured=lambda r: {"participate": "yes" in (r or "").lower().strip()})
        if "yes" not in rep.lower().strip():
            return 0
        agent_list, al_src = self._agent_list()
        n_panel = len(self.panel)

        def _chosen(r):
            nums = [n for n in dict.fromkeys(parse_numbers(r)) if 1 <= n <= n_panel]
            return nums
        rep, _ = self._call(a, "choose_recipients", talk_prompt(agent_list), prompt_src=al_src,
                            round_=t, event_ids=ev,
                            structured=lambda r: {"chosen": [self.panel[n-1].agent_id for n in _chosen(r)]})
        for n in _chosen(rep):
            target = self.panel[n - 1]
            msg, sid = self._call(a, "message", comment_prompt(n, target.specialty), round_=t,
                                  event_ids=ev,
                                  structured=lambda r, tid=target.agent_id: {"to": [tid], "answer": self._answer(r)})
            self.turn_msgs[(a.agent_id, target.agent_id)] = (msg, sid)
            self.inbox.setdefault(target.agent_id, []).append((pos, msg, sid))
        return 1

    def _reanswer_all(self, t: int, ev) -> None:
        for a in list(self.panel):
            txt, sid = self._call(a, "reanswer", reanswer_prompt(self.question), round_=t, event_ids=ev,
                                  structured=lambda r: {"answer": self._answer(r)})
            self.opinions[a.agent_id] = (txt, sid)

    def _respond_gap(self, num_yes, gap_replies, full_txt, full_src, turn, cap, t, ev) -> Tuple[int, bool]:
        """Returns (num_yes incl. recruits, whether the turn cap grows)."""
        self.gap_events += 1
        gev = ev + [f"gap{self.gap_events}"]
        if not hasattr(self, "assistant") or self.gap_events == 1:
            self.assistant = _Agent("assistant", "Assistant", 0, ASSISTANT_SYSTEM)
        agent_list, al_src = self._agent_list()
        all_gaps = "".join(f"({a.specialty}): {rep}\n" for a, rep, _ in gap_replies)
        src = dict(al_src)
        src.update({sid: "verbatim" for _, _, sid in gap_replies})
        gap_txt, s_gap = self._call(self.assistant, "gap_summary",
                                    gap_summary_prompt(all_gaps, self.question, agent_list),
                                    prompt_src=src, round_=t, event_ids=gev)
        knowledge_gap = gap_txt.strip() or None
        self.conversation_history[-1]["structured"] = {"knowledge_gap": knowledge_gap}
        rec_txt, s_rec = self._call(self.recruiter, "gap_recruitment",
                                    gap_recruit_prompt(gap_txt, self.question, agent_list),
                                    prompt_src={s_gap: "verbatim", **al_src}, round_=t, event_ids=gev)
        rec_entry = self.conversation_history[-1]
        if "skip" in rec_txt:
            rec_entry["structured"] = {"recruits": [], "knowledge_gap": knowledge_gap, "skip": True}
            self.recruit_log.append({"step_id": s_rec, "turn": t, "skip": True, "recruits": []})
            # upstream: every agent's last reply (its gap answer) is replaced by the recruiter's text
            for a in self.panel:
                idx = max(i for i, m in enumerate(a.messages) if m["role"] == "assistant")
                old = a.msg_steps[idx]
                a.messages[idx] = {"role": "assistant", "content": rec_txt}
                a.msg_steps[idx] = s_rec
                if old is not None and old not in a.msg_steps:
                    a.read.pop(old, None)
                a.read[s_rec] = "verbatim"
            return num_yes, True
        proposed = parse_recruits(rec_txt)
        room = max(0, self.max_recruits - self.n_recruited)
        new_agents = []
        for role, desc in proposed[:room]:
            k = self.n_recruited
            self.n_recruited += 1
            new_agents.append(self._add_agent(f"recruit_{k}", "Recruit", k, role, desc, s_rec))
        rec_entry["structured"] = {
            "recruits": [{"agent_id": a.agent_id, "specialty": a.specialty} for a in new_agents],
            "knowledge_gap": knowledge_gap, "skip": False,
            "n_proposed": len(proposed)}
        self.recruit_log.append({"step_id": s_rec, "turn": t, "skip": False,
                                 "recruits": [a.agent_id for a in new_agents],
                                 "n_proposed": len(proposed)})
        # new experts answer with the turn-start opinions as context
        for a in new_agents:
            txt, sid = self._call(a, "initial_assessment", assessment_prompt(a.specialty, self.question, full_txt),
                                  prompt_src=full_src, round_=t, event_ids=gev,
                                  structured=lambda r: {"answer": self._answer(r)})
            self.opinions[a.agent_id] = (txt, sid)
        opinions_txt, op_src, _ = self._opinions_block()
        for a in new_agents:
            num_yes += self._discuss(a, turn, t, gev, opinions_txt, op_src)
        if num_yes != 0:
            self._reanswer_all(t, ev)
        return num_yes, turn == cap - 1
