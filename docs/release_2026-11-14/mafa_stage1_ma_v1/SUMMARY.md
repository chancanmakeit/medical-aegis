# MAFA Stage-1 on ma_v1: summary

| arm | traces ok | still failed | schema | flagged (>=1 finding) wrong / right | findings per trace wrong / right | novel modes |
|---|---|---|---|---|---|---|
| mast gemini-4-hydrogen | 298 | 22 | {'json_object': 298} | 72/140 / 62/158 | 1.31 / 0.64 | 15 |
| mast gpt-6.1-terra | 320 | 0 | {'json_schema': 320} | 120/160 / 117/160 | 1.91 / 1.23 | 56 |
| maa gemini-4-hydrogen | 231 | 89 | {'json_object': 231} | 41/79 / 52/152 | 1.05 / 0.72 | 74 |
| maa gpt-6.1-terra | 320 | 0 | {'json_schema': 320} | 132/160 / 118/160 | 2.80 / 2.12 | 269 |

## Flag rate by group (wrong / right)

| group | mast gemini-4-hydrogen | mast gpt-6.1-terra | maa gemini-4-hydrogen | maa gpt-6.1-terra |
|---|---|---|---|---|
| agentverse | 9/17 / 5/20 | 12/20 / 6/20 | 8/18 / 4/20 | 13/20 / 11/20 |
| dylan | 9/20 / 8/20 | 16/20 / 15/20 | 6/12 / 6/19 | 19/20 / 18/20 |
| llm_debate | 6/19 / 1/20 | 11/20 / 12/20 | 4/7 / 7/18 | 19/20 / 19/20 |
| mac_groupchat | 7/19 / 5/20 | 15/20 / 17/20 | 10/10 / 14/20 | 20/20 / 15/20 |
| mdagents | 17/17 / 20/20 | 19/20 / 20/20 | 5/11 / 4/18 | 11/20 / 12/20 |
| mdagents_mm | 15/15 / 20/20 | 19/20 / 20/20 | 3/3 / 12/20 | 19/20 / 15/20 |
| medagents_mc | 2/17 / 2/19 | 13/20 / 13/20 | 2/13 / 3/19 | 14/20 / 10/20 |
| triage_agent | 7/16 / 1/19 | 15/20 / 14/20 | 3/5 / 2/18 | 17/20 / 18/20 |

## Agreement between the two models (same taxonomy, trace flagged or not)

- mast: n=298; both flag 118, gemini only 16, gpt only 98, neither 66
- maa: n=231; both flag 89, gemini only 4, gpt only 81, neither 57

## Organiser-only: does the LLM point at the v3 counterfactual-positive step? (wrong runs with >=1 v3 positive)

| arm | runs | any finding on a v3-positive step | earliest_fault_step = a v3-positive step | mapped step missing |
|---|---|---|---|---|
| mast gemini-4-hydrogen | 95 | 17 | 12 | 0 |
| mast gpt-6.1-terra | 114 | 27 | 13 | 0 |
| maa gemini-4-hydrogen | 49 | 7 | 4 | 0 |
| maa gpt-6.1-terra | 114 | 25 | 18 | 0 |
