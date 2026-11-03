# Round-16 paid runs (approved by the user 2026-10-26 22:50): branching pilot, fmt_v1_2, mdagents opener

Backbone llama-4-maverick via aihubmix (response `model` field: `google/gemma-4-31B-it-turbo`, same as the
recorded mdagents runs; no `system_fingerprint` returned). Spend: branching pilot $0.295, fmt_v1_2 $0.100,
opener $0.140, trials $0.022 -> **$0.557 total** (estimate was $0.46; see "cost" below).

## 1. Branching pilot (scripts/branch_pilot.py, scripts/branch_replay_server.py)
Design: issue round 43 + MHT round 61. 1 branch + 1 control per candidate point. Step t is resampled at the
original temperature 0.7 (mode (a), natural resampling); every step in D(t) (the transitive closure of
the recorded `sources` from t) is generated at temperature 0 in both arms; all other requests are served
from the record. Candidates: wrong-letter answer steps of runs that end wrong (first / middle / last per
run), MAA-overlap questions excluded. Raw outputs: `data_runs/branch_pilot_2026-10-26/`; call logs
(without texts): `branch_calls/`.

| | llm_debate | mdagents |
|---|---|---|
| runs / points | 20 / 58 | 20 / 60 |
| flip (branch final != control final) | **5 (9%)** | **7 (12%)** |
| undetermined (no flip; not a negative) | 53 | 53 |
| flips that turn wrong -> right | 5 | 6 |
| controls re-run (all flips + random undetermined) | 13, disagree **0** | 15, disagree **0** |
| flips confirmed by the 2nd control | 5/5 | 7/7 |
| control final != recorded final | 0/58 | 0/60 |
| same-slot AUROC, recorded step t vs its resample (char 2-5, grouped CV) | **0.47 [0.41, 0.52]** | **0.50 [0.45, 0.55]** |

By position (flip / points):
- llm_debate: round-1 agent 5/20, round-2 agent 0/19, aggregator 0/19.
- mdagents: expert answer 7/40, aggregator 0/20.
- Aggregator points (the last step) have empty D(t): the control is the recorded run and the branch only
  resamples the final step; 0/39 flips -- the final step's own sampling noise never changed the answer.

What drives a flip:
- llm_debate: the resample changed the stated letter at t in 8 points; 5 of those flipped; 0 flips
  among the 31 points whose letter stayed the same.
- mdagents: letter changed at t in 15 points, 5 flipped; 2 more flips with the same letter at t (the
  aggregator reads the experts' reasoning, not only their letters).

Temperature-0 determinism: 28 control re-runs, 0 disagreements in the final answer. In the control arm
all 139 regenerated D(t) steps have new text, but every one states the same letter as the recorded
(0.7) step. With step t kept, the downstream answers are stable, so a flip is attributable to step t.

Greedy continuation and one-sidedness (MHT r61 point 5):
- llm_debate pass 0 (t = a round-1 agent): round 2 was unanimous in 18/20 runs both in the recorded
  0.7 runs and with D(t) at temperature 0. No measurable extra convergence from greedy decoding here.
- Example medxpertqa_text_2287 (gold E):
  - control: round 1 C / E / E, then round 2 C / C / C, final C. The first speaker's wrong answer wins
    against a 2:1 majority.
  - branch: step s0 resampled to E, then round 1 E / E / E, round 2 E / E / E, final E.

  Debate round 2 follows agent 0 here: an order effect that makes round-1 agent 0 decisive.

Caveats:
- Flip rates mix replayed (0.7) and regenerated (0) steps, identically in both arms, so they are not
  comparable with whole-trajectory 0.7 flip rates.
- One resample per point: "undetermined" includes resamples that restated the same answer (31/39 in
  llm_debate D(t)>0 points).

## 2. llm_debate fmt_v1_2 (10 questions, `pair_target_runs [[1,2]]`)
MHT `norm()` applied; same-slot vs normal; pi_version_analysis.py.

| | punct | char |
|---|---|---|
| PI vs normal fmt_v1 -> fmt_v1_2 | 0.64 -> 0.83 | 0.63 -> 0.79 |
| paired diff PI (fmt_v1_2 - fmt_v1) | +0.20 [-0.05, +0.47] | +0.16 [-0.02, +0.32] |
| sham vs normal fmt_v1 -> fmt_v1_2 | 0.63 -> 0.60 | 0.60 -> 0.71 |
| paired diff sham | -0.04 [-0.26, +0.19] | +0.11 [-0.14, +0.36] |
| drop first sentence, fmt_v1_2 PI / sham | 0.81 / 0.50 | 0.74 / 0.74 |
| PI vs sham, same slot (10/10 exact pairs) | 0.90 [0.72, 1.00] | 0.87 [0.70, 1.00] |
| answer change PI / sham | 0.20 / 0.40 | |

Resampling: fmt_v1_2 PI needed 20 tries for 10 kept steps (rejection 0.50); 2/10 kept steps did not
reach a format match. Sham: 10/10 first-try matches.

Only 2 of 10 PI references (1 of 10 sham) walk through the options, so `match_structure` rarely bites.
It did not make sham less detectable, and PI got more detectable (CIs touch 0, the same direction as
fmt_v1_1). **Not promoted**; llm_debate stays on fmt_v1. Note: the fmt_v1 rows come from `_pi5`/`_sham5`,
whose slots differ from the paired fmt_v1_2 slots.

## 3. mdagents match_opener (50 questions sham, `pair_target_runs [[1,2]]`)
| | punct | char |
|---|---|---|
| MHT lexical_norm gate, sham vs normal (normalised): fmt_v1 (`_sham5`) | 0.55 [0.48, 0.61] | 0.65 [0.61, 0.71] |
| same, fmt_v1 + match_opener | **0.59 [0.53, 0.65]** | **0.58 [0.54, 0.63]** |
| paired diff opener - fmt_v1 (pi_version_analysis) | +0.05 [-0.08, +0.17] | -0.07 [-0.16, +0.01] |
| drop first sentence, opener | 0.50 | 0.51 |

- Gate (CI covers 0.5 or <= RC upper 0.62): **passes on both features** (fmt_v1 failed char at 0.65).
- `format_matched = false`: 7/50 (14%), flagged in the labels.
- Tries: 1 try 39, 2 tries 1, 4 (the cap) 10.
- No reference reply opens with a role introduction (0/50), so the filter works by rejecting sham
  replies that do.
- Paired target landed in the same slot as the PI run in 20/20 questions that have a PI run (`_pi5`, first
  20 questions; the other 30 have no PI yet).

## Cost
- Estimate $0.46, actual $0.557 (+21%). The branching pilot was on estimate ($0.295 vs $0.31).
- The two validations cost more than the 1-question trials suggested: fmt_v1_2 $0.0050 vs $0.0028 per
  run, opener $0.0028 vs $0.0017 per run. The trial questions needed no retries, while the full runs hit
  the resampling cap (4 tries) on 10-50% of injected steps. The final figures equal MHT's original
  numbers ($0.09 / $0.14).

## Addendum after MHT round 64
- |D(t)|: llm_debate 0 (19 points, aggregator), 1 (19, round-2 agent -> aggregator), 4 (20, round-1
  agent -> three round-2 agents + aggregator); mdagents 0 (20), 1 (40). All 2,200 source entries of these
  40 runs are recorded at run time (none inferred).
- Missing-edge check: all 29 control-arm misses are on D(t) steps; 0 outside D(t).
- Main analysis without the last step (MHT): llm_debate 5/39 (13%), mdagents 7/40 (18%); the last-step
  points (0/39) serve as the single-step sampling-flip baseline.
- Temperature-0 nondeterminism: 0/28 control re-runs disagree (95% upper bound ~10%, rule of three).
- Files: `dt_sizes.txt`.

## Erratum (2026-11-03)
- The AUROC bootstrap in `scripts/branch_pilot.py` turned the resampled questions into a set and lost
  their multiplicity (found by GPT, issue #1 comment 6599933976). Fixed to a with-replacement question
  cluster bootstrap over the same out-of-fold scores (no refitting variance). Point estimates unchanged:
  llm_debate 0.467 [0.394, 0.542] (was [0.408, 0.519]); mdagents 0.496 [0.430, 0.563] (was [0.447, 0.548]).
- Control re-runs were selective (all flips + random undetermined points). Report them stratified:
  flips 0/12, undetermined 0/16, not as an unconditional 0/28 nondeterminism rate.
