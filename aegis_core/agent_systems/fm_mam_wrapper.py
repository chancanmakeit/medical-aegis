# file: aegis_core/agent_systems/fm_mam_wrapper.py
"""
FM-injection wrapper for MAM (method `mam`, methods/mam/mam_main.py).

Structural roles: TypeClassifier(0), RoleGenerator(0), AudioDescriber(0),
Specialist(0..2) [phases discussion / vote, round k], Moderator(0) [phases
quality_check / summary, round k], Diagnostician(0), Reviewer(0).
Targets may pin `phase` and `round` (e.g. Specialist 1, phase vote, round 2).

MAM answers in free text, so YAMLs use task_type "classification": response
corruption rewrites the class the text ends on and appends an explicit
"Final answer: <other class>" (factory free-text branch); the class list is
handed to the factory per sample.
"""
import os
from typing import Any, Dict

from .fm_structured_wrapper import StructuredFMWrapper


class FMMAMWrapper(StructuredFMWrapper):
    FRAMEWORK = "mam"
    CONFIG_NAME_KEY = "mam_config_name"
    DEFAULT_CONFIG_NAME = "config_audio"

    def configure(self, exp_config: Dict[str, Any]) -> None:
        for key, attr in (("mam_audio_model_name", "audio_model_name"),
                          ("mam_text_model_name", "text_model_name"),
                          ("mam_max_rounds", "max_rounds"),
                          ("mam_web_search", "web_search")):
            if exp_config.get(key) is not None:
                setattr(self.mas, attr, exp_config[key])
        self.mas.max_rounds = int(self.mas.max_rounds)

    def build_sample(self, task: Any) -> Dict[str, Any]:
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        audio = (raw.get("audio") or {}).get("path")
        if not audio:
            raise ValueError("MAM sample has no audio.path (build it with data_processing/audio/convert_mam_datasets.py)")
        if not os.path.isabs(audio):
            audio = os.path.abspath(audio)
        if not os.path.exists(audio):
            raise FileNotFoundError(f"audio file not found: {audio} (run from the repo root or rebuild the dataset)")
        return {"query": task.query, "audio_path": audio}

    def before_run(self, task: Any, sample: Dict[str, Any]) -> None:
        raw = (getattr(task, "metadata", None) or {}).get("raw_sample") or {}
        self.fm_factory.classification_labels = list((raw.get("ground_truth") or {}).get("classes") or [])

    def extra_log(self, final_output: Any) -> Dict[str, Any]:
        fo = final_output if isinstance(final_output, dict) else {}
        return {k: fo.get(k) for k in ("roles", "type_name", "vote_log", "review", "meeting_record")}
