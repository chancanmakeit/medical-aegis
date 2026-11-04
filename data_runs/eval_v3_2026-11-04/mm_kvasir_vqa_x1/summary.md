identity {"records": 752, "unique_run_ids": 752, "pairs": 154, "complete_rep0_pairs": 154, "extra_control_reps": 222, "rep_reasons": {"stage1": 308, "stage2_disagreement": 136}}; problems 0 []

## mdagents: 22 parents, 154 points; {'undetermined': 150, 'positive': 4}; positives per parent 0.18; parents with >= 1 positive 2
- noise floor (stage 1, all points): control rep0 != rep1 8/154 = 0.052; branch rep0 != rep1 9/154
- positives: answer_changed 4, correctness_changed 4, of which branch majority correct (wrong -> right) 3
- reference rule 'control': E0 (expected positives if t had no effect) 0.4, FDR ~ 0.09; positives with the pooled reference 2; positives with perm_p < 0.05 2; positives at empty declared D(t) 1, of which no step after t regenerated (final-call only) 1
  - aggregation: positive 1/22, stage-2 1
  - expert_answer: positive 3/110, stage-2 11
  - recruitment: positive 0/22, stage-2 5

