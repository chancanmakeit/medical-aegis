identity {"records": 2312, "unique_run_ids": 2312, "pairs": 424, "complete_rep0_pairs": 424, "extra_control_reps": 732, "rep_reasons": {"stage2_disagreement": 616, "stage1": 848}}; problems 0 []

## triage_agent: 53 parents, 424 points; {'undetermined': 414, 'positive': 10}; positives per parent 0.19; parents with >= 1 positive 10
- noise floor (stage 1, all points): control rep0 != rep1 27/424 = 0.064; branch rep0 != rep1 52/424
- positives: answer_changed 10, correctness_changed 8, of which branch majority correct (wrong -> right) 8
- reference rule 'control': E0 (expected positives if t had no effect) 1.5, FDR ~ 0.15; positives with the pooled reference 7; positives with perm_p < 0.05 7; positives at empty declared D(t) 0, of which no step after t regenerated (final-call only) 0
  - classify: positive 6/159, stage-2 54
  - consensus: positive 0/53, stage-2 0
  - discuss r1: positive 3/159, stage-2 12
  - summarize: positive 1/53, stage-2 11

