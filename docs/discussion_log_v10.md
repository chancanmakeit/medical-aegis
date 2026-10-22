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

## 第 2 轮（2026-10-21 20:41–20:50）：就补齐预算征求 MHT 意见
- 用户："关于我是否批准需要高达 $6.0 预算这件事，你也可以问问 MedHyperTrace 的意见"。
- 发帖前确认 MHT 在我方第 30 轮之后仍无新回复。
- 已在 issue 发我方第 31 轮（comment 6332128581），列出 4 个方案：
  - A：全部补齐，$6.0；
  - B：不补 llm_debate 的 PI，$5.75；
  - C：在 B 的基础上，前 50 题旧措辞 sham_style 不重跑、保留 `style_v1` 标签，$4.25；
  - D：只跑 sham_style 新措辞 100 题，$3.0。
- 请 MHT 回答 4 个问题：
  1. PI、sham 补到 100 题有没有必要（CI 约 ±0.1 → ±0.07）；
  2. 能否接受两种 sham_style 措辞来源并存；
  3. llm_debate 的 PI 压力测试子集用现有 50 题够不够；
  4. 是否宁可把预算留给主数据。
- 等 MHT 回复后，由用户决定是否批准、选哪个方案。仍未做任何付费运行。

## 第 3 轮（2026-10-21 21:12–21:30）：MHT 第 43 轮回复，核实
MHT 第 43 轮（comment 6332274175）要点和我方核实结果：

1. **格式签名**：任何带说明的注入（PI、sham、sham_style）都会抑制 markdown，而 TF-IDF 门槛看不到这一点。同槽位 MiniLM AUROC：medagents 的 sham 0.86，llm_debate 的 PI 0.73。
   - **核实**：
     - 同槽位 markdown 比例已用 gate7 复算，见 `scripts/sameslot_markdown.py` 和 `anchor_gate_2026-10-21/sameslot_markdown.txt`，与 MHT 基本一致，MAC 的同槽位基线差 0.03–0.06。
     - 例：llm_debate PI 0.24 对 0.99，mdagents sham 0.00 对 0.35。
     - **补充对照**：RC 是直接改输出，不给模型说明，它的注入步和同槽位 normal 的格式没有差别（llm_debate 1.00 对 1.00，MAC 0.99 对 0.98，mdagents 0.38 对 0.37，medagents 0.74 对 0.77）。所以签名来自插入的说明本身。
     - `quality_gate.py` 的 TfidfVectorizer 用的是默认 token_pattern，确实会丢掉 `#` 和 `*`。
     - 同槽位 MiniLM AUROC 尚未复算。
   - **可能的原因**（推测，未验证）：simulation 说明里写了"按上面指令要求的格式……不要加指令没要求的东西"。而 llama 默认会用 markdown，原指令并没有要求 markdown，这句话可能把模型推向纯文本。
2. **sources**：我方第 30 轮说"MAC 约 3400 个读取集有变化的步骤"，**是错的**。3445 是 MAC 300 条 normal 运行的总步数。
   - 按 MHT 的口径（候选数多于真实来源数，且读取集不是槽位众数），复算结果为 MAC 254（按题目内槽位）到 582（按全框架槽位），medagents 25–46，llm_debate 和 mdagents 都是 0。MHT 的 334 落在这个区间里。
   - 结论：锚点数据上做不了填充自监督。
3. **预算**：MHT 建议 A–D 都先不批，先修格式签名。
   - PI 和 sham 不需要补到 100 题；
   - style_v1 用 `sham_variant` 排除出训练，不重跑；
   - llm_debate 的 PI 用现有 50 题；
   - 预算留给主数据。
   - 修复后先做小规模验证：4 个家族 × 10 题，只跑 sham，约 $0.3。

**我方意见**：同意不批 A–D。

**待用户决定**：
1. 是否同意先改生成端（零费用）：
   - 用长度匹配时已经生成的干净回复，按它是否用了 markdown 来写格式要求；
   - 去掉"不要加指令没要求的东西"一句；
   - 门槛加同槽位检测器和保留标点的 TF-IDF。
2. 修复后的真实小样本验证：MHT 建议只跑 sham（约 $0.3）。我方建议同时跑 PI，约 $0.6，因为 PI 的格式差距最大。跑之前先试跑估算成本，再问用户。
