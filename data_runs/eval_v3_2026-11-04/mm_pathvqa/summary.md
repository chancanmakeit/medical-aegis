identity {"records": 1528, "unique_run_ids": 1528, "pairs": 350, "complete_rep0_pairs": 350, "extra_control_reps": 414, "rep_reasons": {"stage1": 700, "stage2_disagreement": 128}}; problems 0 []

## mdagents: 50 parents, 350 points; {'undetermined': 347, 'positive': 3}; positives per parent 0.06; parents with >= 1 positive 3
- noise floor (stage 1, all points): control rep0 != rep1 5/350 = 0.014; branch rep0 != rep1 9/350
- positives: answer_changed 3, correctness_changed 3, of which branch majority correct (wrong -> right) 3
- reference rule 'control': E0 (expected positives if t had no effect) 0.3, FDR ~ 0.10; positives with the pooled reference 3; positives with perm_p < 0.05 3; positives at empty declared D(t) 0, of which no step after t regenerated (final-call only) 0
  - aggregation: positive 0/50, stage-2 0
  - expert_answer: positive 2/250, stage-2 7
  - recruitment: positive 1/50, stage-2 9

