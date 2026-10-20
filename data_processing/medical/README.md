# Medical Multi-Agent Trajectory Generation (AEGIS extension)

This directory adds support for generating **medical** multi-agent trajectories with
AEGIS: both **normal** trajectories (task solved correctly, no injected error) and
**error** trajectories (an injected fault changes the system's final answer away from
the ground truth).

It works on three MAS frameworks (AgentVerse, DyLAN, LLM-Debate) and these datasets:

| Dataset            | Type            | HuggingFace source                         |
|--------------------|-----------------|--------------------------------------------|
| MedQA              | MCQ (A–D)       | `GBaker/MedQA-USMLE-4-options`             |
| MedMCQA            | MCQ (A–D)       | `openlifescienceai/medmcqa`               |
| PubMedQA           | yes/no/maybe    | `qiaojin/PubMedQA` (pqa_labeled)          |
| MMLU medical (×6)  | MCQ             | `cais/mmlu` subsets                        |
| MMLU-Pro health    | MCQ             | `TIGER-Lab/MMLU-Pro` (category=health)    |
| MEDEC-MS           | error detection | `mkieffer/MEDEC-MS`                        |
| MedCalc-Bench      | numeric         | `nsk7153/MedCalc-Bench-Verified`          |

The 6 MMLU medical subsets: `clinical_knowledge, medical_genetics, anatomy,
professional_medicine, college_biology, college_medicine`.

## What was added / changed

New files:
- `data_processing/medical/convert_medical_datasets.py` — HF dataset → AEGIS input JSON.
- `data_processing/medical/build_medical_dataset.py` — raw results → unified normal/error
  trajectory sets (+ optional contrastive pairs), in the official `aegis.jsonl` schema.
- `aegis_core/utils/medical_verifier.py` — decides correct-vs-incorrect (the normal/error
  split). Regex/exact match per dataset, with an LLM-judge fallback when undecidable.
- `configs/config_medical.yaml` — MAS config for medical MCQ.
- `experiments/fm_injection/medical/{agentverse,dylan,llm_debate}_medical_{normal,inject}.yaml`.

Modified files:
- `main.py` — added `--no_inject` (clean mode), a `run_mode` branch, and a post-run
  verification step that writes `is_correct`, `run_mode`, and `is_valid_{normal,error}`
  to every record.
- `aegis_core/agent_systems/base_wrapper.py` — added `run_clean(task)`; empty injection
  lists now route to it.
- The six `aegis_core/agent_systems/fm_*_wrapper.py` — route empty injection to `run_clean`.

## Medical agent roles

The three frameworks handle agent roles differently:

- **DyLAN** uses *static, named* roles looked up in a role-description table.
  Medical roles (`Physician`, `Pharmacologist`, `Pathologist`, `Surgeon`,
  `Medical_Researcher`) were added to `methods/dylan/dylan_main.py:_get_role_map()`
  and `methods/dylan/utils_mmlu.py:ROLE_MAP`. The panel is selected in
  `methods/dylan/configs/config_medical.yaml` (default: Physician, Pharmacologist,
  Pathologist, Medical_Researcher). The DyLAN experiment YAMLs set
  `dylan_config_name: "config_medical"` so this config is actually loaded.
  After this, the trajectory's `role`/`agent_name` fields show the real medical
  role names instead of `Assistant`.
  > Important: if you change `roles`, every name must exist in BOTH role tables
  > above, or DyLAN raises a KeyError when building the system prompt. Also keep
  > the DyLAN `*_inject.yaml` target `role:` names in sync with the panel.

- **AgentVerse** assigns roles *dynamically* — its RoleAssigner LLM invents expert
  names per question. `methods/agentverse/configs/config_medical.yaml` sets
  `role_assigner_advice` to steer it toward a medical expert panel, and the
  AgentVerse YAMLs set `agentverse_config_name: "config_medical"`. Injection still
  targets AgentVerse's *structural* roles (`Solver`, `Critic`, `Evaluator`), which
  are independent of the recruited expert names — leave those inject targets as is.

- **LLM-Debate** has *no role concept*: it runs homogeneous debating agents, so the
  trajectory shows `Agent 1`, `Agent 2`, `User`. This is inherent to the framework
  and is not configurable without modifying the framework itself.



### 0. One-time setup
```bash
pip install -r requirements.txt
pip install datasets                       # needed by the converters
cp configs/model_api_config.json.template model_api_configs/model_api_config.json
# edit model_api_configs/model_api_config.json with your keys
# also fill api_key/model_url in the experiment YAMLs you intend to use
```

### 1. Convert a medical dataset to AEGIS input
```bash
python data_processing/medical/convert_medical_datasets.py \
    --dataset medqa --split test --limit 500
# writes ./datasets/data/medqa.json
# other examples:
#   --dataset mmlu_anatomy --split test
#   --dataset medcalc-bench --split test
#   --dataset medec-ms --split validation
```

### 2a. Collect NORMAL trajectories (no injection)
```bash
python main.py \
    --method_name dylan \
    --experiment_config experiments/fm_injection/medical/dylan_medical_normal.yaml \
    --dataset_file ./datasets/data/medqa.json \
    --test_dataset_name medqa \
    --model_name gpt-4o-mini \
    --no_inject
# -> results_inj/medqa/gpt-4o-mini/dylan_fm_clean_none_none.jsonl
#    each record has is_correct + is_valid_normal
```
Set `benchmark_name` in the YAML (or pass `--test_dataset_name`) to the dataset you are
running so the right verifier is used.

### 2b. Collect ERROR trajectories (with injection)
```bash
python main.py \
    --method_name dylan \
    --experiment_config experiments/fm_injection/medical/dylan_medical_inject.yaml \
    --dataset_file ./datasets/data/medqa.json \
    --test_dataset_name medqa \
    --model_name gpt-4o-mini
# -> results_inj/medqa/gpt-4o-mini/dylan_fm_multi_*.jsonl
#    each record has is_correct + is_valid_error
```

### 3. Build the final datasets
```bash
python data_processing/medical/build_medical_dataset.py \
    --normal "results_inj/medqa/gpt-4o-mini/dylan_fm_clean_none_none.jsonl" \
    --inject "results_inj/medqa/gpt-4o-mini/dylan_fm_multi_*.jsonl" \
    --framework dylan --benchmark medqa --model gpt-4o-mini \
    --out_dir datasets/medical_built --make_pairs
# -> medqa_dylan_gpt-4o-mini_normal.jsonl   (is_correct == True)
# -> medqa_dylan_gpt-4o-mini_error.jsonl    (is_correct == False, injected)
# -> medqa_dylan_gpt-4o-mini_pairs.jsonl    (matched normal/error by query)
```

Output records follow the unified schema used by `evaluation/data/aegis.jsonl`:
`{id, metadata, input, output, ground_truth}`.

## Unified trajectory schema across frameworks

The three frameworks originally logged trajectories differently: DyLAN and LLM-Debate
wrote `full_history` with `{role, content, ...}` reconstructed after the run, while
AgentVerse wrote `conversation_history` with richer live-captured fields
(`input_messages`, `response`, `phase`, `timestamp`). That is why the saved jsonl
looked different per framework.

`aegis_core/utils/trajectory_normalizer.py` now rewrites every framework's log into ONE
canonical shape before saving (applied in `main.py`). Each turn becomes:

```
{
  "step":           <int>,        # 1-based global order across the whole trajectory
  "agent_name":     <str>,        # real role name (e.g. Physician, Solver, Agent 1)
  "role_index":     <int|null>,
  "phase":          <str>,        # initialization / reasoning / discussion / evaluation / ...
  "input_messages": <list|null>,  # exact messages sent to the LLM that step
  "content":        <str>,        # the agent's output text
  "response":       <str>         # alias of content
}
```

About `input_messages`: it is the full message list (OpenAI chat format, system+user)
that was actually sent to the model for that turn. It is now captured for **all three
frameworks**: a lightweight recorder in the base wrapper (`_start_llm_capture`) wraps
each `call_llm` and logs the real inputs/outputs, which are matched back onto the
reconstructed history (`_attach_input_messages`). For LLM-Debate, the assistant
(`Agent N`) turns carry the real `input_messages`; the `User` turns are inputs
themselves and keep `input_messages=null`. The original per-framework history is
preserved untouched under `injection_log.raw_history`, so nothing is lost.

`step` is added for all frameworks. The final dataset builder reads this unified schema,
keeps `input_messages` when present (default mode), and drops it under `--strict_schema`
to stay byte-compatible with the official release.

## Windows / encoding note

The upstream repo opened config, dataset, and output files **without specifying an
encoding**, so on a Chinese-locale Windows machine Python defaults to GBK and any
non-ASCII byte raises `UnicodeDecodeError` (this is what made the DyLAN medical run
crash). Fixed by forcing `encoding='utf-8'` in `methods/utils.py:load_config`, in
`main.py` (experiment config, method config, dataset reads), and in the jsonl
readers/writers in `utils/utils.py` and `aegis_core/utils/utils.py` (the writers also
now use `ensure_ascii=False` so medical text and Chinese characters stay readable).
The medical config files were additionally rewritten as pure ASCII. If you add other
frameworks later (chatdev, macnet, evomac, mapcoder), note that some of their internal
file reads still lack an explicit encoding and may need the same treatment on Windows.

## Official data alignment

The official release (`train.jsonl` 7,146 + `val.jsonl` 1,787) is **error-only**: every
record has `ground_truth.is_injection_successful == True` and ≥1 faulty agent — there are
**no normal trajectories** in it. Your normal set is therefore a new contribution, and the
error set maps directly onto the official notion of a successful injection.

The official per-record schema, which this builder reproduces:

```
id
metadata: {framework, benchmark, model, num_agents, num_injected_agents, task_type}
input:    {query, conversation_history[], final_output?}   # final_output omitted for dylan
  conversation_history[]: {step, agent_name, content, phase, is_injected?}
output:   {faulty_agents[]}            # {agent_name, error_type, injection_strategy}
ground_truth: {correct_answer, injected_agents[], is_injection_successful}
  injected_agents[]: {agent_name, error_type, injection_strategy, malicious_action_description}
```

By default the builder adds two convenience fields under `metadata` (`label`,
`is_correct`) so you can tell normal from error sets. Pass **`--strict_schema`** to drop
them and emit records that are key-for-key identical to the official format — use this when
you want to concatenate your medical error trajectories with the official `train.jsonl`:

```bash
python data_processing/medical/build_medical_dataset.py \
    --inject "results_inj/medqa/gpt-4o-mini/dylan_fm_multi_*.jsonl" \
    --framework dylan --benchmark medqa --model gpt-4o-mini \
    --out_dir datasets/medical_built --strict_schema
```

## LLM API failure handling (graceful degradation)

The MAS frameworks call `call_llm`, which is decorated by tenacity with
`stop_after_attempt(N)` (N=5 by default, override via `AEGIS_LLM_RETRIES`
env var). When all retries fail, tenacity calls `handle_retry_error` which
returns `None`. Previously this `None` flowed into framework code (e.g.
AgentVerse's `re.findall(role_pattern, response)`) and raised cryptic errors
like `expected string or bytes-like object` — which looked like an injection
effect but was really just the API being down.

The wrappers now detect `None` LLM responses at the boundary and raise a
clear `LLMAPIFailure` exception. The outer `inference()` try/except catches
it separately from real injection-induced exceptions, sets
`injection_log.execution_error = "llm_api_failure: ..."`, and `main.py`
short-circuits:

- `save_data.status = "llm_api_failure"` (vs the usual `"success"` / `"error"`)
- `save_data.is_correct = False`
- `save_data.verification = { decision_path: "skipped/llm_api_failure", ..., llm_api_failure_detail: "..." }`
- The LLM judge is NOT called (no point — there's no real response to grade)
- The injection describer is NOT called (no LLM tokens wasted on broken trajectories)

The downstream `build_medical_dataset.py` already filters on `status == "success"`,
so `llm_api_failure` records are automatically excluded from both `normal` and
`error` outputs. The `doctor_injection.py` tool surfaces an aggregate count
plus a `*** LLM API was unreachable ***` warning when this happens.

If your API endpoint is flaky and you see many `llm_api_failure` records, set
`AEGIS_LLM_RETRIES=10` (or higher) before running, or pick a more stable
provider.

## Filename convention (Q5)

Output filenames now use a 0-based `_idx<n>` suffix that matches the
`role_index` field in the saved trajectory data verbatim:

```
dylan_fm_multi_physician_idx0-pharmacologist_idx1_FM-2.3-FM-1.1_...
```

means "Physician at role_index 0, Pharmacologist at role_index 1" — exactly
what you'll see in `conversation_history[*].role_index`. The previous
convention (`physician1`, `pharmacologist2`) used `role_index + 1`, which
confusingly looked like a count of duplicate agents.

## Discussion / round controls across frameworks

Every framework has a notion of "discussion rounds", but they call it differently and
mean slightly different things:

| Framework   | Field(s)                                           | Meaning |
|-------------|----------------------------------------------------|---------|
| DyLAN       | `num_rounds`                                       | Number of activation rounds in the collaboration graph. **Must be > 2** (code asserts this — round 1 is reasoning, round 2 is ranking, round 3+ is iteration). |
| LLM-Debate  | `rounds_num`                                       | Number of full debate rounds before the aggregator. |
| AgentVerse  | `max_turn` + `max_criticizing_rounds`              | Outer Solver/Evaluator loop and inner Critic→Solver loop, respectively. |
| MacNet      | (no single round field — graph structure)          | Depth of the DAG determines it; not controllable as a simple integer. |

You can override any of these from the **experiment YAML** without editing the
per-framework method config (`methods/<fw>/configs/...`). Two ways:

```yaml
# (1) Framework-agnostic: one knob, mapped to each framework's "primary" loop bound.
#     dylan       -> num_rounds
#     llm_debate  -> rounds_num
#     agentverse  -> max_turn
max_rounds: 4

# (2) Framework-specific: full control, including AgentVerse's inner loop.
num_rounds: 5             # DyLAN (must be > 2)
rounds_num: 3             # LLM-Debate
max_turn: 4               # AgentVerse outer
max_criticizing_rounds: 2 # AgentVerse inner
```

If both are set, the framework-specific key wins. The medical YAML templates already
include a commented example block. The actual values applied at runtime are recorded
in `injection_log.round_settings` of every saved trajectory, so you can audit them
after the fact.

## Injection mechanism (`injection_method`)

The malicious factory now supports two injection mechanisms, selected per-run via the
experiment YAML key `injection_method`:

- **`direct_prepend` (default, recommended).** Despite the historical name, the
  instruction is actually appended at the **END** of the target prompt (the place the
  LLM reads last, exploiting recency bias) and framed as
  `[UPDATED INSTRUCTION FOR <role> - SUPERSEDES ALL EARLIER INSTRUCTIONS]`. This wins
  over the "be a good expert" instructions that AgentVerse and similar frameworks put
  earlier in the prompt. Does NOT require an extra LLM call, so it cannot silently
  fail. Works reliably on RLHF'd models like gpt-4o-mini.
- **`llm_rewrite` (legacy AEGIS-paper behavior).** Asks `self.llm` to rewrite the
  prompt or response into a malicious version. Faithful to the original paper, but on
  RLHF'd targets the rewriter frequently returns the original text or a watered-down
  rewrite, leading to silent injection failures. If the rewrite looks ineffective (too
  short, identical to original, or LLM unavailable), the code now automatically falls
  back to `direct_prepend` so injection still happens.

## Injection observability fields

Every injected turn in `conversation_history` now carries diagnostic fields so you can
SEE whether injection had an effect (without diffing against the clean run):

- `injection_applied: true` — this turn was an injection target
- `fm_error_type` / `injection_strategy` — what was applied
- `original_input_messages` — the pre-injection prompt (snapshot)
- `injected_input_messages` — the post-injection prompt actually sent to the LLM
  (for `prompt_injection` only; see note below)
- `prompt_modified: true|false` — did `inject_prompt` actually change the text?
- `clean_response_before_corruption` — the original LLM output (response_corruption only)
- `response_corrupted: true|false` — was the response actually changed?
- `injection_error` — populated only if injection raised an exception
- **`injection_process`** — the factory's full audit trail for THIS turn:
  - `kind`: `"prompt_injection"` or `"response_corruption"`
  - `injection_method`: `"direct_prepend"` or `"llm_rewrite"`
  - For `direct_prepend`: `instruction_template` (prompt) / `corruption_template` (response)
  - For `llm_rewrite`: `fm_instruction` (the per-FM-type adversarial guidance),
    `modification_prefix` / `response_modification_prefix` (the exact meta-prompt
    sent to the rewriter LLM), `raw_llm_output` (what the rewriter returned),
    `fallback_used` (only set if the rewrite was ineffective and the code fell back).

**Important note on `response_corruption`:** this strategy does NOT modify the
prompt — it lets the target agent answer normally, then rewrites the answer. So
`input_messages == original_input_messages` is *correct* for response-corruption
turns; the injection evidence lives in `clean_response_before_corruption` (the
pre-corruption LLM output) and `injection_process.corruption_template` (or
`response_modification_prefix`).

The fields are added by the four relevant wrappers (`fm_agentverse_wrapper`,
`fm_dylan_wrapper`, `fm_debate_wrapper`, `fm_macnet_wrapper`) and preserved by the
trajectory normalizer and the final dataset builder. They are stripped under
`--strict_schema` so the byte-identical official-schema output stays clean.

## Doctor (`doctor_injection.py`)

A diagnostic helper that reads raw main.py output and summarizes whether injection
actually had a behavioral effect:

```bash
# Single-file: stats on one inject run
python data_processing/medical/doctor_injection.py \
    --inject results_inj/medqa/gpt-4o-mini/dylan_fm_multi_*.jsonl

# Paired: align clean vs inject by query and report flips
python data_processing/medical/doctor_injection.py \
    --clean  results_inj/medqa/gpt-4o-mini/dylan_fm_clean_none_none.jsonl \
    --inject results_inj/medqa/gpt-4o-mini/dylan_fm_multi_*.jsonl
```

Reports per-record diagnostics, an aggregate (how many records actually had their
prompt modified or response corrupted, how many flipped from correct to incorrect),
and a warning if injection appears to have had no effect (which usually means you
need to switch to `injection_method: direct_prepend`).

## LLM-powered injection descriptions

The static `malicious_action_description` strings produced by the factory (e.g.
"Deviate from main goal via prompt injection") tell you only the *category* of error,
not what concretely changed in a particular sample. An LLM-powered describer
(`aegis_core/utils/injection_describer.py`) now reads the evidence per injected turn
(`original_input_messages`, `injected_input_messages`, `clean_response_before_corruption`,
`content`/`response`) and generates a CONCRETE, sample-specific description of how
the FM error manifested.

Two granularities are produced:

- **Per-turn** (`conversation_history[*].injection_description`) — one description
  per injected turn, written from the evidence of that turn alone.
- **Sample-level** (`record.injection_summary`) — one summary per sample, written
  from the question, ground truth, all injected turns, and the final response.
  Describes how injections combined, whether they propagated, and the overall effect.

In the **final dataset**, `ground_truth.injected_agents[*].malicious_action_description`
is automatically replaced with the per-turn LLM description (matched by
`(agent_name, fm_error_type)`), and `injection_summary` is surfaced at the record top
level. Under `--strict_schema` both are stripped (kept clean for official-schema merging).

Configuration (inject YAMLs):

```yaml
generate_injection_descriptions: true   # master switch
describe_per_turn: true                 # one description per injected turn
describe_sample_summary: true           # one sample-level summary

# Pick the description model. Priority:
#   description_llm_config  >  description_model_name  >  judge_llm (default)
# description_model_name: "gpt-4o"
# description_llm_config:
#   provider: "openai"
#   model_name: "gpt-4o"
#   ...
```

**Cost note:** this runs one LLM call per injected turn plus one per sample. If your
inject experiments have N injection targets per sample, expect about N+1 extra LLM
calls per sample on top of the MAS run and the LLM judge. To save cost, set
`describe_per_turn: false` (keep only the sample summary) or `describe_sample_summary: false`
(keep only per-turn). The terminal prints a per-sample log line
`[describe] id=... per_turn_descriptions=N sample_summary=True` so you can confirm what ran.

## LLM-Debate trajectory specifics

LLM-Debate has a structure that makes its trajectory harder to read than the
others, so several conventions are worth knowing:

- **`User` entries are inputs, not speakers.** Each per-Agent debate context is a
  list of OpenAI chat messages alternating `user` (the prompt the agent receives —
  the question, or a digest of other agents' previous answers) and `assistant`
  (the agent's actual reply). When we serialize this into `conversation_history`,
  the `user` messages appear as turns with `agent_name: "User"`; they are tagged
  `is_input: true` so you (and downstream tools) don't mistake them for agent
  speech. `agent_names` in the log lists only the actual speakers (`Agent 1..N`
  plus `Aggregator`), never `User`.
- **The Aggregator is a real synthesis step, not just a label.** After the N
  debate rounds, LLM-Debate runs `aggregate(query, answers)` which makes ONE
  more LLM call to synthesize a final answer from the per-Agent answers. This
  call is the source of the record's top-level `response`. The Aggregator step
  is NOT in the framework's `agent_contexts` (which only tracks per-Agent
  rounds), so the wrapper synthesizes a trajectory turn for it with
  `agent_name: "Aggregator"` and `is_aggregator: true`. If the Aggregator was
  the target of response_corruption, the Aggregator turn carries the same
  `clean_response_before_corruption` / `response_corrupted` / `injection_process`
  fields as any other injected turn.
- **Aggregator injection targeting.** In the experiment YAML write
  `role: "Aggregator"` (the role name) — `role_index` is ignored for the
  Aggregator since there is only one. `multi_injection_info` will label such
  injections as `injected_role: "Aggregator"` (not `"Agent N"`).

## Injection engine (Q4 redesign)

The malicious factory is now **task-type aware and covers all 14 FM types** for
both `prompt_injection` and `response_corruption`. Three modes:

| `injection_method`     | Mechanism                                                    | When to use |
|------------------------|--------------------------------------------------------------|-------------|
| `direct_prepend`       | Task-typed hard-coded templates. No factory LLM call. Reliable, can't silently fail. | Default. Works on any RLHF'd target. |
| `llm_rewrite`          | Original AEGIS-paper meta-prompt sent to factory LLM.        | Paper-faithful replication. RLHF'd factories may refuse. |
| `llm_rewrite_strong`   | Same meta-prompt, wrapped in publicly-known jailbreak framing (research-framing + role-play) before sending to factory LLM. | When using an RLHF'd factory model. |

`task_type` selects the template family:

| `task_type`        | Use for                                                       |
|--------------------|---------------------------------------------------------------|
| `mcq` (default)    | MedQA / MedMCQA / PubMedQA / MMLU subsets / MMLU-Pro health   |
| `numeric`          | MedCalc-Bench (numeric clinical calculations)                 |
| `error_correction` | MEDEC-MS (find/correct error in a clinical note)              |
| `open`             | Free-form text tasks                                          |

`prompt_wrapper_style` controls how the adversarial instruction is presented
to the target agent in `direct_prepend` mode:

- `direct`: a visible `[UPDATED INSTRUCTION - SUPERSEDES ALL EARLIER]` block.
- `jailbreak`: a covert fake-supervisor / role-play preamble.

`factory_llm_config` lets you use a dedicated rewriter LLM (e.g. a less-aligned
or local model) while the MAS itself uses something like gpt-4o-mini. Critically:
**we no longer silently fall back when the factory LLM refuses**. The
`injection_process.fallback_used` field records `"refused_by_rlhf"` /
`"ineffective_rewrite"` / `"exception: ..."` with the raw factory output, so you
can SEE refusals and act on them (switch to direct_prepend, or use a different
factory LLM).

## Per-framework agent_names (Q1)

All four wrappers now emit `injection_log.agent_names` — the list of distinct
speakers in the trajectory (in first-seen order, excluding User-input
entries). DyLAN reads from its config's `roles:` list; AgentVerse derives from
the actual conversation history (since RoleAssigner assigns roles dynamically);
LLM-Debate enumerates `Agent 1..N` plus `Aggregator`; MacNet enumerates its
nodes.

## LLM-Debate User-entry display (Q2)

OpenAI chat-protocol `user` messages used to appear in the trajectory as
`User` turns. Two display modes, YAML-configurable:

```yaml
llm_debate_fold_user_inputs: false  # default: keep User entries tagged is_input=true
llm_debate_fold_user_inputs: true   # fold User content into next Agent's input_messages
```

Also fixed a bug where the post-hoc `_attach_input_messages` matcher was
positionally putting Aggregator's `input_messages` on a User turn. User-tagged
entries are now skipped during positional fallback.

## MAST taxonomy (Q3)

- Standalone reference at the repo root: `mast_taxonomy.json` — full 14-FM
  taxonomy with categories and a flat map.
- Per record: `save_data.mast_taxonomy_used` carries one-line descriptions of
  ONLY the FM types used in that record (avoids bloating every record with all
  14). The full taxonomy lives in the standalone file.

## Notes & knobs

- **Strictness / LLM-judge.** Correctness (`is_correct`, which drives the normal/error
  split) is decided by `aegis_core/utils/medical_verifier.py`. The default `judge_mode`
  is **`llm_primary`**: the LLM-as-a-judge is the primary decision-maker, with the
  regex/exact-match parser used as a fast pre-check and as a fallback when no LLM is
  available. Set `judge_mode` to `regex_first` or `llm_only`, and `use_llm_judge: false`
  to disable the LLM entirely. The judge is given a COMPLETE gold answer that combines
  `correct_answer` and `answer_text` (e.g. "D. Cross-linking of DNA"), so it can match
  either the option letter or the full answer text in the response.
- **Verification audit (`save_data.verification`).** Every saved record now contains a
  `verification` dict with the full decision trail so you can see HOW `is_correct` was
  determined: `decision_path` (e.g. `llm_primary/llm_judge_decisive`, `llm_primary/no_llm_used_deterministic`,
  `llm_primary/no_llm_default_false`), `llm_judge_called` (bool), `llm_judge_raw_output`
  (the literal CORRECT/INCORRECT text from the judge), `gold` (what gold answer the
  judge saw), `regex_extracted` (the letter the parser picked, None if it abstained).
  `main.py` also prints a one-line summary per sample to the terminal, e.g.
  `[verify] id=medqa_xxx is_correct=False path=llm_primary/llm_judge_decisive llm_judge_called=True judge_raw='INCORRECT'`,
  so you can spot at a glance whether the LLM judge actually ran. Doctor surfaces an
  aggregate (`records where LLM judge was called: N`) plus a warning when it was never
  invoked. The audit is also preserved in the final dataset under `metadata.verification`
  (stripped under `--strict_schema`).
- **Judge model.** By default the judge reuses the MAS run's LLM. To judge with a
  different model, set either `judge_model_name: "gpt-4o"` (reuses the same provider/
  url/key, overrides only the model) or a full `judge_llm_config:` block (its own
  provider/model/url/key) in the experiment YAML.
- **Injection targets.** Edit `injection_plan.targets` in the `*_inject.yaml` to choose
  which agent role/index, FM error type, and strategy to inject. Valid roles per
  framework: AgentVerse `RoleAssigner/Solver/Critic/Evaluator`, LLM-Debate
  `Agent/Aggregator`, DyLAN `Assistant` (and dataset-specific roles).
- **Yield.** Not every clean run is correct and not every injection flips the answer;
  step 3 filters to the valid ones. Over-generate in steps 2a/2b to hit a target count.
- **Other frameworks.** Swap `--method_name` and the `--experiment_config` to the
  `agentverse_*` or `llm_debate_*` YAMLs to generate on those systems.

## Diverse-dataset orchestrator (`scripts/generate_diverse_dataset.py`)

For enriching dataset variety, this script generates many randomized inject
configs and runs them in parallel:

- Per config, randomizes `injection_method` (direct_prepend / llm_rewrite),
  `prompt_wrapper_style` (direct / jailbreak), and `injection_plan.targets`
  (N distinct (role, role_index) pairs valid for the chosen framework, each
  with a random fm_error_type and injection_strategy).
- Two levels of parallelism: `--workers` controls how many `main.py`
  subprocesses run concurrently; each `main.py` further parallelizes samples
  internally via its async pool (`--max_workers` inside main.py).
- Output layout under `--output_root` (default `./results_diverse`):
  - `configs/<framework>/<label>.yaml` — every generated config
  - `results/<framework>/<label>/trajectories.jsonl` — per-config output
  - `logs/<framework>/<label>.stdout|stderr.log` — captured terminal output
  - `plan.jsonl` — flat record of every config that was generated
  - `summary.json` — overall run stats after completion

Each config's `<label>` directly encodes the random choices, e.g.
`dylan__direct_prepend__jailbreak__physician0-FM-1_2-pi_medical_researcher3-FM-1_4-pi`
makes it immediately clear what produced each result.

Example:
```
python scripts/generate_diverse_dataset.py \
    --frameworks dylan llm_debate agentverse \
    --num_configs 5 --targets_per_config 2 \
    --dataset_file ./datasets/data/medqa.json \
    --test_dataset_name medqa --model_name gpt-4o-mini \
    --workers 2 --no_descriptions
```

Tuning notes:
- `--workers 2` is a good starting point; `--workers 1` is sequential. Total
  LLM concurrency is `workers × main.py.max_workers` (the latter defaults to
  10), so 2×10 = 20 simultaneous LLM calls — turn down if you hit rate limits.
- `--no_descriptions` skips the LLM injection-description pass, which alone
  spends ~N+1 LLM calls per sample. Highly recommended for bulk generation;
  you can re-run the describer on selected samples later.
- `--sample_limit N` caps each config to N samples — useful for piloting
  before committing to a long run.
- `--dry_run` prints the plan without launching subprocesses.

## Multimodal support (MedXpertQA-MM, GPT-4o-mini / GPT-5 / qwen3-vl)

The trajectory pipeline is now multimodal-aware end-to-end. For datasets that
attach images to samples (MedXpertQA-MM is the canonical example), every LLM
call in the MAS run will receive the image(s) so vision-capable models can
actually look at them — not just read a textual note about them.

### How it flows

1. `data_processing/medical/convert_medical_datasets.py --dataset medxpertqa-mm --images_dir /path/to/medxpertqa_images` records `image_paths: [abs_path, ...]` in each sample.
2. `main.py` reads `sample["image_paths"]` and stores it on the `Task` object.
3. Each `FM*Wrapper` (DyLAN, LLM-Debate, AgentVerse, MDAgents) installs an `_attach_task_images(instance, task.image_paths)` layer on `instance.call_llm` BEFORE the capture and injection patches. This layer auto-injects `images=...` into every kwargs passed downstream.
4. `MAS.call_llm(... images=...)` in `methods/mas_base/mas_base.py` calls `_attach_images_to_messages` to convert each image ref into the OpenAI multimodal content part (`{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`) and attaches it to the last user message.
5. For text-only tasks (`image_paths` is None or empty), the layer is a no-op — text trajectories are unaffected.

### MDAgents-specific behavior

`MDAgents_Main._ask` skips images on `Recruiter` and `Classifier` turns by
design (those are purely planning/routing steps). Every `Expert` and
`Aggregator` turn receives the image(s), which is exactly what you want for
medical-image-grounded diagnosis.

### What you need on the LLM side

- An OpenAI-compatible endpoint that supports the vision format. `gpt-4o`,
  `gpt-4o-mini`, `gpt-5*`, `qwen3-vl-*` (via OpenAI-compatible Dashscope
  proxy), Claude (via OpenAI-style proxies), etc. all work.
- The image is sent as a base64 data URL by default (no upload step needed).
- A `http(s)://` URL or pre-built `data:` URL in `image_paths` is forwarded
  through unchanged — useful when images are hosted somewhere already.

### Cost note

Each MM sample sends the image with EVERY non-planning LLM call (5 calls in
the default MDAgents intermediate panel: 3 experts + 1 aggregator turn after
recruitment). For 2000 MedXpertQA-MM-test samples × 5 image-sends = 10k
multimodal calls. Vision tokens are charged separately by most providers;
budget accordingly.

### Quick run

```
# 1. Unpack MedXpertQA images
mkdir -p datasets/medxpertqa_images && unzip MedXpertQA/images.zip -d datasets/medxpertqa_images/

# 2. Build the AEGIS-format dataset with absolute image paths
python data_processing/medical/convert_medical_datasets.py \
    --dataset medxpertqa-mm --split test \
    --images_dir datasets/medxpertqa_images

# 3. Run MDAgents on it (config: gpt-4o-mini or similar vision-capable model)
python main.py --method_name mdagents \
    --experiment_config experiments/fm_injection/medical/mdagents_medical_inject.yaml \
    --dataset_file ./datasets/data/medxpertqa-mm.json \
    --test_dataset_name medxpertqa-mm --model_name gpt-4o-mini
```

## MedConceptsQA (medical-coding MCQ benchmark)

Source: `ofir408/MedConceptsQA` on HuggingFace
(<https://huggingface.co/datasets/ofir408/MedConceptsQA>)

A pure 4-choice (A-D) text MCQ benchmark over 5 medical-coding vocabularies
(ATC, ICD9CM, ICD9PROC, ICD10CM, ICD10PROC) and 3 difficulty levels (easy,
medium, hard). 16 official HF subsets total:

| AEGIS `--dataset`                       | HF subset       | rows (test)    | use case                       |
|----------------------------------------|-----------------|----------------|--------------------------------|
| `medconceptsqa` / `medconceptsqa-all`  | `all`           | 820k           | union of everything            |
| `medconceptsqa-atc-easy`               | `atc_easy`      | 6.4k           | ATC vocabulary, easiest tier   |
| `medconceptsqa-atc-medium`             | `atc_medium`    | 6.4k           |                                |
| `medconceptsqa-atc-hard`               | `atc_hard`      | 5.9k           |                                |
| `medconceptsqa-icd10cm-easy`           | `icd10cm_easy`  | 94.6k          | ICD-10-CM diagnostic codes     |
| `medconceptsqa-icd10cm-medium`         | `icd10cm_medium`| 81.8k          |                                |
| `medconceptsqa-icd10cm-hard`           | `icd10cm_hard`  | 88k            |                                |
| `medconceptsqa-icd10proc-easy`         | `icd10proc_easy`| 191k           | ICD-10-PCS procedure codes     |
| `medconceptsqa-icd10proc-medium`       | `icd10proc_medium`| 191k         |                                |
| `medconceptsqa-icd10proc-hard`         | `icd10proc_hard`| 88.6k          |                                |
| `medconceptsqa-icd9cm-easy`            | `icd9cm_easy`   | 17.7k          | ICD-9-CM diagnostic codes      |
| `medconceptsqa-icd9cm-medium`          | `icd9cm_medium` | 17.7k          |                                |
| `medconceptsqa-icd9cm-hard`            | `icd9cm_hard`   | 16.9k          |                                |
| `medconceptsqa-icd9proc-easy`          | `icd9proc_easy` | 4.67k          | ICD-9 procedure codes          |
| `medconceptsqa-icd9proc-medium`        | `icd9proc_medium`| 4.67k         |                                |
| `medconceptsqa-icd9proc-hard`          | `icd9proc_hard` | 4.44k          |                                |

Both hyphen (`atc-easy`) and underscore (`atc_easy`) separators are accepted,
case-insensitive. Each sample's `question` field already contains the
"A. ... B. ... C. ... D. ..." block inline (no separate options list needed),
so the converter only appends a short imperative to lock the output format.

**ID convention:** the converter emits globally-unique sample ids of the form
`medconceptsqa-<vocab>-<level>-<question_id>` (e.g. `medconceptsqa-icd9proc-medium-29`).
Without the prefix, `question_id` values would collide across subsets.

**Build commands:**

```bash
# Whole "all" subset (huge — use --limit for pilot runs)
python data_processing/medical/convert_medical_datasets.py \
    --dataset medconceptsqa --split test --limit 500

# A specific (vocab, level) pair
python data_processing/medical/convert_medical_datasets.py \
    --dataset medconceptsqa-atc-easy --split test

# The 60-row dev split is convenient for sanity-checking pipelines
python data_processing/medical/convert_medical_datasets.py \
    --dataset medconceptsqa-icd10cm-hard --split dev
```

The verifier (`aegis_core/utils/medical_verifier.py`) recognizes every variant
via `MCQ_DATASETS`, so `--test_dataset_name medconceptsqa-icd10cm-hard` (etc.)
works out of the box with the existing A-J letter-extraction regexes.

## Trial-Success (ClinicalAgent's clinical-trial-outcome dataset)

Source: `algo/agents/tool/risk_model/data/trial_success.csv` from the
[full-clinical-agent release](https://github.com/GuihaiChen1998/full-clinical-agent).
Original paper: Yue et al., "ClinicalAgent" (ACM-BCB 2024, arXiv:2404.14777).

**Schema (tab-separated, 5 columns, 23,045 rows):**

| column     | meaning                                                       |
|------------|---------------------------------------------------------------|
| `nctid`    | ClinicalTrials.gov identifier (globally unique, e.g. NCT00000172) |
| `criteria` | eligibility criteria free text (inclusion + exclusion)         |
| `drugs`    | semicolon-separated list of drug names, lowercase              |
| `diseases` | semicolon-separated list of disease names, lowercase           |
| `label`    | binary outcome: `1` = trial succeeded, `0` = trial failed      |

Label distribution: 13,655 success / 9,390 failure.

**Task:** given (drugs, diseases, criteria), predict the FAILURE probability
p in [0, 1] wrapped in a `<final_result>0.X</final_result>` tag. The verifier
extracts the probability and thresholds it at 0.5 to get a binary prediction,
which it compares to `1 - label` (paper's convention: gold = failure indicator).

The converter's output sample looks like:

```json
{
  "id": "NCT00000172",
  "query": "#My problem#: <problem>...</problem>\n#drugs#: <drug>galantamine</drug>\n...",
  "answer": "0",
  "ground_truth": {
    "correct_answer": "0",
    "raw_label": 1,
    "predict_target": "failure_probability",
    "threshold": 0.5,
    "nctid": "NCT00000172",
    "drugs": "galantamine",
    "diseases": "alzheimer disease"
  }
}
```

**Convert command:**

```bash
# Extract full-clinical-agent.7z somewhere first, then:
python data_processing/medical/convert_medical_datasets.py \
    --dataset trial_success \
    --csv_path /path/to/full-clinical-agent/algo/agents/tool/risk_model/data/trial_success.csv \
    --limit 200 --out_dir ./datasets/data
# Writes ./datasets/data/trial_success.json
```

Under the hood the verifier registers `trial_success`, `trial-success`,
`clinical_trial_outcome`, `clinical-trial-outcome`, `clinicalagent` — all
route to `_verify_probability` in `aegis_core/utils/medical_verifier.py`.
Extraction is tolerant to `<final_result>0.8</final_result>`,
`<final_result>85%</final_result>`, `final_result: 0.7`, and clamps garbage
to [0, 1].

**Injection engine notes:** the trial-success task_type is `probability`
(see `aegis_core/malicious_factory/fm_malicious_system.py:_WRONG_ANSWER_FOR_TASK`).
Because the correct answer is unknown to the factory at injection time, the
factory tells the LLM to "output the opposite probability", which flips the
answer on roughly half of samples (whichever side the true probability sits
on). This is enough signal for downstream analysis but is not a per-sample
guaranteed flip like MCQ injection is.
