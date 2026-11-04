identity {"records": 7132, "unique_run_ids": 7132, "pairs": 1291, "complete_rep0_pairs": 1291, "extra_control_reps": 2275, "rep_reasons": {"stage2_disagreement": 1968, "stage1": 2582}}; problems 0 []

## mam: 86 parents, 1291 points; {'undetermined': 1266, 'positive': 25}; positives per parent 0.29; parents with >= 1 positive 21
- noise floor (stage 1, all points): control rep0 != rep1 96/1291 = 0.074; branch rep0 != rep1 138/1291
- positives: answer_changed 24, correctness_changed 8, of which branch majority correct (wrong -> right) 7
- reference rule 'pooled': E0 (expected positives if t had no effect) 2.9, FDR ~ 0.12; positives with the pooled reference 25; positives with perm_p < 0.05 25; positives at empty declared D(t) 2, of which no step after t regenerated (final-call only) 0
  - diagnosis: positive 4/86, stage-2 8
  - discussion r1: positive 15/305, stage-2 82
  - quality_check r1: positive 1/235, stage-2 12
  - review: positive 0/86, stage-2 0
  - role_generation: positive 2/86, stage-2 48
  - summary r1: positive 1/86, stage-2 16
  - type_classification: positive 2/86, stage-2 58
  - vote r1: positive 0/235, stage-2 22
  - web_search: positive 0/86, stage-2 0

