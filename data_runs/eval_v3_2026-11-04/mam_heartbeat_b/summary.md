identity {"records": 2060, "unique_run_ids": 2060, "pairs": 377, "complete_rep0_pairs": 377, "extra_control_reps": 653, "rep_reasons": {"stage2_disagreement": 552, "stage1": 754}}; problems 0 []

## mam: 25 parents, 377 points; {'undetermined': 368, 'positive': 9}; positives per parent 0.36; parents with >= 1 positive 6
- noise floor (stage 1, all points): control rep0 != rep1 33/377 = 0.088; branch rep0 != rep1 44/377
- positives: answer_changed 8, correctness_changed 3, of which branch majority correct (wrong -> right) 3
- reference rule 'control': E0 (expected positives if t had no effect) 1.2, FDR ~ 0.13; positives with the pooled reference 8; positives with perm_p < 0.05 8; positives at empty declared D(t) 0, of which no step after t regenerated (final-call only) 0
  - diagnosis: positive 1/25, stage-2 1
  - discussion r1: positive 5/80, stage-2 20
  - discussion r2: positive 1/2, stage-2 1
  - quality_check r1: positive 0/70, stage-2 5
  - quality_check r2: positive 0/2, stage-2 0
  - review: positive 0/25, stage-2 0
  - role_generation: positive 0/25, stage-2 17
  - summary r1: positive 0/25, stage-2 3
  - summary r2: positive 0/1, stage-2 0
  - type_classification: positive 0/25, stage-2 18
  - vote r1: positive 2/70, stage-2 4
  - vote r2: positive 0/2, stage-2 0
  - web_search: positive 0/25, stage-2 0

