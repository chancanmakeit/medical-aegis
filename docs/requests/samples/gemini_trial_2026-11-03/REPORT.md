# Gemini trial (2026-11-03): gemini-2.5-flash-lite on the xiaojingai endpoint

Backbone chosen by the user for the new multi-framework batch. Trial quoted at <= $1 (issue #1 r51).
**Spend at the Google list price ($0.10 / $0.40 per M tokens), an upper bound: $0.48** (natural runs $0.21,
branching $0.27) + ~$0.03 for a failed DyLAN attempt + probes (< $0.001). The xiaojingai price list says
¥0.036 / ¥0.144 for this model; if that is per M tokens, the real spend is about ¥0.2 (to be confirmed
against the account balance).

Outputs (all records exported with 0 problems; `sources` runtime-recorded on 101/101 normal runs):
`data_runs/gemini_trial_2026-11-03/{natural,branch_cal}/`; candidates, call logs without texts and the
calibration output in this folder. Questions: `datasets/data/pools_v1/eval.json` (built by
`scripts/build_question_pools.py`: MedXpertQA-Text minus the 100 anchor questions and 101 MAA overlaps,
grouped by stem Jaccard >= 0.3, 400 eval / 1,849 corpus; anchor questions are in MHT's TAPT corpus).

## 1. Endpoint behaviour
- Served model `gemini-2.5-flash-lite` on every call (no substitution, unlike aihubmix's llama name).
- **Temperature 0 is not deterministic**: same prompt 5x (2x with `seed`): 5 different texts.
- **Two channels**: identical requests are billed either n or n + 253 prompt tokens (10 calls: 5 / 5;
  also inside runs, e.g. three identical llm_debate round-1 prompts at 224 / 224 / 477). The model reports
  no visible preamble. Recorded per step in `labels.llm_meta[step].prompt_tokens`, so runs can be
  stratified by channel if needed.

## 2. Natural runs (K = 1, eval pool)
| framework | runs | accuracy | LLM steps | tokens in / out per run | $ per run (list) |
|---|---|---|---|---|---|
| llm_debate | 31 | 0.42 | 7.0 | 8.1k / 1.9k | 0.0016 |
| mdagents | 30 | 0.43 | 7.0 | 4.2k / 1.2k | 0.0009 |
| medagents_mc | 10 | 0.60 | 18.0 | 27.7k / 6.5k | 0.0054 |
| MAC group chat | 10 | 0.70 | 9.4 | 19.9k / 1.3k | 0.0025 |
| DyLAN | 10 | 0.60 | 11.0 | 18.6k / 5.6k | 0.0041 |
| AgentVerse | 10 | 0.60 | 6.9 | 7.5k / 1.8k | 0.0015 |

All six run on a real endpoint. **DyLAN had been broken since the round cap of 2026-10-21**:
`methods/dylan/configs/config_medical.yaml` set `num_rounds: 2`, DyLAN asserts `> 2` and builds its
network from that value at init, so every run ended with an empty AssertionError, status "success" and no
steps. Fixed: `num_rounds: 3` (the smallest valid value, upstream default). Also: the structured wrapper now
keeps the exception type and traceback, `main.py` marks a run whose framework crashed before any step as
`status: framework_error`, and the exporter skips it.

## 3. Branching calibration (protocol v2, every LLM step of every wrong-ending run)
| | llm_debate | mdagents |
|---|---|---|
| parents / points | 18 / 126 | 17 / 119 |
| flips (rep 0) | 9 | 7 |
| confirmed (2nd control agrees, both != branch) | **7** | **5** |
| 2nd control = branch (noise) | 2 | 1 |
| control re-runs disagree: flipped / random undetermined | 2/9 / 0/12 | 2/7 / 0/11 |
| wrong -> right among flips | 1 | 0 |
| **confirmed flips per parent** | **0.39** (5/18 parents have >= 1) | **0.29** (3/17) |

By step type: llm_debate round 1 6/54 flips (4 confirmed), round 2 2/54 (2), aggregator 1/18;
mdagents experts 6/85 (5), recruiter 1/17 (0), aggregator 0/17. The resample changed the letter at t much
less often than on the anchor backbone (llm_debate round 1: 12/54 vs 51/90 in plan A), so gemini is
"stickier": fewer flips per point. Note: for aggregator points D(t) is empty, the control is a pure replay
and "confirmation" is vacuous; the single aggregator flip is single-step sampling noise by construction.

## 4. Quote for the eval set (gemini, list price; yields from 18 / 17 parents, wide uncertainty)
| framework | $ per parent (branching + confirmation) | confirmed / parent | per 100 confirmed |
|---|---|---|---|
| llm_debate | 0.0100 | 0.39 | ~257 parents, **~$3.3** |
| mdagents | 0.0051 | 0.29 | ~340 parents, **~$2.3** |

200 confirmed (100 each): **~$5.6** at list price (at the xiaojingai price list, if per M tokens, ~20x less).
Needs more parents than the 400-question eval pool gives at K = 1 (~58% of runs end wrong): K = 2-3 per
question, or a larger eval pool. medagents_mc / MAC / DyLAN / AgentVerse yields are not measured yet.
