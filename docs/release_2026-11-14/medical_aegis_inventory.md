# medical-aegis trajectory data inventory (2026-11-14)

Read-only inventory. Counts computed from the files by `/home/claude/inventory/scripts/{analyze,evalv3,branchdirs}.py`;
full per-file / per-group numbers in `medical_aegis_inventory.json`. "correct / wrong" = `is_correct` True / False.
Repo: `/home/claude/medical-aegis`, HEAD `ac1151e` (origin/main is 1 commit ahead: only `docs/ISSUE5_PROPOSAL.md`).
All 457 files under `data_runs/` and all 392 under `docs/requests/samples/` are git-tracked.
**[UNVERIFIED]** marks statements taken from docs/cards and not checked against data.

## 0. Overview

| set | type | backbone | frameworks | trajectories | labels (who) | where |
|---|---|---|---|---|---|---|
| A eval_v3 parents | real natural runs | gemini-2.5-flash-lite (xiaojingai) | 8 (+mdagents MM) | 5,471 unique runs (2,950 correct / 2,521 wrong) | outcome only (verifier) | git |
| A eval_v3 branches | counterfactual branch + control replays | same | 8 | 79,976 replay runs; 14,688 labelled points on 1,789 wrong parents | 379 positive / 14,023 undetermined / 286 needs_stage2 — program (`branch_v3_analysis`), statistics | git |
| B corpus_v1 | real natural runs | gemini-2.5-flash-lite (duckcoding) | 4 | 4 × 1,449 = 5,796 (2,492 correct / 3,304 wrong) | outcome only | git |
| C gemini_trial natural | real natural runs | gemini-2.5-flash-lite | 6 (+MM) | 381 (incl. 55 superseded unreplayable DyLAN) | outcome only | git |
| C branch pilots | counterfactual branch/control | llama-4-maverick (pilot, planA), gemini (cal, cal2) | 2–4 | 264 + 426 + 529 + 1,921 runs | none stored as labels (analysis in REPORTs) | git |
| D anchor_llama | real normal + injected (fault + sham) | llama-4-maverick (aihubmix) | 4 | 1,200 normal + 1,000 fault-injected + 580 sham = 2,780 | injection-derived (program) | git |
| E samples | pilots (real, incl. injected) + mock | mercury-2.5-preview, llama-4-maverick, mock | 2 real / 14 mock | pilot 440 raw runs; mock 4 per file | injection-derived | git |
| F aegis_data | real clean + injected (simulated) | not recorded [UNVERIFIED] | 4 (mdagents, dylan, clinical_agent, clinical_agent5) | 440 clean + 3,519 simulated | injection-derived | local + HF |
| G public_mas | public non-medical MAS logs | various | 25 | 26,108 converted (raw larger) | dataset-native (human / LLM / injection, see §G) | local + HF |
| I MAA / MAFA | human labels | — | — | MAA 400 human instances; MAFA 0 human labels yet | human (MAA), LLM-only so far (MAFA) | not local |

---

## A. `data_runs/eval_v3_2026-11-04` — protocol-v3 counterfactual branch eval set (git, 187 MB)

Backbone gemini-2.5-flash-lite, T 0.7 (branch arm resamples step t at 0.7, descendants D(t) at 0, rest replayed).
Parents = real natural runs that end wrong. Labels: `annotator {kind: program, version: branch_v3_analysis}` on all
14,688 records; claim `outcome_sensitive_under_protocol`; evidence `counterfactual_replay`; Fisher exact on 2+2 (stage 1)
/ 6+6 (stage 2), p<0.05 → `positive`, else `undetermined`; never `negative`. Not LLM-judged, not human.

### A.1 Parent pools (`parents/*.jsonl.gz`, real natural runs, all `status=success`; `*_x` deduped by (fw, dataset, id, run_index))

| framework | dataset / modality | unique runs | questions | correct | wrong | files |
|---|---|---|---|---|---|---|
| agentverse | MedXpertQA-Text (text MCQ) | 800 | 800 | 330 | 470 | agentverse__normal_eval (7.0 MB) |
| dylan | MedXpertQA-Text | 699 | 699 | 306 | 393 | dylan__normal_eval (15.3 MB) |
| llm_debate | MedXpertQA-Text | 800 | 800 | 386 | 414 | llm_debate__normal_eval (4.3 MB) |
| mac_groupchat | MedXpertQA-Text | 140 | 140 | 67 | 73 | mac_groupchat__normal_eval (1.2 MB) |
| medagents_mc | MedXpertQA-Text | 110 | 110 | 50 | 60 | medagents_mc__normal_eval (5.3 MB) |
| mdagents | MedXpertQA-Text | 800 | 800 | 344 | 456 | mdagents__normal_eval (3.6 MB) |
| mdagents | MedXpertQA-MM (image) | 200 | 200 | 115 | 85 | mdagents__normal_mm_medxpertqa_mm |
| mdagents | PathVQA (image) | 200 | 200 | 146 | 54 | …_mm_pathvqa |
| mdagents | SLAKE (image) | 200 | 200 | 179 | 21 | …_mm_slake |
| mdagents | Kvasir-VQA-x1 (image) | 200 | 200 | 178 | 22 | …_mm_kvasir_vqa_x1 |
| mam | heartbeat_a (audio, PASCAL heart sound A) | 218 (r0 109 + r1 109) | 109 | 106 | 112 | base 109 + `_x` 193 (84 repeat) |
| mam | heartbeat_b (audio) | 180 (r0 90 + r1 90) | 90 | 69 | 111 | base 90 + `_x` 155 (65 repeat) |
| mam | sounddr (audio, cough, yes/no) | 60 | 60 | 30 | 30 | mam__normal_audio_sounddr |
| triage_agent | triage_esi (ESI 1–5 text) | 864 (r0–r3) | 216 | 644 | 220 | base 216 + `_x` 648 (r1–3) |
| **total** | | **5,471** | | **2,950** | **2,521** | 52 MB |

`parents_mastraj/` (30 MB) holds the same runs as mas-traj/1 exports (counts identical per file, verified). MAM's
text and audio steps are all gemini-2.5-flash-lite in these runs (llm_meta model per step, checked on one record).

### A.2 Jobs (labels_v3 + branch_records_compact)

| job | framework | modality | parents labelled | points (labels) | positive | undetermined | needs_stage2 | parents with ≥1 pos | ref rule | branch records (branch/control) | replay final correct / wrong |
|---|---|---|---|---|---|---|---|---|---|---|---|
| agentverse | agentverse | text | 250 | 2,087 | 99 | 1,988 | 0 | 86 | control | 13,740 (6,870/6,870) | 1,324 / 12,416 |
| dylan | dylan | text | 170 | 566 | 0 | 280 | 286 | 0 | — (stage 1 only, PAUSED) | 2,264 | 178 / 2,086 |
| llm_debate | llm_debate | text | 300 | 2,100 | 61 | 2,039 | 0 | 53 | control | 11,944 | 564 / 11,380 |
| mac_groupchat | mac_groupchat | text | 40 | 387 | 8 | 379 | 0 | 8 | control | 1,884 | 69 / 1,815 |
| medagents_mc | medagents_mc | text | 40 | 741 | 16 | 725 | 0 | 10 | control | 3,876 | 313 / 3,563 |
| mdagents | mdagents | text | 425 | 2,975 | 97 | 2,878 | 0 | 72 | control | 16,316 | 1,096 / 15,220 |
| mm_medxpertqa_mm | mdagents | image | 50 | 350 | 13 | 337 | 0 | 10 | control | 1,776 | 73 / 1,703 |
| mm_pathvqa | mdagents | image | 50 | 350 | 3 | 347 | 0 | 3 | control | 1,528 | 48 / 1,480 |
| mm_slake | mdagents | image | 21 | 147 | 1 | 146 | 0 | 1 | control | 708 | 74 / 634 |
| mm_kvasir_vqa_x1 | mdagents | image | 22 | 154 | 4 | 150 | 0 | 2 | control | 752 | 93 / 659 |
| mam_heartbeat_a | mam | audio | 25 | 376 | 3 | 373 | 0 | 3 | control | 1,968 | 183 / 1,785 |
| mam_heartbeat_a_x | mam | audio | 40 | 625 | 8 | 617 | 0 | 7 | pooled | 3,060 | 273 / 2,787 |
| mam_heartbeat_b | mam | audio | 25 | 377 | 9 | 368 | 0 | 6 | control | 2,060 | 306 / 1,754 |
| mam_heartbeat_b_x | mam | audio | 86 | 1,291 | 25 | 1,266 | 0 | 21 | pooled | 7,132 | 947 / 6,185 |
| mam_sounddr | mam | audio | 25 | 402 | 0 | 402 | 0 | 0 | control | 1,616 | 0 / 1,616 |
| triage_agent | triage_agent | text ESI | 53 | 424 | 10 | 414 | 0 | 10 | control | 2,312 | 299 / 2,013 |
| triage_agent_x | triage_agent | text ESI | 167 | 1,336 | 22 | 1,314 | 0 | 21 | pooled | 7,040 | 768 / 6,272 |
| **total** | | | **1,789** | **14,688** | **379** | **14,023** | **286** | | | **79,976** | |

Matches REPORT.md (379 positives / 14,688 points). Per-framework positives: AgentVerse 99, mdagents 97 (+21 MM), llm_debate 61,
MAM 45, triage 32, MedAgents 16, MAC 8, DyLAN 0. REPORT: pooled-reference positives 303, E0 ≈ 49 (FDR ≈ 0.13), 36 final-call-only.
Full uncompacted outputs with call logs: `/home/claude/eval_v3/` (11 GB, local only).

## B. `data_runs/corpus_v1_2026-11-04` — corpus-pool natural runs (git, 135 MB)

gemini-2.5-flash-lite via duckcoding, T 0.7, K=1, `datasets/data/pools_v1/corpus.json` (MedXpertQA-Text, 1,449 Qs disjoint
from eval/anchor/MAA). Real runs, no injection, no step labels. `raw/` and `mastraj/` have identical counts.

| framework | runs | correct | wrong |
|---|---|---|---|
| llm_debate | 1,449 | 653 | 796 |
| mac_groupchat | 1,449 | 610 | 839 |
| mdagents | 1,449 | 620 | 829 |
| medagents_mc | 1,449 | 609 | 840 |
| total | 5,796 | 2,492 | 3,304 |

Local only: `/home/claude/corpus_runs/` (uncompressed copy) and `corpus_runs/failed_quota/` 4 × 160 runs, all
`status=llm_api_failure` (quota exhausted; discarded, not in git).

## C. Gemini trial and branch pilots (git)

**`gemini_trial_2026-11-03/natural/`** (gemini-2.5-flash-lite, xiaojingai, K=1, eval pool; real runs, outcome only):
agentverse 55 (26/29), dylan 55 (27/28), dylan_globalrng_unreplayable 55 (22/33, superseded), llm_debate 31 (13/18),
mac_groupchat 60 (32/28), mdagents 30 (13/17), medagents_mc 55 (23/32), mdagents MM 4 × 10 (kvasir 9/1, medxpertqa_mm 4/6,
pathvqa 8/2, slake 8/2). Note: the 4 MM files carry `dataset = medxpertqa-text` (the tag bug that `fix_dataset_tag.py`
fixed only in the eval_v3 archive). REPORT lists fewer runs (e.g. medagents 10) than the files hold — files were later
extended (cal2 parents) [UNVERIFIED which].

| branch dir | backbone | protocol | frameworks: parents / points | records (branch / control) | final correct / wrong |
|---|---|---|---|---|---|
| branch_pilot_2026-10-26 | llama-4-maverick | v1 (1+1, 2nd control on some) | llm_debate 20/58, mdagents 20/60 | 118 / 146 (264) | 11 / 253 |
| branch_planA_2026-11-03 | llama-4-maverick | Plan A prereg | llm_debate 131 parents / 180 points | 180 / 246 (426) | 162 / 264 |
| gemini_trial/branch_cal | gemini-2.5-flash-lite | v2 calibration | llm_debate 18/126, mdagents 17/119 | 245 / 284 (529) | 12 / 517 |
| gemini_trial/branch_cal2 | gemini-2.5-flash-lite | v2 calibration | agentverse 20/162, dylan 20/219, mac 20/195, medagents 20/381 | 957 / 1,164 (2,121)* | 111 / 2,010 |

*cal2 file count 195; records summed from all `*_out` files. No label files: flips / confirmations exist only in REPORT /
analysis text (protocol statistics, program). Local copies with call logs: `/home/claude/branch_pilot`, `branch_planA`,
`branch_gemini_cal`, `branch_gemini_cal2` (incl. `old_dylan/`, superseded).

## D. `data_runs/anchor_llama_2026-10-21` — anchor runs (git, 43 MB)

llama-4-maverick (aihubmix; response `model` field says `google/gemma-4-31B-it-turbo`, user said not to re-check),
T 0.7, MedXpertQA-Text anchor 100 (`datasets/data/anchor_medxpertqa100.json`, difficulty band), round cap 2.
Injection label = injection log (program); **sham** = placebo note with no error requested (`attack_spec.sham`;
export outcome `sham`, "not a fault by construction"); `sham_style` = assertive-style placebo. All `status=success`.

| file | kind | run_index | runs | fired | not fired | correct | wrong |
|---|---|---|---|---|---|---|---|
| llm_debate__normal | normal | 0–2 | 300 | – | – | 159 | 141 |
| llm_debate__inject | RC (response_corruption) | 0 | 100 | 100 | 0 | 40 | 60 |
| llm_debate__inject | PI old (superseded by pi4) | 1 | 100 | 100 | 0 | 58 | 42 |
| llm_debate__inject_pi4 / pi5 / pi6 | PI length-matched / fmt_v1 / fmt_v1_1 | 1 | 50 / 20 / 10 | all | 0 | 31 / 11 / 3 | 19 / 9 / 7 |
| llm_debate__inject_v12 | PI fmt_v1_2 + sham | 1 / 2 | 10 + 10 | all | 0 | 6 + 6 | 4 + 4 |
| llm_debate__inject_sham / sham5 / sham6 | sham | 2 | 50 / 20 / 10 | all | 0 | 21 / 8 / 4 | 29 / 12 / 6 |
| llm_debate__inject_shamstyle | sham_style (old wording) | 3 | 50 | 50 | 0 | 27 | 23 |
| mac_groupchat__normal | normal | 0–2 | 300 | – | – | 168 | 132 |
| mac_groupchat__inject | RC / PI old | 0 / 1 | 100 / 100 | 96 / 95 | 4 / 5 | 39 / 51 | 61 / 49 |
| mac_groupchat__inject_pi4 / pi5 | PI | 1 | 50 / 20 | 49 / 20 | 1 / 0 | 24 / 9 | 26 / 11 |
| mac_groupchat__inject_sham / sham5 | sham | 2 | 50 / 20 | 46 / 19 | 4 / 1 | 21 / 10 | 29 / 10 |
| mac_groupchat__inject_shamstyle | sham_style | 3 | 50 | 46 | 4 | 28 | 22 |
| mdagents__normal | normal | 0–2 | 300 | – | – | 159 | 141 |
| mdagents__inject | RC only (no old PI in file) | 0 | 100 | 100 | 0 | 38 | 62 |
| mdagents__inject_pi4 / pi5 | PI | 1 | 50 / 20 | all | 0 | 20 / 12 | 30 / 8 |
| mdagents__inject_sham / sham5 / op | sham (op = match_opener) | 2 | 50 / 50 / 50 | all | 0 | 24 / 22 / 23 | 26 / 28 / 27 |
| mdagents__inject_shamstyle | sham_style | 3 | 50 | 50 | 0 | 20 | 30 |
| medagents_mc__normal | normal | 0–2 | 300 | – | – | 139 | 161 |
| medagents_mc__inject | RC / PI old | 0 / 1 | 100 / 100 | all | 0 | 31 / 47 | 69 / 53 |
| medagents_mc__inject_pi4 / pi5 | PI | 1 | 50 / 20 | all | 0 | 24 / 10 | 26 / 10 |
| medagents_mc__inject_sham / sham5 | sham | 2 | 50 / 20 | all | 0 | 21 / 10 | 29 / 10 |
| medagents_mc__inject_shamstyle | sham_style | 3 | 50 | 50 | 0 | 17 | 33 |

Totals: normal 1,200 (625 correct / 575 wrong); fault-injected (RC+PI, all versions) 1,000 (454 / 546; 990 fired, 10 MAC
not fired); sham + sham_style 580 (262 / 318; 571 fired, 9 MAC not fired). Fired ≠ flipped: a fired injection still ends
correct in ~45% of runs. Old PI (`__inject` run 1) and `_shamstyle` (style_v1) are flagged in docs as not for training.
Derived mas-traj exports in `docs/requests/samples/anchor_*` (git) and `/home/claude/anchor_runs/` (1.6 GB, local; also HF).
`labels.maa_overlap`: 2 anchor questions overlap MAA (1499, 1939; 51 runs).

## E. `docs/requests/samples/` (git)

| item | type | backbone | content | correct / wrong |
|---|---|---|---|---|
| pilot_2026-10-20 (`pilot_raw_results.tar.gz`, `pilot_export.jsonl.gz`) | real normal + injected | mercury-2.5-preview, llama-4-maverick | medagents_mc (MedConceptsQA) and triage_agent (ESI) × 2 models: normal 20 Q × K=4 = 80 each; RC 10, PI(direct) 10, PI(simulation) 10 each → 440 raw runs (400 original + 40 mercury simulation re-runs) | e.g. medagents llama normal 61/19; triage llama 66/14. **mercury PI(direct) 20/20 `llm_api_failure`** (403), counted wrong; export keeps 420 (failures skipped). All injections fired. |
| real_probe_2026-10-20 | real normal | mercury, llama | 1 run each of medagents_mc / triage (4 runs) + schema export | 2 / 2 |
| `*_mock_{clean,inject}.jsonl` (28 files), `schema_v1_mock_export.jsonl` | **MOCK LLM** (model `mock`) | — | 14 frameworks: agentverse, clinical_agent, cmas, consensus(+_cmd/_debate/_mad/_reconcile), dylan, llm_debate, mam, mdagents, medagents_mc, triage_agent; 4 runs per file (2 Q × 2), inject = PI+RC, all fired; triage `_inject_multi` 1 run | not meaningful |
| anchor_2026-10-21 / anchor_gate / anchor_fmt_val | mas-traj exports of D | llama | anchor_export_4fw 1,900 runs (no sham); gate7 2,192 (incl. sham/sham_style); fmt_val 558; llmd10 fmt_v1_1 90 | as D |
| screen_2026-10-21 | single-LLM difficulty screen (not MAS) | llama, mercury | 3,994 answers | — |
| aegis_simulated_check_2026-10-22 | analysis txt of F | — | — | — |
| public_spotcheck_2026-10-26 | analysis of G (140 sampled records) | — | — | — |
| replay_hit, round16, position_check, phase_canonical, planA, gemini_trial, eval_v3 | reports / candidates / call logs (no texts) | — | — | — |
| `data_runs/workspace_2026-10-27/*.tar.gz` | tarred local workdirs | llama | anchor_runs_trial (3 runs: v12 PI+sham, mdagents op sham; all wrong), branch_pilot (= C), logs, val16 txt | — |

## F. `/home/claude/aegis_data` — AEGIS(-medical) original data (local only, 430 MB; HF `UUUooUUU/medical-aegis-workspace/aegis_data.tar` 450.5 MB)

Source: `GuihaiChen1998/nature-sub-record` (the user's own earlier AEGIS-medical runs; `_source_file` paths point to a local
"AEGIS-medical-v23" tree). **It is medical.** It is not the arXiv AEGIS public release. Backbone: not recorded in the
records (`model` absent) — [UNVERIFIED]. Labels: injection-derived (`multi_injection_info`, `fm_error_types`), program.
MAFA's full copy also has `faulty/` (1,112 natural wrong runs) not present here.

| file | framework | task | kind | runs | unique Q | correct | wrong | fired |
|---|---|---|---|---|---|---|---|---|
| clean/medxpertqa-mm-100-mdagents | mdagents | MedXpertQA-MM (image MCQ) | clean | 49 | 49 | 49 | 0 | – |
| clean/mmlu_pro_health-100-dylan | dylan | MMLU-Pro health (text MCQ) | clean | 66 | 66 | 66 | 0 | – |
| clean/trial_success-200-500-clinical_agent5 | clinical_agent5 | trial_success (probability) | clean | 192 | 192 | 192 | 0 | – |
| clean/trial_success-200-clinical_agent | clinical_agent | trial_success | clean | 133 | 133 | 133 | 0 | – |
| simulated/…mdagents_error | mdagents | MedXpertQA-MM | PI 149 / RC 102 / PI+RC 752 | 1,003 | 49 | 0 | 1,003 | 1,003 |
| simulated/…dylan_error | dylan | MMLU-Pro health | PI 127 / RC 404 / PI+RC 531 | 1,062 | 66 | 0 | 1,062 | 1,062 |
| simulated/…clinical_agent5_error | clinical_agent5 | trial_success | PI 52 / RC 534 / PI+RC 466 | 1,052 | 192 | 0 | 1,052 | 1,052 |
| simulated/…clinical_agent_error | clinical_agent | trial_success | PI 173 / RC 55 / PI+RC 174 | 402 | 133 | 0 | 402 | 402 |

Clean = only correct runs ("paired_normal"), simulated = only successful (wrong) injections: a selected, outcome-filtered set.
Known artifacts: RC template sentence is the fault; PI has leakage/refusal signatures (`signature_check.txt`, MAFA RUN §53/§70).

## G. `/home/claude/public_mas` — public MAS failure datasets (local only; HF `UUUooUUU/medical-aegis-workspace` raw.tar 869 MB + r57/r61 tars; also `UUUooUUU/mht-session-data`)

Converted by MHT converters (r61, `mas_traj_r61/`, 86 MB, 26,108 runs, all `run_mode normal`; `mas_traj/` = r57 version).
Medical content was deliberately removed (ARIA medical MMLU 2,231; MAST AG2 groupchat medical 12) → **none is medical**.
Labels live in `labels.external`. "Annotator" column quotes each dataset card (read via HF Hub 2026-11-14).

| dataset | raw | converted (r61) | frameworks (converted counts) | domain | outcome | labels / annotator |
|---|---|---|---|---|---|---|
| Who&When (Kevin355) | 184 (AG 126 + HC 58) | 184 | captainagent 126, magentic_one 58 | GAIA, AssistantBench | all failed | mistake agent + step + reason; card: "fine-grained annotations", annotator not stated in card — human per the paper [UNVERIFIED from card]; 44 HC runs also carry AgentRx labels |
| MAST-Data (mcemri) | 1,642 (+19 human_labelled IAA rows, not downloaded) | 1,630 | ag2_mathchat 429, metagpt 430, chatdev 332, magentic_one 195, ag2_groupchat 156, openmanus 30, appworld 30, hyperagent 28 | code, math, GAIA, MMLU, SWE | is_correct mostly null | MAST-14 trajectory-level codes, no step; card: "**produced by an LLM judge, not by human labelling**" (19-trace human IAA set separate) |
| TraceElephant | 220 traces (zip) | 220 | magentic_one 91, captainagent 85, swe_agent 44 | GAIA, AssistantBench, SWE-bench | all failed | mistake agent + step; card empty — annotator [UNVERIFIED] |
| ARIA (Edlison) | 24,468 | 22,237 | openmanus 13,501, metagpt 3,809, ag2_student_verifier 2,558, magentic_one 2,369 | GSM-Plus, MMLU (non-core-medical), Olympiad, SWE, GAIA, HumanEval | 3,584 T / 18,653 F | localization + attribution; card: "**model-generated**" (LLM) |
| AFTraj (ZBox008003) | safe 1,162 + unsafe 1,114 (728 injected + 386 diagnosed) | 1,548 (1,162 safe + 386 natural) | agents_handoff 821, smolagents 528, aftraj_expert_team 137, single_tool_agent 62 | math, coding, agentic | 1,162 T / 386 F | decisive-error step + agent; injected ones skipped; kept 386 are from "multi-judge propose-verify pipeline" (LLM) |
| mascope-bench | LG-Ctrl 408 + Inject-Mix 961 | 260 (clean only) | debate 94, autogen 55, crewai 31, langgraph ×4 80 | planning, RAG, tool use | null | topology + MAST labels; LG-Ctrl/Inject-Mix "anomaly-injection derived"; converted subset is the uninjected one |
| AgentRx (microsoft; private mirror UUUooUUU/AgentRx) | tau 29 + magentic 58 traj (44 labelled) | 29 (tau) | tau_bench_agent 29 | retail tool use | all failed | step-level failure categories + root cause; card does not state annotator [UNVERIFIED] |

## H. HF datasets of user UUUooUUU (listing via HF Hub; nothing downloaded)

| repo | vis. | what (docs / listing) |
|---|---|---|
| medical-aegis-workspace | private | 2026-10-27 snapshot: anchor_runs (raw + derived exports), anchor_runs_trial, branch_pilot, val16, run16_logs, mht_ref, public_mas raw.tar (869 MB) + mas_traj_r57/r61, aegis_data.tar (450.5 MB). Does **not** contain eval_v3 / corpus / gemini (those are in git). |
| mht-session-data | private | MHT copy of the 7 public conversions + raw (1.5 GB) |
| mht-midtrain-pilot, mhb-artifacts | private | MHT training artifacts (TAPT pilot corpus etc.) |
| clinical-agents | public | `trial_success-200.json`, `trial_success-full.json` (task inputs, not trajectories) |
| full-clinical-agent | public | one 7z, 409 MB [content UNVERIFIED] |
| Heartbeat, Sound-Dr | public | raw audio inputs for MAM (heartbeat A/B zips; Sound-Dr cough/breath) |
| ConSensus, REFUGE2, MIMIC-III/IV, DAICWOZ | mixed | raw task inputs |
| AgentRx | private | byte-identical mirror of gated microsoft/AgentRx |
| medqa_5options, mmlu_no_train_5options, code4upload, counterfactual-context-attribution | | unrelated / older |

## I. Human labels

- **MAA (MedAgentAudit human evaluation)**: 400 instances (step × code, present?) with 3 human votes each; majority yes 158 /
  no 242; 10 codes × 40; 285 questions / 391 runs; MAS medagent 107, colacare 92, healthcareagent 71, mac 67, reconcile 49,
  mdagents 14; defect layer only (no responsibility label). Source: MedAgentAudit release (`human_eval/…` in
  nature-sub-record), built by MHT `data_tools/maa_human_eval.py` → `maa_human400.jsonl` on MHT's Linux #2 box. Numbers from
  MHT `results/stage0_manifest/README.md` (local clone `/home/claude/medhypertrace` @77efab3) — [UNVERIFIED here; data not
  local]. medical-aegis only holds `docs/requests/maa_exclusion_v1.json` (600 question stems to exclude, from MHT).
- **MAFA (human–AI annotation, repo chancanmakeit/MAFA-human-ai-annotation, local clone @745ae59, 2026-10-23)**: review
  packages `mast_v1.json` / `medagentaudit_v1.json`, 360 traces each (180 wrong / 180 correct; mdagents, clinical_agent,
  clinical_agent5, dylan × 90) drawn from AEGIS clean/faulty (not simulated); dev 120 / test 240. **No human labels exist in
  the clone**: every imported `attribution.jsonl` is `source=llm` (human-like v2 claude-haiku-5-5: 19; closest-human-like
  v1/v2 gemini-4-argon: 19 / 39; human-like v1 claude-fable-5-1: 20 rows). Stage-1 model labels: mimo-v2.6-flash +
  glm-5.3-flash (+ deepseek/gpt arms). Online tool held 1 in-progress real label (MM-51). Experts were on leave from
  2026-10-15; whether labels arrived after 2026-10-23 is not checked (no fetch).
- medical-aegis itself has **no human labels**; all its labels are injection-derived or protocol statistics.

## Local-only working copies (not in git)

| path | size | relation |
|---|---|---|
| /home/claude/eval_v3 | 11 GB | full uncompacted v3 outputs + call logs (A) |
| /home/claude/gemini_frozen, gemini_runs | 729 / 667 MB | uncompressed parents of A (gemini_runs dylan has 772 lines incl. unreplayable) |
| /home/claude/corpus_runs | 1.1 GB | B raw + failed_quota 640 failed runs |
| /home/claude/anchor_runs | 1.6 GB | D raw + derived exports (also on HF) |
| /home/claude/branch_pilot, branch_planA, branch_gemini_cal, branch_gemini_cal2 | 25 MB / 58 MB / 48 MB / 743 MB | C with call logs |
| /home/claude/replay_gem | 38 MB | replay re-executions of gemini natural runs (359 runs, 8 fw; replay-determinism check) |
| /home/claude/val16, run16_logs, posts | 68 MB / 72 KB / 474 MB | round-16 validation exports; posts = scratch exports and mock runs |
| /home/claude/mm_data, data_mam | 1.6 GB / 316 MB | raw images (SLAKE, PathVQA, Kvasir, MedXpertQA-MM) and audio inputs |
| /home/claude/aegis_data, public_mas | 430 MB / 1.0 GB | F, G |
