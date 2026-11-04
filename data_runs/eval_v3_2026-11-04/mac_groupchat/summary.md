identity {"records": 1884, "unique_run_ids": 1884, "pairs": 387, "complete_rep0_pairs": 387, "extra_control_reps": 555, "rep_reasons": {"stage2_disagreement": 336, "stage1": 774}}; problems 0 []

## mac_groupchat: 40 parents, 387 points; {'undetermined': 379, 'positive': 8}; positives per parent 0.20; parents with >= 1 positive 8
- noise floor (stage 1, all points): control rep0 != rep1 17/387 = 0.044; branch rep0 != rep1 21/387
- positives: answer_changed 8, correctness_changed 4, of which branch majority correct (wrong -> right) 4
- reference rule 'control': E0 (expected positives if t had no effect) 0.9, FDR ~ 0.11; positives with the pooled reference 6; positives with perm_p < 0.05 6; positives at empty declared D(t) 0, of which no step after t regenerated (final-call only) 0
  - discussion r1: positive 8/40, stage-2 12
  - discussion r2: positive 0/40, stage-2 1
  - discussion r3: positive 0/33, stage-2 1
  - discussion r4: positive 0/25, stage-2 2
  - discussion r5: positive 0/8, stage-2 0
  - discussion r6: positive 0/4, stage-2 0
  - discussion r7: positive 0/1, stage-2 0
  - select_speaker r1: positive 0/40, stage-2 15
  - select_speaker r2: positive 0/40, stage-2 1
  - select_speaker r3: positive 0/40, stage-2 3
  - select_speaker r4: positive 0/34, stage-2 4
  - select_speaker r5: positive 0/27, stage-2 1
  - select_speaker r6: positive 0/9, stage-2 0
  - select_speaker r7: positive 0/5, stage-2 0
  - supervision r3: positive 0/7, stage-2 1
  - supervision r4: positive 0/9, stage-2 1
  - supervision r5: positive 0/18, stage-2 0
  - supervision r6: positive 0/4, stage-2 0
  - supervision r7: positive 0/3, stage-2 0

