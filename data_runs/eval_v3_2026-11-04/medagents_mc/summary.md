identity {"records": 3876, "unique_run_ids": 3876, "pairs": 741, "complete_rep0_pairs": 741, "extra_control_reps": 1197, "rep_reasons": {"stage2_disagreement": 912, "stage1": 1482}}; problems 0 []

## medagents_mc: 40 parents, 741 points; {'undetermined': 725, 'positive': 16}; positives per parent 0.40; parents with >= 1 positive 10
- noise floor (stage 1, all points): control rep0 != rep1 52/741 = 0.070; branch rep0 != rep1 61/741
- positives: answer_changed 16, correctness_changed 10, of which branch majority correct (wrong -> right) 7
  - consensus_vote r1: positive 1/280, stage-2 1
  - consensus_vote r2: positive 0/14, stage-2 3
  - decision: positive 0/40, stage-2 1
  - expert_gathering: positive 3/80, stage-2 29
  - option_analysis: positive 6/80, stage-2 12
  - question_analysis: positive 6/200, stage-2 61
  - revision r1: positive 0/2, stage-2 1
  - revision r2: positive 0/1, stage-2 0
  - revision_advice r1: positive 0/3, stage-2 1
  - revision_advice r2: positive 0/1, stage-2 1
  - synthesis: positive 0/40, stage-2 4

