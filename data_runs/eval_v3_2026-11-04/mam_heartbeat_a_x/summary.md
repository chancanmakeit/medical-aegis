identity {"records": 3060, "unique_run_ids": 3060, "pairs": 625, "complete_rep0_pairs": 625, "extra_control_reps": 905, "rep_reasons": {"stage2_disagreement": 560, "stage1": 1250}}; problems 0 []

## mam: 40 parents, 625 points; {'undetermined': 617, 'positive': 8}; positives per parent 0.20; parents with >= 1 positive 7
- noise floor (stage 1, all points): control rep0 != rep1 21/625 = 0.034; branch rep0 != rep1 49/625
- positives: answer_changed 8, correctness_changed 2, of which branch majority correct (wrong -> right) 2
- reference rule 'pooled': E0 (expected positives if t had no effect) 0.7, FDR ~ 0.09; positives with the pooled reference 8; positives with perm_p < 0.05 8; positives at empty declared D(t) 1, of which no step after t regenerated (final-call only) 0
  - diagnosis: positive 1/40, stage-2 2
  - discussion r1: positive 5/155, stage-2 23
  - quality_check r1: positive 0/115, stage-2 6
  - review: positive 0/40, stage-2 0
  - role_generation: positive 1/40, stage-2 15
  - summary r1: positive 1/40, stage-2 3
  - type_classification: positive 0/40, stage-2 18
  - vote r1: positive 0/115, stage-2 3
  - web_search: positive 0/40, stage-2 0

