# MAFA Stage-1 LLM pre-annotation of the doctor-annotation batch `ma_v1` (2026-11-15)

This folder holds the **LLM pre-annotation** (MAFA Stage 1) of a 320-trace batch drawn from
`annotation_ready/`. The review packages for the doctors are **not** built here: the MAFA project
builds them from these files (primary/secondary choice, queue rules, offline tool), see
MAFA-human-ai-annotation issue "medical-aegis → MAFA: ma_v1 Stage-1 pre-annotation".

## The batch

- `ma_v1_ids.txt`: 320 MAFA trace ids (`<fw>::<file stem>#<0-based line, 5 digits>#<question id>`),
  resolvable against `annotation_ready/data/{faulty,clean}/` with the MAFA specs added in MAFA 0.7.61.
- 8 groups x (20 wrong + 20 right): agentverse, dylan, llm_debate, mac_groupchat, mdagents
  (text), mdagents_mm (4 multimodal pools), medagents_mc, triage_agent. MAM is excluded (audio).
  All are real runs (gemini-2.5-flash-lite as the agents' model), no injection.
- Selection (`scripts/select_mafa_batch.py`, seed 20261115): wrong runs with a v3
  counterfactual-positive step first, then other v3 branch parents; right runs on the same
  questions first where possible (triage).
- `ma_v1_selection.jsonl` (**organisers only — never show to doctors**): per trace the source
  file and line, run_id, `is_correct`, and the v3 counterfactual-positive steps
  (`v3_positive_steps`, `v3_positive_steps_pooled`; v3 step ids are 0-based, MAFA's are 1-based:
  v3 `s4` = MAFA `s05`). Wrong runs with >= 1 v3 positive: agentverse 20, dylan 0, llm_debate 20,
  mac 8, mdagents 20, mdagents_mm 16, medagents 10, triage 20.

## The arms (`arms/<taxonomy>_<model>/stage1.jsonl`)

| arm | taxonomy (signature) | model | schema mode | scoring |
|---|---|---|---|---|
| `mast_gemini-4-hydrogen` | MAST (T0:321a19c96e, `mafa/seeds/mast_seed_v1.json`) | gemini-4-hydrogen | json_object (json_schema not honoured) | verbalised 0-100 (no logprobs) |
| `mast_gpt-6.1-terra` | MAST | gpt-6.1-terra | json_schema | verbalised 0-100 (no logprobs) |
| `maa_gemini-4-hydrogen` | MedAgentAudit (T0:210546d507, MAFA default seed) | gemini-4-hydrogen | json_object | verbalised |
| `maa_gpt-6.1-terra` | MedAgentAudit | gpt-6.1-terra | json_schema | verbalised |

All four: `scripts/run_stage1.py --annotator-backend chat --images datasets/medical_aegis_images`,
two-pass, prompt=current. One schema mode per arm (MAFA §30). Each file is the merge of the
processes that ran the arm (see `scripts/ma_stage1_summary.py`): one record per trace (320 lines),
an `ok` record preferred over a `failed` one.

**Coverage (status ok): all four arms 320/320** (completed 2026-11-16).

**Endpoints:** gpt-6.1-terra via a6api. gemini-4-hydrogen via a6api for most traces, then via the
S3AI endpoint (ai.furry.vg, same model name) after the a6api quota ran out, and the last 6 traces via
a6api again during an S3AI outage ("No available channel for model gemini-4-hydrogen"). Same
model name, prompt, schema mode and scoring throughout. gemini-4-hydrogen was slow (10-40 min per
trace under load) and its failed calls (502 / 524 / schema violations) were billed, so it cost
several times as much per completed trace as gpt.

**Notable (for MAFA's choice of primary/secondary):**
- gpt-6.1-terra flags correct-answer runs almost as often as wrong ones (MAST 120/160 vs 117/160;
  MedAgentAudit 132/160 vs 118/160).
- gemini-4-hydrogen is more lenient but separates outcomes better (MAST 89/160 vs 64/160;
  MedAgentAudit 104/160 vs 55/160). Under MAST it flags every mdagents run (text and MM),
  correct or not (framework-constant, cf. MAFA §30/§31).
- Agreement: gemini's flagged traces are mostly a subset of gpt's (MAST: both 136, gemini only 17,
  gpt only 101, neither 66).
- Organiser-only: a finding on a v3 counterfactual-positive step in 23-27 of 114 wrong runs with a
  positive, for every arm.

`SUMMARY.md` gives coverage, flag rates by group and outcome, agreement between the two models,
and (organisers only) how often the LLM points at the v3 counterfactual-positive step.

## Scripts

- `scripts/run_ma_stage1.sh`, `scripts/run_ma_stage1_sub.sh`: the launchers (keys from an env file).
- `scripts/select_mafa_batch.py`, `scripts/ma_stage1_summary.py`: from the medical-aegis repo.
