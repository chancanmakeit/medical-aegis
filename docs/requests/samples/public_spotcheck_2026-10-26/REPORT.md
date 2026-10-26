# Spot-check of MHT's public mas-traj/1 conversions (MHT r57 converters), 2026-10-26

Script: `scripts/public_conversion_spotcheck.py` (20 records per dataset, seed 0, 140 records; each compared
with its RAW dataset row). Raw files from HuggingFace in the layouts the converters read; converters run
unchanged (`python -m data_tools.public_to_mas_traj.<module>`). Numbers: `spotcheck_summary.txt`,
`spotcheck.json`. Extra whole-dataset checks below were run ad hoc on the same files.

## Reproduction
Record counts match MHT's: who_and_when 184, traceelephant 220, mast_data 1642, aria 22,237, aftraj 1,548,
mascope 260, agentrx_tau 29 (26,120). `check()` problems: 0 in every file.

## Fidelity (sampled 140 records, 3,120 steps)
| dataset | non-empty step outputs found in raw | empty outputs | raw text covered by steps / query / inputs / tool_calls | what is not covered |
|---|---|---|---|---|
| who_and_when | 100% verbatim | 0 | 0.997 | -- |
| traceelephant | 100% verbatim | 41.7% (llm steps that only call tools; see A) | 0.998 | completion ids |
| mast_data | 96.2% verbatim + 3.3% after unescaping | 0.4% | 0.50 | runtime logs (docker / pip / telemetry), ChatDev system and role prompts; all ChatDev utterances (679/679 in 60 traces) and all MetaGPT agent lines are kept |
| aria | 100% | 0 | 0.976 | "Benchmark: ... Task: ..." header of the first event (moved to `task.query`) |
| aftraj | 100% | 15.2% (llm steps with tool calls) | 0.944 | the instruction prefix of the first user turn |
| mascope | 100% | 0 | 0.873 | `[system]` blocks (documented: system_blocks_dropped) |
| agentrx_tau | 100% | 28.2% (llm steps with tool calls; `think` tool echoes) | 0.41 | the 5.7K-char retail **policy** system prompt (see C) |

No dataset judgment text (mistake_reason, failure_summary, ...) appears in steps or query. Two Who&When
hits are AgentRx step_reasons that quote an error message verbatim; ARIA `evidence.quote` fields quote the
trajectory by design.

## Findings
**A. TraceElephant SWE-agent: agent actions lost (bug).** In 344 of 1,551 SWE-agent step records the
model's tool call is only in the record's `tool_logs` (`message.tool_calls` empty, content empty,
finish_reason `tool_calls`). The converter reads `message.tool_calls` only, so these llm steps have empty
output and no tool_calls. **18 of the 44 labelled SWE-agent mistake steps are empty after conversion; 17 of
them have the action in `tool_logs`.** CaptainAgent has 51 more steps whose tool call is only in
`tool_logs` (content is present). Fix: if `message.tool_calls` is empty, take the calls from `tool_logs`.

**B. Agent naming in labels (by design, but affects agent-level evaluation).** Step alignment is right:
for all 218 TraceElephant records with a mappable label, the labelled converted step has the raw step's
output. But `mistake_agent` uses TraceElephant's `agent_name`, which differs from the converted
`agent_id` in 118/218 records: Magentic-One 59 (Orchestrator calls whose `agent_name` is the steered agent),
SWE-agent 44 (`agent_name` is the tool: bash, str_replace_editor), CaptainAgent 15. The converter keeps
`labels.external.step_agent_names`, so nothing is lost; agent-level accuracy must be scored in the
dataset's naming (or a `mistake_agent_id` in converted naming added). Who&When has the same pattern
(`Orchestrator (-> WebSurfer)` entries labelled WebSurfer); 3 Hand-Crafted `mistake_step` values are past
the end of the history (mapped to null, 1 in the sample).

**C. Dropped scaffold that the labels depend on.** AgentRx tau failures are judged against the retail
policy ("authenticate the user before ..."), but the policy prompt is dropped, so a model cannot see the
rule that was broken. Proposal: keep it as `kind: environment, env_type: scaffold_prompt` (truncation
allowed). Likewise the tau user turns are an LLM user simulator; as `llm` steps they are attribution
candidates (1 of the 24 sampled AgentRx labels lands on a user-simulator step). Proposal:
`env_type: user_simulator`.

**D. ARIA labels on the task input.** 254 labelled ARIA records have first-bad events that map to no step:
Magentic-One 221 (event 0003 = the user task message) and MetaGPT 33 (event 0001 = launch). The task
became `task.query` (`first_event_as_task`), so the label has nowhere to go. Proposal: flag them
(`first_bad_on_task: true`) and leave them out of step-level evaluation. OpenManus: 140 records have one of
several first-bad events unmapped (dropped rollups).

**E. ChatDev: possible forwarded text counted as generations (please check).** 99 of 732 CEO `Reflection`
steps have output identical to the step before (e.g. the Programmer's `EnvironmentDoc` requirements.txt).
If this is ChatDev's reflection prompt forwarding the previous conclusion rather than a new generation,
these should be `environment/template` or dropped. Other consecutive repeats (ChatDev 2,766; HyperAgent
914; AppWorld 599) occur twice in the raw logs too (real loops, e.g. Qwen ChatDev DemandAnalysis).

**F. phase is assigned everywhere** (0% `unknown` in the sample). Correction to our round 42, which said
public data had `unknown` phases. There are 77 distinct values, many of them role names
(`product_manager`, `SimpleTester`, `*_turn`); `configs/phase_canonical_v0.yaml` proposes a mapping.
