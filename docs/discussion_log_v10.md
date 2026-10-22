# medical-aegis 讨论记录 v10

> 新会话（2026-10-21 晚开始）。上一会话的完整记录见 `docs/discussion_log_v9.md`（第 21–24 轮是锚点和门槛的最新进展）；交接见 `docs/HANDOFF.md`。

---

## 第 1 轮（2026-10-21 20:25–20:45）：新会话续接；`_shamstyle2` mock 冒烟测试

**续接**
- 按 Project 文档「medical-aegis_新会话入口」挂载并 clone 仓库（HEAD `c06eb10`），读了 HANDOFF 当前状态、v9 第 21–24 轮、`data_runs/anchor_llama_2026-10-21/README.md`。
- 重建 `/home/claude/.mht_api.env`（600，只含 aihubmix 的 key 和 base url，未提交）。
- 原始运行结果已解压到 `/home/claude/anchor_runs/`，共 2500 条，与 README 一致。

**issue #1**：我方第 30 轮（comment 6331769814，03:13Z）之后 MHT **没有新回复**。MHT 对补齐的已有表态在第 41 轮：支持补齐，前提是先改写 sham_style 措辞（已在 `46e5a66` 完成），预算由用户批准。

**用户的决定栏**：本轮消息里"是否批准"一项仍是占位符，未填写。**因此没有做任何付费运行**，补齐预算（约 $6.0）仍待用户决定。

**mock 冒烟测试**（零费用，本地 mock 服务器，4 个框架 × 3 题 `_shamstyle2`，run_index_start 3）
- 12/12 运行成功，183 次调用全部打到 127.0.0.1，没有请求发往 aihubmix。
- 每条运行 run_index = 3，`sham = style`，`sham_variant = style_v2_<i>`，12 条里抽到了 0–5 中的 6 种措辞。
- 导出（2500 条真实 + 12 条 mock）：2512 条 run_id **全部唯一**；同一题的新旧 sham_style 签名不同（例：medxpertqa_text_2287，旧 `inject-75d7e27a`，新 `inject-eb04f6bb`）。
- `build_anchor_gate_export.py`：不加参数得 2204 = 2192（gate7）+ 12；加 `--new_sham_style_only` 得 2008，196 条 `style_v1` 被剔除，`plain_v1` 和 `style_v2` 保留。
- 已知情况（非新问题）：MAC 的 sham、sham_style 各有 4/50 条没有生效（导出里无注入标签），与 MAC RC 少几条的原因相同（目标 agent 没被选为发言者）。补齐时 MAC 预计也会有约 8% 不生效。
- 小坑：`pkill -f "mock_openai_server..."` 会顺带杀掉执行它的 shell（和 HANDOFF 里提到的 `pgrep -f` 是同一个问题），下次用 `kill <pid>`。

**待用户决定**：是否批准约 $6.0 的补齐（剩下 50 题 PI + sham 约 $3.0；sham_style 新措辞全部 100 题约 $3.0；llm_debate 的 PI 不补可省约 $0.25）。批准后直接用 `scripts/runners/anchor_run.sh` 真实运行，冒烟测试这一步已完成。
