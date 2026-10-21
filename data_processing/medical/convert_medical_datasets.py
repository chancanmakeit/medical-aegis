#!/usr/bin/env python3
# file: data_processing/medical/convert_medical_datasets.py
"""
Convert medical QA datasets into AEGIS input JSON (a list of samples).

Supported datasets (--dataset):
  MCQ (single best option):
    medqa            -> bigbio/med_qa (or GBaker/MedQA-USMLE-4-options)
    medmcqa          -> openlifescienceai/medmcqa
    mmlu_<subset>    -> cais/mmlu, subsets:
                          clinical_knowledge, medical_genetics, anatomy,
                          professional_medicine, college_biology, college_medicine
    mmlu_pro_health  -> TIGER-Lab/MMLU-Pro (filtered to category 'health')
  yes/no/maybe:
    pubmedqa         -> qiaojin/PubMedQA (pqa_labeled)
  error detection:
    medec-ms         -> mkieffer/MEDEC-MS
  numeric:
    medcalc-bench    -> nsk7153/MedCalc-Bench-Verified

Output is written to ./datasets/data/<dataset>.json so it can be fed to
main.py via --dataset_file ./datasets/data/<dataset>.json (or by
--test_dataset_name <dataset>).

Requires `pip install datasets`. Network access to huggingface.co is needed
at runtime; this script does no network calls on import.
"""

import argparse
import json
import os
import hashlib
import re
from typing import List, Dict, Any


# Letters used for MCQ option labelling.
LETTERS = "ABCDEFGHIJ"

MMLU_MED_SUBSETS = {
    "clinical_knowledge", "medical_genetics", "anatomy",
    "professional_medicine", "college_biology", "college_medicine",
}


def _hash_id(prefix: str, text: str) -> str:
    h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{h}"


def _format_mcq_query(question: str, options: List[str]) -> str:
    lines = [question.strip(), "", "Options:"]
    for i, opt in enumerate(options):
        lines.append(f"{LETTERS[i]}. {opt}")
    lines.append("")
    lines.append("Answer with the single best option letter and a brief justification.")
    return "\n".join(lines)


def _load(path: str, **kw):
    try:
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit(
            "The `datasets` package is required. Install it with:\n"
            "    pip install datasets\n"
            f"(original error: {e})"
        )
    return load_dataset(path, **kw)


# --------------------------------------------------------------------------- #
# Per-dataset builders. Each returns List[sample dict] in AEGIS input format.
# --------------------------------------------------------------------------- #

def build_medqa(split: str) -> List[Dict[str, Any]]:
    ds = _load("GBaker/MedQA-USMLE-4-options", split=split)
    out = []
    for i, row in enumerate(ds):
        opts_map = row["options"]  # dict like {"A": "...", "B": "..."}
        options = [opts_map[k] for k in sorted(opts_map.keys())]
        gold_letter = row.get("answer_idx") or row.get("answer")
        if isinstance(gold_letter, str) and gold_letter in opts_map:
            letter = gold_letter
        else:
            # answer text -> letter
            letter = next((k for k, v in opts_map.items() if v == row.get("answer")), "A")
        q = _format_mcq_query(row["question"], options)
        out.append({
            "id": _hash_id("medqa", row["question"]),
            "query": q,
            "answer": letter,
            "ground_truth": {"correct_answer": letter, "answer_text": opts_map.get(letter, "")},
        })
    return out


def build_medmcqa(split: str) -> List[Dict[str, Any]]:
    ds = _load("openlifescienceai/medmcqa", split=split)
    out = []
    for row in ds:
        options = [row["opa"], row["opb"], row["opc"], row["opd"]]
        letter = LETTERS[int(row["cop"])]  # cop is 0-indexed gold option
        q = _format_mcq_query(row["question"], options)
        out.append({
            "id": _hash_id("medmcqa", row["question"]),
            "query": q,
            "answer": letter,
            "ground_truth": {"correct_answer": letter, "answer_text": options[int(row["cop"])]},
        })
    return out


def build_mmlu(subset: str, split: str) -> List[Dict[str, Any]]:
    ds = _load("cais/mmlu", subset, split=split)
    out = []
    for row in ds:
        options = list(row["choices"])
        letter = LETTERS[int(row["answer"])]
        q = _format_mcq_query(row["question"], options)
        out.append({
            "id": _hash_id(f"mmlu_{subset}", row["question"]),
            "query": q,
            "answer": letter,
            "ground_truth": {"correct_answer": letter, "answer_text": options[int(row["answer"])]},
        })
    return out


def build_mmlu_pro_health(split: str) -> List[Dict[str, Any]]:
    ds = _load("TIGER-Lab/MMLU-Pro", split=split)
    out = []
    for row in ds:
        if str(row.get("category", "")).lower() not in {"health", "medical"}:
            continue
        options = list(row["options"])
        letter = row["answer"]  # already a letter in MMLU-Pro
        q = _format_mcq_query(row["question"], options)
        out.append({
            "id": _hash_id("mmlu_pro_health", row["question"]),
            "query": q,
            "answer": letter,
            "ground_truth": {"correct_answer": letter},
        })
    return out


def build_pubmedqa(split: str) -> List[Dict[str, Any]]:
    ds = _load("qiaojin/PubMedQA", "pqa_labeled", split=split)
    out = []
    for row in ds:
        contexts = row.get("context", {})
        ctx_text = " ".join(contexts.get("contexts", [])) if isinstance(contexts, dict) else ""
        question = row["question"]
        q = (
            f"Context: {ctx_text}\n\nQuestion: {question}\n\n"
            "Answer with exactly one of: yes / no / maybe, then justify briefly."
        )
        gold = str(row["final_decision"]).strip().lower()
        out.append({
            "id": _hash_id("pubmedqa", question),
            "query": q,
            "answer": gold,
            "ground_truth": {"correct_answer": gold},
        })
    return out


def build_medec(split: str) -> List[Dict[str, Any]]:
    ds = _load("mkieffer/MEDEC-MS", split=split)
    out = []
    for row in ds:
        # MEDEC text is split into numbered sentences; the system must find the
        # erroneous one (if any) and provide the correction.
        text = row.get("text") or row.get("Sentences") or row.get("clinical_note") or ""
        error_flag = row.get("error_flag", row.get("Error Flag", 0))
        err_sent_id = row.get("error_sentence_id", row.get("Error Sentence ID", -1))
        correction = row.get("corrected_sentence", row.get("Corrected Sentence", ""))
        try:
            err_sent_id = int(err_sent_id)
        except (TypeError, ValueError):
            err_sent_id = -1
        has_error = str(error_flag) in {"1", "True", "true"} or err_sent_id >= 0

        q = (
            "The following clinical text has numbered sentences. Identify whether it "
            "contains a medical error. If it does, state the erroneous sentence id "
            "(format: 'Sentence <id>') and provide the corrected sentence. If there is "
            "no error, reply 'No error'.\n\n"
            f"{text}"
        )
        gt_answer = correction if has_error else "CORRECT"
        out.append({
            "id": _hash_id("medec", str(text)[:200]),
            "query": q,
            "answer": gt_answer,
            "ground_truth": {
                "correct_answer": gt_answer,
                "error_sentence_id": err_sent_id if has_error else -1,
                "has_error": bool(has_error),
            },
        })
    return out


def build_medcalc(split: str) -> List[Dict[str, Any]]:
    ds = _load("nsk7153/MedCalc-Bench-Verified", split=split)
    out = []
    for row in ds:
        question = row.get("Question") or row.get("question") or ""
        note = row.get("Patient Note") or row.get("patient_note") or ""
        gold = row.get("Ground Truth Answer") or row.get("ground_truth_answer") or row.get("answer")
        lower = row.get("Lower Limit") or row.get("lower_limit")
        upper = row.get("Upper Limit") or row.get("upper_limit")
        q = (
            f"Patient Note:\n{note}\n\nQuestion: {question}\n\n"
            "Show your calculation and give the final numeric answer."
        )
        out.append({
            "id": _hash_id("medcalc", (note + question)[:200]),
            "query": q,
            "answer": gold,
            "ground_truth": {
                "correct_answer": gold,
                "lower_limit": lower,
                "upper_limit": upper,
            },
        })
    return out


def build_medxpertqa(subset: str, split: str,
                     images_dir: str = None) -> List[Dict[str, Any]]:
    """Build MedXpertQA samples (Text or MM subset).

    The HF dataset has these fields per record:
        id, question, options (dict letter→text), label (gold letter),
        medical_task, body_system, question_type
        + for MM: images: [filename, ...]

    The `question` field already contains the answer-choices block formatted as
    "Answer Choices: (A) ... (B) ...", so we use it verbatim and only append a
    short instruction line.

    Args:
      subset: "text" or "mm"
      split:  "dev" or "test"
      images_dir: optional local directory where MM images live. If provided,
                  each MM sample's image filenames are resolved to absolute
                  paths under this dir and stored in `image_paths`. (Trajectory
                  generation is currently text-only; image paths are preserved
                  so a downstream multimodal-capable MAS run can use them.)
    """
    if subset.lower() not in ("text", "mm"):
        raise SystemExit(f"MedXpertQA subset must be 'text' or 'mm', got '{subset}'.")
    hf_subset = "Text" if subset.lower() == "text" else "MM"
    # MedXpertQA uses HuggingFace config-name 'Text' or 'MM' and split 'dev'/'test'.
    ds = _load("TsinghuaC3I/MedXpertQA", name=hf_subset, split=split)
    out = []
    for row in ds:
        q_text = row["question"].strip()
        # The dataset embeds Answer Choices in the question already, so we just
        # append a short imperative to make the expected output unambiguous.
        query = q_text + "\n\nAnswer with the single best option letter and a brief justification."
        opts_map = row.get("options") or {}
        gold_letter = (row.get("label") or "").strip()
        gold_text = opts_map.get(gold_letter, "") if isinstance(opts_map, dict) else ""

        sample = {
            "id": str(row.get("id") or _hash_id(f"mxq_{subset.lower()}", q_text)),
            "query": query,
            "answer": gold_letter,
            "ground_truth": {"correct_answer": gold_letter, "answer_text": gold_text},
            # Preserve dataset-specific metadata for downstream filtering.
            "medical_task": row.get("medical_task"),
            "body_system": row.get("body_system"),
            "question_type": row.get("question_type"),
        }

        if hf_subset == "MM":
            image_filenames = list(row.get("images") or [])
            # Always store the bare filenames. This is the PORTABLE form —
            # main.py resolves them at runtime via its --images_dir flag, so
            # the same dataset JSON works on any machine / cwd.
            sample["images"] = image_filenames
            if images_dir and image_filenames:
                # Bake absolute paths ONLY when caller explicitly asks for it
                # (--images_dir at conversion time). This is a CONVENIENCE
                # cache, NOT the canonical reference. main.py prefers runtime
                # --images_dir > baked paths > recovery from filenames.
                resolved = [os.path.join(os.path.abspath(images_dir), fn)
                            for fn in image_filenames]
                sample["image_paths"] = resolved
            if image_filenames:
                # Inject a textual reference so text-only MAS frameworks at
                # least know an image exists (they will not see it). Frameworks
                # with multimodal support can read sample["image_paths"] or
                # sample["images"].
                sample["query"] = sample["query"] + (
                    f"\n\n[Note: this question references {len(image_filenames)} "
                    f"image(s): {', '.join(image_filenames)}. A multimodal-capable "
                    f"agent should consult the image(s) for diagnosis.]"
                )
        out.append(sample)
    return out


def medxpertqa_lines_layout(rows) -> List[Dict[str, Any]]:
    """MedXpertQA Text rows (HF jsonl) -> samples in the common MCQ layout
    "<stem>\n\nOptions:\nA. ..\n...\n\nAnswer with ...", i.e. the layout the
    frameworks' option parsers expect (medagents_mc.parse_mcq_query, the
    factory's option-letter reader). The inline "Answer Choices: (A) .. (B) .."
    block of the raw question is removed and rebuilt from `options`.
    Added 2026-10-21 (user: MDAgents can use MedXpertQA-Text)."""
    out = []
    for row in rows:
        stem = re.split(r"\n?Answer Choices:", row["question"])[0].strip()
        opts = row.get("options") or {}
        letters = sorted(opts)
        # option texts are put on one line each (a few contain newlines)
        query = _format_mcq_query(stem, [" ".join(str(opts[k]).split()) for k in letters])
        gold = (row.get("label") or "").strip()
        out.append({
            "id": f"medxpertqa_text_{row.get('id', '').replace('Text-', '')}",
            "query": query,
            "answer": gold,
            "ground_truth": {"correct_answer": gold, "answer_text": opts.get(gold, "")},
            "medical_task": row.get("medical_task"),
            "body_system": row.get("body_system"),
            "question_type": row.get("question_type"),
        })
    return out


def build_medxpertqa_text(split: str) -> List[Dict[str, Any]]:
    return build_medxpertqa("text", split)


def build_medxpertqa_mm(split: str, images_dir: str = None) -> List[Dict[str, Any]]:
    return build_medxpertqa("mm", split, images_dir=images_dir)


# --------------------------------------------------------------------------- #
# MedConceptsQA  (https://huggingface.co/datasets/ofir408/MedConceptsQA)
# --------------------------------------------------------------------------- #
# A medical-coding MCQ benchmark with 16 official subsets:
#   "all"  -> union of everything (820k rows in test)
#   "<vocab>_<level>"  for each of 5 vocabularies x 3 difficulties (15 subsets)
#
# Schema per row (already MCQ-ready, options inlined into the question text):
#   question_id, question, answer (full text), answer_id (A/B/C/D),
#   option1..option4, vocab, level
#
# We turn each row into the AEGIS sample shape (id / query / answer /
# ground_truth) used by the rest of the pipeline. Because `question_id` is
# only unique WITHIN a (vocab, level) subset, we prefix the AEGIS id with the
# subset to make it globally unique across the converted file.
MEDCONCEPTSQA_VOCABS = ("atc", "icd9cm", "icd9proc", "icd10cm", "icd10proc")
MEDCONCEPTSQA_LEVELS = ("easy", "medium", "hard")


def _parse_medconceptsqa_subset(subset_spec: str) -> str:
    """Normalize the user-facing AEGIS subset name into the HF subset name.

    AEGIS CLI accepts (case-insensitive):
        - "all"  / "" / None  -> "all"
        - "<vocab>_<level>"   -> passed through (HF native form)
        - "<vocab>-<level>"   -> converted to "<vocab>_<level>"
    """
    if not subset_spec or subset_spec.lower() == "all":
        return "all"
    s = subset_spec.strip().lower().replace("-", "_")
    if s == "all":
        return "all"
    parts = s.split("_")
    if len(parts) >= 2 and parts[-1] in MEDCONCEPTSQA_LEVELS:
        # vocab can itself contain underscores, so glue everything except the
        # last token back together (covers e.g. icd10cm_easy).
        vocab = "_".join(parts[:-1])
        level = parts[-1]
        if vocab in MEDCONCEPTSQA_VOCABS:
            return f"{vocab}_{level}"
    raise SystemExit(
        f"Unknown MedConceptsQA subset '{subset_spec}'. "
        f"Use 'all' or '<vocab>_<level>' / '<vocab>-<level>' where "
        f"vocab in {MEDCONCEPTSQA_VOCABS} and level in {MEDCONCEPTSQA_LEVELS}."
    )


def build_medconceptsqa(subset_spec: str, split: str) -> List[Dict[str, Any]]:
    """Build MedConceptsQA samples from a chosen subset + split.

    Args:
        subset_spec: AEGIS name for the subset, e.g. "all", "atc-easy",
                     "icd10cm_hard". See _parse_medconceptsqa_subset for the
                     accepted forms. The "all" subset spans every vocabulary
                     and difficulty.
        split:       "dev" (60 rows per subset, useful for piloting) or
                     "test" (full split — can be very large).
    """
    hf_subset = _parse_medconceptsqa_subset(subset_spec)
    ds = _load("ofir408/MedConceptsQA", hf_subset, split=split)
    out = []
    for row in ds:
        q_text = (row.get("question") or "").strip()
        # `question` already contains "What is the description of ... A. ... B. ... C. ... D. ...".
        # Append a single imperative so model output format is unambiguous.
        query = q_text + "\n\nAnswer with the single best option letter (A-D) and a brief justification."

        gold_letter = (row.get("answer_id") or "").strip().upper()
        gold_text = row.get("answer") or ""

        # Globally-unique id: subset + per-subset question_id (which may
        # otherwise collide across vocab/level combinations).
        vocab = row.get("vocab") or "?"
        level = row.get("level") or "?"
        qid = row.get("question_id")
        sample_id = f"medconceptsqa-{vocab.lower()}-{level.lower()}-{qid}"

        sample = {
            "id": sample_id,
            "query": query,
            "answer": gold_letter,
            "ground_truth": {"correct_answer": gold_letter, "answer_text": gold_text},
            # Metadata for downstream filtering / per-vocab analysis
            "vocab": vocab,
            "level": level,
        }
        out.append(sample)
    return out


# --------------------------------------------------------------------------- #
# Trial-Success  (ClinicalAgent's clinical-trial-outcome-prediction dataset)
# --------------------------------------------------------------------------- #
# Source: `algo/agents/tool/risk_model/data/trial_success.csv` from the
#         GuihaiChen1998/full-clinical-agent release (based on the LeoYML
#         clinical-agent repo, ACM-BCB 2024).
#
# Format: TAB-separated (\t), 5 columns:
#   nctid    - ClinicalTrials.gov identifier (globally unique, e.g. NCT00000172)
#   criteria - eligibility criteria free text (inclusion + exclusion)
#   drugs    - semicolon-separated list of drug names, lowercase
#   diseases - semicolon-separated list of disease names, lowercase
#   label    - binary outcome: 1 = trial succeeded, 0 = trial failed
#
# 23,045 rows total (label dist: 13,655 success / 9,390 failure).
#
# TASK: given (drugs, diseases, criteria), predict FAILURE probability p in [0,1].
# The paper's convention is to predict 1-label (i.e. failure), and verify by
# thresholding at 0.5. We keep the RAW label (1=success) in the sample and let
# the verifier handle the inversion + thresholding.
#
# The framework outputs its answer wrapped in `<final_result>0.X</final_result>`
# tags -- this drives the "probability" task_type in the verifier and factory.
def build_trial_success(csv_path: str, limit: int = None) -> List[Dict[str, Any]]:
    """Read trial_success.csv into the AEGIS sample shape.

    Args:
      csv_path: path to trial_success.csv. Required (no HF download available).
      limit:    optional row cap.

    The output samples have:
      id            = nctid (e.g. "NCT00000172")
      query         = a formatted user problem asking the framework to predict
                      the trial's failure probability
      answer        = "1" if the trial FAILED (label==0 flipped), "0" otherwise
      ground_truth  = {"correct_answer": <"0"|"1">, "raw_label": <0|1>,
                       "predict_target": "failure_probability",
                       "threshold": 0.5, "nctid": ..., "drugs": ...,
                       "diseases": ...}
    """
    if not os.path.exists(csv_path):
        raise SystemExit(
            f"trial_success.csv not found at {csv_path}. Extract "
            f"full-clinical-agent.7z and point --csv_path to "
            f"algo/agents/tool/risk_model/data/trial_success.csv."
        )

    import csv as _csv
    out = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = _csv.DictReader(f, delimiter="\t")
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            nctid = (row.get("nctid") or "").strip()
            criteria = (row.get("criteria") or "").strip()
            drugs = (row.get("drugs") or "").strip()
            diseases = (row.get("diseases") or "").strip()
            raw_label_str = (row.get("label") or "").strip()
            try:
                raw_label = int(raw_label_str)
            except ValueError:
                continue  # skip malformed rows
            if raw_label not in (0, 1):
                continue
            # Framework predicts FAILURE probability. If raw_label==1 (success),
            # the correct FAILURE prediction is 0 (i.e. probability <0.5).
            # If raw_label==0 (failure), correct FAILURE prediction is 1.
            failure_gold = "0" if raw_label == 1 else "1"

            query = (
                f"#My problem#: <problem>I have designed a clinical trial and hope "
                f"you can help me predict the probability of failure for this "
                f"clinical trial.</problem>\n"
                f"#drugs#: <drug>{drugs}</drug>\n"
                f"#diseases#: <disease>{diseases}</disease>\n"
                f"#criteria#: <criteria>{criteria}</criteria>\n\n"
                f"Analyze safety, efficacy, and enrollment feasibility, then give "
                f"your final failure probability in `<final_result>0.X</final_result>` "
                f"tags (value between 0 and 1, where 1 = trial will fail)."
            )
            out.append({
                "id": nctid or f"trial-{i}",
                "query": query,
                "answer": failure_gold,
                "ground_truth": {
                    "correct_answer": failure_gold,
                    "raw_label": raw_label,
                    "predict_target": "failure_probability",
                    "threshold": 0.5,
                    "nctid": nctid,
                    "drugs": drugs,
                    "diseases": diseases,
                },
            })
    return out


def build(dataset: str, split: str, images_dir: str = None,
          csv_path: str = None, limit: int = None) -> List[Dict[str, Any]]:
    d = dataset.lower()
    if d == "medqa":
        return build_medqa(split)
    if d == "medmcqa":
        return build_medmcqa(split)
    if d == "pubmedqa":
        return build_pubmedqa(split)
    if d in {"medec-ms", "medec"}:
        return build_medec(split)
    if d in {"medcalc-bench", "medcalc"}:
        return build_medcalc(split)
    if d == "mmlu_pro_health":
        return build_mmlu_pro_health(split)
    if d in {"medxpertqa", "medxpertqa-text", "medxpertqa_text"}:
        return build_medxpertqa_text(split)
    if d in {"medxpertqa-mm", "medxpertqa_mm"}:
        return build_medxpertqa_mm(split, images_dir=images_dir)
    # MedConceptsQA: "medconceptsqa" (=all) or "medconceptsqa-<vocab>-<level>"
    # / "medconceptsqa_<vocab>_<level>" / "medconceptsqa-<vocab>_<level>".
    # Examples: medconceptsqa, medconceptsqa-all, medconceptsqa-atc-easy,
    #           medconceptsqa-icd10cm-hard, medconceptsqa_icd9proc_medium.
    if d == "medconceptsqa" or d.startswith("medconceptsqa-") or d.startswith("medconceptsqa_"):
        if d in {"medconceptsqa", "medconceptsqa-all", "medconceptsqa_all"}:
            subset_spec = "all"
        else:
            # Strip the "medconceptsqa-" or "medconceptsqa_" prefix to get the
            # subset spec ("atc-easy", "icd10cm_hard", etc.).
            sep_idx = d.find("-") if d.find("-") != -1 else d.find("_")
            subset_spec = d[sep_idx + 1:]
        return build_medconceptsqa(subset_spec, split)
    if d.startswith("mmlu_"):
        subset = d[len("mmlu_"):]
        if subset not in MMLU_MED_SUBSETS:
            raise SystemExit(
                f"Unknown MMLU medical subset '{subset}'. "
                f"Choose from: {sorted(MMLU_MED_SUBSETS)}"
            )
        return build_mmlu(subset, split)
    # Trial-Success (ClinicalAgent's clinical-trial-outcome prediction dataset).
    # This one lives on disk (not HF) — the caller must pass `csv_path` pointing
    # at trial_success.csv from full-clinical-agent's risk_model/data/ dir.
    if d in {"trial_success", "trial-success", "clinical_trial_outcome",
             "clinical-trial-outcome", "clinicalagent"}:
        if not csv_path:
            raise SystemExit(
                f"--csv_path is required for '{dataset}'. Point it at "
                f"algo/agents/tool/risk_model/data/trial_success.csv from "
                f"the full-clinical-agent release."
            )
        return build_trial_success(csv_path, limit=limit)
    raise SystemExit(f"Unknown dataset '{dataset}'.")


def main():
    p = argparse.ArgumentParser(description="Convert medical datasets to AEGIS input JSON.")
    p.add_argument("--dataset", required=True,
                   help="medqa | medmcqa | pubmedqa | medec-ms | medcalc-bench | "
                        "mmlu_<subset> | mmlu_pro_health | "
                        "medxpertqa-text | medxpertqa-mm | "
                        "medconceptsqa (=all) | medconceptsqa-<vocab>-<level> "
                        "(vocab in {atc, icd9cm, icd9proc, icd10cm, icd10proc}, "
                        "level in {easy, medium, hard}) | "
                        "trial_success (needs --csv_path)")
    p.add_argument("--split", default="test", help="HF split (e.g. test, validation, dev, train).")
    p.add_argument("--limit", type=int, default=None, help="Keep only the first N samples.")
    p.add_argument("--out_dir", default="./datasets/data", help="Output directory.")
    p.add_argument("--images_dir", default=None,
                   help="(MedXpertQA-MM only, OPTIONAL) If provided, ALSO bake absolute "
                        "image_paths into the dataset JSON as a convenience cache. NOT "
                        "RECOMMENDED for portable datasets — pass --images_dir to main.py "
                        "at run time instead; the same dataset JSON then works on any "
                        "machine. The canonical reference is sample['images'] (bare "
                        "filenames), which is always saved.")
    p.add_argument("--csv_path", default=None,
                   help="(trial_success only) Path to trial_success.csv from the "
                        "full-clinical-agent release: "
                        "algo/agents/tool/risk_model/data/trial_success.csv")
    args = p.parse_args()

    samples = build(args.dataset, args.split, images_dir=args.images_dir,
                    csv_path=args.csv_path, limit=args.limit)
    if args.limit:
        samples = samples[:args.limit]

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{args.dataset}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(samples)} samples -> {out_path}")


if __name__ == "__main__":
    main()
