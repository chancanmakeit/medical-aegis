identity {"records": 1776, "unique_run_ids": 1776, "pairs": 350, "complete_rep0_pairs": 350, "extra_control_reps": 538, "rep_reasons": {"stage1": 700, "stage2_disagreement": 376}}; problems 0 []

## mdagents: 50 parents, 350 points; {'undetermined': 337, 'positive': 13}; positives per parent 0.26; parents with >= 1 positive 10
- noise floor (stage 1, all points): control rep0 != rep1 14/350 = 0.040; branch rep0 != rep1 27/350
- positives: answer_changed 13, correctness_changed 3, of which branch majority correct (wrong -> right) 2
- reference rule 'control': E0 (expected positives if t had no effect) 1.2, FDR ~ 0.09; positives with the pooled reference 9; positives with perm_p < 0.05 9; positives at empty declared D(t) 0, of which no step after t regenerated (final-call only) 0
  - aggregation: positive 0/50, stage-2 2
  - expert_answer: positive 11/250, stage-2 30
  - recruitment: positive 2/50, stage-2 15

