# Plan A results (run 2026-11-03, approved by the user)

Pre-registration: `PLAN.md` (same folder). Analysis: `scripts/branch_planA_analysis.py`, full output
`analysis.md`. Raw outputs with embedded `branch` identity: `data_runs/branch_planA_2026-11-03/` (25 files,
426 records: 180 branch + 180 control rep 0 + 66 control rep 1); call logs without texts: `branch_calls/`.
Exporter check: 300 normal + 426 branch runs, 0 problems, 426 unique run_ids.

**Spend: $1.528** (branch + control rep 0 $1.299, estimate $1.30; control rep 1 $0.229, estimate ~$0.14
because flips were 29%, not 15%) plus ~$0.0003 for the determinism probe below. Approved: ~$1.45, upper
bound ~$1.6.

## 1. Pre-registered primary test: the recency prediction is not supported
Main points (wrong letter at t, run ends wrong), flip = branch final != control final:

| position | peers right 0 | peers right >= 1 | standardized [95% CI] | confirmed by 2nd control |
|---|---|---|---|---|
| 0 | 3/15 | 8/15 | 0.37 [0.20, 0.53] | 4 |
| 1 | 4/15 | 7/15 | 0.37 [0.20, 0.55] | 11 |
| 2 | 3/15 | 4/15 | 0.23 [0.10, 0.39] | 5 |

- pos 2 - pos 0: -0.13 [-0.35, +0.08]; linear trend -0.07 per position [-0.18, +0.04].
- Prediction "pos 2 > 1 > 0": **falsified in direction** (pos 2 is the lowest raw rate; with confirmed
  flips pos 1 is highest). The round-2 recency in *adoption* (position_check_2026-10-27) does not show up
  as a position-dependent *causal* effect of resampling a round-1 agent. Power was limited (~0.6), so this is
  "no support", not proof of no effect.
- What does drive flips: the resample changed the letter at t in 51/90 points; 24 of those flipped, against
  5/39 when the letter stayed the same (those 5 are within the noise level of section 2).
- Direction: wrong -> right 11, wrong -> another wrong 18. (The pilot's "almost all wrong -> right" does not
  hold at this scale.)

## 2. New: temperature 0 is not deterministic with this provider
- Control rep 1 vs rep 0: **all 264 regenerated step texts differ** (in the pilot too: 55/55; the pilot only
  compared final letters). Direct probe: the same short prompt 5x at temperature 0 (2x with `seed`) gave 5
  different texts; the endpoint reports `google/gemma-4-31B-it-turbo`.
- Final-answer level: control rep 1 disagrees with control rep 0 on **13/53 flipped points** and 0/13 random
  undetermined points. Reweighted to all 180 points: **~7% control-vs-control disagreement** (the noise
  floor of a single comparison; the undetermined share has an upper bound of ~23% from 0/13).
- Control rep 0 final != recorded final: 20/180 (the pilot: 0/118).
- Consequence: a single branch-vs-control flip is not attributable to step t on its own. The pilot's
  "0/28 control re-runs disagree" was true at the letter level but is not evidence of determinism.

## 3. Peer support, after accounting for noise
- Main points, raw: peers right >= 1 19/45 vs 0 10/45 (+0.20 [+0.02, +0.38]). **Confirmed flips: 10 vs 10.**
  All 9 unconfirmed main flips are in the peers >= 1 stratum: when the group is split, the downstream answer
  is itself unstable. The raw peer-support effect on main points is therefore mostly noise.
- Control candidates 2 (right letter, run ends right): the **lone correct agent is pivotal**. Peers right 0:
  12/15 flip to wrong (11 confirmed); peers right >= 1: 0/30. This is the strongest effect in the data.
- Control candidates 1 (right letter in a run that ends wrong): 12/45 flips (9 confirmed); peers 0: 9/21,
  >= 1: 3/24.

## 4. Implications for branching labels (proposal, needs user / MHT agreement)
1. Protocol v2 (adaptive confirmation): 1 branch + 1 control per point; on every flip, one more control.
   Label `outcome_sensitive_under_protocol` only when both controls agree and differ from the branch
   ("confirmed"); a flip whose 2nd control matches the branch is noise; keep "undetermined" otherwise.
   Cost: +~30% of the control arm. Report the control-vs-control rate per stratum as the noise floor.
2. Do not call D(t) "temperature 0 / deterministic" any more; it is a second stochastic sample. Record the
   provider's behaviour in `protocol_id` notes.
3. Trivial baselines for attribution models: round x position, peer support, and "letter at t changed".
4. The lone-correct-dissenter effect is a candidate finding about debate dynamics (reported separately, not
   mixed into labels).
