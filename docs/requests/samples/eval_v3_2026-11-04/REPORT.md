# Protocol v3 branching eval set — gemini-2.5-flash-lite (2026-11-03/04)

Status: **complete except DyLAN stage 2** (paused; MHT recommends not running it). Expansion of triage_agent and MAM done (v11 r11). Discussion: `docs/discussion_log_v11.md` rounds 8–9.

## Protocol
- Parent runs: natural runs with gemini-2.5-flash-lite (xiaojingai), temperature 0.7, that **end wrong**; frozen in `data_runs/eval_v3_2026-11-04/parents/`. Every LLM step t of a parent is a point.
- Branch arm: step t resampled at 0.7, its descendants D(t) regenerated at 0, every other step replayed from the parent. Control arm: same, but step t replayed (D(t) still regenerated) — measures how much the regenerated tail alone moves the answer.
- Stage 1: 2 branch + 2 control. If the 4 finals are not all equal → stage 2: 6 + 6. Fisher exact, one-sided, on "final == the controls' modal answer", p < 0.05 → `positive` (claim `outcome_sensitive_under_protocol`); otherwise `undetermined`. **Never `negative`.**
- Points with empty D(t) (the final / aggregator call) only measure resampling of the last call; reported separately.
- Replay keys: message text + attached image/audio sha1 + (MAM) the sample id (`--sample_keys`). Identity: every record carries a `branch` block (`scripts/branch_identity.py`); all jobs 0 identity problems.

## Results
| job | framework | rule | parents | points | noise floor | to stage 2 | positives | pooled-ref positives | E0 | FDR ≈ | final-call-only | correctness changed | wrong → right | needs stage 2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentverse | agentverse | control | 250 | 2087 | 0.152 | 0.32 | 99 | 81 | 15.1 | 0.15 | 0 | 25 | 18 | 0 |
| dylan | dylan | control | 170 | 566 | 0.254 | 0.00 | 0 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | 286 |
| llm_debate | llm_debate | control | 300 | 2100 | 0.078 | 0.21 | 61 | 42 | 6.9 | 0.11 | 20 | 13 | 12 | 0 |
| mac_groupchat | mac_groupchat | control | 40 | 387 | 0.044 | 0.11 | 8 | 6 | 0.9 | 0.11 | 0 | 4 | 4 | 0 |
| mam_heartbeat_a | mam | control | 25 | 376 | 0.064 | 0.15 | 3 | 3 | 0.9 | 0.29 | 0 | 2 | 2 | 0 |
| mam_heartbeat_a_x | mam | pooled | 40 | 625 | 0.034 | 0.11 | 8 | 8 | 0.7 | 0.09 | 0 | 2 | 2 | 0 |
| mam_heartbeat_b | mam | control | 25 | 377 | 0.088 | 0.18 | 9 | 8 | 1.2 | 0.13 | 0 | 3 | 3 | 0 |
| mam_heartbeat_b_x | mam | pooled | 86 | 1291 | 0.074 | 0.19 | 25 | 25 | 2.9 | 0.12 | 0 | 8 | 7 | 0 |
| mam_sounddr | mam | control | 25 | 402 | 0.000 | 0.00 | 0 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | 0 |
| mdagents | mdagents | control | 425 | 2975 | 0.064 | 0.19 | 97 | 77 | 11.6 | 0.12 | 15 | 36 | 28 | 0 |
| medagents_mc | medagents_mc | control | 40 | 741 | 0.070 | 0.15 | 16 | 9 | 2.7 | 0.17 | 0 | 10 | 7 | 0 |
| mm_kvasir_vqa_x1 | mdagents | control | 22 | 154 | 0.052 | 0.11 | 4 | 2 | 0.4 | 0.09 | 1 | 4 | 3 | 0 |
| mm_medxpertqa_mm | mdagents | control | 50 | 350 | 0.040 | 0.13 | 13 | 9 | 1.2 | 0.09 | 0 | 3 | 2 | 0 |
| mm_pathvqa | mdagents | control | 50 | 350 | 0.014 | 0.05 | 3 | 3 | 0.3 | 0.10 | 0 | 3 | 3 | 0 |
| mm_slake | mdagents | control | 21 | 147 | 0.048 | 0.10 | 1 | 1 | 0.4 | 0.41 | 0 | 1 | 1 | 0 |
| triage_agent | triage_agent | control | 53 | 424 | 0.064 | 0.18 | 10 | 7 | 1.5 | 0.15 | 0 | 8 | 8 | 0 |
| triage_agent_x | triage_agent | pooled | 167 | 1336 | 0.061 | 0.16 | 22 | 22 | 2.5 | 0.11 | 0 | 18 | 16 | 0 |

Total: 14688 points, 379 positives (pooled reference: 303), E0 49.0, 36 final-call-only positives, 286 points still need stage 2.

Columns: `rule` = reference used for the judgment (`control`: modal control answer, first batch; `pooled`: modal answer of all 12 finals, symmetric, used from the expansion on). `pooled-ref positives` re-judges every job with the pooled reference. `E0` = expected positives if t had no effect (permutation null of the full procedure, Monte Carlo 2,000 per stage-2 point); FDR ≈ E0 / positives (MHT #1 round 84 audit; our E0 43.0 vs their 46.8 on the first batch, pooled positives identical: 248). `final-call-only` = declared D(t) empty and no step after t regenerated in any branch run.

**Per framework (all jobs, positives / pooled-reference positives):** AgentVerse 99 / 81, mdagents 97 / 77, llm_debate 61 / 42, **MAM 45 / 44** (heartbeat_a 3+8, heartbeat_b 9+25, sounddr 0), **triage_agent 32 / 29**, mdagents multimodal 21 / 15, MedAgents 16 / 9, MAC 8 / 6, DyLAN stage 1 only.

Notes
- noise floor = share of points whose two stage-1 control runs disagree. It is the trigger rate of stage 2; positives need p < 0.05 on 6+6.
- **Trivial baselines (MHT audit):** except mdagents, positives are longer and earlier than other points of the same trajectory (step-length AUROC 0.76–0.81 within trajectory). The labelling does not use length, but labels correlate with it: report length / position baselines next to any attribution result; mdagents is the cleanest subset.
- **Declared vs real D(t):** AgentVerse criticism steps have `sources`-empty D(t) but their branch runs regenerate later steps (hidden dependency); `context.downstream_regenerated` records it. Parent exports carry `provenance.sources_complete` (false for dylan, agentverse, triage_agent, mdagents; see `sources_known_gaps`).
- **DyLAN**: capped at 40 parents (all steps) plus step 0 of all 170 parents; noise floor 0.254; 286 / 566 points need stage 2. MHT recommends no stage 2 (low power at this noise; incomplete read sets): DyLAN serves as an unlabelled held-out framework.
- **llm_debate**: 61 positives, 20 at the aggregation step (final-call-only).
- **MAM sounddr**: the answers barely vary (control disagreement 0/402) → no positives; not expanded.
- **Expansion (v11 r11, user-approved ≈ ¥5):** triage_agent run_index 1–3 (648 natural runs, 167 wrong-ending parents); MAM heartbeat_a / heartbeat_b: run-0 parents unused by the first batch plus run_index 1 (`scripts/build_expansion_parents.py`). Different run_index of the same question are correlated: group by question when evaluating.
- Positive ≠ "this step caused the error": the final answer is sensitive to resampling this step under the protocol. "wrong → right" counts positives where the branch majority is correct.

## Cost
- First batch: xiaojingai usage 3881.41 → 6899.93 (≈ ¥30.2, incl. natural runs of triage_agent and MAM).
- Expansion: ≈ ¥5.0 by token count (v3 ¥4.5 + natural runs ¥0.5); the usage counter rose ≈ ¥11.2 in the same 3.7 h, but it also rises ≈ ¥1.1 / h with none of our processes running (another client on the same key), so the counter overstates our spend.
- DyLAN stage 2 would add ≈ ¥2.5.

## Files
- `data_runs/eval_v3_2026-11-04/<job>/`: `labels_v3.jsonl.gz` (typed annotation records), `summary.md` (per step type), `*_candidates.jsonl.gz`, `*_stage2_plan.txt`, `branch_records_compact.jsonl.gz` (every branch record: `branch` block, final answer, correctness, text of the **regenerated** steps; replayed steps = the parent's).
- `data_runs/eval_v3_2026-11-04/parents/`: frozen parent runs (`*_x` = expansion parents; they repeat the unused run-0 records of the base file).
- `data_runs/eval_v3_2026-11-04/parents_mastraj/`: the same parents exported as mas-traj/1 normal runs (sources with `collection`, `provenance.sources_complete`); every label's `target.run_id` is found there.
- Scripts: `scripts/runners/branch_v3.sh`, `scripts/branch_pilot.py`, `scripts/branch_v3_analysis.py`, `scripts/branch_v3_compact.py`, `scripts/branch_v3_report.py`, `scripts/branch_restamp.py`, `scripts/fix_dataset_tag.py`, `scripts/build_expansion_parents.py`, watchdog `scripts/runners/eval_v3_watchdog.sh`.
- Full uncompacted outputs (~9 GB, with call logs) stay in the session container `/home/claude/eval_v3/` and are not archived.
