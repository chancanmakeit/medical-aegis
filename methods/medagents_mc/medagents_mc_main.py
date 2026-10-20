"""
MedAgents (Multi-disciplinary Collaboration, "MC") re-implemented on the AEGIS
`MAS` base class.

Reference:
  Tang et al., "MedAgents: Large Language Models as Collaborators for Zero-shot
  Medical Reasoning", ACL 2024 Findings, arXiv:2311.10537.
  Source: https://github.com/gersteinlab/MedAgents  (utils.fully_decode,
  prompt_generator.py, data_utils.py)

Method name in AEGIS: `medagents_mc` -- deliberately distinct from `mdagents`
(MDAgents, Kim et al. 2024), which is a different framework.

Five stages (upstream `syn_verif` method, the paper's full framework):
  1. Expert gathering   : QuestionClassifier -> 5 question domains,
                          OptionClassifier   -> 2 option domains
  2. Analysis proposition: QuestionAnalyst x5 (reads the question),
                          OptionAnalyst   x2 (reads question + ALL question analyses)
  3. Report summarization: Synthesizer (reads all 7 analyses)
  4. Collaborative consultation (<= max_attempt_vote rounds):
        each of the 7 domain experts votes YES/NO on the current report;
        each NO-voter proposes revisions; a Reviser rewrites the report.
  5. Decision making     : Decider picks the option letter from the final report.

Faithfulness notes (kept on purpose so trajectories match upstream behaviour):
  - Prompt texts are copied verbatim from upstream prompt_generator.py.
  - Upstream quirk kept: in the option-analysis prompt the options/instructions
    block is appended INSIDE the loop over question analyses, so it is repeated
    once per question domain.
  - Upstream quirk kept: cleansing_syn_report tests `"Key Knowledge" in tmp`
    where tmp is a list, so Key Knowledge is (almost) always dropped from the
    report that downstream agents read.
  - Options are rendered as a Python dict string ({'A': '...', ...}) exactly as
    upstream does with MedQA-style samples.

Necessary adaptations (documented, minimal):
  - All LLM calls go through `self.call_llm` (AEGIS routing / retries / capture).
  - Temperature comes from the global config (upstream hard-codes 0) so that
    normal runs can be repeatedly sampled. Set model_temperature=0 to match.
  - Upstream per-stage max_tokens (30/50/300/500/2500) are only applied when
    `use_original_max_tokens: true`; they truncate reasoning models, so the
    default uses the global model_max_tokens.
  - Answer extraction accepts the letters actually present in the options
    (A-J for 10-option MMLU-Pro); upstream only recognises A-E. The decider
    prompt's "like A, B, C, D, or E" wording is kept verbatim.
  - cleansing_syn_report no longer crashes when "Total Analysis:" is missing
    (upstream raises IndexError); the whole output is used instead.
  - Upstream maps API failures to the literal "ERROR." and then substitutes
    defaults; here a failed call returns "" and the same defaults apply.

Injection contract (used by aegis_core/agent_systems/fm_medagents_mc_wrapper.py):
  Before every call_llm the method sets current_role / current_role_index /
  current_phase / current_round. Structural roles (stable across samples):
    QuestionClassifier(0), OptionClassifier(0),
    QuestionAnalyst(0..4), OptionAnalyst(0..1), Synthesizer(0),
    Voter(0..6)  [index into question_domains + option_domains],
    Advisor(0..6) [same index; only called when that voter says NO],
    Reviser(0), Decider(0)
  Voter/Advisor/Reviser may be invoked once per consultation round.

Read-set recording (`sources`):
  Every recorded step carries `step_id` and `sources` (the step_ids whose
  outputs were inserted into this step's prompt), recorded at prompt-assembly
  time, so downstream hypergraph construction need not guess via substring
  matching.
"""

import re
from string import punctuation
from typing import Any, Dict, List, Optional, Tuple

from methods.mas_base import MAS


NUM_QD = 5
NUM_OD = 2
_ALL_LETTERS = "ABCDEFGHIJ"

# Upstream per-stage token budgets (utils.fully_decode).
_ORIGINAL_MAX_TOKENS = {
    "question_domain": 50, "option_domain": 50,
    "question_analysis": 300, "option_analysis": 300,
    "synthesis": 2500, "vote": 30, "advice": 500,
    "revision": 2500, "decision": 2500,
}


# --------------------------------------------------------------------------- #
# Prompts (verbatim from upstream prompt_generator.py)
# --------------------------------------------------------------------------- #
def get_question_domains_prompt(question):
    question_domain_format = "Medical Field: " + " | ".join(["Field" + str(i) for i in range(NUM_QD)])
    question_classifier = "You are a medical expert who specializes in categorizing a specific medical scenario into specific areas of medicine."
    prompt_get_question_domain = f"You need to complete the following steps:" \
            f"1. Carefully read the medical scenario presented in the question: '''{question}'''. \n" \
            f"2. Based on the medical scenario in it, classify the question into five different subfields of medicine. \n" \
            f"3. You should output in exactly the same format as '''{question_domain_format}'''."
    return question_classifier, prompt_get_question_domain


def get_question_analysis_prompt(question, question_domain):
    question_analyzer = f"You are a medical expert in the domain of {question_domain}. " \
        f"From your area of specialization, you will scrutinize and diagnose the symptoms presented by patients in specific medical scenarios."
    prompt_get_question_analysis = f"Please meticulously examine the medical scenario outlined in this question: '''{question}'''." \
                        f"Drawing upon your medical expertise, interpret the condition being depicted. " \
                        f"Subsequently, identify and highlight the aspects of the issue that you find most alarming or noteworthy."
    return question_analyzer, prompt_get_question_analysis


def get_options_domains_prompt(question, options):
    options_domain_format = "Medical Field: " + " | ".join(["Field" + str(i) for i in range(NUM_OD)])
    options_classifier = f"As a medical expert, you possess the ability to discern the two most relevant fields of expertise needed to address a multiple-choice question encapsulating a specific medical context."
    prompt_get_options_domain = f"You need to complete the following steps:" \
                f"1. Carefully read the medical scenario presented in the question: '''{question}'''." \
                f"2. The available options are: '''{options}'''. Strive to understand the fundamental connections between the question and the options." \
                f"3. Your core aim should be to categorize the options into two distinct subfields of medicine. " \
                f"You should output in exactly the same format as '''{options_domain_format}'''"
    return options_classifier, prompt_get_options_domain


def get_options_analysis_prompt(question, options, op_domain, question_analysis):
    option_analyzer = f"You are a medical expert specialized in the {op_domain} domain. " \
                f"You are adept at comprehending the nexus between questions and choices in multiple-choice exams and determining their validity. " \
                f"Your task, in particular, is to analyze individual options with your expert medical knowledge and evaluate their relevancy and correctness."

    prompt_get_options_analyses = f"Regarding the question: '''{question}''', we procured the analysis of five experts from diverse domains. \n"
    for _domain, _analysis in question_analysis.items():
        prompt_get_options_analyses += f"The evaluation from the {_domain} expert suggests: {_analysis} \n"
        # Upstream quirk (kept): this block sits inside the loop.
        prompt_get_options_analyses += f"The following are the options available: '''{options}'''." \
                    f"Reviewing the question's analysis from the expert team, you're required to fathom the connection between the options and the question from the perspective of your respective domain, " \
                    f"and scrutinize each option individually to assess whether it is plausible or should be eliminated based on reason and logic. "\
                    f"Pay close attention to discerning the disparities among the different options and rationalize their existence. " \
                    f"A handful of these options might seem right on the first glance but could potentially be misleading in reality."
    return option_analyzer, prompt_get_options_analyses


def get_final_answer_prompt_wsyn(syn_report):
    prompt = f"Here is a synthesized report: {syn_report} \n" \
        f"Based on the above report, select the optimal choice to answer the question. \n" \
        f"Points to note: \n" \
        f"1. The analyses provided should guide you towards the correct response. \n" \
        f"2. Any option containing incorrect information inherently cannot be the correct choice. \n" \
        f"3. Please respond only with the selected option's letter, like A, B, C, D, or E, using the following format: '''Option: [Selected Option's Letter]'''. " \
        f"Remember, it's the letter we need, not the full content of the option."
    return prompt


def get_synthesized_report_prompt(question_analyses, option_analyses):
    synthesizer = "You are a medical decision maker who excels at summarizing and synthesizing based on multiple experts from various domain experts."
    syn_report_format = f"Key Knowledge: [extracted key knowledge] \n" \
                f"Total Analysis: [synthesized analysis] \n"
    prompt = f"Here are some reports from different medical domain experts.\n "
    prompt += f"You need to complete the following steps:" \
                f"1. Take careful and comprehensive consideration of the following reports." \
                f"2. Extract key knowledge from the following reports. " \
                f"3. Derive the comprehensive and summarized analysis based on the knowledge." \
                f"4. Your ultimate goal is to derive a refined and synthesized report based on the following reports." \
                f"You should output in exactly the same format as '''{syn_report_format}'''"
    prompt += question_analyses
    prompt += option_analyses
    return synthesizer, prompt


def get_consensus_prompt(domain, syn_report):
    voter = f"You are a medical expert specialized in the {domain} domain."
    cons_prompt = f"Here is a medical report: {syn_report} \n"\
        f"As a medical expert specialized in {domain}, please carefully read the report and decide whether your opinions are consistent with this report." \
        f"Please respond only with: [YES or NO]."
    return voter, cons_prompt


def get_consensus_opinion_prompt(domain, syn_report):
    opinion_prompt = f"Here is a medical report: {syn_report} \n"\
        f"As a medical expert specialized in {domain}, please make full use of your expertise to propose revisions to this report." \
        f"You should output in exactly the same format as '''Revisions: [proposed revision advice] '''"
    return opinion_prompt


def get_revision_prompt(syn_report, revision_advice):
    revision_prompt = f"Here is the original report: {syn_report}\n\n"
    for domain, advice in revision_advice.items():
        revision_prompt += f"Here is advice from a medical expert specialized in {domain}: {advice}.\n"
    revision_prompt += f"Based on the above advice, output the revised analysis in exactly the same format as '''Total Analysis: [revised analysis] '''"
    return revision_prompt


# --------------------------------------------------------------------------- #
# Cleansing helpers (upstream data_utils.py, with the noted robustness fixes)
# --------------------------------------------------------------------------- #
def _remove_incomplete_sentence(text: str) -> str:
    # Upstream uses nltk.sent_tokenize; a regex splitter avoids the nltk
    # punkt download and behaves the same on the cases that matter (drop a
    # trailing sentence that does not end with '.').
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if len(sentences) > 1 and sentences[-1][-1] != ".":
        return " ".join(sentences[:-1]) + "."
    return text


def cleansing_analysis(analyses, domains, type_):
    analysis = {}
    for i, item in enumerate(analyses):
        if not item:  # upstream: item == "ERROR."
            item = f"There is no analysis for this {type_}."
        item = _remove_incomplete_sentence(item)
        if "as an ai language model" in item.lower():
            end_index = item.lower().find("as an ai language model") + len("as an ai language model")
            item = item[end_index:].strip().strip(",").strip()
        # Duplicate domain names collapse in upstream's dict; keep that.
        analysis[domains[i]] = item
    return analysis


def cleansing_syn_report(question, options, raw_synthesized_report):
    tmp = (raw_synthesized_report or "").split("Total Analysis:")
    # Robustness fix: upstream indexes tmp[1] unconditionally.
    total_analysis_text = tmp[1].strip() if len(tmp) > 1 else tmp[0].strip()
    if "Key Knowledge" in tmp:  # upstream quirk kept (list membership)
        key_knowledge_text = tmp[0].split("Key Knowledge:")[-1].strip()
        return f"Question: {question} \n" \
            f"Options: {options} \n" \
            f"Key Knowledge: {key_knowledge_text} \n" \
            f"Total Analysis: {total_analysis_text} \n"
    return f"Question: {question} \n" \
        f"Options: {options} \n" \
        f"Total Analysis: {total_analysis_text} \n"


def cleansing_final_output(output: str, letters: str) -> str:
    pat = "|".join(letters)
    ans = re.findall(pat, (output or "").split(":")[-1])
    if ans:
        return ans[0]
    ans = re.findall(pat, output or "")
    return ans[-1] if ans else ""


def cleansing_voting(output: str) -> str:
    ans = re.findall(r"yes|no", (output or "").lower())
    return ans[0] if ans else "yes"


def transform_dict2text(analyses, type_, content):
    report = ""
    for i, (_domain, _analysis) in enumerate(analyses.items()):
        if type_ == "question":
            report += f"Report{i} \n" \
                f"Question: {content} \n" \
                f"Domain: {_domain} \n" \
                f"Analysis: {_analysis} \n\n"
        else:
            report += f"Report{i}: \n" \
                f"Options: {content} \n" \
                f"Domain: {_domain} \n" \
                f"Analysis: {_analysis} \n\n"
    return report


# --------------------------------------------------------------------------- #
# Query parsing: AEGIS converters fold question + options into one string.
# --------------------------------------------------------------------------- #
_OPT_LINE = re.compile(r"^\s*([A-J])[.)]\s+(.*\S)\s*$")
_INSTRUCTION_LINE = re.compile(r"^\s*Answer with the single best option letter", re.I)


def parse_mcq_query(query: str) -> Tuple[str, Dict[str, str]]:
    """Split an AEGIS MCQ query into (question_stem, {letter: option_text}).

    Handles both converter layouts:
      - "<stem>\\n\\nOptions:\\nA. ..\\nB. ..\\n\\nAnswer with ..." (MMLU-Pro etc.)
      - "<stem>\\nA. ..\\nB. ..\\n\\nAnswer with ..."             (MedConceptsQA)
    Falls back to (query, {}) when no option block is found.
    """
    lines = [l for l in (query or "").splitlines() if not _INSTRUCTION_LINE.match(l)]
    # The option block is the LAST run of consecutive "X. text" lines whose
    # letters are A, B, C, ... in order.
    best = None
    i = 0
    while i < len(lines):
        m = _OPT_LINE.match(lines[i])
        if m and m.group(1) == "A":
            j, opts = i, {}
            while j < len(lines):
                mj = _OPT_LINE.match(lines[j])
                if not mj or mj.group(1) != _ALL_LETTERS[len(opts)]:
                    break
                opts[mj.group(1)] = mj.group(2)
                j += 1
            if len(opts) >= 2:
                best = (i, opts)
            i = max(j, i + 1)
        else:
            i += 1
    if best is None:
        return (query or "").strip(), {}
    start, opts = best
    stem_lines = lines[:start]
    while stem_lines and stem_lines[-1].strip() in ("", "Options:"):
        stem_lines.pop()
    return "\n".join(stem_lines).strip(), opts


class MedAgentsMC_Main(MAS):
    """MedAgents multi-disciplinary collaboration (upstream `syn_verif`)."""

    def __init__(self, general_config, method_config_name="config_medical"):
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.max_attempt_vote = int(mc.get("max_attempt_vote", 3))
        self.use_original_max_tokens = bool(mc.get("use_original_max_tokens", False))

        self.conversation_history: List[Dict[str, Any]] = []
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None
        self.current_round: Optional[int] = None
        self._step_counter = 0

    # ------------------------------------------------------------------ #
    def _ask(self, role: str, role_index: int, phase: str, stage: str,
             prompt: str, system_prompt: Optional[str],
             sources: List[str], round_: Optional[int] = None,
             event_ids: Optional[List[str]] = None, agent_id: Optional[str] = None,
             source_how: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
        """call_llm with structural context; returns (response, step_id)."""
        self.current_role = role
        self.current_role_index = role_index
        self.current_phase = phase
        self.current_round = round_
        kwargs = {}
        if self.use_original_max_tokens:
            kwargs["max_tokens"] = _ORIGINAL_MAX_TOKENS[stage]
        # Upstream passes system_role="" for the reviser/decider: no system msg.
        resp = self.call_llm(prompt=prompt, system_prompt=system_prompt or None, **kwargs)
        resp = resp if resp is not None else ""
        step_id = f"s{self._step_counter}"
        self._step_counter += 1
        self.conversation_history.append({
            "step_id": step_id,
            "role": role,
            "role_index": role_index,
            "phase": phase,
            "round": round_,
            "event_ids": list(event_ids or []),
            "sources": list(sources),
            "content": resp,
            # stable across phases (MedHyperTrace spec v1.1): an expert keeps
            # its id from analysis through voting and advice
            "agent_id": agent_id or role.lower(),
        })
        if source_how:
            self.conversation_history[-1]["source_how"] = {
                k: v for k, v in source_how.items() if k in sources}
        return resp, step_id

    def _set_structured(self, **kv):
        self.conversation_history[-1]["structured"] = kv

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        query = sample["query"] if isinstance(sample, dict) else str(sample)
        self.conversation_history = []
        self._step_counter = 0

        stem, opt_dict = parse_mcq_query(query)
        if isinstance(sample, dict) and sample.get("mcq_options"):
            stem = sample.get("mcq_question") or stem
            opt_dict = dict(sample["mcq_options"])
        question = stem if (stem and stem[-1] in punctuation) else stem + "?"
        options: Any = opt_dict if opt_dict else ""
        letters = "".join(opt_dict.keys()) if opt_dict else "ABCDE"

        # ---- Stage 1: expert gathering --------------------------------- #
        sys_p, p = get_question_domains_prompt(question)
        raw_qd, s_qd = self._ask("QuestionClassifier", 0, "expert_gathering",
                                 "question_domain", p, sys_p, sources=[],
                                 agent_id="question_classifier")
        if not raw_qd:
            raw_qd = "Medical Field: " + " | ".join(["General Medicine"] * NUM_QD)
        question_domains = raw_qd.split(":")[-1].strip().split(" | ")
        self._set_structured(domains=list(question_domains))

        sys_p, p = get_options_domains_prompt(question, options)
        raw_od, s_od = self._ask("OptionClassifier", 0, "expert_gathering",
                                 "option_domain", p, sys_p, sources=[],
                                 agent_id="option_classifier")
        if not raw_od:
            raw_od = "Medical Field: " + " | ".join(["General Medicine"] * NUM_OD)
        options_domains = raw_od.split(":")[-1].strip().split(" | ")
        self._set_structured(domains=list(options_domains))
        # How each source enters a prompt: the classifiers contribute a domain
        # NAME (structured_field); analyses / reports pass through cleansing
        # (incomplete last sentence dropped, "Total Analysis" section cut), so
        # they enter as excerpts.
        SF, EX, VB = "structured_field", "excerpt", "verbatim"

        # ---- Stage 2: analysis proposition ----------------------------- #
        # The domain NAME produced by the classifier is inserted into the
        # analyst's system prompt, so the classifier step is a source.
        tmp_q, q_steps = [], []
        for i, dom in enumerate(question_domains):
            sys_p, p = get_question_analysis_prompt(question, dom)
            r, sid = self._ask("QuestionAnalyst", i, "question_analysis",
                               "question_analysis", p, sys_p, sources=[s_qd],
                               agent_id=f"q_expert_{i}", source_how={s_qd: SF})
            tmp_q.append(r); q_steps.append(sid)
        question_analyses = cleansing_analysis(tmp_q, question_domains, "question")
        # Steps whose analysis survived dict de-duplication (last writer wins).
        q_kept = {dom: q_steps[i] for i, dom in enumerate(question_domains)}

        tmp_o, o_steps = [], []
        for i, dom in enumerate(options_domains):
            sys_p, p = get_options_analysis_prompt(question, options, dom, question_analyses)
            r, sid = self._ask("OptionAnalyst", i, "option_analysis",
                               "option_analysis", p, sys_p,
                               sources=[s_od] + list(q_kept.values()),
                               agent_id=f"o_expert_{i}",
                               source_how={s_od: SF, **{q: EX for q in q_kept.values()}})
            tmp_o.append(r); o_steps.append(sid)
        option_analyses = cleansing_analysis(tmp_o, options_domains, "option")
        o_kept = {dom: o_steps[i] for i, dom in enumerate(options_domains)}

        # ---- Stage 3: report summarization ----------------------------- #
        q_text = transform_dict2text(question_analyses, "question", question)
        o_text = transform_dict2text(option_analyses, "options", options)
        sys_p, p = get_synthesized_report_prompt(q_text, o_text)
        raw_syn, s_syn = self._ask("Synthesizer", 0, "synthesis", "synthesis", p, sys_p,
                                   sources=list(q_kept.values()) + list(o_kept.values()),
                                   agent_id="synthesizer",
                                   source_how={x: EX for x in list(q_kept.values()) + list(o_kept.values())})
        syn_report = cleansing_syn_report(question, options, raw_syn)
        report_step = s_syn  # step whose output currently IS the report

        # ---- Stage 4: collaborative consultation ----------------------- #
        all_domains = question_domains + options_domains
        # Each voter's domain name comes from one of the two classifiers.
        dom_src = [s_qd] * len(question_domains) + [s_od] * len(options_domains)
        nq = len(question_domains)
        expert_id = [f"q_expert_{i}" for i in range(nq)] + \
                    [f"o_expert_{j}" for j in range(len(options_domains))]
        syn_repo_history, vote_history, revision_history = [syn_report], [], []
        hasno_flag, num_try = True, 0
        while num_try < self.max_attempt_vote and hasno_flag:
            num_try += 1
            hasno_flag = False
            vote_event = f"vote{num_try}"
            domain_opinions, revision_advice, advice_by_domain = {}, {}, {}
            for vi, domain in enumerate(all_domains):
                voter, cons_prompt = get_consensus_prompt(domain, syn_report)
                raw_v, s_v = self._ask("Voter", vi, "consensus_vote", "vote",
                                       cons_prompt, voter,
                                       sources=[report_step, dom_src[vi]],
                                       round_=num_try, event_ids=[vote_event],
                                       agent_id=expert_id[vi],
                                       source_how={report_step: EX, dom_src[vi]: SF})
                opinion = cleansing_voting(raw_v)
                self._set_structured(vote=opinion.upper() if opinion in ("yes", "no") else None,
                                     on_report_step=report_step)
                domain_opinions[domain] = opinion
                if opinion == "no":
                    advice_prompt = get_consensus_opinion_prompt(domain, syn_report)
                    adv, s_adv = self._ask("Advisor", vi, "revision_advice", "advice",
                                           advice_prompt, voter,
                                           sources=[report_step, dom_src[vi]],
                                           round_=num_try, event_ids=[vote_event],
                                           agent_id=expert_id[vi],
                                           source_how={report_step: EX, dom_src[vi]: SF})
                    # The advisor is the same expert who just voted NO; its
                    # prompt does not quote the vote, so the link is structural.
                    self._set_structured(responds_to_vote_step=s_v)
                    # Upstream keys advice by domain name: when a question expert
                    # and an option expert share a domain, the later advice
                    # replaces the earlier one in the reviser prompt. Keep that
                    # behaviour, and list only the advice the reviser really reads.
                    revision_advice[domain] = adv
                    advice_by_domain[domain] = s_adv
                    hasno_flag = True
            if hasno_flag:
                advice_steps = list(advice_by_domain.values())
                rev_prompt = get_revision_prompt(syn_report, revision_advice)
                revised, s_rev = self._ask("Reviser", 0, "revision", "revision",
                                           rev_prompt, None,
                                           sources=[report_step] + advice_steps,
                                           round_=num_try, event_ids=[vote_event],
                                           agent_id="reviser",
                                           source_how={report_step: EX, **{a: VB for a in advice_steps}})
                syn_report = cleansing_syn_report(question, options, revised)
                report_step = s_rev
                revision_history.append(revision_advice)
                syn_repo_history.append(syn_report)
            vote_history.append(domain_opinions)

        # ---- Stage 5: decision making ---------------------------------- #
        answer_prompt = get_final_answer_prompt_wsyn(syn_report)
        output, s_dec = self._ask("Decider", 0, "decision", "decision",
                                  answer_prompt, None, sources=[report_step],
                                  agent_id="decider", source_how={report_step: EX})
        ans = cleansing_final_output(output, letters)
        self._set_structured(answer=ans or None)

        # The verifier reads `response`; keep upstream's raw decider output
        # and make the chosen letter explicit for robust extraction.
        response = f"{output}\n\nFinal answer: {ans}" if ans else output
        return {
            "response": response,
            "history": list(self.conversation_history),
            "pred_answer": ans,
            "question_domains": question_domains,
            "option_domains": options_domains,
            "vote_history": vote_history,
            "revision_history": revision_history,
            "num_consultation_rounds": num_try,
            "final_step_id": s_dec,
        }
