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

---

# Part 2 (2026-11-03 11:42-, after the user's decisions: add the other frameworks; multimodal QA datasets
# for image frameworks; eval pool per our recommendation)

**Measured price.** The xiaojingai usage endpoint (`/v1/dashboard/billing/usage`, units of ¥0.01) moved by
23.32 for 185 natural runs whose tokens cost ¥0.2336 at ¥0.036 / ¥0.144 per M tokens: **the price list is
per M tokens**, about 1/20 of the Google list price. Spend in this part: ¥2.25 (≈ $0.31); the whole trial
day ≈ ¥2.5 (≈ $0.35).

## A. Eval pool: 800 questions
`datasets/data/pools_v1/eval.json` now holds 800 (corpus 1,449); the previous 400 are its first 400 (same
seeded group order), so every run so far stays in the eval pool.

## B. Four more frameworks: calibration (20 wrong-ending parents each, every LLM step, protocol v2)
| | points | flips | confirmed | 2nd control disagrees (flipped / random undetermined) | noise floor d | expected noise-confirmed (~d/2 per point) | excess |
|---|---|---|---|---|---|---|---|
| llm_debate | 126 | 9 | 7 | 2/9, 0/12 | 0.016 | 1.0 | +6 |
| mdagents | 119 | 7 | 5 | 2/7, 0/11 | 0.017 | 1.0 | +4 |
| AgentVerse | 162 | 31 | 19 | 12/31, 1/13 | 0.136 | 11.0 | +8 |
| DyLAN | 219 | 51 | 28 | 23/51, 1/17 | 0.150 | 16.4 | +12 |
| MAC group chat | 195 | 5 | 4 | 1/5, 1/19 | 0.056 | 5.5 | -1.5 |
| MedAgents | 381 | 37 | 21 | 16/37, 2/34 | 0.095 | 18.1 | +3 |

(noise floor d = control-vs-control disagreement reweighted to all points; under the null the branch is a
third draw of the same downstream, so a "confirmed" flip still happens with probability ~ P(c1 = c2 != b) ~
d/2 for near-binary outcomes.) **Protocol v2 is enough only where the downstream is stable (llm_debate,
mdagents on gemini: d ~ 2%).** In AgentVerse, DyLAN and MedAgents the downstream answer of a single
re-generation changes 10-15% of the time, so most "confirmed" flips there are compatible with noise; in MAC
all of them are. Step types with many unconfirmed flips: MedAgents question_analysis (18 flips, 11 second
controls = branch), DyLAN round-1 answers (34, 10).

## C. Fixes found by the calibration
- **DyLAN used the module-level `random`** (shared by main.py's worker threads), so node order depended on
  thread scheduling and runs could not be replayed (offline replay 85/220 hits). Now a private
  `random.Random(seed)` per run: 599/599 hits. The 55 earlier gemini DyLAN runs are kept as
  `dylan__normal_eval_globalrng_unreplayable` (valid natural runs, not usable as branching parents); the
  DyLAN calibration above uses 55 new runs. Other frameworks replay 100% offline (MedAgents 372/372, MAC
  202/202, AgentVerse 143/143, llm_debate 217/217).
- **Branch identity in frameworks with parallel calls / dynamic control flow**: MedAgents numbers steps in
  completion order and AgentVerse / MAC / DyLAN can stop earlier or run longer after t. Upstream calls are
  now matched to steps of the run by the request key (identical inputs told apart by text), step t gets
  `t_step_id_in_run`, and `branch.structure` records `parent_step_ids`, `new_step_ids`, `dropped_step_ids`,
  `renumbered` and, when the structure is unchanged, `hidden_dependency_step_ids` (parent steps outside
  {t} + D(t) that had to be regenerated: a read or control dependency the recorded `sources` miss: DyLAN
  221 / 350 unchanged records, MedAgents 1, AgentVerse 1, mdagents / llm_debate 0). 2,121 + 529 records,
  0 identity problems.

## D. Multimodal datasets (image framework: mdagents)
Built by `scripts/build_mm_datasets.py` into `datasets/data/mm_v1/` (images under `/home/claude/mm_data`,
not in git; sources pinned to HF commit SHAs; eval 200 per dataset, split by image group):
| dataset | license | kept (closed MCQ) | eval / corpus | notes |
|---|---|---|---|---|
| MedXpertQA MM | MIT | 1,998 / 2,000 | 200 / 1,798 | 2 items dropped (distractor text leaks the answer); 82 flagged `options_are_image_labels` |
| PathVQA | MIT (images: publishers / PEIR) | 3,354 yes/no of 6,719 | 200 / 3,154 | yes 54% |
| SLAKE | CC-BY-4.0 | 412 English closed of 2,094 | 200 / 212 | only 96 images |
| Kvasir-VQA-x1 | **CC-BY-NC-4.0** | 1,124 yes/no of 15,955 | 200 / 924 | about 2/3 of kept questions are non-clinical (text / box artifacts) |
mdagents trial, 10 questions each: all ran; images reach every expert and the aggregator (recorded as task
observations); accuracy 4/10 MedXpertQA-MM, 8/10 PathVQA, 8/10 SLAKE, 9/10 Kvasir; ¥0.019 in total.
Replay keys now ignore image parts (recorded inputs keep the text; images are observations): mdagents MM
replays 70/70.
