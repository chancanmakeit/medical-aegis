# MAFA Stage-1 on ma_v1: summary

| arm | traces ok | still failed | schema | flagged (>=1 finding) wrong / right | findings per trace wrong / right | novel modes |
|---|---|---|---|---|---|---|
| mast gemini-4-hydrogen | 320 | 0 | {'json_object': 320} | 89/160 / 64/160 | 1.52 / 0.67 | 23 |
| mast gpt-6.1-terra | 320 | 0 | {'json_schema': 320} | 120/160 / 117/160 | 1.91 / 1.23 | 56 |
| maa gemini-4-hydrogen | 320 | 0 | {'json_object': 320} | 104/160 / 55/160 | 1.73 / 0.73 | 276 |
| maa gpt-6.1-terra | 320 | 0 | {'json_schema': 320} | 132/160 / 118/160 | 2.80 / 2.12 | 269 |

## Flag rate by group (wrong / right)

| group | mast gemini-4-hydrogen | mast gpt-6.1-terra | maa gemini-4-hydrogen | maa gpt-6.1-terra |
|---|---|---|---|---|
| agentverse | 12/20 / 5/20 | 12/20 / 6/20 | 10/20 / 4/20 | 13/20 / 11/20 |
| dylan | 9/20 / 8/20 | 16/20 / 15/20 | 11/20 / 6/20 | 19/20 / 18/20 |
| llm_debate | 7/20 / 1/20 | 11/20 / 12/20 | 15/20 / 8/20 | 19/20 / 19/20 |
| mac_groupchat | 8/20 / 5/20 | 15/20 / 17/20 | 20/20 / 14/20 | 20/20 / 15/20 |
| mdagents | 20/20 / 20/20 | 19/20 / 20/20 | 9/20 / 4/20 | 11/20 / 12/20 |
| mdagents_mm | 20/20 / 20/20 | 19/20 / 20/20 | 20/20 / 12/20 | 19/20 / 15/20 |
| medagents_mc | 4/20 / 3/20 | 13/20 / 13/20 | 8/20 / 4/20 | 14/20 / 10/20 |
| triage_agent | 9/20 / 2/20 | 15/20 / 14/20 | 11/20 / 3/20 | 17/20 / 18/20 |

## Agreement between the two models (same taxonomy, trace flagged or not)

- mast: n=320; both flag 136, gemini only 17, gpt only 101, neither 66
- maa: n=320; both flag 151, gemini only 8, gpt only 99, neither 62

## Organiser-only: does the LLM point at the v3 counterfactual-positive step? (wrong runs with >=1 v3 positive)

| arm | runs | any finding on a v3-positive step | earliest_fault_step = a v3-positive step | mapped step missing |
|---|---|---|---|---|
| mast gemini-4-hydrogen | 114 | 23 | 15 | 0 |
| mast gpt-6.1-terra | 114 | 27 | 13 | 0 |
| maa gemini-4-hydrogen | 114 | 26 | 20 | 0 |
| maa gpt-6.1-terra | 114 | 25 | 18 | 0 |
