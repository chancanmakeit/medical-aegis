identity {"records": 16316, "unique_run_ids": 16316, "pairs": 2975, "complete_rep0_pairs": 2975, "extra_control_reps": 5183, "rep_reasons": {"stage1": 5950, "stage2_disagreement": 4416}}; problems 0 []

## mdagents: 425 parents, 2975 points; {'undetermined': 2878, 'positive': 97}; positives per parent 0.23; parents with >= 1 positive 72
- noise floor (stage 1, all points): control rep0 != rep1 189/2975 = 0.064; branch rep0 != rep1 348/2975
- positives: answer_changed 92, correctness_changed 36, of which branch majority correct (wrong -> right) 28
  - aggregation: positive 15/425, stage-2 37
  - expert_answer: positive 76/2125, stage-2 362
  - recruitment: positive 6/425, stage-2 153

