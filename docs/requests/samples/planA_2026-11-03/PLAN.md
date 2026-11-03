# Plan A: llm_debate round-1 branching, stratified by speaker position x peer support (pre-registered)

Status: candidates fixed (`llm_debate_candidates.jsonl`, seed 0) before the run; **run 2026-11-03, results in `REPORT.md`** (this file is unchanged otherwise).
Design: issue #1 rounds 46-48 (MHT r64 cont. concerns (a) position, (b) visible selection condition).

## Candidates (180 points, all K=3 recorded runs, MAA overlap excluded, letter-less steps excluded)
Per speaker position (0, 1, 2), split by peers_right (round-1 peers stating the gold letter: 0 / >= 1):

| type | run end | letter at t | per position (0 / >= 1) | total |
|---|---|---|---|---|
| main | wrong | wrong | 15 / 15 | 90 |
| control candidate 1 | wrong | right | 7 / 8 | 45 |
| control candidate 2 | right | right | 5 / 10 | 45 |

Peer support is balanced across positions by construction, so position is not confounded with it.
9 batches (one run_index each, distinct questions per batch). Protocol unchanged from the pilot
(`branch-resample-t-at-0.7_descendants-at-0_replay-rest_v1`); every output record carries `branch` identity.

## Prediction (recency, `position_check_2026-10-27`)
In round 2 an agent sees its own answer, then the other two in source order; the last one pulls ~56%,
the first ~20%. Agent 2 is the last "other" for agents 0 and 1; agent 1 is last for agent 2 and first for
agent 0; agent 0 is first for both. **Prediction: flip rate of main points pos 2 > pos 1 > pos 0**,
within each peers_right stratum. Falsified if pos 2 is not the highest in the pooled (peer-stratified)
estimate.

## Analysis (fixed before the run)
- Primary: main-point flip rate by position, Mantel-Haenszel pooled over peers_right; trend test
  (pos 0 < 1 < 2) with question-clustered bootstrap CIs. Power is limited: with 30 points per position,
  simulated one-sided power is about 0.6 both for pos 2 vs pos 0 at 30% vs 10% and for a 10 / 20 / 30%
  trend. A null result is reported as underpowered, not as "no position effect"; if the direction holds
  but the CI covers 0, scaling the main stratum is the next decision.
- Secondary: flip rate by peers_right (0 vs >= 1) within position; control candidates: right -> wrong
  flips (type 2) and right -> other flips (type 1); `answer_changed` and `correctness_changed` reported
  separately.
- Control repetition 1: all flips + 10% random undetermined points; reported stratified by reason.
- Trivial baselines for any later attribution model: round x position, peer support.

## Cost estimate
From the recorded token usage of exactly these steps (the pilot's estimate was within 5% of actual):
branch arms $0.69 + control arms $0.61 = **$1.30**; control repetition ~$0.14 (15% flips + 10% of the
rest). **Total about $1.45**, upper bound about $1.6. (Higher than the $1.2 quoted on 10-27: runs 1-2
questions are longer than the pilot's run-0 questions, $0.0072 vs $0.0064 per point.)
