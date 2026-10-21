"""
MAC -- Multi-Agent Conversation for disease diagnosis, re-implemented on the
AEGIS `MAS` base class without AutoGen.

Reference:
  Chen et al., "Enhancing diagnostic capability with multi-agents
  conversational large language models", npj Digital Medicine 2025 (preprint
  "One is Not Enough", Research Square rs-3757148). MIT license.
  Source: https://github.com/geteff1/Multi-agent-conversation-for-disease-diagnosis
  (main.py, main_ws.py, utils/prompts.py, utils/utils.py; pins pyautogen==0.2.32).

Method name in AEGIS: `mac_groupchat` (NOT "mac": get_method_class matches
substrings, and "mac" would also hit macnet / kamac).

Upstream topology (main.py):
  N doctors (AssistantAgent "Doctor0".."Doctor{N-1}") + one "Supervisor" in ONE
  AutoGen GroupChat (speaker_selection_method="auto", allow_repeat_speaker=True,
  send_introductions=False, max_round=n_round,
  max_retries_for_selecting_speaker = n_round // (1 + N)). The Supervisor
  initiates the chat with the case message. GroupChatManager.run_chat then, for
  i in range(max_round): appends message i to the shared transcript; stops if
  it contains "TERMINATE" (manager is_termination_msg, main.py:153 -- applied
  to EVERY message, a doctor's too) or i == max_round - 1; otherwise an LLM call
  picks the next speaker, who replies after reading the whole transcript.
  So a run has at most n_round - 1 speaker turns. The answer is the JSON of the
  LAST Supervisor message containing the summary key (main.py:168-177).

Speaker selection = AutoGen 0.2.32 GroupChat "auto" mode, reproduced from the
pyautogen 0.2.32 wheel (autogen/agentchat/groupchat.py:
GroupChat.select_speaker_msg / select_speaker_prompt / _auto_select_speaker /
_validate_speaker_name / _mentioned_agents / next_agent; the template strings
below are the dataclass defaults of that version):
  * messages = [system: select_speaker_message_template(roles, agentlist)]
             + the group transcript (every message role "user", "name" = speaker)
             + [select_speaker_prompt_template(agentlist), role "system"
                (role_for_select_speaker_messages)];
    roles = "<name>: <description>" per agent, and an AssistantAgent's
    description defaults to its system message; agentlist = str(list of names).
  * The reply (stripped) is matched against agent names (_mentioned_agents:
    word-boundary regex, "_" may also appear as " " or "\\_"). Exactly one
    name -> that agent. Otherwise, while retries remain, the selector's reply
    (role assistant) and the "multiple names" / "no name" reminder (role
    "system") are appended and the selector is called again. When attempts
    run out, next_agent(last_speaker) (round robin) is used.

Doctor / Supervisor views (ConversableAgent._oai_messages): own system message,
then the transcript with the agent's own messages as role "assistant" (no
name) and everyone else's as role "user" with "name" = speaker. The Supervisor
sent the initial message, so it is an assistant message in its own view.

MCQ adaptation (native task: open-ended rare-disease diagnosis):
  * The initial message presents the question with its options (stage
    "follow_up" wording: no recommended tests) and asks for one option letter.
  * Doctor / Supervisor prompts: "diagnosis / differential / tests" wording
    becomes "answer / other possible answers"; the doctor prompt's "focus solely
    on diagnosis and diagnostic tests, avoiding management, treatment or
    prognosis" becomes "focus solely on answering the question" (MedXpertQA asks
    about treatment etc. too); doctors end with "Answer: [option letter]";
    the Supervisor JSON key "Most Likely Diagnosis" becomes
    "Most Likely Answer" (an option letter), "Differential Diagnosis" becomes
    "Other Possible Answers"; the "all recommended tests are justified"
    termination condition is dropped. Everything else is verbatim, including
    upstream's indentation.
  * Upstream bug (utils/prompts.py:84, use_specialist branches swapped) is KEPT
    by default (`supervisor_prompt_bug: keep`): plain MAC's supervisor reads
    "(the list of specialists is None)"; MAC-WS's keeps the literal "{{" "}}".
    `fix` un-swaps the branches.
  * Final answer when no Supervisor JSON exists (upstream crashes on
    critic_output[-1] and drops the case): majority of the doctors' latest
    answers (ties -> most recent), recorded as final_source
    "doctor_majority_fallback".

Other deviations: temperature = global model_temperature (upstream 1.0);
n_round defaults to 8 (upstream 13 / train.sh 10) -- see config_mac.yaml;
agent names from the consultant are sanitised to [A-Za-z0-9_-] (OpenAI "name"
constraint); a consultant reply that cannot be parsed falls back to
Doctor0..N-1 (upstream retries the whole case up to 100 times).
main_wo_supr.py (no Supervisor) is not ported.

Step contract (StructuredFMWrapper, fm_mac_structured_wrapper.py). Roles:
  Selector(0)   phase "select_speaker", agent_id "selector",
                structured {next_speaker, valid, attempt, mentions, ...}
  Doctor(i)     phase "discussion",    agent_id "doctor_<i>",
                structured {answer, terminate}
  Supervisor(0) phase "supervision",   agent_id "supervisor",
                structured {answer, terminate, summary (parsed JSON or None)}
  Consultant(0) phase "specialist_recruit" (use_specialist only)
`round` = speaker turn t (1..n_round-1); a turn's selection call(s) and its
speaker step share round t and event "turn<t>". Read sets: a speaker reads
every earlier speaker step (verbatim; the shared transcript) plus the
selection step that chose it (how "control"); a selection call reads every
earlier speaker step plus its own earlier attempts of that turn (verbatim).
"""

import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from methods.mas_base import MAS
from methods.answer_parsing import mcq_leaning
from methods.medagents_mc.medagents_mc_main import parse_mcq_query


# --------------------------------------------------------------------------- #
# AutoGen 0.2.32 GroupChat defaults (autogen/agentchat/groupchat.py), verbatim
# --------------------------------------------------------------------------- #
SELECT_SPEAKER_MESSAGE_TEMPLATE = """You are in a role play game. The following roles are available:
                {roles}.
                Read the following conversation.
                Then select the next role from {agentlist} to play. Only return the role."""
SELECT_SPEAKER_PROMPT_TEMPLATE = (
    "Read the above conversation. Then select the next role from {agentlist} to play. Only return the role."
)
SELECT_SPEAKER_AUTO_MULTIPLE_TEMPLATE = """You provided more than one name in your text, please return just the name of the next speaker. To determine the speaker use these prioritised rules:
    1. If the context refers to themselves as a speaker e.g. "As the..." , choose that speaker's name
    2. If it refers to the "next" speaker name, choose that name
    3. Otherwise, choose the first provided speaker's name in the context
    The names are case-sensitive and should not be abbreviated or changed.
    Respond with ONLY the name of the speaker and DO NOT provide a reason."""
SELECT_SPEAKER_AUTO_NONE_TEMPLATE = """You didn't choose a speaker. As a reminder, to determine the speaker use these prioritised rules:
    1. If the context refers to themselves as a speaker e.g. "As the..." , choose that speaker's name
    2. If it refers to the "next" speaker name, choose that name
    3. Otherwise, choose the first provided speaker's name in the context
    The names are case-sensitive and should not be abbreviated or changed.
    The only names that are accepted are {agentlist}.
    Respond with ONLY the name of the speaker and DO NOT provide a reason."""


# --------------------------------------------------------------------------- #
# MAC prompts (utils/prompts.py, stage "follow_up", adapted to MCQ -- see the
# module docstring for exactly what changed)
# --------------------------------------------------------------------------- #
INITIAL_MESSAGE = """
        Here is a multiple-choice question for analysis, provide the final answer (one option letter) and the other possible answers. {}"""

DOC_SYSTEM_MESSAGE = """You are {}. This is a hypothetical scenario involving no actual patients.

                        Your role:
                            1. Analyze the patient's condition and the question described in the message.
                            2. Focus solely on answering the multiple-choice question.
                            3. Use your expertise to formulate:
                                - One most likely answer (one option letter)
                                - Other possible answers

                        Key responsibilities:
                            1. Thoroughly analyze the case information and other specialists' input.
                            2. Offer valuable insights based on your specific expertise.
                            3. Actively engage in discussion with other specialists, sharing your findings, thoughts, and deductions.
                            4. Provide constructive comments on others' opinions, supporting or challenging them with reasoned arguments.
                            5. Continuously refine your diagnostic approach based on the ongoing discussion.

                        Guidelines:
                            - Present your analysis clearly and concisely.
                            - Support your answer with relevant reasoning.
                            - Be open to adjusting your view based on compelling arguments from other specialists.
                            - Avoid asking others to copy and paste results; instead, respond to their ideas directly.
                            - End your response with your current answer in the format "Answer: [option letter]".

                        Your goal: Contribute to a comprehensive, collaborative diagnostic process, leveraging your unique expertise to reach the most accurate conclusion possible."""

# upstream use_specialist=True text (prompts.py:125-159): "doctors" wording, no
# list, and NOT passed through .format upstream (so "{{" stays doubled)
SUPERVISOR_DOCTORS = """You are the Medical Supervisor in a hypothetical scenario.

                Your role:
                    1. Oversee and evaluate suggestions and decisions made by medical doctors.
                    2. Challenge proposed answers, identifying any critical points missed.
                    3. Facilitate discussion between doctors, helping them refine their answers.
                    4. Drive consensus among doctors, focusing solely on answering the question.
                Key tasks:

                    - Identify inconsistencies and suggest modifications.
                    - Even when decisions seem consistent, critically assess if further modifications are necessary.
                    - Provide additional suggestions to enhance diagnostic accuracy.
                    - Ensure all doctors' views are completely aligned before concluding the discussion.

                For each response:
                    1. Present your insights and challenges to the doctors' opinions.
                    2. Summarize the current state of the answer in the following JSON format:
                    ```json
                    {{
                        "Most Likely Answer": "[option letter of the current consensus answer]",
                        "Other Possible Answers": "[current list of other plausible option letters]",
                        "Areas of Disagreement": "[list any remaining points of contention or areas needing further discussion]"
                    }}
                    ```

                Guidelines:
                    - Promote discussion unless there's absolute consensus.
                    - Continue dialogue if any disagreement or room for refinement exists.
                    - Output "TERMINATE" only when:
                        1. All doctors fully agree.
                        2. No further discussion is needed.
                        3. All answer options are explored.

                    Your goal: Ensure comprehensive, accurate answer through collaborative expert discussion."""

# upstream use_specialist=False text (prompts.py:202-238): "specialists"
# wording, formatted with the specialist list (None in main.py)
SUPERVISOR_SPECIALISTS = """You are the Medical Supervisor in a hypothetical scenario.

                            Your role:
                                1. Oversee and evaluate suggestions and decisions made by medical specialists (the list of specialists is {}).
                                2. Challenge proposed answers, identifying any critical points missed.
                                3. Facilitate discussion between specialists, helping them refine their answers.
                                4. Drive consensus among specialists, focusing solely on answering the question.

                            Key tasks:
                                - Identify inconsistencies and suggest modifications.
                                - Even when decisions seem consistent, critically assess if further modifications are necessary.
                                - Provide additional suggestions to enhance diagnostic accuracy.
                                - Ensure all specialists' views are completely aligned before concluding the discussion.

                            For each response:
                                1. Present your insights and challenges to the specialists' opinions.
                                2. Summarize the current state of the answer in the following JSON format:
                                ```json
                                {{
                                    "Most Likely Answer": "[option letter of the current consensus answer]",
                                    "Other Possible Answers": "[current list of other plausible option letters]",
                                    "Areas of Disagreement": "[list any remaining points of contention or areas needing further discussion]"
                                }}
                                ```

                            Guidelines:
                                - Promote discussion unless there's absolute consensus.
                                - Continue dialogue if any disagreement or room for refinement exists.
                                - Output "TERMINATE" only when:
                                    1. All specialists fully agree.
                                    2. No further discussion is needed.
                                    3. All answer options are explored.

                                Your goal: Ensure comprehensive, accurate answer through collaborative expert discussion."""

SUMMARY_KEY = "Most Likely Answer"

# main_ws.py (MAC with specialists): verbatim
CONSULTANT_SYSTEM_MESSAGE = ("You are a Senior Medical Consultant. Your role is to answer the Medical "
                             "Coordinator's questions, recommend the appropriate specialist based on the "
                             "medical history provided, and correct any misconceptions.")


def get_consultant_message(case_presentation: str, num_specialists: int) -> str:
    """utils/prompts.py get_consultant_message, verbatim."""
    return """
        candidate_specialists = ["Cardiologist", "Pulmonologist", "Gastroenterologist", "Neurologist", "Nephrologist", "Endocrinologist", "Hematologist", "Rheumatologist",
            "Infectious disease specialist", "Oncologist", "General surgeon", "Cardiothoracic surgeon", "Neurosurgeon", "Orthopedic surgeon", "Urologist", "Plastic and reconstructive surgeon",
            "Gynecologist", "Obstetrician", "Reproductive endocrinologist", "Neonatologist", "Pediatrician", "Pediatric surgeon", "Ophthalmologist", "Otolaryngologist",
            "Dentist", "Dermatologist", "Psychiatrist", "Rehabilitation specialist", "Emergency physician", "Anesthesiologist", "Radiologist", "Ultrasonologist",
            "Nuclear medicine physician", "Clinical laboratory scientist", "Pathologist", "Pharmacist", "Physical therapist", "Transfusion medicine specialist"]

        patient's medical history = {case_presentation}

        When recommending the appropriate specialist, you need to complete the following steps:
            1. Carefully read the medical scenario presented in <patient's medical history>.
            2. Based on the medical scenario, calculate the relevance of each specialist in the <candidate_specialists> with <patient's medical history>, and select the top {top_k} most relevant specialists as top_k_specialists.

        The output must be formatted in JSON as follows:
            ```json
            {{
            "top_k_specialists": [top_k_specialist list],
            }}
            ```
            """.format(case_presentation=case_presentation, top_k=num_specialists)


def supervisor_system_message(use_specialist: bool, specialists: Optional[List[str]],
                              bug: str = "keep") -> str:
    if bug == "fix":
        return (SUPERVISOR_SPECIALISTS.format(specialists) if use_specialist
                else SUPERVISOR_DOCTORS.format())
    # upstream (swapped) behaviour
    return SUPERVISOR_DOCTORS if use_specialist else SUPERVISOR_SPECIALISTS.format(specialists)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def prase_json(text: str):
    """utils/utils.py prase_json (sic); returns None instead of raising."""
    text = text or ""
    try:
        for fence in ("```json", "```JSON"):
            if fence in text:
                m = re.search(re.escape(fence) + r"(.*?)```", text, re.DOTALL)
                return json.loads(m.group(1).strip()) if m else None
        if "```" in text:
            m = re.search(r"```(.*?)```", text, re.DOTALL)
            return json.loads(m.group(1).strip()) if m else None
        m = re.search(r"{.*?}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0).strip())
        return json.loads(text.strip("```json\n").strip("\n```"))
    except Exception:
        return None


def mentioned_agents(message_content: str, names: List[str]) -> Dict[str, int]:
    """GroupChat._mentioned_agents (AutoGen 0.2.32), verbatim logic."""
    mentions = {}
    for name in names:
        regex = (r"(?<=\W)(" + re.escape(name) + r"|" + re.escape(name.replace("_", " "))
                 + r"|" + re.escape(name.replace("_", r"\_")) + r")(?=\W)")
        count = len(re.findall(regex, f" {message_content} "))
        if count > 0:
            mentions[name] = count
    return mentions


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", t or "")).strip().lower()


def letter_from_value(v: Any, options: Dict[str, str]) -> Optional[str]:
    """Option letter named by a JSON value ("C", "C. text", "Option C", the option text)."""
    if v is None:
        return None
    if isinstance(v, list):
        v = v[0] if v else ""
    s = str(v).strip()
    m = re.match(r"^[\s\[\(\"'*]*(?:[Oo]ption\s*)?\(?([A-J])(?![A-Za-z])", s)
    if m and (not options or m.group(1) in options):
        return m.group(1)
    ns, best, blen = _norm(s), None, 0
    for k, t in (options or {}).items():
        nt = _norm(t)
        if len(nt) >= 4 and nt in ns and len(nt) > blen:
            best, blen = k, len(nt)
    return best


def supervisor_answer(text: str, options: Dict[str, str]) -> Tuple[Optional[str], Optional[dict]]:
    """(letter, parsed JSON) of a Supervisor message; the JSON field wins."""
    parsed = prase_json(text) if f'"{SUMMARY_KEY}":' in (text or "") else None
    if isinstance(parsed, dict) and SUMMARY_KEY in parsed:
        a = letter_from_value(parsed.get(SUMMARY_KEY), options)
        if a is not None:
            return a, parsed
    m = re.search(r'"' + SUMMARY_KEY + r'"\s*:\s*"([^"]*)"', text or "")
    if m:
        a = letter_from_value(m.group(1), options)
        if a is not None:
            return a, parsed if isinstance(parsed, dict) else None
    return None, parsed if isinstance(parsed, dict) else None


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(s).strip().replace(" ", "_")) or "Doctor"


class MAC_Main(MAS):
    """MAC group chat (upstream main.py; main_ws.py with use_specialist)."""

    def __init__(self, general_config, method_config_name="config_mac"):
        method_config_name = method_config_name or "config_mac"
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.num_doctors = int(mc.get("num_doctors", 4))
        self.n_round = int(mc.get("n_round", 8))
        self.max_retries_for_selecting_speaker = mc.get("max_retries_for_selecting_speaker")
        self.use_specialist = bool(mc.get("use_specialist", False))
        self.supervisor_prompt_bug = str(mc.get("supervisor_prompt_bug", "keep"))
        self.select_speaker_role = str(mc.get("select_speaker_role", "system"))
        self.speaker_name_in_content = bool(mc.get("speaker_name_in_content", False))
        self.consultant_temperature = mc.get("consultant_temperature", 0.0)

        self.conversation_history: List[Dict[str, Any]] = []
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None
        self.current_round: Optional[int] = None
        self._step_counter = 0

    # ------------------------------------------------------------------ #
    def _ask(self, role, role_index, phase, round_, agent_id, agent_label, messages,
             sources, source_how, event_ids=(), **kw) -> Tuple[str, str]:
        self.current_role, self.current_role_index = role, role_index
        self.current_phase, self.current_round = phase, round_
        resp = self.call_llm(messages=messages, **kw)
        resp = resp if resp is not None else ""
        sid = f"s{self._step_counter}"
        self._step_counter += 1
        srcs = list(dict.fromkeys(sources))
        self.conversation_history.append({
            "step_id": sid, "role": role, "role_index": role_index, "phase": phase,
            "round": round_, "agent_id": agent_id, "agent_label": agent_label,
            "event_ids": list(event_ids), "sources": srcs,
            "source_how": {k: v for k, v in source_how.items() if k in srcs},
            "content": resp,
        })
        return resp, sid

    def _set_structured(self, **kv):
        self.conversation_history[-1]["structured"] = kv

    def _max_attempts(self) -> int:
        r = self.max_retries_for_selecting_speaker
        if r is None:
            r = self.n_round // (1 + self.num_doctors)   # main.py:146
        return 1 + int(r)

    def _view_content(self, msg) -> str:
        if self.speaker_name_in_content:
            return f"{self.agents[msg['speaker']]['name']}: {msg['content']}"
        return msg["content"]

    # ------------------------------------------------------------------ #
    def _recruit_specialists(self, case_text: str) -> Tuple[List[str], Optional[str]]:
        """main_ws.py: Medical_Coordinator -> Senior_Medical_Consultant, max_turns=1
        (query_round 1), i.e. one consultant reply to the consultant message."""
        msgs = [{"role": "system", "content": CONSULTANT_SYSTEM_MESSAGE},
                {"role": "user", "content": get_consultant_message(case_text, self.num_doctors)}]
        kw = {}
        if self.consultant_temperature is not None:
            kw["temperature"] = float(self.consultant_temperature)
        resp, sid = self._ask("Consultant", 0, "specialist_recruit", None, "consultant",
                              "Senior_Medical_Consultant", msgs, [], {}, **kw)
        parsed = prase_json(resp)
        spec = parsed.get("top_k_specialists") if isinstance(parsed, dict) else None
        ok = isinstance(spec, list) and len(spec) == self.num_doctors   # upstream asserts this
        names = []
        if ok:
            for s in spec:
                n = _safe_name(s)
                while n in names:
                    n += "_2"
                names.append(n)
        else:
            names = [f"Doctor{i}" for i in range(self.num_doctors)]
        self._set_structured(specialists=list(spec) if isinstance(spec, list) else None,
                             parse_ok=ok, agent_names=list(names))
        return names, sid

    def _select_speaker(self, transcript, last_speaker: int, turn: int, extra_src) -> Tuple[int, str]:
        names = [a["name"] for a in self.agents]
        agentlist = f"{names}"
        roles = "\n".join(f"{a['name']}: {a['system']}".strip() for a in self.agents)
        msgs = [{"role": "system",
                 "content": SELECT_SPEAKER_MESSAGE_TEMPLATE.format(roles=roles, agentlist=agentlist)}]
        msgs += [{"role": "user", "name": names[m["speaker"]], "content": self._view_content(m)}
                 for m in transcript]
        msgs.append({"role": self.select_speaker_role,
                     "content": SELECT_SPEAKER_PROMPT_TEMPLATE.format(agentlist=agentlist)})
        read = [m["step_id"] for m in transcript if m["step_id"]]
        max_attempts = self._max_attempts()
        attempts = []
        for attempt in range(1, max_attempts + 1):
            how = {s: "verbatim" for s in read + attempts}
            how.update({s: "structured_field" for s in extra_src})
            resp, sid = self._ask("Selector", 0, "select_speaker", turn, "selector", "speaker_selection_agent",
                                  msgs, read + attempts + list(extra_src), how,
                                  event_ids=[f"turn{turn}"])
            mentions = mentioned_agents(resp.strip(), names)
            left = max_attempts - attempt
            if len(mentions) == 1:
                idx = names.index(next(iter(mentions)))
                self._set_structured(next_speaker=self.agents[idx]["agent_id"], valid=True,
                                     attempt=attempt, mentions=mentions, fallback=None)
                return idx, sid
            reason = "multiple" if mentions else "none"
            if left:
                tmpl = SELECT_SPEAKER_AUTO_MULTIPLE_TEMPLATE if mentions else SELECT_SPEAKER_AUTO_NONE_TEMPLATE
                msgs = msgs + [{"role": "assistant", "content": resp},
                               {"role": self.select_speaker_role, "content": tmpl.format(agentlist=agentlist)}]
                self._set_structured(next_speaker=None, valid=False, attempt=attempt,
                                     mentions=mentions, retry_reason=reason, fallback=None)
                attempts.append(sid)
                continue
            # attempts exhausted: GroupChat.next_agent(last_speaker) (round robin)
            idx = (last_speaker + 1) % len(self.agents)
            self._set_structured(next_speaker=self.agents[idx]["agent_id"], valid=False,
                                 attempt=attempt, mentions=mentions, retry_reason=reason,
                                 fallback="next_agent")
            return idx, sid
        raise RuntimeError("unreachable")

    def _speak(self, idx: int, transcript, sel_step: str, turn: int, extra_src) -> Tuple[str, str]:
        a = self.agents[idx]
        msgs = [{"role": "system", "content": a["system"]}]
        for m in transcript:
            if m["speaker"] == idx:
                msgs.append({"role": "assistant", "content": m["content"]})
            else:
                msgs.append({"role": "user", "name": self.agents[m["speaker"]]["name"],
                             "content": self._view_content(m)})
        read = [m["step_id"] for m in transcript if m["step_id"]]
        how = {s: "verbatim" for s in read}
        # specialist names (consultant output) enter via the system message
        # (doctors) or the other speakers' "name" fields
        names_seen = a["role"] == "Doctor" or any(m["speaker"] != idx for m in transcript) \
            or self.supervisor_prompt_bug == "fix"
        ext = list(extra_src) if names_seen else []
        how.update({s: "structured_field" for s in ext})
        how[sel_step] = "control"
        resp, sid = self._ask(a["role"], a["role_index"], a["phase"], turn, a["agent_id"], a["name"],
                              msgs, read + ext + [sel_step], how, event_ids=[f"turn{turn}"])
        terminate = resp.find("TERMINATE") >= 0
        if a["role"] == "Supervisor":
            ans, parsed = supervisor_answer(resp, self.options)
            if ans is None:
                ans = mcq_leaning(resp, self.options)
            self._set_structured(answer=ans, terminate=terminate, summary=parsed)
        else:
            self._set_structured(answer=mcq_leaning(resp, self.options), terminate=terminate)
        return resp, sid

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        query = sample["query"] if isinstance(sample, dict) else str(sample)
        self.conversation_history = []
        self._step_counter = 0
        stem, opts = parse_mcq_query(query)
        if isinstance(sample, dict) and sample.get("mcq_options"):
            stem = sample.get("mcq_question") or stem
            opts = dict(sample["mcq_options"])
        self.options = opts
        case_text = (stem + "\n\nOptions:\n" + "\n".join(f"{k}. {v}" for k, v in opts.items())) \
            if opts else query.strip()

        extra_src: List[str] = []
        if self.use_specialist:
            names, s_cons = self._recruit_specialists(case_text)
            extra_src = [s_cons]
        else:
            names = [f"Doctor{i}" for i in range(self.num_doctors)]
        self.agents = [{"name": n, "role": "Doctor", "role_index": i, "agent_id": f"doctor_{i}",
                        "phase": "discussion", "system": DOC_SYSTEM_MESSAGE.format(n)}
                       for i, n in enumerate(names)]
        self.agents.append({"name": "Supervisor", "role": "Supervisor", "role_index": 0,
                            "agent_id": "supervisor", "phase": "supervision",
                            "system": supervisor_system_message(
                                self.use_specialist, names if self.use_specialist else None,
                                self.supervisor_prompt_bug)})
        sup = len(self.agents) - 1

        # Supervisor.initiate_chat(manager, message=initial_message)
        transcript = [{"speaker": sup, "content": INITIAL_MESSAGE.format(case_text), "step_id": None}]
        speaker, terminated_by, order = sup, "max_round", []
        for i in range(self.n_round):                     # GroupChatManager.run_chat
            message = transcript[-1]
            if message["content"].find("TERMINATE") >= 0:
                terminated_by = "supervisor_terminate" if message["speaker"] == sup else "doctor_terminate"
                break
            if i == self.n_round - 1:
                break
            turn = i + 1
            speaker, sel_sid = self._select_speaker(transcript, speaker, turn, extra_src)
            reply, sid = self._speak(speaker, transcript, sel_sid, turn, extra_src)
            transcript.append({"speaker": speaker, "content": reply, "step_id": sid})
            order.append(self.agents[speaker]["agent_id"])

        # main.py:168-177: last Supervisor message carrying the summary JSON
        by_id = {h["step_id"]: h for h in self.conversation_history}
        final_sid, ans, final_source, final_srcs = None, None, "none", []
        for m in reversed(transcript[1:]):
            if m["speaker"] == sup and f'"{SUMMARY_KEY}":' in m["content"]:
                a, _ = supervisor_answer(m["content"], opts)
                if a is not None:
                    final_sid, ans, final_source = m["step_id"], a, "supervisor_json"
                    final_srcs = [m["step_id"]]
                    break
        if ans is None:
            latest = {}
            for m in transcript[1:]:
                if m["speaker"] != sup:
                    a = (by_id[m["step_id"]].get("structured") or {}).get("answer")
                    if a is not None:
                        latest[m["speaker"]] = (a, m["step_id"])
            if latest:
                cnt = Counter(a for a, _ in latest.values())
                top = max(cnt.values())
                for a, s in sorted(latest.values(), key=lambda x: int(x[1][1:]), reverse=True):
                    if cnt[a] == top:
                        ans = a
                        break
                final_source = "doctor_majority_fallback"
                final_srcs = [s for a, s in latest.values()]
        last_content = transcript[-1]["content"] if len(transcript) > 1 else ""
        if final_sid:
            last_content = by_id[final_sid]["content"]
        response = f"{last_content}\n\nFinal answer: {ans}" if ans else last_content
        return {
            "response": response,
            "history": list(self.conversation_history),
            "pred_answer": ans,
            "final_step_id": final_sid,
            "final_source": final_source,
            "final_source_step_ids": final_srcs,
            "terminated_by": terminated_by,
            "speaker_order": order,
            "num_speaker_turns": len(order),
            "agent_names": [a["name"] for a in self.agents],
        }
