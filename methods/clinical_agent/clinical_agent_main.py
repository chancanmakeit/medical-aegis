"""
ClinicalAgent (Clinical Trial Multi-Agent System with LLM-based Reasoning)
reimplemented on top of the AEGIS `MAS` base class.

Reference:
  Yue et al., "ClinicalAgent: Clinical Trial Multi-Agent System with Large
  Language Model-based Reasoning", ACM-BCB 2024. arXiv:2404.14777.
  Source: https://github.com/lingyue404/clinical-agent (original)
          https://github.com/GuihaiChen1998/full-clinical-agent (release with data)

Adaptations vs. the upstream implementation
-------------------------------------------
1) LLM routing: every LLM call goes through `self.call_llm(...)` so all AEGIS
   knobs apply (multiple providers, retries, AEGIS_LLM_RETRIES).
2) OpenAI tool_calls -> text-based dispatch: the upstream ClinicalAgent uses
   OpenAI's function-calling API to let the top-level orchestrator choose which
   sub-agent to invoke. That's provider-specific and clutters trajectories.
   Here we hard-wire the three-lane structure (Safety / Efficacy / Enrollment
   in that order) at the framework level, so the LLM's "reasoning" surfaces
   as free-form text at each site. This makes injection targeting fully
   deterministic (see structural roles below).
3) Deterministic tools stubbed: DrugBank, Hetionet, the enrollment MLP, and
   the risk_model KDE are all replaced with fixed-string placeholders (or
   optional LLM synthesis via `tools_mode: llm_synth`), so the framework runs
   without those external dependencies. The paper's absolute PR-AUC numbers
   are not reproducible from AEGIS runs — but the multi-agent trajectory
   structure IS reproduced, which is what error-injection needs.
4) Sub-agent decomposition is skipped: upstream each sub-agent (Safety,
   Efficacy) also runs Least-to-Most decomposition -> tool loop. Here each
   sub-agent is a single LLM call that consumes the (stubbed) tool outputs
   directly. This keeps the trajectory to at most 6 LLM turns per sample.

Structural roles for injection targeting (used by fm_clinical_agent_wrapper)
--------------------------------------------------------------------------
    role="Planner",         role_index=0    - decomposition + coordination:
                                              announces the three lanes and the
                                              weighting scheme (absorbs the old
                                              orchestrator turn). Skipped when
                                              use_planner=false.
    role="SafetyAgent",     role_index=0    - SAFETY lane only; emits <safety_score>
    role="EfficacyAgent",   role_index=0    - EFFICACY lane only; emits <efficacy_score>
    role="EnrollmentAgent", role_index=0    - ENROLLMENT lane only; emits <enrollment_score>
    role="Reasoner",        role_index=0    - weighted synthesis; emits final
                                              <final_result>0.X</final_result>

These 5 roles are stable across every sample -- there is NO LLM-decided role
naming (unlike MDAgents where specialty names come from the Recruiter).

NOTE ON AGENT COUNT: the original paper ("ClinicalAgent", arXiv:2404.14777) has
five agents (planning + three domain agents + reasoning) with NO separate
top-level "ClinicalAgent" orchestrator turn. An earlier version of this file
added a redundant "ClinicalAgent" coordination turn; that has been REMOVED and
its coordination role folded into the Planner, so this integration now matches
the paper's 5-agent structure. Each domain agent is strictly scoped to its own
lane (its prompt carries only the facts it needs and forbids cross-lane
analysis), and each emits a per-lane risk score that the Reasoner combines with
an explicit weighted average.
"""

import re
from typing import Any, Dict, List, Optional

from methods.mas_base import MAS


# --------------------------------------------------------------------------- #
# Stubs for the deterministic ClinicalAgent tools.
#
# The real ones live at algo/agents/tool/{risk_model,drugbank,hetionet,enrollment}
# in the upstream repo and require external data + trained models. AEGIS's
# error-injection studies target the LLM reasoning layer, so we replace them
# with fixed placeholder strings that keep the sub-agent prompts semantically
# meaningful (they still see something drug/disease-specific looking).
# --------------------------------------------------------------------------- #
def _stub_drug_risk(drug: str) -> str:
    return f"The historical failure rate of {drug or 'the given drug'} in clinical trials is 0.42 (moderate)."


def _stub_disease_risk(disease: str) -> str:
    return f"The historical failure rate of trials targeting {disease or 'the given disease'} is 0.55 (moderate-high)."


def _stub_drugbank(drug: str) -> str:
    return (f"DrugBank record for {drug or 'the drug'}: pharmacological class not "
            f"available (stub); typical route of administration and metabolic "
            f"pathway apply.")


def _stub_hetionet(drug: str, disease: str) -> str:
    return (f"Hetionet path {drug or 'drug'} -> compound-treats-disease -> {disease or 'disease'}: "
            f"1 direct edge (stub).")


def _stub_smiles(drug: str) -> str:
    return f"SMILES notation for {drug or 'the drug'} is not available (stub)."


def _stub_enrollment(criteria_head: str) -> str:
    return f"Enrollment difficulty for the given eligibility criteria is 0.4 (moderate)."


# --------------------------------------------------------------------------- #
# Dimension-score parsing + weighted combination helpers
# --------------------------------------------------------------------------- #
def _extract_dim_score(text: str, tag: str) -> Optional[float]:
    """Pull a <tag>0.X</tag> lane score out of a sub-agent's response.

    Tolerant to percentages and stray text inside the tag. Returns a float in
    [0, 1] or None if no parseable score is present.
    """
    if not text:
        return None
    m = re.search(rf"<{tag}>\s*([^<>]+?)\s*</{tag}>", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    inner = m.group(1)
    nums = re.findall(r"[-+]?\d*\.?\d+", inner)
    if not nums:
        return None
    try:
        v = float(nums[0])
    except ValueError:
        return None
    if "%" in inner:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def _weighted_average(pairs) -> Optional[float]:
    """Weighted average over (score, weight) pairs, skipping None scores and
    renormalizing the weights of the present scores. Returns None if nothing
    parsed."""
    present = [(s, w) for (s, w) in pairs if s is not None and w is not None]
    if not present:
        return None
    total_w = sum(w for _, w in present)
    if total_w <= 0:
        return None
    return max(0.0, min(1.0, sum(s * w for s, w in present) / total_w))


def _fmt(x: Optional[float]) -> str:
    return "N/A" if x is None else f"{x:.2f}"


class ClinicalAgent_Main(MAS):
    """Hierarchical clinical-trial-outcome multi-agent system.

    `inference(sample)` -> {"response": "...", "history": [...], "prob": <float or None>}.
    The response ends with a `<final_result>0.X</final_result>` tag that the
    verifier extracts and thresholds.
    """

    def __init__(self, general_config, method_config_name="config_medical"):
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.use_planner = bool(mc.get("use_planner", True))
        self.planner_subproblems = int(mc.get("planner_subproblems", 3))
        self.tools_mode = mc.get("tools_mode", "placeholder")
        self.reasoner_extra_hint = mc.get("reasoner_extra_hint",
            "Give your final failure probability in `<final_result>0.X</final_result>` tags.")
        # Weights for combining the three lane scores into the final failure
        # probability (safety, efficacy, enrollment). Announced by the Planner
        # and applied by the Reasoner. Defaults match the ClinicalAgent
        # response's example (30% / 40% / 30%). Configurable via method config.
        dw = mc.get("dimension_weights", {}) or {}
        w_s = float(dw.get("safety", 0.30))
        w_e = float(dw.get("efficacy", 0.40))
        w_n = float(dw.get("enrollment", 0.30))
        _tot = w_s + w_e + w_n
        if _tot <= 0:
            w_s, w_e, w_n = 0.30, 0.40, 0.30
            _tot = 1.0
        # Normalize so they sum to 1.
        self.dimension_weights = (w_s / _tot, w_e / _tot, w_n / _tot)

        # Conversation log — the wrapper reads from here.
        self.conversation_history: List[Dict[str, Any]] = []

        # Mutable "current" pointer set right before every call_llm; the
        # injection wrapper reads these to decide whether to inject.
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Recording helpers (mirrors MDAgents_Main pattern)
    # ------------------------------------------------------------------ #
    def _record(self, role: str, role_index: int, phase: str, content: str):
        self.conversation_history.append({
            "role": role,
            "role_index": role_index,
            "phase": phase,
            "content": content,
        })

    def _ask(self, role: str, role_index: int, phase: str,
             prompt: str, system_prompt: Optional[str] = None) -> str:
        """Wrapper around self.call_llm that sets current_role/role_index/phase
        BEFORE the call so the FM wrapper can target this site.

        ClinicalAgent is a text-only framework (no medical imaging in the
        trial-success dataset), so we pass images=None explicitly to prevent
        the multimodal auto-attach layer from wasting tokens on text-only
        clinical trial predictions.
        """
        self.current_role = role
        self.current_role_index = role_index
        self.current_phase = phase
        resp = self.call_llm(prompt=prompt, system_prompt=system_prompt, images=None)
        self._record(role, role_index, phase, resp if resp is not None else "")
        return resp or ""

    # ------------------------------------------------------------------ #
    # Deterministic-tool stubs (may be overridden by LLM synthesis)
    # ------------------------------------------------------------------ #
    def _tool_drug_risk(self, drug: str) -> str:
        if self.tools_mode == "llm_synth":
            return self._ask(
                "ToolSynth", 0, "tool_drug_risk",
                f"Synthesize a plausible one-line historical failure rate for the drug '{drug}' "
                f"in clinical trials as a value in [0,1]. Reply with a single sentence.",
            )
        return _stub_drug_risk(drug)

    def _tool_disease_risk(self, disease: str) -> str:
        if self.tools_mode == "llm_synth":
            return self._ask(
                "ToolSynth", 0, "tool_disease_risk",
                f"Synthesize a plausible one-line historical failure rate for trials targeting "
                f"'{disease}' as a value in [0,1]. Reply with a single sentence.",
            )
        return _stub_disease_risk(disease)

    def _tool_drugbank(self, drug: str) -> str:
        if self.tools_mode == "llm_synth":
            return self._ask(
                "ToolSynth", 0, "tool_drugbank",
                f"Summarize (2 sentences) plausible DrugBank facts for '{drug}': "
                f"pharmacological class, route, metabolism.",
            )
        return _stub_drugbank(drug)

    def _tool_hetionet(self, drug: str, disease: str) -> str:
        if self.tools_mode == "llm_synth":
            return self._ask(
                "ToolSynth", 0, "tool_hetionet",
                f"Describe (one sentence) the plausible Hetionet path linking '{drug}' to '{disease}'.",
            )
        return _stub_hetionet(drug, disease)

    def _tool_enrollment(self, criteria: str) -> str:
        if self.tools_mode == "llm_synth":
            head = (criteria or "")[:400]
            return self._ask(
                "ToolSynth", 0, "tool_enrollment",
                f"Given this eligibility criteria, output a single sentence with a difficulty "
                f"score in [0,1]:\n{head}",
            )
        return _stub_enrollment((criteria or "")[:100])

    # ------------------------------------------------------------------ #
    # Extract (drugs, diseases, criteria) tuple from the sample query.
    # The trial_success builder emits a well-formed <drug>..</drug>,
    # <disease>..</disease>, <criteria>..</criteria> block; parse it back.
    # ------------------------------------------------------------------ #
    _DRUG_RE = re.compile(r"<drug>(.*?)</drug>", re.DOTALL | re.IGNORECASE)
    _DIS_RE = re.compile(r"<disease>(.*?)</disease>", re.DOTALL | re.IGNORECASE)
    _CRIT_RE = re.compile(r"<criteria>(.*?)</criteria>", re.DOTALL | re.IGNORECASE)

    def _parse_query(self, query: str) -> Dict[str, str]:
        drugs = self._DRUG_RE.search(query)
        diseases = self._DIS_RE.search(query)
        criteria = self._CRIT_RE.search(query)
        return {
            "drugs": drugs.group(1).strip() if drugs else "",
            "diseases": diseases.group(1).strip() if diseases else "",
            "criteria": criteria.group(1).strip() if criteria else "",
        }

    # ------------------------------------------------------------------ #
    # Main pipeline
    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        question = sample["query"] if isinstance(sample, dict) else str(sample)
        self.conversation_history = []
        parsed = self._parse_query(question)
        drugs = parsed["drugs"] or "the drug"
        diseases = parsed["diseases"] or "the disease"
        criteria = parsed["criteria"] or "not specified"

        # A COMPACT background block that carries ONLY the trial facts, WITHOUT
        # the top-level user instruction ("Analyze safety, efficacy, and
        # enrollment ... give final failure probability ..."). Passing the raw
        # `question` to every sub-agent made them over-step their role (e.g. the
        # Safety agent also doing efficacy + enrollment analysis). Each sub-agent
        # now receives only the facts relevant to ITS lane.
        drug_disease_bg = (
            f"Drug(s): {drugs}\n"
            f"Disease(s)/condition(s): {diseases}"
        )

        # The per-dimension weights the Planner announces and the Reasoner uses.
        w_safety, w_efficacy, w_enroll = self.dimension_weights

        # === Step 1: Planner — decomposition + coordination ===
        # The Planner now ALSO plays the (former) ClinicalAgent's coordination
        # role: it announces the three lanes and the weighting scheme that the
        # Reasoner will apply. The original paper's ClinicalAgent has no separate
        # top-level orchestrator agent, so folding it in here is closer to the
        # paper AND removes a redundant LLM turn.
        subproblems: List[str] = []
        if self.use_planner:
            planner_system = (
                "You are the planning and coordination agent of a clinical-trial "
                "outcome-prediction system. You decompose the task into three "
                "independent analysis lanes — safety, efficacy, and enrollment — "
                "each handled by a dedicated specialist agent, and you state how "
                "their per-lane scores will be combined into a final failure "
                "probability. You do NOT perform the analyses yourself."
            )
            planner_prompt = (
                f"Trial under review:\n{drug_disease_bg}\n\n"
                f"Plan the analysis. Emit exactly three subproblems — one for the "
                f"Safety agent, one for the Efficacy agent, one for the Enrollment "
                f"agent — each wrapped in <subproblem>...</subproblem> tags. Then "
                f"state that the final failure probability will be a weighted "
                f"average of the three lane scores using weights "
                f"safety={w_safety:.2f}, efficacy={w_efficacy:.2f}, "
                f"enrollment={w_enroll:.2f}."
            )
            plan = self._ask("Planner", 0, "decomposition_coordination",
                             planner_prompt, system_prompt=planner_system)
            subproblems = [m.strip() for m in re.findall(
                r"<subproblem>(.*?)</subproblem>", plan, re.DOTALL
            )]
        if not subproblems:
            subproblems = [
                "Safety agent: assess drug/disease historical failure rates.",
                "Efficacy agent: assess drug-disease pathway evidence.",
                "Enrollment agent: assess enrollment feasibility from criteria.",
            ]

        # === Step 2: Safety Agent (scoped to safety ONLY) ===
        safety_tool_out = "\n".join([
            self._tool_drug_risk(drugs.split(";")[0].strip()),
            self._tool_disease_risk(diseases.split(";")[0].strip()),
        ])
        safety_system = (
            "You are a drug-safety specialist in a clinical-trial panel. Your "
            "SOLE responsibility is the SAFETY dimension — assess drug and "
            "disease safety from historical failure rates. Do NOT analyze "
            "efficacy or enrollment; those are handled by other specialists. "
            "End your answer with a safety failure-risk score in the tag "
            "<safety_score>0.X</safety_score> (0 = very safe / low failure risk, "
            "1 = very unsafe / high failure risk)."
        )
        safety_prompt = (
            f"Trial facts:\n{drug_disease_bg}\n\n"
            f"Safety tool outputs:\n{safety_tool_out}\n\n"
            "Give a brief (3-5 sentence) SAFETY-only analysis, then the "
            "<safety_score> tag."
        )
        safety_out = self._ask("SafetyAgent", 0, "safety_analysis",
                               safety_prompt, system_prompt=safety_system)

        # === Step 3: Efficacy Agent (scoped to efficacy ONLY) ===
        efficacy_tool_out = "\n".join([
            self._tool_drugbank(drugs.split(";")[0].strip()),
            self._tool_hetionet(drugs.split(";")[0].strip(), diseases.split(";")[0].strip()),
        ])
        efficacy_system = (
            "You are a drug-efficacy specialist in a clinical-trial panel. Your "
            "SOLE responsibility is the EFFICACY dimension — assess whether the "
            "drug is likely to treat the disease, using the DrugBank and Hetionet "
            "evidence. Do NOT analyze safety or enrollment. End your answer with "
            "an efficacy failure-risk score in the tag "
            "<efficacy_score>0.X</efficacy_score> (0 = strong efficacy evidence / "
            "low failure risk, 1 = weak efficacy / high failure risk)."
        )
        efficacy_prompt = (
            f"Trial facts:\n{drug_disease_bg}\n\n"
            f"Efficacy tool outputs:\n{efficacy_tool_out}\n\n"
            "Give a brief (3-5 sentence) EFFICACY-only analysis, then the "
            "<efficacy_score> tag."
        )
        efficacy_out = self._ask("EfficacyAgent", 0, "efficacy_analysis",
                                 efficacy_prompt, system_prompt=efficacy_system)

        # === Step 4: Enrollment Agent (scoped to enrollment ONLY) ===
        enrollment_tool_out = self._tool_enrollment(criteria)
        enrollment_system = (
            "You are an enrollment-feasibility specialist in a clinical-trial "
            "panel. Your SOLE responsibility is the ENROLLMENT dimension — judge "
            "whether the eligibility criteria will support sufficient patient "
            "recruitment. Do NOT analyze safety or efficacy. End your answer with "
            "an enrollment failure-risk score in the tag "
            "<enrollment_score>0.X</enrollment_score> (0 = easy recruitment / low "
            "failure risk, 1 = very hard recruitment / high failure risk)."
        )
        enrollment_prompt = (
            f"Eligibility criteria (truncated):\n{criteria[:1200]}\n\n"
            f"Enrollment tool output:\n{enrollment_tool_out}\n\n"
            "Give a brief (2-4 sentence) ENROLLMENT-only analysis, then the "
            "<enrollment_score> tag."
        )
        enrollment_out = self._ask("EnrollmentAgent", 0, "enrollment_analysis",
                                   enrollment_prompt, system_prompt=enrollment_system)

        # Pull the three lane scores back out (for the weighted computation and
        # for logging). If a sub-agent omitted its tag, we leave it None and the
        # Reasoner is asked to estimate it.
        s_safety = _extract_dim_score(safety_out, "safety_score")
        s_efficacy = _extract_dim_score(efficacy_out, "efficacy_score")
        s_enroll = _extract_dim_score(enrollment_out, "enrollment_score")

        # Deterministic weighted average over whatever scores parsed (used as a
        # sanity value + logged; the authoritative number is the Reasoner's tag).
        computed_prob = _weighted_average(
            [(s_safety, w_safety), (s_efficacy, w_efficacy), (s_enroll, w_enroll)]
        )

        # === Step 5: Reasoner — weighted synthesis ===
        reasoner_system = (
            "You are the senior reasoning agent. You combine the three "
            "specialists' per-lane failure-risk scores into a single final "
            "failure probability using the announced weighted average "
            f"(safety={w_safety:.2f}, efficacy={w_efficacy:.2f}, "
            f"enrollment={w_enroll:.2f}). Show the arithmetic explicitly. "
            + self.reasoner_extra_hint
        )
        scores_line = (
            f"safety_score={_fmt(s_safety)}, "
            f"efficacy_score={_fmt(s_efficacy)}, "
            f"enrollment_score={_fmt(s_enroll)}"
        )
        reasoner_prompt = (
            f"Trial facts:\n{drug_disease_bg}\n\n"
            f"[Safety Agent]\n{safety_out}\n\n"
            f"[Efficacy Agent]\n{efficacy_out}\n\n"
            f"[Enrollment Agent]\n{enrollment_out}\n\n"
            f"Parsed lane scores: {scores_line}\n"
            f"(If any score is missing, estimate it from that agent's analysis.)\n\n"
            f"Compute the final failure probability as:\n"
            f"  p = {w_safety:.2f}*safety + {w_efficacy:.2f}*efficacy "
            f"+ {w_enroll:.2f}*enrollment\n"
            f"Show the substituted arithmetic in one line, then output the result "
            f"in <final_result>0.X</final_result> tags (0-1, 1 = trial fails)."
        )
        final = self._ask("Reasoner", 0, "final_synthesis",
                          reasoner_prompt, system_prompt=reasoner_system)

        # Extract the Reasoner's final probability (authoritative). Fall back to
        # the deterministic weighted average if the tag is missing.
        prob = None
        m = re.search(r"<final_result>\s*([-+]?\d*\.?\d+%?)\s*</final_result>",
                      final, re.IGNORECASE | re.DOTALL)
        if m:
            try:
                v = float(re.findall(r"[-+]?\d*\.?\d+", m.group(1))[0])
                if "%" in m.group(1):
                    v = v / 100.0
                prob = max(0.0, min(1.0, v))
            except (ValueError, IndexError):
                prob = None
        if prob is None:
            prob = computed_prob

        return {
            "response": final,
            "history": list(self.conversation_history),
            "prob": prob,
            "lane_scores": {
                "safety": s_safety, "efficacy": s_efficacy, "enrollment": s_enroll,
                "weights": {"safety": w_safety, "efficacy": w_efficacy,
                            "enrollment": w_enroll},
                "computed_weighted_prob": computed_prob,
            },
        }
