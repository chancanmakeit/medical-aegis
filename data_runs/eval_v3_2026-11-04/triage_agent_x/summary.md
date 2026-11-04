identity {"records": 7040, "unique_run_ids": 7040, "pairs": 1336, "complete_rep0_pairs": 1336, "extra_control_reps": 2184, "rep_reasons": {"stage1": 2672, "stage2_disagreement": 1696}}; problems 0 []

## triage_agent: 167 parents, 1336 points; {'undetermined': 1314, 'positive': 22}; positives per parent 0.13; parents with >= 1 positive 21
- noise floor (stage 1, all points): control rep0 != rep1 81/1336 = 0.061; branch rep0 != rep1 120/1336
- positives: answer_changed 22, correctness_changed 18, of which branch majority correct (wrong -> right) 16
- reference rule 'pooled': E0 (expected positives if t had no effect) 2.5, FDR ~ 0.11; positives with the pooled reference 22; positives with perm_p < 0.05 22; positives at empty declared D(t) 0, of which no step after t regenerated (final-call only) 0
  - classify: positive 16/501, stage-2 160
  - consensus: positive 0/167, stage-2 1
  - discuss r1: positive 4/501, stage-2 25
  - summarize: positive 2/167, stage-2 26

