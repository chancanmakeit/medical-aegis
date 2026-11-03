# Plan A results (180 points with both arms; upstream cost $1.528)

identity: {"records": 426, "unique_run_ids": 426, "pairs": 180, "complete_rep0_pairs": 180, "extra_control_reps": 66, "rep_reasons": {"flipped_at_rep0": 53, "random_undetermined": 13}}; problems 0 []

## Primary: main points (wrong letter, run ends wrong), flip by speaker position
| position | peers right 0 | peers right >= 1 | standardized [95% CI, question bootstrap] |
|---|---|---|---|
| 0 | 3/15 = 0.20 | 8/15 = 0.53 | 0.37 [0.20, 0.53] |
| 1 | 4/15 = 0.27 | 7/15 = 0.47 | 0.37 [0.20, 0.55] |
| 2 | 3/15 = 0.20 | 4/15 = 0.27 | 0.23 [0.10, 0.39] |

- pos 2 - pos 0: -0.13 [-0.35, +0.08]
- linear trend per position: -0.067 [-0.175, +0.040]
- prediction pos 2 > 1 > 0: observed order [0, 1, 2]; pos 2 highest: False
- peer support (>= 1 minus 0), pooled over positions: +0.20 [+0.02, +0.38] (19/45 = 0.42 vs 10/45 = 0.22)
- flips wrong -> right: 11; wrong -> other wrong: 18
- step-t letter changed by the resample: 51/90; flips among them 24, among unchanged 5

## Control candidates (right letter at t)
- run ends wrong (right letter in a wrong run): flips 12/45 = 0.27; to wrong 6, to right 4; by position 0: 3/15 = 0.20, 1: 5/15 = 0.33, 2: 4/15 = 0.27; by peers 0 / >= 1: 9/21 = 0.43 / 3/24 = 0.12
- run ends right (right -> wrong direction): flips 12/45 = 0.27; to wrong 12, to right 0; by position 0: 4/15 = 0.27, 1: 4/15 = 0.27, 2: 4/15 = 0.27; by peers 0 / >= 1: 12/15 = 0.80 / 0/30 = 0.00

## Determinism
- control rep 0 final != recorded final: 20/180
- control re-runs (flipped_at_rep0): disagree 13/53
- control re-runs (random_undetermined): disagree 0/13
- control-vs-control disagreement reweighted to all 180 points (post hoc noise baseline): 0.072 (flipped share 0.25, undetermined share 0.00 of 13, upper bound for the latter ~0.23)

## Post hoc: flips confirmed by the second control (control rep 1 == control rep 0)
- main: pos 0: flips 11, confirmed 4, 2nd control = branch 5 (of 30); pos 1: flips 11, confirmed 11, 2nd control = branch 0 (of 30); pos 2: flips 7, confirmed 5, 2nd control = branch 2 (of 30)
  - peers right 0: flips 10/45, confirmed 10
  - peers right >= 1: flips 19/45, confirmed 10
- ctl1: pos 0: flips 3, confirmed 2, 2nd control = branch 1 (of 15); pos 1: flips 5, confirmed 4, 2nd control = branch 0 (of 15); pos 2: flips 4, confirmed 3, 2nd control = branch 1 (of 15)
  - peers right 0: flips 9/21, confirmed 6
  - peers right >= 1: flips 3/24, confirmed 3
- ctl2: pos 0: flips 4, confirmed 4, 2nd control = branch 0 (of 15); pos 1: flips 4, confirmed 4, 2nd control = branch 0 (of 15); pos 2: flips 4, confirmed 3, 2nd control = branch 1 (of 15)
  - peers right 0: flips 12/15, confirmed 11
  - peers right >= 1: flips 0/30, confirmed 0
