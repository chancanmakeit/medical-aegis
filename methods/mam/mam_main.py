"""
MAM (Modular Multi-Agent framework for Multi-modal medical diagnosis)
re-implemented on the AEGIS `MAS` base class, for AUDIO inputs.

Reference:
  Zhou et al., "MAM: Modular Multi-Agent Framework for Multi-Modal Medical
  Diagnosis via Role-Specialized Collaboration", ACL 2025 Findings,
  arXiv:2506.19835. Source: https://github.com/yczhou001/MAM
  (inference.py, pipeline/*.py, model/language_model.py, model/audio_model.py)

Per-sample flow (upstream run_pipeline with step_id=9, audio modality):
  1. modality_selection   : file extension -> "audio" (deterministic, no LLM)
  2. type_classification  : AUDIO model, "What kind of audio is this?
                            Cardiovascular, Respiratory"            -> type_name
  3. role_generation      : TEXT model (General Practitioner) writes a role
                            prompt; upstream regex keeps <= 3 roles
  4. web_search_check     : AUDIO model describes the audio, then Google
                            search + TEXT summary.  (see "Search" below)
  5. load_history         : cross-sample memory                (see "Memory")
  6. roles_meeting        : up to 3 rounds; per round
       for each role: discuss (AUDIO) -> Moderator quality check (TEXT,
         "any errors? yes/no"); on "yes" the role discusses again and the new
         text replaces the old one;
       Moderator summary (TEXT) over ALL discussions so far;
       each role votes yes/no on the summary (AUDIO); stop when nobody
       disagrees, or after round 3.
     Specialists never see each other's text; only the Moderator's summary
     reads all discussions, and only the votes read the summary.
  7. final_diagnosis      : AUDIO model reads the question + meeting record
                            (round summaries + vote counts)      -> answer
  8. review               : AUDIO model yes/no check of the diagnosis
                            (logged only; does not change the answer)
  9. memory               : appends the diagnosis to a history file (disabled)

Faithfulness notes:
  - Prompts are copied verbatim from upstream (including typos such as
    "summery" / "rollowing" and the 4-space indentation inside the f-strings).
  - TEXT calls use upstream MedicalAssistant's system message; AUDIO calls use
    Qwen-Audio-Chat's default system prompt ("You are a helpful assistant.")
    and no history, exactly one audio + one text part, audio first.
  - Upstream decisions on model text are kept: determine() = "yes" substring,
    vote counted as agree if "yes" in output, elif "no" -> disagree, else agree.
  - Role extraction uses upstream's regex and its first-3 rule.

Necessary adaptations (documented):
  - Models: upstream runs local Medichat-Llama3-8B (text) and Qwen-Audio-Chat
    (audio). Here both are API models: `audio_model_name` (default: the run's
    model) and `text_model_name` (default: the run's model). User decision
    2026-10-20: audio backend = mimo-v2.6-flash.
  - Search: no Google API in this environment. Upstream wraps the whole
    search step in try/except and continues with search_result = "" on
    failure; we reproduce that failure path: the audio-description call is
    made (it precedes the search upstream), the search itself is recorded as a
    TOOL step with an empty result and `stub: true`, and the TEXT summary call
    is skipped (it is never reached on failure upstream).
    `web_search: "skip"` drops the whole step instead.
  - Memory: upstream reads the last 3 diagnoses of PREVIOUS samples from a
    JSON history file and writes each new one back, i.e. samples are not
    independent and an injected diagnosis would leak into later samples.
    Disabled by default (`use_memory: false`), so history_item = "" exactly as
    on a fresh upstream install.
  - max_new_tokens (512 / 2560 / 256) only with `use_original_max_tokens`.
  - Temperature: global config (upstream: model defaults).

Injection contract (fm_mam_wrapper.py): structural roles
  TypeClassifier(0), RoleGenerator(0), AudioDescriber(0),
  Specialist(0..2)  phases "discussion" (round k, possibly twice per round
                    after a failed quality check) and "vote" (round k),
  Moderator(0)      phases "quality_check" (round k) and "summary" (round k),
  Diagnostician(0), Reviewer(0)
Targets can pin `phase` / `round` (StructuredFMWrapper).

Recorded per step: step_id, agent_id (stable across phases: specialist_i,
moderator, ...), role, role_index, phase, round, event_ids, sources,
source_how, observations (["audio"] when the clip was attached), structured
(vote / quality-check verdict / type), content. The search is an `is_tool`
entry with `tool_calls`.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from methods.mas_base import MAS

TEXT_SYSTEM = '''
        You are an AI Medical Assistant trained on a vast dataset of health information. Please be thorough and
        provide an informative answer. If you don't know the answer to a specific medical inquiry, advise seeking professional help.
        '''
AUDIO_SYSTEM = "You are a helpful assistant."

_ORIGINAL_MAX_TOKENS = {"discuss": 512, "determine": 512, "summarize": 2560, "vote": 512,
                        "search_summary": 256, "default": 512}


# --------------------------------------------------------------------------- #
# Prompts (verbatim from upstream pipeline/*.py)
# --------------------------------------------------------------------------- #
def get_discuss_prompt(role_name, role_responsibilities, question, disease_type):
    prompt = f'''You are a {role_name}, responsible for the following tasks: {role_responsibilities}. Please thoughtfully express your views for the following question.
    Input:
    **Question type**: {disease_type}.
    **Question**: {question}.

    Example output:
    **Assessment Steps**:
    - Initial Assessment: [Provide a detailed overview of the initial assessment process]
    - Diagnostic Studies (e.g., imaging, lab tests): [Include relevant details about any studies conducted]
    - Additional Considerations: [Mention any other pertinent factors or evaluations]
    **Possible Answers**:
    - Answer 1: [Briefly explain answer 1]
      Reasoning: [Briefly describe the corresponding reason for answer 1]
    - Answer 2: [Briefly explain answer 2]
      Reasoning: [Briefly describe the corresponding reason for answer 2]
    - Answer 3: [Briefly explain answer 3]
      Reasoning: [Briefly describe the corresponding reason for answer 3]
    **Conclusion**: [Summarize the findings and provide a final recommendation or insight]
    '''
    return prompt


def get_summarize_prompt(question, discussion):
    prompt = f'''You are a specialized doctor serving as the moderator of this meeting. Please provide a detailed summary of the discussions that have taken place.

    Example output:
    **Possible Answers**:
    - Answer 1: [Briefly explain answer 1]
    - Answer 2: [Briefly explain answer 2]
    - Answer 3: [Briefly explain answer 3]
    **Agreements**:
    - [Description of any agreements reached]
    **Disagreements**:
    - [Description of any disagreements that were noted]
    **Conclusions**:
    - [Final thoughts or conclusions drawn from the discussion]

    Input: The question is {question}. The previous discussion of the meeting includes: {discussion}.
    '''
    return prompt


def get_vote_prompt(role_name, role_responsibilities, question, summary):
    prompt = f'''You are a {role_name}, responsible for the following tasks: {role_responsibilities}.
    Please answer just using "yes" or "no" according to the following questions and the corresponding summery and the contents of the given file(if any).
    Input: The question is {question}, and the summery of the discussion is:
    {summary}
    Do you agree with the summery above? Please answer just using "yes" or "no".
    '''
    return prompt


def get_determine_prompt(dis):
    prompt = f'''
    Question: Is there any medical reasoning errors, redundant statements, or invalid outputs in the following paragraph? Please answer just using "yes" or "no".
    Please read the rollowing paragraph:
    {dis}
    '''
    return prompt


def get_role_generation_prompts(disease_type, modality_type, question):
    system_prompt = f"Given a disease type, generate a system prompt that assigns tasks to relevant medical roles, including **Specialist Doctor**, **Radiologic Technologist**, etc, from the perspective of a General Practitioner."
    user_prompt = f'''Input: The modality type is {modality_type}, the disease type is {disease_type}, and the patient question is {question}.
    Output:
    A system prompt that:
        Identifies the relevant Specialist Doctor(s), Radiologic Technologist(s), and other Specialist(s) for the given disease type.
        Assigns tasks to each identified role, specifying the necessary actions, tests, or examinations required for diagnosis and treatment.

    Output example:
        **Specialist Doctor** (Pulmonologist):
        - Assess Patient's Health: Evaluate patient's function and overall health
        - Use {modality_type} Studies: Utilize expertise in the {disease_type} domains to diagnose diseases
        - Analyze Patient History and Symptoms: Determine the cause and severity of diseases by analyzing patient's medical history and symptoms
    '''
    # upstream: assistant.generate_response(system_prompt + "\n" + user_prompt)
    return system_prompt + "\n" + user_prompt


def get_audio_describe():
    prompt = f'''
    Please describe this audio:
    '''
    return prompt


def get_diagnosis_prompt(ques, record):
    prompt = f'''
    Input: Based on the provided image/video/audio (if applicable) and the meeting record, please provide answer to the following question.

    Question: {ques}.

    Meeting record: {record}
    '''
    return prompt


def get_review_prompt(ques, record):
    prompt = f'''
    Input: You're a medical assistant. Please check whether the answer to this question is reasonable, if it is, please answer "yes", if not, please answer "no"

    Question: {ques}.

    Answer: {record}
    '''
    return prompt


TYPE_QUERY_AUDIO = 'Please answer with a single word: What kind of audio is this? Cardiovascular, Respiratory'


def extract_roles_from_text(text):
    """Upstream meeting.extract_roles_from_text: (name, responsibilities) of the first 3 matches."""
    role_pattern = r"\*\*(.*?)\*\*(.*?):\n(.*?)(?=\n\*\*|$)"
    matches = re.findall(role_pattern, text or "", re.DOTALL)
    roles = []
    for i, (n, name, responsibilities) in enumerate(matches):
        if i < 3:
            roles.append((n + name, responsibilities))
    return roles


class MAM_Main(MAS):
    """MAM for audio diagnosis (Heartbeat / Sound-Dr)."""

    def __init__(self, general_config, method_config_name="config_audio"):
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.audio_model_name = mc.get("audio_model_name") or None   # None -> run's model
        self.text_model_name = mc.get("text_model_name") or None
        self.max_rounds = int(mc.get("max_rounds", 3))
        self.web_search = mc.get("web_search", "fail")              # fail | skip
        self.use_memory = bool(mc.get("use_memory", False))
        self.use_original_max_tokens = bool(mc.get("use_original_max_tokens", False))
        self.conversation_history: List[Dict[str, Any]] = []
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None
        self.current_round: Optional[int] = None
        self._step_counter = 0
        self._audio: Optional[str] = None

    # ------------------------------------------------------------------ #
    def _record(self, entry: Dict[str, Any]) -> str:
        sid = f"s{self._step_counter}"
        self._step_counter += 1
        entry = {"step_id": sid, **entry}
        self.conversation_history.append(entry)
        return sid

    def _ask(self, role, role_index, phase, agent_id, prompt, *, audio: bool, sources=(),
             round_=None, event_ids=None, stage="default", source_how=None, agent_label=None) -> Tuple[str, str]:
        self.current_role, self.current_role_index = role, role_index
        self.current_phase, self.current_round = phase, round_
        kwargs = {}
        if self.use_original_max_tokens:
            kwargs["max_tokens"] = _ORIGINAL_MAX_TOKENS.get(stage, 512)
        if audio:
            resp = self.call_llm(prompt=prompt, system_prompt=AUDIO_SYSTEM,
                                 model_name=self.audio_model_name, audios=[self._audio], **kwargs)
        else:
            resp = self.call_llm(prompt=prompt, system_prompt=TEXT_SYSTEM,
                                 model_name=self.text_model_name, **kwargs)
        resp = resp if resp is not None else ""
        entry = {"agent_id": agent_id, "role": role, "role_index": role_index, "phase": phase,
                 "agent_label": agent_label or agent_id, "round": round_,
                 "event_ids": list(event_ids or []), "sources": list(dict.fromkeys(sources)),
                 "observations": ["audio"] if audio else [], "content": resp}
        if source_how:
            entry["source_how"] = dict(source_how)
        sid = self._record(entry)
        return resp, sid

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        self.conversation_history, self._step_counter = [], 0
        question = sample["query"]
        self._audio = sample["audio_path"]
        modality_type = "audio"  # step 1: upstream modality_selection by extension (.wav)

        # ---- step 2: type classification (audio) ------------------------ #
        type_name, s_type = self._ask("TypeClassifier", 0, "type_classification", "type_classifier",
                                      TYPE_QUERY_AUDIO, audio=True)
        type_name = str(type_name)  # upstream parse_type_result for a non-tuple
        self.conversation_history[-1]["structured"] = {"type": type_name.strip()}

        # ---- step 3: role generation (text) ----------------------------- #
        roles_generated, s_roles = self._ask(
            "RoleGenerator", 0, "role_generation", "general_practitioner",
            get_role_generation_prompts(type_name, modality_type, question),
            audio=False, sources=[s_type])
        roles = extract_roles_from_text(roles_generated)
        self.conversation_history[-1]["structured"] = {"roles": [r[0] for r in roles]}

        # ---- step 4: web search check ------------------------------------ #
        search_result = ""
        if self.web_search != "skip":
            describe, s_desc = self._ask("AudioDescriber", 0, "web_search", "audio_describer",
                                         get_audio_describe(), audio=True)
            qq = describe + question
            self._record({"agent_id": "web_search_tool", "role": "WebSearch", "role_index": 0,
                          "phase": "web_search", "agent_label": "GoogleSearchAPI", "round": None,
                          "event_ids": [], "sources": [s_desc], "observations": [], "is_tool": True,
                          "tool_calls": [{"name": "GoogleSearchAPI.response",
                                          "arguments": {"method": "text", "max_results": 3, "query": qq},
                                          "result": None, "error": "search unavailable (stub)"}],
                          "stub": True, "content": ""})
            # upstream: exception -> search_result = '' and the TEXT summary is never called

        # ---- step 5: history ----------------------------------------------- #
        history_item = ""  # use_memory=False (see module docstring)
        if search_result:
            history_item = f"Web search reference:\n{search_result}\n\nHistory reference:\n{history_item}"

        # ---- step 6: meeting ---------------------------------------------- #
        record_all, meeting_sources, meeting_how, vote_log = self._meeting(
            roles, question, type_name, history_item, s_roles, s_type)

        # ---- step 7: final diagnosis (audio) ------------------------------ #
        diagnosis, s_diag = self._ask("Diagnostician", 0, "diagnosis", "diagnostician",
                                      get_diagnosis_prompt(question, record_all), audio=True,
                                      sources=meeting_sources, source_how=meeting_how)

        # ---- step 8: review (audio) --------------------------------------- #
        review, _ = self._ask("Reviewer", 0, "review", "reviewer",
                              get_review_prompt(question, diagnosis), audio=True, sources=[s_diag])
        self.conversation_history[-1]["structured"] = {"verdict": "yes" if "yes" in review.lower() else (
            "no" if "no" in review.lower() else None)}

        # ---- step 9: memory -------------------------------------------------- #
        # disabled (use_memory=False)

        return {"response": diagnosis, "history": list(self.conversation_history),
                "final_step_id": s_diag, "roles": [r[0] for r in roles], "type_name": type_name,
                "vote_log": vote_log, "review": review, "meeting_record": record_all}

    # ------------------------------------------------------------------ #
    def _meeting(self, roles, question, type_name, history_item, s_roles, s_type):
        """Upstream discussion_and_voting; returns (record_all, sources, source_how, votes)."""
        history_information = f"\n The following is the relevant information that can be used as a reference：{history_item}"
        record_all = ""
        record_discussions = "Record of discussion:\n"
        disc_steps: List[str] = []          # discussion steps whose text is in record_discussions
        summary_steps: List[str] = []
        vote_steps: List[str] = []
        vote_log = []
        for round_number in range(1, self.max_rounds + 1):
            ev = [f"meeting{round_number}"]
            for ri, (name, resp_) in enumerate(roles):
                aid = f"specialist_{ri}"
                out, s_d = self._ask("Specialist", ri, "discussion", aid,
                                     get_discuss_prompt(name, resp_, question, type_name), audio=True,
                                     sources=[s_roles, s_type], round_=round_number, event_ids=ev,
                                     agent_label=name, source_how={s_roles: "excerpt"})
                dis = f"{name} discussed:\n {out}\n"
                det, s_q = self._ask("Moderator", 0, "quality_check", "moderator",
                                     get_determine_prompt(dis), audio=False, sources=[s_d],
                                     round_=round_number, event_ids=ev, stage="determine")
                flagged = "yes" in det.lower()
                self.conversation_history[-1]["structured"] = {"errors_found": flagged, "about_step": s_d}
                if flagged:
                    out, s_d = self._ask("Specialist", ri, "discussion", aid,
                                         get_discuss_prompt(name, resp_, question, type_name), audio=True,
                                         sources=[s_roles, s_type], round_=round_number, event_ids=ev,
                                         agent_label=name, source_how={s_roles: "excerpt"})
                    self.conversation_history[-1]["structured"] = {"redo_after": s_q}
                    dis = f"{name} discussed:\n {out}\n"
                record_discussions += dis
                disc_steps.append(s_d)
            record_discussions += history_information
            summ, s_sum = self._ask("Moderator", 0, "summary", "moderator",
                                    get_summarize_prompt(question, record_discussions), audio=False,
                                    sources=list(disc_steps), round_=round_number, event_ids=ev,
                                    stage="summarize")
            summary = "Summary of discussions:\n" + summ
            summary_steps.append(s_sum)
            record_all += "Summary of discussions:\n"
            record_all += f"{summary}\n"
            agree, disagree = 0, 0
            for ri, (name, resp_) in enumerate(roles):
                v, s_v = self._ask("Specialist", ri, "vote", f"specialist_{ri}",
                                   get_vote_prompt(name, resp_, question, summary), audio=True,
                                   sources=[s_sum, s_roles], round_=round_number, event_ids=ev,
                                   stage="vote", agent_label=name, source_how={s_roles: "excerpt"})
                lv = v.lower()
                if "yes" in lv:
                    agree += 1; vv = "yes"
                elif "no" in lv:
                    disagree += 1; vv = "no"
                else:
                    agree += 1; vv = "yes(default)"
                self.conversation_history[-1]["structured"] = {"vote": vv, "on_summary": s_sum}
                vote_steps.append(s_v)
            vote_log.append({"round": round_number, "agree": agree, "disagree": disagree})
            record_all += f"Votes: agree number: {agree}, disagree number: {disagree}\n"
            if disagree == 0:
                record_all += "All roles agree on the diagnosis."
                break
            elif round_number == self.max_rounds:
                record_all += "Reached maximum discussion rounds.\n"
                if agree > disagree:
                    record_all += "The minority is subordinate to the majority, and the opinion of the meeting is carried"
                break
            else:
                record_all += "Not all roles agree, continuing discussion."
        sources = summary_steps + vote_steps
        how = {s: "structured_field" for s in vote_steps}  # only vote COUNTS enter the record
        return record_all, sources, how, vote_log
