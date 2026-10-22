"""
MDAgents (Adaptive Collaboration of LLMs for Medical Decision-Making)
reimplemented on top of the AEGIS `MAS` base class.

Reference:
  Kim et al., "MDAgents: An Adaptive Collaboration of LLMs for Medical
  Decision-Making", arXiv:2404.15155.
  Source: https://github.com/mitmedialab/MDAgents

Key adaptations vs. the upstream implementation:
  - All LLM calls go through `self.call_llm(...)` instead of MDAgents'
    embedded OpenAI client. This makes the method compatible with the AEGIS
    LLM-routing layer (multiple providers, retries, AEGIS_LLM_RETRIES knob).
  - Trajectory is recorded into `self.conversation_history` so the wrapper
    can extract a unified per-turn log.
  - Difficulty is configurable via the method config (`difficulty: basic |
    intermediate | advanced | adaptive`). We currently fully support BASIC
    and INTERMEDIATE; ADVANCED is included in skeleton form with a clear
    fallback to intermediate (see `_process_advanced`).

Step contract (StructuredFMWrapper, fm_mdagents_structured_wrapper.py; the
legacy fm_mdagents_wrapper.py is kept only to reproduce old data):
  every call records step_id, agent_id (stable: recruiter, expert_<i>,
  aggregator, classifier, medical_expert, team<t>_member<m>, team_lead_<t>),
  agent_label (the recruited specialty), sources + source_how (experts read
  the Recruiter's specialty/description as a structured field; the aggregator
  reads the expert answers verbatim), observations (attached images, ids
  image_<k>, registered in `task_observations`) and structured
  ({"answer": <letter>} parsed from "Final answer: X"; recruiter: specialties;
  classifier: difficulty).

Injection contract (role names unchanged, so old YAML targets still apply):
  Every LLM call goes through `self.call_llm` AND carries a structural role
  context that the wrapper reads via `self.current_role` / `self.current_role_index`.
  The wrapper monkey-patches `call_llm` to selectively inject errors at
  specific (role, role_index) sites. Structural roles used:
    - "Recruiter"  (role_index 0)       : panel-recruitment turn
    - "Expert"     (role_index 0..N-1)  : independent expert answers
    - "Aggregator" (role_index 0)       : final synthesis
  These are stable across samples (no LLM-decided role names leak into the
  injection key).
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from methods.mas_base import MAS
from methods.answer_parsing import mcq_answer


# Letters used for MCQ option labelling (matches MedXpertQA up to 10 choices).
_OPTION_LETTERS = "ABCDEFGHIJ"


def final_letter(text: str) -> Optional[str]:
    """Option letter the reply commits to (see methods/answer_parsing.py)."""
    return mcq_answer(text)


class MDAgents_Main(MAS):
    """MDAgents-style adaptive medical multi-agent system.

    `inference(sample)` returns {"response": "...", "history": [...]} (the
    history is also stored on `self.conversation_history` for the wrapper).
    """

    def __init__(self, general_config, method_config_name="config_medical"):
        super().__init__(general_config, method_config_name=method_config_name)
        # Method-config knobs (set defaults so the class works even when no
        # config file is present).
        mc = getattr(self, "method_config", {}) or {}
        self.difficulty = mc.get("difficulty", "intermediate")
        self.num_experts = int(mc.get("num_experts", 5))
        self.debate_rounds = int(mc.get("debate_rounds", 1))
        # Optional text backbone for the image-free roles (Recruiter,
        # Classifier); None = the run's model. Lets a multimodal run separate
        # modality from backbone on those steps (MedHyperTrace issue #1, r26).
        self.text_model_name = mc.get("text_model_name") or None
        self.recruiter_advice = mc.get("recruiter_advice",
            "Recruit a diverse panel of medical experts relevant to the question.")

        # Conversation log — the wrapper reads from here.
        # Each entry: {"role": <structural role>, "role_index": int,
        #              "phase": <str>, "content": <model output>,
        #              "input_messages": <captured by wrapper>}
        self.conversation_history: List[Dict[str, Any]] = []

        # Mutable "current" pointer set right before every call_llm; the
        # injection wrapper reads these to decide whether to inject.
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None

        # Images attached to the current sample, set at the start of inference().
        # Forwarded to every LLM call so multimodal-capable models can see them.
        self.current_images: Optional[List[str]] = None

    # --------------------------------------------------------------------- #
    # Recording helper
    # --------------------------------------------------------------------- #
    def _record(self, role: str, role_index: int, phase: str, content: str,
                agent_id: Optional[str] = None, agent_label: Optional[str] = None,
                sources=(), source_how=None, observations=(), round_=None) -> str:
        sid = f"s{len(self.conversation_history)}"
        entry = {
            "step_id": sid,
            "role": role,
            "role_index": role_index,
            "phase": phase,
            "content": content,
            "agent_id": agent_id or f"{role.lower()}_{role_index}",
            "agent_label": agent_label,
            "round": round_,
            "event_ids": [],
            "sources": list(dict.fromkeys(sources)),
            "observations": list(observations),
            "structured": {"answer": final_letter(content)},
        }
        if source_how:
            entry["source_how"] = {k: v for k, v in source_how.items() if k in entry["sources"]}
        self.conversation_history.append(entry)
        return sid

    def _ask(self, role: str, role_index: int, phase: str,
             prompt: str, system_prompt: Optional[str] = None, *,
             agent_id: Optional[str] = None, agent_label: Optional[str] = None,
             sources=(), source_how=None, round_=None) -> str:
        """Wrapper around self.call_llm that sets current_role/role_index/phase
        before the call so the FM wrapper can target this site.

        Forwards `self.current_images` (set per-sample in inference()) so every
        agent in the panel can ground its reasoning in the attached image(s).
        Skipping for the Recruiter is intentional — recruitment is a purely
        text-based planning step; sending the images then would be wasteful and
        could leak visual info into agent specialty names. The Classifier turn
        is also kept text-only for the same reason.
        """
        self.current_role = role
        self.current_role_index = role_index
        self.current_phase = phase
        self.current_round = round_
        # Skip images for purely planning/classification turns.
        text_only = role in ("Recruiter", "Classifier")
        send_images = self.current_images if not text_only else None
        kw = {"model_name": self.text_model_name} if (text_only and self.text_model_name) else {}
        resp = self.call_llm(prompt=prompt, system_prompt=system_prompt,
                             images=send_images, **kw)
        # If retries exhausted, mas_base returns None; downstream code must
        # treat that as a hard failure, but we keep recording so the trajectory
        # still reflects what was attempted.
        obs = [f"image_{k}" for k in range(len(send_images or []))]
        self.last_step = self._record(role, role_index, phase, resp if resp is not None else "",
                                      agent_id=agent_id, agent_label=agent_label,
                                      sources=sources, source_how=source_how,
                                      observations=obs, round_=round_)
        return resp

    # --------------------------------------------------------------------- #
    # Difficulty branch
    # --------------------------------------------------------------------- #
    def inference(self, sample) -> Dict[str, Any]:
        """Dispatch by configured difficulty."""
        question = sample["query"] if isinstance(sample, dict) else str(sample)
        self.conversation_history = []  # reset per-sample
        self.current_round = None
        # Pick up multimodal attachments from the sample (set by main.py via Task).
        self.current_images = None
        if isinstance(sample, dict):
            self.current_images = (sample.get("image_paths")
                                   or sample.get("images")
                                   or None)
        self.task_observations = [{"id": f"image_{k}", "type": "image", "path": p}
                                  for k, p in enumerate(self.current_images or [])]
        self.final_step_id = None

        diff = (self.difficulty or "intermediate").lower()
        if diff == "adaptive":
            diff = self._classify_difficulty(question)

        if diff == "basic":
            response = self._process_basic(question)
        elif diff == "advanced":
            response = self._process_advanced(question)
        else:  # intermediate (default)
            response = self._process_intermediate(question)

        return {"response": response, "history": list(self.conversation_history),
                "difficulty": diff, "final_step_id": self.final_step_id}

    # --------------------------------------------------------------------- #
    # ADAPTIVE classification (only used when difficulty == "adaptive")
    # --------------------------------------------------------------------- #
    def _classify_difficulty(self, question: str) -> str:
        prompt = (
            "Classify the difficulty/complexity of the medical question below "
            "by choosing exactly ONE label:\n"
            "  basic        - a single medical expert can answer directly.\n"
            "  intermediate - several specialists should discuss to be confident.\n"
            "  advanced     - multiple multidisciplinary teams are required.\n\n"
            f"Question:\n{question}\n\n"
            "Respond with a single word: basic, intermediate, or advanced."
        )
        resp = self._ask("Classifier", 0, "difficulty_classification", prompt,
                         agent_id="classifier") or ""
        r = resp.lower()
        if "basic" in r or "1)" in r:
            d = "basic"
        elif "advanced" in r or "3)" in r:
            d = "advanced"
        else:
            d = "intermediate"
        self.conversation_history[-1]["structured"] = {"difficulty": d}
        return d

    # --------------------------------------------------------------------- #
    # BASIC: single agent
    # --------------------------------------------------------------------- #
    def _process_basic(self, question: str) -> str:
        system_prompt = ("You are a helpful medical expert. Answer the following "
                         "multiple-choice medical question. Reason step by step, "
                         "then conclude with: 'Final answer: <letter>'.")
        prompt = f"Question:\n{question}\n\nAnswer:"
        resp = self._ask("MedicalExpert", 0, "basic_answer", prompt,
                         system_prompt=system_prompt, agent_id="medical_expert")
        self.final_step_id = self.last_step
        return resp or ""

    # --------------------------------------------------------------------- #
    # INTERMEDIATE: recruit experts -> each answers -> aggregator decides
    # --------------------------------------------------------------------- #
    def _process_intermediate(self, question: str) -> str:
        # === Step 1: Recruiter proposes a panel ===
        recruit_system = (
            "You are an experienced senior medical expert who builds a small "
            "panel of specialists to answer a difficult medical question."
        )
        recruit_prompt = (
            f"{self.recruiter_advice}\n\n"
            f"Question:\n{question}\n\n"
            f"List exactly {self.num_experts} specialists, one per line, in the "
            "format `N. <Specialty> - <one-line description>`. "
            "Do not add any other text."
        )
        recruited = self._ask("Recruiter", 0, "recruitment",
                              recruit_prompt, system_prompt=recruit_system,
                              agent_id="recruiter") or ""
        s_rec = self.last_step

        # Parse specialty names; fall back to generic names if parsing fails.
        experts: List[Dict[str, str]] = []
        for line in (recruited.splitlines() if recruited else []):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\d+\.\s*([^-]+?)\s*-\s*(.+)$", line)
            if m:
                experts.append({"specialty": m.group(1).strip(),
                                "description": m.group(2).strip()})
            if len(experts) >= self.num_experts:
                break
        n_parsed = len(experts)
        while len(experts) < self.num_experts:
            experts.append({"specialty": f"Generalist {len(experts)+1}",
                            "description": "general medical reasoning"})
        self.conversation_history[-1]["structured"] = {
            "specialties": [e["specialty"] for e in experts], "parsed": n_parsed}

        # === Step 2: Each expert answers independently ===
        expert_answers: List[str] = []
        latest = []      # step whose answer is expert idx's current entry
        for idx, ex in enumerate(experts):
            sp = ex["specialty"]
            desc = ex["description"]
            expert_system = (
                f"You are a {sp}. {desc}. You are part of a panel discussing "
                "a medical question. Provide your independent, well-reasoned "
                "answer with a clear final option letter."
            )
            expert_prompt = (
                f"Question:\n{question}\n\n"
                "Provide a concise reasoning (3-6 sentences) and conclude with "
                "'Final answer: <letter>'."
            )
            # The specialty / description come from the Recruiter's output only
            # when they were parsed from it (fallback generalists are fixed text).
            src = [s_rec] if idx < n_parsed else []
            ans = self._ask("Expert", idx, "expert_answer",
                            expert_prompt, system_prompt=expert_system,
                            agent_id=f"expert_{idx}", agent_label=sp,
                            sources=src, source_how={s_rec: "structured_field"}) or ""
            expert_answers.append(f"[{sp}] {ans}")
            latest.append(self.last_step)

        # Optional extra debate rounds: experts see each other's answers and revise.
        for r in range(1, self.debate_rounds):
            joined = "\n\n".join(expert_answers)
            snapshot = list(latest)   # `joined` is built once per round
            for idx, ex in enumerate(experts):
                sp = ex["specialty"]
                rev_system = (
                    f"You are a {sp}. You have seen your peers' answers below. "
                    "Reconsider and update your answer if warranted."
                )
                rev_prompt = (
                    f"Panel answers so far:\n{joined}\n\n"
                    f"Question:\n{question}\n\n"
                    f"Your updated answer (conclude with 'Final answer: <letter>'):"
                )
                rev = self._ask("Expert", idx, "expert_revise",
                                rev_prompt, system_prompt=rev_system,
                                agent_id=f"expert_{idx}", agent_label=sp, round_=r,
                                sources=list(snapshot) + ([s_rec] if idx < n_parsed else []),
                                source_how={s_rec: "structured_field"}) or ""
                expert_answers[idx] = f"[{sp}, r{r}] {rev}"
                latest[idx] = self.last_step

        # === Step 3: Aggregator synthesizes a final answer ===
        agg_system = (
            "You are a senior physician synthesizing a panel of specialists' "
            "answers. Weigh the evidence and produce a single final answer."
        )
        agg_prompt = (
            f"Question:\n{question}\n\n"
            f"Panel answers:\n" + "\n\n".join(expert_answers) +
            "\n\nBased on the panel, give your concise final reasoning and "
            "conclude with 'Final answer: <letter>'."
        )
        final = self._ask("Aggregator", 0, "aggregation",
                          agg_prompt, system_prompt=agg_system,
                          agent_id="aggregator", sources=latest) or ""
        self.final_step_id = self.last_step
        return final

    # --------------------------------------------------------------------- #
    # ADVANCED: multiple MDTs (Multidisciplinary Teams). For dataset
    # generation we use a simplified form: 2 teams of 3 specialists each
    # produce a team-consensus answer, then an FRDT lead picks the final.
    # If you need full per-paper fidelity (IAT/DET/PHT/FRDT structure) you
    # can extend this method using the same `_ask` primitive.
    # --------------------------------------------------------------------- #
    def _process_advanced(self, question: str) -> str:
        n_teams = 2
        n_per_team = 3
        team_summaries: List[str] = []
        lead_steps: List[str] = []
        for t in range(n_teams):
            team_role = f"Team{t+1}"
            members, member_steps = [], []
            for m in range(n_per_team):
                role_idx = t * n_per_team + m
                ex_system = (
                    f"You are a specialist in team {t+1} (member {m+1}). Provide "
                    "your view on the question."
                )
                ans = self._ask("MDTMember", role_idx, f"{team_role}_member{m+1}",
                                f"Question:\n{question}\n\nYour view (3-5 sentences):",
                                system_prompt=ex_system,
                                agent_id=f"team{t+1}_member{m+1}") or ""
                members.append(ans)
                member_steps.append(self.last_step)
            # Team consensus
            joined = "\n\n".join(f"- {m}" for m in members)
            cons = self._ask("TeamLead", t, f"{team_role}_consensus",
                             f"Team views:\n{joined}\n\nQuestion:\n{question}\n\n"
                             "Produce the team's consensus answer ('Final answer: <letter>').",
                             system_prompt=f"You lead {team_role}.",
                             agent_id=f"team_lead_{t+1}", sources=member_steps) or ""
            team_summaries.append(f"{team_role} consensus: {cons}")
            lead_steps.append(self.last_step)

        # FRDT
        final = self._ask("Aggregator", 0, "frdt",
                          "Team consensus answers:\n" + "\n\n".join(team_summaries) +
                          f"\n\nQuestion:\n{question}\n\nProduce the final answer ('Final answer: <letter>').",
                          system_prompt="You are the Final Review and Decision Team lead.",
                          agent_id="aggregator", sources=lead_steps) or ""
        self.final_step_id = self.last_step
        return final
