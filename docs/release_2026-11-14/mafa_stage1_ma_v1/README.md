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

**Coverage (status ok):** gpt-6.1-terra MAST 320/320, MedAgentAudit 320/320; gemini-4-hydrogen
MAST 298/320, MedAgentAudit 231/320. The remaining gemini records are `status: failed` (upstream
502s, schema violations "'verdicts' is a required property", and finally exhausted quota on both
endpoints); treat them as gaps, not as "no fault".

**Endpoints:** gpt-6.1-terra via a6api; gemini-4-hydrogen via a6api, and the last ~76 gemini traces
via the S3AI endpoint (ai.furry.vg), which serves the same model name. gemini-4-hydrogen was slow
(~10 min per trace under load) and its 502 / schema failures were billed, so it cost several times
as much per completed trace as gpt.

**Notable (for MAFA's choice of primary/secondary):** both models flag correct-answer runs almost
as often as wrong ones (gpt MAST 75% vs 73%); gemini is more lenient (MAST 51% vs 39%) but flags
every mdagents run, correct or not (framework-constant, cf. MAFA §30/§31). See `SUMMARY.md`.

`SUMMARY.md` gives coverage, flag rates by group and outcome, agreement between the two models,
and (organisers only) how often the LLM points at the v3 counterfactual-positive step.

## Scripts

- `scripts/run_ma_stage1.sh`, `scripts/run_ma_stage1_sub.sh`: the launchers (keys from an env file).
- `scripts/select_mafa_batch.py`, `scripts/ma_stage1_summary.py`: from the medical-aegis repo.
