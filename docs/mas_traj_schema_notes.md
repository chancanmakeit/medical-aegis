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
