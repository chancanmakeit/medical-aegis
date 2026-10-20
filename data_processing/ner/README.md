# NER dataset processing (CMAS / WikiGold)

Converts NER datasets into the AEGIS sample shape. Currently supports WikiGold
as shipped with the CMAS framework (WWW 2025, arXiv:2502.18702).

## WikiGold

Source: the CMAS release's `data/wikigold/` directory (pre-processed).

Convert the test set:

```bash
python data_processing/ner/convert_ner_datasets.py \
    --dataset wikigold \
    --data_dir /path/to/CMAS/data/wikigold \
    --split test --out_dir ./datasets/data
# -> ./datasets/data/wikigold.json  (274 samples)
```

Each sample:

```json
{
  "id": "wikigold-0",
  "query": "Given entity label set: ['Organization', 'Person', 'Location', 'Miscellaneous'], please recognize the named entities in the given text. Provide the answer in the following JSON format: [{\"Entity Name\": \"Entity Label\"}]. If there is no entity in the text, return the following empty list: [].\n\nText: UK Edition came with the OSC-DIS video ...",
  "answer": "[{\"OSC-DIS\": \"Miscellaneous\"}, {\"UK\": \"Location\"}]",
  "ground_truth": {
    "entities": {"OSC-DIS": "Miscellaneous", "UK": "Location"},
    "label_set": ["Organization", "Person", "Location", "Miscellaneous"],
    "sentence": "UK Edition came with the OSC-DIS video ...",
    "eval": "ner_micro_f1"
  }
}
```

## Scoring

NER is scored by `aegis_core/utils/ner_verifier.py` with entity-level micro-F1
using EXACT matching (both the span text and type must match, per the paper's
"complete matching" evaluation). AEGIS's per-sample `is_correct` thresholds the
F1: correct iff `F1 >= ner_f1_threshold` (default 1.0 = perfect prediction;
set lower in the experiment YAML for partial credit). The audit dict stores the
raw precision/recall/F1 and tp/fp/fn so a downstream aggregator can compute
corpus-level micro-F1 across samples.

## Demonstration pool (for CMAS in-context learning)

CMAS's demonstration discriminator and overall predictor use in-context demos
drawn from the self-annotated `train.json`. Copy it somewhere and point the
experiment YAML at it:

```yaml
cmas_demo_pool_path: "/path/to/CMAS/data/wikigold/train.json"
cmas_demo_retrieval_mode: "stub_topk"   # first-N demos (deterministic)
cmas_few_shot_number: 4
```

When no demo pool is provided, CMAS runs demo-free (pure zero-shot); the
discriminator agent is skipped in that case since it has nothing to score.
