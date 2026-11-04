# Protocol v3 branching eval set — gemini-2.5-flash-lite (2026-11-03/04)

Status: **complete except DyLAN stage 2** (paused at the approved budget; waits for the user). Discussion: `docs/discussion_log_v11.md` rounds 8–9.

## Protocol
- Parent runs: natural runs with gemini-2.5-flash-lite (xiaojingai), temperature 0.7, that **end wrong**; frozen in `data_runs/eval_v3_2026-11-04/parents/`. Every LLM step t of a parent is a point.
- Branch arm: step t resampled at 0.7, its descendants D(t) regenerated at 0, every other step replayed from the parent. Control arm: same, but step t replayed (D(t) still regenerated) — measures how much the regenerated tail alone moves the answer.
- Stage 1: 2 branch + 2 control. If the 4 finals are not all equal → stage 2: 6 + 6. Fisher exact, one-sided, on "final == the controls' modal answer", p < 0.05 → `positive` (claim `outcome_sensitive_under_protocol`); otherwise `undetermined`. **Never `negative`.**
- Points with empty D(t) (the final / aggregator call) only measure resampling of the last call; reported separately.
- Replay keys: message text + attached image/audio sha1 + (MAM) the sample id (`--sample_keys`). Identity: every record carries a `branch` block (`scripts/branch_identity.py`); all jobs 0 identity problems.

## Results
| job | framework | parents | points | noise floor | to stage 2 | positives | of which D(t) empty | positives, D(t) non-empty | correctness changed | wrong → right | undetermined | still needs stage 2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentverse | agentverse | 250 | 2087 | 0.152 | 0.32 | 99 | 5 | 94 | 25 | 18 | 1988 | 0 |
| dylan | dylan | 170 | 566 | 0.254 | 0.00 | 0 | 0 | 0 | 0 | 0 | 280 | 286 |
| llm_debate | llm_debate | 300 | 2100 | 0.078 | 0.21 | 61 | 20 | 41 | 13 | 12 | 2039 | 0 |
| mac_groupchat | mac_groupchat | 40 | 387 | 0.044 | 0.11 | 8 | 0 | 8 | 4 | 4 | 379 | 0 |
| mam_heartbeat_a | mam | 25 | 376 | 0.064 | 0.15 | 3 | 1 | 2 | 2 | 2 | 373 | 0 |
| mam_heartbeat_b | mam | 25 | 377 | 0.088 | 0.18 | 9 | 0 | 9 | 3 | 3 | 368 | 0 |
| mam_sounddr | mam | 25 | 402 | 0.000 | 0.00 | 0 | 0 | 0 | 0 | 0 | 402 | 0 |
| mdagents | mdagents | 425 | 2975 | 0.064 | 0.19 | 97 | 15 | 82 | 36 | 28 | 2878 | 0 |
| medagents_mc | medagents_mc | 40 | 741 | 0.070 | 0.15 | 16 | 1 | 15 | 10 | 7 | 725 | 0 |
| mm_kvasir_vqa_x1 | mdagents | 22 | 154 | 0.052 | 0.11 | 4 | 1 | 3 | 4 | 3 | 150 | 0 |
| mm_medxpertqa_mm | mdagents | 50 | 350 | 0.040 | 0.13 | 13 | 0 | 13 | 3 | 2 | 337 | 0 |
| mm_pathvqa | mdagents | 50 | 350 | 0.014 | 0.05 | 3 | 0 | 3 | 3 | 3 | 347 | 0 |
| mm_slake | mdagents | 21 | 147 | 0.048 | 0.10 | 1 | 0 | 1 | 1 | 1 | 146 | 0 |
| triage_agent | triage_agent | 53 | 424 | 0.064 | 0.18 | 10 | 0 | 10 | 8 | 8 | 414 | 0 |

Total: 11436 points, 324 positives (43 at empty D(t)), 286 points still need stage 2.

Notes
- noise floor = share of points whose two stage-1 control runs disagree (temperature-0 nondeterminism of the endpoint plus regenerated tails). It is the false-trigger rate of stage 2, not of positives: positives need Fisher p < 0.05 on 6+6.
- **DyLAN**: capped at 40 parents for cost (all steps), plus step 0 of all 170 parents (that batch was already running) — hence "170 parents". Noise floor 0.254 (others 0.00–0.15): 286 / 566 points need stage 2; without it DyLAN has no positives.
- **AgentVerse** is noisy (0.152) but stage 2 resolves it: 99 positives, 94 with non-empty D(t).
- **llm_debate**: 61 positives, 20 at the aggregation step; below the target of 100.
- **MAM sounddr**: the answers barely vary (control disagreement 0/402, branch 1/402) → no positives.
- Multimodal (mdagents, the only native image framework): MedXpertQA-MM 13, PathVQA 3, SLAKE 1, Kvasir-VQA-x1 4.
- Positive ≠ "this step caused the error": it says the final answer is sensitive to resampling this step under the protocol. "wrong → right" counts positives where the branch majority is correct.

## Cost
xiaojingai usage (¥0.01 units) 3881.41 at the start → 6899.93 after AgentVerse (≈ **¥30.2**, including the natural runs of triage_agent and MAM). Approved: ≈ ¥25 + ≈ ¥1–3 each for triage_agent and MAM. DyLAN stage 2 would add ≈ ¥2.5.

## Files
- `data_runs/eval_v3_2026-11-04/<job>/`: `labels_v3.jsonl.gz` (typed annotation records), `summary.md` (per step type), `*_candidates.jsonl.gz`, `*_stage2_plan.txt`, `branch_records_compact.jsonl.gz` (every branch record: `branch` block, final answer, correctness, text of the **regenerated** steps; replayed steps = the parent's).
- `data_runs/eval_v3_2026-11-04/parents/`: frozen parent runs.
- Scripts: `scripts/runners/branch_v3.sh`, `scripts/branch_pilot.py`, `scripts/branch_v3_analysis.py`, `scripts/branch_v3_compact.py`, `scripts/branch_v3_report.py`, `scripts/branch_restamp.py`, watchdog `scripts/runners/eval_v3_watchdog.sh`.
- Full uncompacted outputs (~9 GB, with call logs) stay in the session container `/home/claude/eval_v3/` and are not archived.
