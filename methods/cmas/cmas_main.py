"""
CMAS (Cooperative Multi-Agent System for Zero-Shot NER) reimplemented on top of
the AEGIS `MAS` base class.

Reference:
  Wang et al., "A Cooperative Multi-Agent Framework for Zero-Shot Named Entity
  Recognition", WWW 2025. arXiv:2502.18702.
  Source: https://github.com/WZH-NLP/WWW25-CMAS

The paper's CMAS has FOUR agents:
  1. Self-annotator          - annotates the unlabeled corpus OFFLINE (once) and
                               builds the demonstration pool. This is NOT a
                               per-test-sample step, so AEGIS does not run it:
                               we consume the shipped self-annotated pool
                               (data/wikigold/train.json) directly.
  2. TRF extractor           - identifies type-related features (tokens strongly
                               associated with entity types) in the target
                               sentence. (Prompt 2 in the paper.)
  3. Demonstration discriminator - self-reflection agent that scores how helpful
                               each retrieved demonstration is for the target
                               sentence. (Prompt 3.)
  4. Overall predictor       - produces the final NER prediction, integrating the
                               TRFs and helpfulness scores. (Prompt 4.)

So per test sentence there are up to THREE injectable LLM agents (TRF extractor,
discriminator, overall predictor). These are the structural roles targeted by
the FM wrapper:

    role="TRFExtractor",      role_index=0   - TRF identification
    role="Discriminator",     role_index=0   - demonstration helpfulness scoring
    role="OverallPredictor",  role_index=0   - final NER answer

Adaptations vs. upstream
------------------------
- LLM routing through self.call_llm (AEGIS providers/retries).
- Demonstration RETRIEVAL is stubbed: instead of GPTEmb diverse-KNN over
  sentence embeddings, we take the first N demos from the pool (config
  demo_retrieval_mode="stub_topk") or run demo-free. The retrieval machinery is
  offline and orthogonal to the multi-agent reasoning we inject into.
- Pseudo-TRF-label generation (mutual-information over the corpus) is replaced by
  using the shipped trf.json type->features lists when available, else the demo
  agents run without pseudo-labels. This keeps the injectable reasoning intact.
- Two-stage self-consistency voting (sample 5, majority vote) is NOT run per
  sample (it multiplies every trajectory 5x, which breaks 1:1 injection
  attribution). We take a single overall-predictor pass. The verifier scores
  the single answer with exact-match micro-F1.

The final answer is a JSON list [{ "Entity": "Type" }, ...] which
aegis_core/utils/ner_verifier.py parses and scores.
"""

import ast
import json
import os
import re
from typing import Any, Dict, List, Optional

from methods.mas_base import MAS


class CMAS_Main(MAS):
    """Cooperative multi-agent zero-shot NER system.

    `inference(sample)` -> {"response": <json entity list str>, "history": [...],
                            "trfs": [...], "helpfulness": {...}}.
    """

    def __init__(self, general_config, method_config_name="config_ner"):
        super().__init__(general_config, method_config_name=method_config_name)
        mc = getattr(self, "method_config", {}) or {}
        self.few_shot_number = int(mc.get("few_shot_number", 4))
        self.demo_retrieval_mode = mc.get("demo_retrieval_mode", "stub_topk")
        self.demo_pool_path = mc.get("demo_pool_path", None)
        self.use_trf_extractor = bool(mc.get("use_trf_extractor", True))
        self.use_discriminator = bool(mc.get("use_discriminator", True))

        # Lazily-loaded demonstration pool: list of {"sentence":..., "label":...}.
        self._demo_pool: Optional[List[Dict[str, Any]]] = None

        # Conversation log — the wrapper reads from here.
        self.conversation_history: List[Dict[str, Any]] = []

        # Mutable "current" pointer set right before every call_llm; the
        # injection wrapper reads these to decide whether to inject.
        self.current_role: Optional[str] = None
        self.current_role_index: int = 0
        self.current_phase: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Recording helpers
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
        """call_llm wrapper that sets current_role/_index/_phase before the call
        so the FM wrapper can target this site. CMAS is text-only NER, so we
        pass images=None explicitly to skip the multimodal auto-attach layer."""
        self.current_role = role
        self.current_role_index = role_index
        self.current_phase = phase
        resp = self.call_llm(prompt=prompt, system_prompt=system_prompt, images=None)
        self._record(role, role_index, phase, resp if resp is not None else "")
        return resp or ""

    # ------------------------------------------------------------------ #
    # Demonstration pool loading + retrieval stub
    # ------------------------------------------------------------------ #
    def _load_demo_pool(self) -> List[Dict[str, Any]]:
        if self._demo_pool is not None:
            return self._demo_pool
        pool: List[Dict[str, Any]] = []
        path = self.demo_pool_path
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for r in raw:
                    pool.append({"sentence": r.get("sentence", ""),
                                 "label": r.get("label", "")})
            except Exception as e:
                print(f"[CMAS] could not load demo pool from {path}: {e}")
        self._demo_pool = pool
        return pool

    def _retrieve_demos(self, target_sentence: str) -> List[Dict[str, Any]]:
        if self.demo_retrieval_mode == "none":
            return []
        pool = self._load_demo_pool()
        if not pool:
            return []
        # stub_topk: deterministic first-N. (Full CMAS uses GPTEmb diverse-KNN.)
        return pool[: self.few_shot_number]

    @staticmethod
    def _format_label(label_field: Any) -> str:
        """Render a demo's label (str-dict or dict) as a compact JSON entity list."""
        mapping = {}
        if isinstance(label_field, dict):
            mapping = label_field
        elif isinstance(label_field, str) and label_field.strip():
            try:
                parsed = ast.literal_eval(label_field)
                if isinstance(parsed, dict):
                    mapping = parsed
            except (ValueError, SyntaxError):
                mapping = {}
        return json.dumps([{k: v} for k, v in mapping.items()], ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # Parse the target sentence + label set out of the AEGIS query.
    # ------------------------------------------------------------------ #
    _LABELSET_RE = re.compile(r"entity label set:\s*(\[[^\]]*\])", re.IGNORECASE)
    _TEXT_RE = re.compile(r"Text:\s*(.*)\s*$", re.IGNORECASE | re.DOTALL)

    def _parse_query(self, query: str) -> Dict[str, str]:
        label_set = "['Organization', 'Person', 'Location', 'Miscellaneous']"
        m = self._LABELSET_RE.search(query)
        if m:
            label_set = m.group(1)
        sentence = ""
        m2 = self._TEXT_RE.search(query)
        if m2:
            sentence = m2.group(1).strip()
        return {"label_set": label_set, "sentence": sentence}

    # ------------------------------------------------------------------ #
    # Main pipeline
    # ------------------------------------------------------------------ #
    def inference(self, sample) -> Dict[str, Any]:
        query = sample["query"] if isinstance(sample, dict) else str(sample)
        self.conversation_history = []
        parsed = self._parse_query(query)
        label_set = parsed["label_set"]
        sentence = parsed["sentence"]

        demos = self._retrieve_demos(sentence)
        demo_block = ""
        if demos:
            lines = []
            for d in demos:
                lines.append(f"Text: {d['sentence']}\n"
                             f"Entity labels: {self._format_label(d['label'])}")
            demo_block = "\n\n".join(lines)

        # === Agent 2: TRF Extractor ===
        trfs_text = ""
        if self.use_trf_extractor:
            trf_system = (
                "You are a type-related feature (TRF) extractor for named entity "
                "recognition. TRFs are tokens or short phrases strongly associated "
                "with entity types (e.g. 'member', 'teams' relate to Person; "
                "'music video games' relates to Miscellaneous)."
            )
            trf_prompt = (
                f"Given entity label set: {label_set} and target sentence: "
                f"'{sentence}', please identify the TRFs for the target sentence. "
                f"Provide the answer in the following list format: "
                f"['TRF1', 'TRF2', ...]."
            )
            trfs_text = self._ask("TRFExtractor", 0, "trf_extraction",
                                  trf_prompt, system_prompt=trf_system)

        # === Agent 3: Demonstration Discriminator (self-reflection) ===
        helpfulness_text = ""
        if self.use_discriminator and demos:
            disc_system = (
                "You are a demonstration discriminator. Using a self-reflection "
                "mechanism, you assess how helpful each provided example is for "
                "recognizing entities in the target sentence."
            )
            disc_prompt = (
                f"Given entity label set: {label_set}, target sentence: "
                f"'{sentence}'"
                + (f" and its TRF set: {trfs_text}" if trfs_text else "")
                + ".\n\nHere are some example sentences and their entity labels:\n"
                + demo_block +
                "\n\nPlease predict the helpfulness score of each example "
                "sentence (1=least helpful, 5=most helpful) for extracting "
                "entities from the target sentence. Provide the answer in the "
                "JSON format: [{\"sentence id\": \"helpfulness score\"}]."
            )
            helpfulness_text = self._ask("Discriminator", 0, "helpfulness_scoring",
                                         disc_prompt, system_prompt=disc_system)

        # === Agent 4: Overall Predictor ===
        pred_system = (
            "You are an expert in named entity recognition. You are good at "
            "information extraction. Integrate the type-related features and "
            "demonstration helpfulness scores to produce the final answer."
        )
        pred_parts = [f"Given entity label set: {label_set}."]
        if trfs_text:
            pred_parts.append(f"Consider the TRFs for the target sentence: {trfs_text}.")
        if helpfulness_text:
            pred_parts.append(f"Consider the helpfulness scores: {helpfulness_text}.")
        if demo_block:
            pred_parts.append("Here are some example sentences and their entity "
                              "labels:\n" + demo_block)
        pred_parts.append(
            f"Now recognize the named entities in the target sentence. "
            f"Provide the answer in the following JSON format: "
            f"[{{\"Entity Name\": \"Entity Label\"}}]. If there is no entity in "
            f"the text, return the following empty list: [].\n\n"
            f"Target sentence: {sentence}\nAnswer:"
        )
        pred_prompt = "\n\n".join(pred_parts)
        final = self._ask("OverallPredictor", 0, "final_prediction",
                          pred_prompt, system_prompt=pred_system)

        return {
            "response": final,
            "history": list(self.conversation_history),
            "trfs": trfs_text,
            "helpfulness": helpfulness_text,
        }
