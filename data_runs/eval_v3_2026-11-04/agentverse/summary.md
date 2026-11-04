identity {"records": 13740, "unique_run_ids": 13740, "pairs": 2087, "complete_rep0_pairs": 2087, "extra_control_reps": 4783, "rep_reasons": {"stage1": 4174, "stage2_disagreement": 5392}}; problems 0 []

## agentverse: 250 parents, 2087 points; {'undetermined': 1988, 'positive': 99}; positives per parent 0.40; parents with >= 1 positive 86
- noise floor (stage 1, all points): control rep0 != rep1 317/2087 = 0.152; branch rep0 != rep1 427/2087
- positives: answer_changed 99, correctness_changed 25, of which branch majority correct (wrong -> right) 18
- reference rule 'control': E0 (expected positives if t had no effect) 15.1, FDR ~ 0.15; positives with the pooled reference 81; positives with perm_p < 0.05 81; positives at empty declared D(t) 5, of which no step after t regenerated (final-call only) 0
  - criticism r1: positive 6/556, stage-2 59
  - criticism r2: positive 4/302, stage-2 23
  - evaluation r1: positive 23/250, stage-2 78
  - evaluation r2: positive 0/121, stage-2 0
  - revise r1: positive 3/56, stage-2 41
  - revise r2: positive 2/60, stage-2 7
  - role_assignment r1: positive 3/250, stage-2 200
  - role_assignment r2: positive 1/121, stage-2 54
  - solve r1: positive 47/250, stage-2 178
  - solve r2: positive 10/121, stage-2 34

