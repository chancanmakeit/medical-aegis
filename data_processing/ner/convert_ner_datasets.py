#!/usr/bin/env python3
# file: data_processing/ner/convert_ner_datasets.py
"""
Convert NER datasets (currently WikiGold, as shipped with the CMAS framework)
into the AEGIS sample shape used by main.py and the FM-injection wrappers.

WikiGold source: the CMAS release's data/wikigold/ directory, which contains
pre-processed test.json / train.json plus TRF and embedding artifacts:
    test.json                 - list of {idx, sentence, label} for evaluation
    train.json                - demonstration pool (self-annotated corpus)
    abb2labelname.json        - abbreviation -> full label name map
                                (ORG->Organization, PER->Person, ...)
    trf.json                  - type-related features per entity type
    trf_embd.pkl              - TRF embeddings (unused by AEGIS; retrieval stub)
    *_GPTEmb.npy              - sentence embeddings (unused by AEGIS)

Each `label` field is a STRING repr of a dict {entity_text: entity_type}, e.g.
    "{'OSC-DIS': 'Miscellaneous', 'UK': 'Location'}"

We convert every test record into an AEGIS sample:
    id            = "wikigold-<idx>"
    query         = a zero-shot NER instruction embedding the label set + the
                    target sentence, asking for the JSON [{ "Entity": "Type" }]
                    answer format CMAS uses.
    answer        = the gold label dict (normalized) as a JSON string
    ground_truth  = {"entities": {entity: type, ...},   # normalized gold
                     "label_set": [...],                  # full type names
                     "sentence": "...",
                     "eval": "ner_micro_f1"}

The NER task is scored with entity-level micro-F1 (exact span+type match) by
aegis_core/utils/ner_verifier.py.
"""
import argparse
import ast
import json
import os
from typing import Any, Dict, List, Optional


# Default WikiGold label set (full names), from abb2labelname.json values.
WIKIGOLD_LABELS = ["Organization", "Person", "Location", "Miscellaneous"]


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_label_field(label_field: Any) -> Dict[str, str]:
    """Parse the label field (a str repr of a dict, or a dict) into a clean
    {entity_text: entity_type} mapping."""
    if isinstance(label_field, dict):
        return {str(k): str(v) for k, v in label_field.items()}
    if isinstance(label_field, str):
        s = label_field.strip()
        if not s or s in ("{}", "[]", "None"):
            return {}
        try:
            parsed = ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
        # Some datasets store a list of single-key dicts.
        if isinstance(parsed, list):
            out = {}
            for item in parsed:
                if isinstance(item, dict):
                    for k, v in item.items():
                        out[str(k)] = str(v)
            return out
    return {}


def _resolve_label_set(data_dir: str) -> List[str]:
    """Prefer abb2labelname.json's values; fall back to the WikiGold default."""
    abb_path = os.path.join(data_dir, "abb2labelname.json")
    if os.path.exists(abb_path):
        try:
            abb = _load_json(abb_path)
            vals = list(abb.values())
            if vals:
                return vals
        except Exception:
            pass
    return list(WIKIGOLD_LABELS)


def build_wikigold(data_dir: str, split: str = "test",
                   limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Build AEGIS samples from the CMAS wikigold directory.

    Args:
        data_dir: path to .../data/wikigold
        split:    which json to read ("test" or "train"); test is the eval set.
        limit:    optional cap on number of samples.
    """
    json_path = os.path.join(data_dir, f"{split}.json")
    if not os.path.exists(json_path):
        raise SystemExit(
            f"{split}.json not found in {data_dir}. Point --data_dir at the "
            f"CMAS data/wikigold directory."
        )
    records = _load_json(json_path)
    label_set = _resolve_label_set(data_dir)
    label_set_str = str(label_set)

    out = []
    for i, row in enumerate(records):
        if limit and i >= limit:
            break
        idx = row.get("idx", i)
        sentence = (row.get("sentence") or "").strip()
        gold_entities = _parse_label_field(row.get("label"))

        query = (
            f"Given entity label set: {label_set_str}, please recognize the "
            f"named entities in the given text. Provide the answer in the "
            f"following JSON format: [{{\"Entity Name\": \"Entity Label\"}}]. "
            f"If there is no entity in the text, return the following empty "
            f"list: [].\n\n"
            f"Text: {sentence}"
        )

        # answer: canonical JSON string of the gold entity->type mapping,
        # rendered as a list of single-key dicts (CMAS output convention).
        answer_list = [{ent: typ} for ent, typ in gold_entities.items()]

        out.append({
            "id": f"wikigold-{idx}",
            "query": query,
            "answer": json.dumps(answer_list, ensure_ascii=False),
            "ground_truth": {
                "entities": gold_entities,        # {entity_text: type}
                "label_set": label_set,
                "sentence": sentence,
                "eval": "ner_micro_f1",
            },
        })
    return out


def build(dataset: str, data_dir: str, split: str,
          limit: Optional[int] = None) -> List[Dict[str, Any]]:
    d = (dataset or "").strip().lower()
    if d in {"wikigold", "cmas", "cmas-wikigold"}:
        return build_wikigold(data_dir, split=split, limit=limit)
    raise SystemExit(
        f"Unknown NER dataset '{dataset}'. Supported: wikigold."
    )


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True,
                   help="NER dataset name. Supported: wikigold.")
    p.add_argument("--data_dir", required=True,
                   help="Path to the dataset directory, e.g. the CMAS "
                        "data/wikigold folder containing test.json.")
    p.add_argument("--split", default="test", help="test | train (default test).")
    p.add_argument("--limit", type=int, default=None, help="Keep only first N samples.")
    p.add_argument("--out_dir", default="./datasets/data", help="Output directory.")
    args = p.parse_args()

    samples = build(args.dataset, args.data_dir, args.split, limit=args.limit)
    os.makedirs(args.out_dir, exist_ok=True)
    out_name = f"{args.dataset.lower()}.json" if args.split == "test" else \
               f"{args.dataset.lower()}_{args.split}.json"
    out_path = os.path.join(args.out_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(samples)} samples to {out_path}")
    # Quick sanity print
    if samples:
        s0 = samples[0]
        n_ent = len(s0["ground_truth"]["entities"])
        print(f"  sample[0]: id={s0['id']} entities={n_ent} label_set={s0['ground_truth']['label_set']}")


if __name__ == "__main__":
    main()
