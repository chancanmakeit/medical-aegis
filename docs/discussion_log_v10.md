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

## 第 4 轮（2026-10-21 21:21–21:50）：生成端修复（fmt_v1）、新门槛基线、真实试跑
用户："按你推荐的继续吧"。即：先改生成端，验证跑 sham+PI，跑之前先试跑估算成本，再问用户。

**新门槛在 gate7 上的基线**（`quality_gate.py` 新增 same_slot 一节，以及 `--features tfidf_punct|char`）
- same_slot AUROC，tfidf_punct（保留标点、区分大小写）：

  | 框架 | PI | sham | sham_style | RC（对照） |
  |---|---|---|---|---|
  | llm_debate | 0.94 | 0.73 | 0.84 | 0.56 / 0.57 |
  | MAC | 0.70 | 0.72 | 0.79 | 0.49 / 0.47 |
  | mdagents | 0.78 | 0.54 | 0.64 | 0.51 / 0.59 |
  | medagents | 0.89 | **0.90** | **0.97** | 0.56 / 0.48 |

- 默认 tfidf 下 medagents sham 只有 0.57，签名几乎全是标点或格式。
- RC 在各种特征下都在 0.5 附近，可以作为检测器的负对照。
- char n-gram 版太慢（3 个门槛并行时超过 10 分钟），本轮没有出结果。

**第二个格式签名**（`scripts/sameslot_format_scan.py`）
- medagents 的 consensus_vote：normal 回复是 `[YES]`，注入步变成 `YES`，同槽位方括号比例 0.00 对 0.45。medagents 一半的注入落在这个阶段。
- 列表行也有类似的差距，例如 llm_debate PI 0.14 对 0.91。
- 大写的 YES/NO 本身不是签名，同槽位下两边比例相同。

**生成端修复 fmt_v1**（commit `18eca0c`）
- simulation 说明改为按同题干净参考回复的格式写明要求：用了哪些 markdown（标题、加粗、列表），或者是否是方括号短答案。只给格式，不给内容。同时删掉"不要加指令没要求的东西"一句。
- 配置项 `pi_length_match.state_format`：开启上述说明。
- 配置项 `match_format`：重采样时除了长度，还要求格式签名（markdown、列表、方括号）和参考回复一致。两项都已加入 4 个锚点 inject YAML。
- 导出时 run_id 签名加 `note=fmt_v1` / `fmtsel`，标签记 `note_version`；门槛按 `@fmt_v1` 分组，和旧数据分开。
- mock 测试：24/24 成功，注入 prompt 全部是新说明，2524 个 run_id 全部唯一。

**真实试跑**（2 题 × 4 框架 × PI+sham，写入 `_pi5` / `_sham5`）
- 16/16 成功，其中 15 次注入生效（MAC 的 sham 有 1 次没生效，属已知情况）。
- **15/15 第一次就和参考回复的格式签名一致**，没有触发重采样，包括 medagents 的 `[YES]` 投票。长度比 0.80–1.12。
- 花费 $0.097（`scripts/run_cost.py`，按 llama 列表价 $0.27/$0.85 每百万 token，在 sham 批次上校准，误差约 4%），合计约 $0.048/题。
- 2 题样本太小，只能说明说明本身起作用，签名是否消失要等验证批的同槽位门槛。

**待用户决定**：验证批规模。
- 10 题（MHT 提议）：再跑 8 题，约 $0.39。同槽位 AUROC 的 CI 约 ±0.2，判读有限。
- 20 题：再跑 18 题，约 $0.87。CI 约 ±0.13。
- 已在 issue 发我方第 32 轮（comment 6332928992）：复算确认、方括号签名、fmt_v1 修复和试跑结果、更正"3400 步"、同意不批 A–D、验证批规模待用户决定。下一条我方编号为第 33 轮。

## 第 5 轮（2026-10-21 22:12–22:55）：fmt_v1 验证批（20 题）结果
用户："按你推荐的继续吧"，即验证批跑 20 题 PI+sham。

**运行**：在试跑 2 题的基础上续跑 18 题，160/160 成功，无报错。20 题合计 $1.137，其中试跑 $0.097，续跑约 $1.04。预估是 $0.87，**超出约 20%**。主要是 medagents 和 MAC 的单题成本比试跑的 2 题高。
- 生效的注入：MAC 的 sham 有 1 次没生效，其余全部生效。
- **格式签名一致率**：第一次就一致的有 151/159（95%），最终保留的有 157/159。很少需要重采样，说明是说明本身在起作用。

**配对比较**（`scripts/build_fmt_validation_export.py`：同一 20 题、同一槽位，旧说明对 fmt_v1）。结果在 `docs/requests/samples/anchor_fmt_val_2026-10-21/`。

同槽位 markdown 比例（注入/normal）：

| 框架 | PI 旧 → fmt_v1 | sham 旧 → fmt_v1 |
|---|---|---|
| llm_debate | 0.25/1.00 → 1.00/1.00 | 0.50/1.00 → 1.00/1.00 |
| MAC | 0.44/0.78 → 0.78/0.78 | 0.47/0.79 → 0.75/0.75 |
| mdagents | 0.00/0.48 → 0.60/0.48 | 0.00/0.42 → 0.55/0.42 |
| medagents | 0.10/0.38 → 0.45/0.38 | 0.10/0.33 → 0.35/0.33 |

medagents 投票的方括号：0.05/0.50 → 0.50/0.50。

同槽位 AUROC（旧 → fmt_v1）：

| 框架 | 策略 | MiniLM | tfidf_punct | char |
|---|---|---|---|---|
| llm_debate | PI | 0.68 → **0.53** | 0.90 → 0.88 | 0.96 → 0.90 |
| llm_debate | sham | 0.64 → 0.57 | 0.65 → **0.78** | 0.80 → 0.88 |
| MAC | PI | 0.53 → 0.52 | 0.68 → 0.79 | 0.77 → 0.77 |
| MAC | sham | 0.52 → 0.47 | 0.67 → 0.60 | 0.68 → 0.63 |
| mdagents | PI | 0.57 → 0.60 | 0.76 → 0.70 | 0.82 → 0.80 |
| mdagents | sham | 0.55 → 0.54 | 0.57 → **0.73** | 0.67 → 0.76 |
| medagents | PI | 0.83 → **0.59** | 0.89 → **0.62** | 0.90 → 0.62 |
| medagents | sham | 0.88 → **0.44** | 0.89 → **0.48** | 0.89 → 0.50 |

- 噪声底：同 20 题的 RC，tfidf_punct 同槽位 AUROC 为 0.43–0.62。
- PI 对 sham（MiniLM）：0.35–0.53，两种说明之间差别不大。

**判读**
- 按 MHT 第 43 轮的验收标准（同槽位 markdown 比例、同槽位 MiniLM AUROC），**fmt_v1 通过**：markdown 比例对齐，MiniLM 全部 ≤ 0.60。medagents 的修复最明显。
- 但词面检测器（保留标点）在 llm_debate、mdagents、MAC 的 PI 上仍然明显高于噪声底，有的还**比旧说明更高**。原因（`format_scan.txt` 新增的几列）：**fmt_v1 矫枉过正，模型换成了自己的 markdown 写法**。
  - 星号列表：llm_debate sham 0.85 对同槽位 0.57，mdagents PI 0.25 对 0.02；
  - 短横线列表完全消失：0.00 对 0.10–0.28；
  - 粗体标签 `**Correct Option:**` 一类变多；
  - mdagents PI 的第一人称（I have / I believe）0.35 对 0.00，样本小，有待确认。
  - 格式签名只比较"有没有 markdown、有没有列表、是不是方括号"，看不到列表符号，所以重采样也筛不掉。
- 也就是说，旧签名（不用 markdown）没有了，换成了一个更弱、但读原文的模型仍然看得到的新签名（markdown 写法不同）。

**建议 fmt_v2**（尚未实现，待用户决定）：
1. 说明里写明参考回复的具体写法：列表符号（`-` 还是 `*`）、编号还是项目符号、粗体用于标签还是用于术语、标题级别。仍然只给格式，不给内容。
2. 格式签名加入列表符号类型，重采样按细化后的签名筛选。
3. 验证：同 20 题重跑 PI+sham，约 $1.1（按本批实际单价）。验收看 MiniLM 和 tfidf_punct 两种同槽位 AUROC，以 RC 噪声底为参照。
- 已在 issue 发我方第 33 轮（comment 6333571254，验证批结果，并请 MHT 判断词面检测器要不要算进验收）。
- 之后才发现 MHT 第 46 轮（comment 6333295535）早几分钟已经发出：同意 fmt_v1 思路；建议验证批 20 题（与用户的选择一致）；要求报告同槽位 MiniLM 和列表行比例，并提交导出；另告知 LLM 层在 MedAgentAudit 上的试跑结果（零样本 Qwen3-8B 宏 AUROC 0.616，编码器 0.655，配对差跨 0）。已补发第 33 轮补充（列表行比例、MiniLM 用的是我方实现、导出路径）。教训：读最新评论和发帖要分成两步，读完再发。
- 下一条我方编号为第 34 轮。
