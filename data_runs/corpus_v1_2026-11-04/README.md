# Corpus-pool natural runs v1 (2026-11-04, v11 r13)

For MedHyperTrace's interaction-CPT (MHT #3 round 86, prereg `MedHyperTrace-v2/docs/design/InteractionCPT_prereg_v1.md`). User-approved: 4 frameworks, no DyLAN.

- Questions: `datasets/data/pools_v1/corpus.json`, all 1,449, K = 1 (run_index 0). Disjoint from the eval pool (800) and from the anchor / MAA questions.
- Backbone: gemini-2.5-flash-lite, temperature 0.7, max_tokens 4096 — the same configuration as the v3 eval parents, served by the **duckcoding** endpoint (the eval parents used xiaojingai; same model name).
- Frameworks: llm_debate, mdagents, medagents_mc, mac_groupchat (YAMLs `experiments/fm_injection/gemini/`). Not run: DyLAN (read sets incomplete), AgentVerse / triage_agent / MAM (held-out evaluation layer).
- All 4 × 1,449 runs: status success, no empty trajectories; accuracy 0.42–0.45.
- `raw/`: main.py records. `mastraj/`: mas-traj/1 normal export (`scripts/export_schema_v1.py`), runtime `sources` with `collection: runtime`, `provenance.sources_complete` / `sources_known_gaps`. No reasoning, no injection.

Rendered tokens (`scripts/corpus_token_stats.py`: query + step outputs + ~12 header tokens per step, o200k):

| file | runs | rendered tokens / run: mean (median, p90) | total | steps / run | share of LLM steps reading a strict subset of history |
|---|---|---|---|---|---|
| llm_debate__normal_corpus.mastraj.jsonl.gz | 1449 | 2382 (2209, 3458) | 3.45M | 7.0 | 0.50 |
| mac_groupchat__normal_corpus.mastraj.jsonl.gz | 1449 | 1504 (1455, 2105) | 2.18M | 10.8 | 0.90 |
| mdagents__normal_corpus.mastraj.jsonl.gz | 1449 | 1728 (1635, 2241) | 2.50M | 7.0 | 0.83 |
| medagents_mc__normal_corpus.mastraj.jsonl.gz | 1449 | 7071 (6962, 8043) | 10.25M | 18.6 | 0.94 |

Total ≈ 18.4M rendered tokens. API tokens (gemini counts): prompt 80.8M, completion 15.7M; ≈ ¥5.2 at the xiaojingai price list.
