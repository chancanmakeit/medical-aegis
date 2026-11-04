identity {"records": 11944, "unique_run_ids": 11944, "pairs": 2100, "complete_rep0_pairs": 2100, "extra_control_reps": 3872, "rep_reasons": {"stage1": 4200, "stage2_disagreement": 3544}}; problems 0 []

## llm_debate: 300 parents, 2100 points; {'undetermined': 2039, 'positive': 61}; positives per parent 0.20; parents with >= 1 positive 53
- noise floor (stage 1, all points): control rep0 != rep1 164/2100 = 0.078; branch rep0 != rep1 267/2100
- positives: answer_changed 61, correctness_changed 13, of which branch majority correct (wrong -> right) 12
- reference rule 'control': E0 (expected positives if t had no effect) 6.9, FDR ~ 0.11; positives with the pooled reference 42; positives with perm_p < 0.05 42; positives at empty declared D(t) 20, of which no step after t regenerated (final-call only) 20
  - aggregation: positive 20/300, stage-2 36
  - discussion r1: positive 32/900, stage-2 260
  - discussion r2: positive 9/900, stage-2 147

