# 锚点原始运行结果（llama-4-maverick，2026-10-21）

`main.py` 的原始输出（gzip）。新会话靠它们续跑和重新导出：沙箱 scratch 每次会话都会清空。

| 文件 | 内容 |
|---|---|
| `<fw>__normal.jsonl.gz` | 100 题 × K=3 normal（run_index 0–2） |
| `<fw>__inject.jsonl.gz` | run 0 = RC inplace（100 题）；run 1 = **旧版 PI**（已被 `_pi4` 取代，导出门槛数据时过滤掉） |
| `<fw>__inject_pi4.jsonl.gz` | run 1 = 长度匹配版 PI（前 50 题） |
| `<fw>__inject_sham.jsonl.gz` | run 2 = sham（前 50 题） |
| `<fw>__inject_shamstyle.jsonl.gz` | run 3 = sham_style **旧措辞**（前 50 题，导出后 `sham_variant = style_v1`） |
| `<fw>__inject_pi5.jsonl.gz` / `<fw>__inject_sham5.jsonl.gz` | run 1 = PI / run 2 = sham，**fmt_v1 格式匹配说明**（v10 第 4 轮，验证批，进行中；导出 run_id 带 `note=fmt_v1`，门槛分组 `@fmt_v1`） |

fw ∈ medagents_mc、mac_groupchat、llm_debate、mdagents。mac_groupchat 的 RC 少几条（少数运行没能生效，或被记成 not_fired）。

## 恢复与续跑

```bash
D=/home/claude/medical-aegis/data_runs/anchor_llama_2026-10-21
OUT=/home/claude/anchor_runs; mkdir -p $OUT
for f in $D/*.jsonl.gz; do gunzip -c $f > $OUT/$(basename ${f%.gz}); done
# 续跑示例（先征得用户同意：会产生 API 费用）
OUT=$OUT SUFFIX=_pi4       EXTRA="--num_runs 1 --run_index_start 1" bash scripts/runners/anchor_run.sh medagents_mc inject 50
OUT=$OUT SUFFIX=_sham      EXTRA="--num_runs 1 --run_index_start 2" bash scripts/runners/anchor_run.sh medagents_mc inject 50
# sham_style 新措辞写到新文件，从第 1 题开始全部 100 题
OUT=$OUT SUFFIX=_shamstyle2 EXTRA="--num_runs 1 --run_index_start 3" bash scripts/runners/anchor_run.sh medagents_mc inject 100
```

付费前先用 mock 服务器跑 2–3 题的 `_shamstyle2`，确认 `sham_variant` 是 `style_v2_<i>`，并且导出后 run_id 和旧的 `_shamstyle` 不冲突（新措辞的签名带 `sham_v2`）。

续跑按 (id, run_index) 跳过已完成的运行，`--limit N` 取接下来 N 道未处理的题。所以 `_pi4` 和 `_sham` 用 limit 50 就是补后 50 题。

## 导出和门槛

MiniLM 门槛需要先安装：`pip install --break-system-packages sentence-transformers`（约 2 分钟，会装 CPU 版 torch）。

```bash
python3 scripts/export_schema_v1.py $OUT/*__normal.jsonl $OUT/*__inject*.jsonl --out $OUT/anchor_all.jsonl
python3 scripts/build_anchor_gate_export.py $OUT/anchor_all.jsonl $OUT/gate_export.jsonl [--new_sham_style_only]
python3 scripts/quality_gate.py $OUT/gate_export.jsonl                     # TF-IDF，约 5 分钟
python3 scripts/quality_gate.py $OUT/gate_export.jsonl --features minilm  # MiniLM，2 核 CPU 上约 8 分钟，放后台跑
python3 scripts/sources_provenance_analysis.py $OUT/gate_export.jsonl
```

- 导出时 run_id 签名会区分 PI 版本和 sham 类型，所以把所有文件一起传入不会冲突。
- 2026-10-21 的门槛结果见 `docs/requests/samples/anchor_gate_2026-10-21/gate7_*.txt`。
- 两个门槛不要同时写同一个输出文件。
