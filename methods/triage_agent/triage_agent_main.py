"""
TriageAgent (Lu et al., "TriageAgent: Towards Better Multi-Agents
Collaborations for Large Language Model-Based Clinical Triage", EMNLP 2024
Findings) on the AEGIS `MAS` base class, for ESI 1-5 emergency triage.

Source: the user's reproduction chancanmakeit/TriageAgent (src/agents.py,
src/rag.py, src/config.py; HEAD fdec6ee). The original authors released no
code; that reproduction rebuilt the 5-stage pipeline from the paper. This port
follows it line by line; prompts are copied verbatim.

Per-case flow (upstream classify_case):
  0. retrieval   : TF-IDF top-3 over ESI Handbook v4, query = vignette, shared
                   by all agents. Precomputed by
                   data_processing/triage/convert_triage_dataset.py (identical
                   hits to upstream, verified on all 216 cases) and recorded
                   here as an `is_tool` step.
  1. Doctor A    : coarse HIGH {1,2,3} / LOW {3,4,5}; unparsable -> HIGH.
  2. Doctor B    : refines to an exact level within A's coarse group (reads A's
                   coarse class + confidence).
  3. Doctor C    : direct ESI 1-5.
  4. Summarizer  : reads the three reports (full text + parsed values).
  5. Discussion  : up to `max_discuss_rounds` (5) rounds. Agents speak in order
                   A, B, C; each sees the summary and the CURRENT positions of
                   the other ACTIVE agents (so later speakers in a round see
                   earlier speakers' updates of that same round). Doctor A
                   enters with Doctor B's level. Exit (a): an agent repeating
                   its level with confidence >= 90 both times leaves; stop (b):
                   all active agents agree with confidence >= 90; also stops on
                   agreement without high confidence, or when nobody is left.
  6. Consensus   : coordinator reads all final positions. Unparsable -> the
                   most confident doctor's level; none -> summarizer's
                   suggestion.

Necessary adaptations (documented):
  - Answer parsing reads the reply CONTENT only. Upstream parses
    reasoning + content concatenated, so a level mentioned while thinking can
    be taken as the answer (e.g. "ESI 1, 2, 3" in the reasoning). The reasoning
    text is still recorded per step (`llm_meta.reasoning`, StructuredFMWrapper).
  - Summarizer's suggested level reads "Suggested ESI level:" first, then the
    upstream extractor (upstream's first-match regex can pick a doctor's level
    quoted earlier in the summary). Only used as the last-resort fallback.
  - Generation settings: the run's global temperature / max_tokens. Upstream
    uses temperature 0.9 and 1024/2048 token budgets; set
    `use_original_max_tokens: true` for the latter (with a reasoning backbone
    they truncated ~51% of upstream's calls).
  - Models: any model_api_config backend (upstream: ling-3.0-flash).

Injection contract (fm_triage_agent_wrapper.py): roles
  Doctor(0) = Doctor A, Doctor(1) = Doctor B, Doctor(2) = Doctor C
             phases "classify" and "discuss" (round k),
  Summarizer(0) phase "summarize", Coordinator(0) phase "consensus".

Recorded per step: step_id, agent_id (doctor_a / doctor_b / doctor_c /
summarizer / coordinator / esi_rag_tool; stable across phases), role,
role_index, phase, round, sources, source_how, structured (coarse class or
ESI level, confidence, changed / exited for discussion), content.
"""

import re
from typing import Any, Dict, List, Optional

from methods.mas_base import MAS

DOCTORS = [("Doctor A", "doctor_a"), ("Doctor B", "doctor_b"), ("Doctor C", "doctor_c")]

_ORIGINAL_MAX_TOKENS = {"classify": 1024, "summarize": 2048, "discuss": 1024, "consensus": 1024}

ANSWER_FORMAT = """Reply in exactly this format:
ESI level: <1|2|3|4|5>
Confidence: <0-100>%
Rationale: <1-3 sentences>
References: <ESI Handbook citations, e.g. Chapter 2, p. 10-13>"""


# --------------------------------------------------------------------------- #
# Prompts (verbatim from upstream src/agents.py)
# --------------------------------------------------------------------------- #
def _self_check_instruction() -> str:
    return ("Follow a two-round self-check: propose your answer, then "
            "double-check it against the ESI Handbook excerpts and the "
            "clinical record before giving the final answer.")


def doctor_a_prompt(vignette, evidence):
    return [
        {"role": "system",
         "content": "You are Doctor A, an experienced emergency department "
                    "triage physician."},
        {"role": "user", "content": f"""TASK (coarse classification): decide whether the clinical case below is HIGH acuity or LOW acuity.
- HIGH acuity covers ESI levels 1, 2, 3.
- LOW acuity covers ESI levels 3, 4, 5.
(ESI level 3 belongs to both; use your best judgment.)

{_self_check_instruction()}
Use the ESI Handbook excerpts as evidence.

ESI Handbook excerpts:
{evidence}

Clinical record:
{vignette}

Reply in exactly this format:
Coarse class: <HIGH|LOW>
Confidence: <0-100>%
Rationale: <1-3 sentences>
References: <handbook citations, e.g. Chapter 2, p. 10-13>"""},
    ]


def doctor_b_prompt(vignette, evidence, coarse, coarse_conf):
    allowed = "1, 2, 3" if coarse == "HIGH" else "3, 4, 5"
    return [
        {"role": "system",
         "content": "You are Doctor B, an experienced emergency department "
                    "triage physician."},
        {"role": "user", "content": f"""Doctor A performed a coarse classification: {coarse} (confidence {coarse_conf}%).

TASK (fine-grained refinement): assign the exact ESI level for the clinical case below.
- Since the coarse class is {coarse}, choose from ESI levels {allowed}.

{_self_check_instruction()}
Use the ESI Handbook excerpts as evidence.

ESI Handbook excerpts:
{evidence}

Clinical record:
{vignette}

{ANSWER_FORMAT}"""},
    ]


def doctor_c_prompt(vignette, evidence):
    return [
        {"role": "system",
         "content": "You are Doctor C, an experienced emergency department "
                    "triage physician."},
        {"role": "user", "content": f"""TASK (direct fine-grained classification): assign the ESI level (1-5) for the clinical case below directly.

{_self_check_instruction()}
Use the ESI Handbook excerpts as evidence.

ESI Handbook excerpts:
{evidence}

Clinical record:
{vignette}

{ANSWER_FORMAT}"""},
    ]


def summarizer_prompt(vignette, reports):
    body = "\n\n".join(
        f"{name} report:\n{rep['text']}\n(Parsed: {rep['parsed']})"
        for name, rep in reports.items())
    return [
        {"role": "system",
         "content": "You are a clinical report summarizer. Synthesize the "
                    "triage doctors' analyses into one consolidated report."},
        {"role": "user", "content": f"""Synthesize the three doctors' ESI classifications for the case below into a single report.

{body}

Clinical record:
{vignette}

Produce the report in exactly this format:
Key information: <clinical facts and handbook references>
Confidence scores: <each doctor's ESI level and confidence>
Rationales: <each doctor's rationale in one line>
Consolidated analysis: <2-4 sentences weighing all evidence>
Suggested ESI level: <1-5>"""},
    ]


def discussion_prompt(name, role, vignette, summary, my_level, my_conf, peers):
    peer_text = "\n".join(
        f"- {p['name']}: ESI level {p['level']}, confidence {p['confidence']}%. "
        f"Rationale: {p['rationale']}" for p in peers)
    return [
        {"role": "system",
         "content": f"You are {name}, {role}."},
        {"role": "user", "content": f"""The team is discussing the ESI classification of the case below.

Clinical record:
{vignette}

Team summary report:
{summary}

Your colleagues' latest positions:
{peer_text}

Your current position: ESI level {my_level}, confidence {my_conf}%.

TASK: critically review the summary report and your colleagues' classifications, reasoning and confidence scores.
- If a colleague's reasoning persuades you, or their confidence is higher than yours, you may UPDATE your ESI level to theirs (explain why).
- Otherwise KEEP your level and justify why you reject their reasoning.
{_self_check_instruction()}

Reply in exactly this format:
ESI level: <1-5>
Confidence: <0-100>%
Changed: <yes|no>
Rationale: <1-3 sentences justifying keep/update>"""},
    ]


def consensus_prompt(vignette, finals):
    pos = "\n".join(
        f"- {p['name']}: ESI level {p['level']}, confidence {p['confidence']}%. "
        f"Rationale: {p['rationale']}" for p in finals)
    return [
        {"role": "system",
         "content": "You are the consensus coordinator of the triage team. "
                    "Your decision is final."},
        {"role": "user", "content": f"""The triage team finished discussing the case below. Determine the single final ESI level.

Clinical record:
{vignette}

Final positions:
{pos}

If the doctors agree, confirm their level. Otherwise weigh the confidence scores and rationales - prefer the most confident, best-evidenced positions - and decide the final ESI level.
{_self_check_instruction()}

{ANSWER_FORMAT}
Final justification: <one sentence>"""},
    ]


def format_evidence(hits):
    return "\n".join(f"[ESI Handbook v4, p. {h['page']}] {h['text']}" for h in hits)


# --------------------------------------------------------------------------- #
# Parsing (upstream src/llm_client.py + src/agents.py)
# --------------------------------------------------------------------------- #
def extract_esi_level(text: str) -> Optional[int]:
    m = re.search(r"ESI\s*level\s*:\s*([1-5])", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"final[^.\n]{0,80}?ESI[^0-9]{0,10}([1-5])", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"ESI\s*[-–]?\s*([1-5])\b", text)
    if m:
        return int(m.group(1))
    return None


def extract_confidence(text: str) -> Optional[int]:
    m = re.search(r"Confidence(?:\s+score)?\s*:\s*(\d{1,3})\s*%?", text, re.I)
    if m:
        return max(0, min(100, int(m.group(1))))
    m = re.search(r"(\d{1,3})\s*%\s*confidence", text, re.I)
    if m:
        return max(0, min(100, int(m.group(1))))
    return None


def parse_coarse(text: str) -> Optional[str]:
    m = re.search(r"Coarse\s*class\s*:\s*(HIGH|LOW)", text, re.I)
    return m.group(1).upper() if m else None


def rationale_of(text: str) -> str:
    m = re.search(r"Rationale\s*:\s*(.+)", text, re.I | re.S)
    if not m:
        return ""
    return " ".join(m.group(1).split())[:400]


def suggested_level(text: str) -> Optional[int]:
    m = re.search(r"Suggested\s*ESI\s*level\s*:\s*([1-5])", text, re.I)
    return int(m.group(1)) if m else extract_esi_level(text)


# --------------------------------------------------------------------------- #
class TriageAgent_Main(MAS):
    """TriageAgent: 5-stage multi-agent ESI triage with RAG over the ESI Handbook."""

    def __init__(self, general_config, method_config_name="config_triage"):
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.max_discuss_rounds = int(mc.get("max_discuss_rounds", 5))
        self.high_conf_threshold = int(mc.get("high_conf_threshold", 90))
        self.use_original_max_tokens = bool(mc.get("use_original_max_tokens", False))
        self.conversation_history: List[Dict[str, Any]] = []
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None
        self.current_round: Optional[int] = None
        self._step_counter = 0

    # ------------------------------------------------------------------ #
    def _record(self, entry: Dict[str, Any]) -> str:
        sid = f"s{self._step_counter}"
        self._step_counter += 1
        self.conversation_history.append({"step_id": sid, **entry})
        return sid

    def _ask(self, role, role_index, phase, agent_id, agent_label, messages, *,
             sources=(), source_how=None, round_=None):
        self.current_role, self.current_role_index = role, role_index
        self.current_phase, self.current_round = phase, round_
        kwargs = {}
        if self.use_original_max_tokens:
            kwargs["max_tokens"] = _ORIGINAL_MAX_TOKENS[phase]
        resp = self.call_llm(messages=messages, **kwargs)
        resp = resp if resp is not None else ""
        srcs = list(dict.fromkeys(s for s in sources if s))
        entry = {"agent_id": agent_id, "role": role, "role_index": role_index, "phase": phase,
                 "agent_label": agent_label, "round": round_, "event_ids": [],
                 "sources": srcs, "observations": [], "content": resp}
        if source_how:
            entry["source_how"] = {s: h for s, h in source_how.items() if s in srcs}
        sid = self._record(entry)
        return resp, sid

    def _set_structured(self, **kv):
        self.conversation_history[-1]["structured"] = kv

    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        self.conversation_history, self._step_counter = [], 0
        vignette = sample["vignette"]
        hits = sample["retrieval_hits"]
        evidence = format_evidence(hits)
        hi = self.high_conf_threshold

        # ---- 0: retrieval (tool) ---------------------------------------- #
        s_rag = self._record({
            "agent_id": "esi_rag_tool", "role": "Retriever", "role_index": 0, "phase": "retrieval",
            "agent_label": "tfidf_esi_handbook", "round": None, "event_ids": [], "sources": [],
            "observations": [], "is_tool": True,
            "tool_calls": [{"name": "tfidf_esi_handbook",
                            "arguments": {"query": vignette, "top_k": len(hits)},
                            "result": hits, "error": None}],
            "precomputed": True, "content": evidence})

        # ---- 1-3: group classification --------------------------------- #
        a_text, s_a = self._ask("Doctor", 0, "classify", "doctor_a", "Doctor A",
                                doctor_a_prompt(vignette, evidence), sources=[s_rag])
        coarse_parsed = parse_coarse(a_text)
        coarse = coarse_parsed or "HIGH"
        a_conf = extract_confidence(a_text)
        self._set_structured(coarse=coarse, coarse_parsed=coarse_parsed, confidence=a_conf)

        b_text, s_b = self._ask("Doctor", 1, "classify", "doctor_b", "Doctor B",
                                doctor_b_prompt(vignette, evidence, coarse, a_conf),
                                sources=[s_rag, s_a], source_how={s_a: "structured_field"})
        b_level, b_conf = extract_esi_level(b_text), extract_confidence(b_text)
        self._set_structured(esi_level=b_level, confidence=b_conf)

        c_text, s_c = self._ask("Doctor", 2, "classify", "doctor_c", "Doctor C",
                                doctor_c_prompt(vignette, evidence), sources=[s_rag])
        c_level, c_conf = extract_esi_level(c_text), extract_confidence(c_text)
        self._set_structured(esi_level=c_level, confidence=c_conf)

        # ---- 4: summarizer ---------------------------------------------- #
        reports = {
            "Doctor A": {"text": a_text, "parsed": f"coarse={coarse}, conf={a_conf}%"},
            "Doctor B": {"text": b_text, "parsed": f"ESI={b_level}, conf={b_conf}%"},
            "Doctor C": {"text": c_text, "parsed": f"ESI={c_level}, conf={c_conf}%"},
        }
        s_text, s_sum = self._ask("Summarizer", 0, "summarize", "summarizer", "Summarizer",
                                  summarizer_prompt(vignette, reports), sources=[s_a, s_b, s_c])
        suggested = suggested_level(s_text)
        self._set_structured(suggested_esi_level=suggested)

        # ---- 5: discussion ----------------------------------------------- #
        # *_src: the step each part of an agent's CURRENT position came from,
        # so a prompt's read set names exactly the steps whose text it quotes.
        agents = [
            {"name": "Doctor A", "agent_id": "doctor_a", "idx": 0,
             "role": "triage physician (coarse-group lead)",
             "level": b_level, "confidence": a_conf, "rationale": rationale_of(a_text),
             "level_src": s_b, "conf_src": s_a, "rat_src": s_a, "active": True},
            {"name": "Doctor B", "agent_id": "doctor_b", "idx": 1,
             "role": "triage physician (refinement specialist)",
             "level": b_level, "confidence": b_conf, "rationale": rationale_of(b_text),
             "level_src": s_b, "conf_src": s_b, "rat_src": s_b, "active": True},
            {"name": "Doctor C", "agent_id": "doctor_c", "idx": 2,
             "role": "triage physician (direct classifier)",
             "level": c_level, "confidence": c_conf, "rationale": rationale_of(c_text),
             "level_src": s_c, "conf_src": s_c, "rat_src": s_c, "active": True},
        ]
        rounds, stopped_early, stop_reason = [], False, "max_rounds"
        for rnd in range(1, self.max_discuss_rounds + 1):
            round_trace = {"round": rnd, "updates": []}
            for ag in agents:
                if not ag["active"]:
                    continue
                peers = [p for p in agents if p["name"] != ag["name"] and p["active"]]
                prev = (ag["level"], ag["confidence"])
                srcs, how = [s_sum], {s_sum: "verbatim"}
                for p in peers:
                    for k in ("level_src", "conf_src"):
                        srcs.append(p[k]); how.setdefault(p[k], "structured_field")
                    srcs.append(p["rat_src"]); how[p["rat_src"]] = "excerpt"
                for k in ("level_src", "conf_src"):
                    srcs.append(ag[k]); how.setdefault(ag[k], "structured_field")
                d_text, s_d = self._ask(
                    "Doctor", ag["idx"], "discuss", ag["agent_id"], ag["name"],
                    discussion_prompt(ag["name"], ag["role"], vignette, s_text,
                                      ag["level"], ag["confidence"], peers),
                    sources=srcs, source_how=how, round_=rnd)
                parsed_level, parsed_conf = extract_esi_level(d_text), extract_confidence(d_text)
                new_level = parsed_level or ag["level"]
                new_conf = parsed_conf if parsed_conf is not None else ag["confidence"]
                ag["rationale"], ag["rat_src"] = rationale_of(d_text), s_d
                if parsed_level:
                    ag["level_src"] = s_d
                if parsed_conf is not None:
                    ag["conf_src"] = s_d
                exited = (new_level == prev[0] and prev[1] is not None
                          and prev[1] >= hi and new_conf is not None and new_conf >= hi)
                if exited:
                    ag["active"] = False
                ag["level"], ag["confidence"] = new_level, new_conf
                upd = {"agent": ag["name"], "agent_id": ag["agent_id"], "step_id": s_d,
                       "level": new_level, "confidence": new_conf,
                       "changed": prev[0] != new_level, "exited": exited}
                round_trace["updates"].append(upd)
                self._set_structured(esi_level=new_level, confidence=new_conf,
                                     level_parsed=parsed_level, confidence_parsed=parsed_conf,
                                     changed=prev[0] != new_level, exited=exited)
            rounds.append(round_trace)
            active = [a for a in agents if a["active"]]
            levels = {a["level"] for a in active if a["level"] is not None}
            confs = [a["confidence"] for a in active if a["confidence"] is not None]
            if levels and len(levels) == 1 and confs and min(confs) >= hi:
                stopped_early, stop_reason = True, "unanimous_high_confidence"
                break
            if levels and len(levels) == 1:
                stop_reason = "agreement"
                break
            if not active:
                stop_reason = "no_active_agents"
                break

        # ---- 6: consensus ------------------------------------------------- #
        finals = [{"name": a["name"], "level": a["level"], "confidence": a["confidence"],
                   "rationale": a["rationale"]} for a in agents]
        srcs, how = [], {}
        for a in agents:
            for k in ("level_src", "conf_src"):
                srcs.append(a[k]); how.setdefault(a[k], "structured_field")
            srcs.append(a["rat_src"]); how[a["rat_src"]] = "excerpt"
        f_text, s_f = self._ask("Coordinator", 0, "consensus", "coordinator", "Coordinator",
                                consensus_prompt(vignette, finals), sources=srcs, source_how=how)
        final_level, final_conf = extract_esi_level(f_text), extract_confidence(f_text)
        final_source, final_step = "coordinator", s_f
        if final_level is None:
            ranked = sorted([a for a in agents if a["level"]],
                            key=lambda a: (a["confidence"] or 0), reverse=True)
            if ranked:
                final_level, final_conf = ranked[0]["level"], ranked[0]["confidence"]
                final_source, final_step = f"fallback_most_confident:{ranked[0]['agent_id']}", ranked[0]["level_src"]
            else:
                final_level, final_conf = suggested, None
                final_source, final_step = "fallback_summarizer", s_sum
        self._set_structured(esi_level=extract_esi_level(f_text), confidence=extract_confidence(f_text))

        response = f"ESI level: {final_level}" if final_level else "ESI level: unknown"
        return {"response": response, "history": list(self.conversation_history),
                "final_step_id": final_step, "final_source": final_source,
                "final_level": final_level, "final_confidence": final_conf,
                "discussion": {"rounds": rounds, "stopped_early": stopped_early,
                               "stop_reason": stop_reason},
                "retrieval": {"tool": "tfidf_esi_handbook", "top_k": len(hits),
                              "pages": [h["page"] for h in hits]}}
