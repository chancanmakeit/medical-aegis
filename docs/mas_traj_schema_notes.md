# mas-traj/1 schema notes (additions proposed in v10 round 15 / issue round 43)

Status: **draft, to be agreed with MedHyperTrace**. `check()` in `scripts/export_schema_v1.py` already accepts
both additions; our own exports do not use them yet (all our steps are `llm`).

## 1. `kind: "environment"` + `env_type`

A step whose text **no agent wrote in this run**: prompt templates, page or tool dumps that enter the
conversation as messages, scaffold messages, a simulated user.

| field | values |
|---|---|
| `kind` | `llm` \| `tool` \| `environment` |
| `env_type` (only when `kind == "environment"`) | `template` (a framework's fixed or templated message, e.g. a reflection prompt that forwards an earlier conclusion), `tool_output` (a tool / code executor result that is not a structured `tool` step), `web_page` (page text, accessibility tree, screenshot description), `scaffold_prompt` (policy, system or role prompt that the agents work under, e.g. the tau-bench retail policy), `user_simulator` (an LLM that plays the user) |

Rules:
1. Only `llm` steps (and `tool` steps that are an agent's own action) are **attribution candidates**.
   An `environment` step is never a labelled faulty step; a dataset label that points at one is kept in
   `labels.external` and flagged (e.g. `label_on_environment: true`), not moved to another step.
2. `environment` steps may be **truncated or compressed** (keep head and tail, or a deterministic
   extract); say so in `structured.compression`. `llm` steps are **never rewritten or summarised** (MATE
   compresses observations only; rewriting agent messages would erase the faults we attribute and add a
   uniform style that a model can key on).
3. `environment` steps can be cited in `sources` like any other step; `tool_calls` must be empty.
4. Processing must be **symmetric across data sources**: whatever is compressed or masked in one source is
   compressed or masked the same way in all sources, and a source-identifiability check (predict the data
   source from model-visible input after `norm()`, AUROC within a label class) is reported.

## 2. `phase_canonical` (draft v0)

A fixed vocabulary for what a step does, next to the framework's own `phase` (unchanged):
`plan, route, analyze, answer, discuss, synthesize, vote, review, revise, decide, act, tool, environment, other`.
Definitions and the per-framework table: `configs/phase_canonical_v0.yaml`; lookup and coverage report:
`scripts/phase_canonical.py`. Peer rule: `answer` vs `discuss` is decided by whether the step reads
(`sources`) an answer/discuss step of another agent.

Coverage (`docs/requests/samples/phase_canonical_2026-10-26/coverage.txt`): our 4 anchor frameworks, the
mock exports of the other registry frameworks (kamac not yet observed) and all 7 public datasets as
converted by MHT r57 -- 194,183 steps, 0 left as `other`. The public-dataset rows are our proposal and
need MHT's review.

## 3. Branching runs: `run_mode: "branch"` + `labels.branch` (2026-11-03, issue #1 rounds 47-49)

A branch or control arm of a branching run (`scripts/branch_pilot.py`) re-plays a recorded normal run,
regenerates some steps, and keeps everything else from the record. It is **not** a normal run and has
its own identity:

- `run_mode: "branch"`; `run_id = "<pair_id>|<arm>|rep<k>"`; never listed in `paired_normal_run_ids`.
- `labels.branch` (label side only; renderers and graph features must not read it — arm and protocol are
  the treatment, a model that sees them can condition on its own arm):
  - `experiment_id`, `protocol_id` (`branch-resample-t-at-0.7_descendants-at-0_replay-rest_v1`)
  - `parent_run_id`: exporter run_id of the recorded normal run (same `run_index`)
  - `candidate_step_id`: stable key of step t in the parent run; `candidate_index`:
    `{"t", "base": 0, "sequence": "llm_steps"}` (llm_steps = `conversation_history` entries whose
    `input_messages` is a list; position only, join on `candidate_step_id`)
  - `pair_id = parent_run_id|candidate_step_id|protocol_id`: a **group** (one branch rep 0, one control
    rep 0, optional further control repetitions)
  - `arm` (`branch` / `control`), `repetition` (0-based), `pass` (the candidate's index under its rule)
  - `descendant_step_ids` (D(t)), `regenerated_step_ids` (branch: t + D(t); control: D(t)),
    `replayed_step_ids` (the rest); `evidence[step]`: call-log tag, temperature, sha1 of the text —
    every upstream call of the run maps to exactly one regenerated step
  - `selection`: `candidate_rule`; stratum fields when the rule has them (`position`, `peers_right`,
    `letter_status`, `run_end`); for control repetitions >= 1 `repetition_rule` + `repetition_reason`
    (`flipped_at_rep0` / `random_undetermined`) — repetitions are selective, report them stratified.
- Source: runs from 2026-11-03 embed a `branch` block in each output record; the 2026-10-26 pilot has a
  sidecar `data_runs/branch_pilot_2026-10-26/branch_sidecar.jsonl` (`--branch_sidecar`). A branch_pilot
  output without identity is refused by the exporter. `check()` validates the block; tests:
  `tests/test_branch_identity.py`.
- Outcome labels (flip, answer_changed, correctness_changed) are derived per pair by the analysis, not
  stored in this block: a flip is `outcome_sensitive_under_protocol` for step t, never `decisive_step`,
  and no flip is `undetermined`, never a negative.
