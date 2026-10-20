#!/usr/bin/env python3
"""Convert a ConSensus split (WESAD / SleepEDF) into an AEGIS dataset JSON.

Upstream pipeline (nokia/multi-agent-collaboration-for-multimodal-sensing):
  python preprocess/preprocess_<WESAD|SleepEDF>.py --path <raw> --out_dir <out>
  python preprocess/split.py --data_path <out> --test_per_class 30 \
         --examples_per_class 1 --output_path <out>/splits
This script reads <out>/splits/default_ex_1_seed_0 (a datasets.save_to_disk
folder with info.json) and writes one AEGIS sample per test record:

  {
    "id": "<dataset>-<user_id>-<sample_id>",
    "query": "<task description + classes>",          # human-readable only
    "answer": "<gold label>",
    "ground_truth": {"correct_answer": "<gold>", "classes": [...]},
    "consensus": {
        "test":     {"features": {...}, "user_id": ..., "sample_id": ...},   # NO label
        "examples": [{"features": {...}, "label": ..., ...}, ...],          # labelled few-shot
        "info":     <info.json>                                             # task/classes/modalities
    }
  }

The gold label is removed from consensus.test so nothing the MAS reads can
contain it (upstream also never shows it to the agents; it only logs it).

Usage:
  python data_processing/sensing/convert_consensus_datasets.py \
      --split_dir <out>/splits/default_ex_1_seed_0 --dataset sleepedf \
      --out ./datasets/data/sleepedf.json
"""
import argparse
import json
import os


def convert(split_dir: str, dataset: str):
    import datasets  # HF datasets (load_from_disk)
    info = json.load(open(os.path.join(split_dir, "info.json"), encoding="utf-8"))
    ds = datasets.load_from_disk(split_dir)
    classes = list(info["class"].keys())
    classes_txt = "\n".join(f"  - {k}: {v}" for k, v in info["class"].items())
    query = f"**Task**:\n{info['task']}\n\n**Classes**:\n{classes_txt}"
    out = []
    for rec in ds:
        test = dict(rec["test"])
        gold = test.pop("label")
        out.append({
            "id": f"{dataset}-{test.get('user_id')}-{test.get('sample_id')}",
            "query": query,
            "answer": gold,
            "ground_truth": {"correct_answer": gold, "classes": classes},
            "consensus": {"test": test, "examples": [dict(e) for e in rec["examples"]], "info": info},
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split_dir", required=True)
    ap.add_argument("--dataset", required=True, choices=["wesad", "sleepedf"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    data = convert(a.split_dir, a.dataset)
    if a.limit:
        data = data[: a.limit]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print(f"wrote {len(data)} samples to {a.out}; label counts: {dict(Counter(d['answer'] for d in data))}")


if __name__ == "__main__":
    main()
