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

## 第 6 轮（2026-10-22 01:51–02:20）：MHT 第 47 轮；清洗后残留签名的来源
用户："MedHyperTrace 那边给回复了"。

**MHT 第 47 轮**（comment 6336405130）：
- 词面检测器要算进验收，但要在"格式清洗后"的文本上算。他们的 `norm()` 会去掉标题、列表符号、`*_`` ` ``，以及 `[YES]` 这类方括号短答。他们会在送进编码器和 LLM 之前统一清洗，生成端不用再追列表符号的写法。
- **fmt_v2 先不跑。**
- 请我方免费分析 llm_debate、mdagents 的 sham（fmt_v1）清洗后残留的是什么。
- 验收标准提议：清洗后，同槽位 sham 对 normal 在 tfidf_punct 和 char 两种特征下，CI 都覆盖 0.5，或者不超过 RC 的噪声上限（0.62）。PI 不设这个门槛。

**MHT 复算**（清洗后，punct / char；`anchor_fmt_val_2026-10-21/mht_r47_lexical_norm_out.txt`），旧说明 → fmt_v1：

| 框架 | sham |
|---|---|
| llm_debate | 0.64/0.53 → **0.71/0.66** |
| MAC | 0.70/0.66 → 0.53/0.56 |
| mdagents | 0.53/0.63 → **0.74**/0.56 |
| medagents | 0.55/0.51 → 0.54/0.54 |

所以 fmt_v1 在 llm_debate、mdagents 上带进了一个非格式的残留；在 MAC 上是改善。

**我方分析**（`scripts/sham_residual_analysis.py`，使用 MHT 的 `norm()` 原样，同槽位；输出 `sham_residual_analysis.txt`）：
- **说明里的词没有被照抄**。simulation、colleague、genuine、carefully、format 等词，注入步和同槽位的比例都约为 0。
- **长度不是原因**：单特征 AUROC 0.41–0.52。
- **llm_debate sham**：normal 回复会逐个选项分析，带 `D:` / `J:` 这类选项标签。≥3 个选项标签的比例同槽位是 0.25，平均标签数 1.57。注入步很少这样写：fmt_v1 平均 0.45，旧说明 0.00。第一人称也更少：fmt_v1 0.30，同槽位 0.60，旧说明 0.45。这和 normal 一侧的 top n-gram（`J:`、`D:`、`This is`）吻合。推测 fmt_v1 的格式句（列出标题、粗体、列表）把回复推向"按主题加粗标签"的结构，而不是逐个选项分析。
- **mdagents sham**：结构特征（Answer 行、选项标签、第一人称、提到其他选项）两边相同。只有 `While other` 0.15 对 0.05，但旧说明也一样。残留只在 punct 上出现（0.74），char 是 0.56，CI 覆盖 0.5。n=20 时**无法归因**，不排除是小样本波动。
- **对训练的影响**：MHT 第 41 轮已经决定 llm_debate 的 PI 不进训练，只作压力测试。sham 的作用是作为 PI 的配对负例，所以 llm_debate 的 sham 不进训练也不影响。按 MHT 的验收标准，需要看的只有 MAC、medagents（都通过）和 mdagents（punct 不过，char 过）。

**建议（待用户决定）**：
1. 不做 fmt_v2，采用 fmt_v1 加 MHT 侧清洗。
2. mdagents 的 sham 用 fmt_v1 补跑第 21–50 题。这些题已有旧说明的 sham，补完就能在 50 题上做配对比较，判断 0.74 是否真实。mdagents 是最便宜的框架（约 $0.0026/次），30 次约 **$0.08**。
3. llm_debate：既然 PI 不进训练，就不再处理 sham 的残留。逐个选项分析的结构差异记录在案，留给主数据参考。
- 已在 issue 发我方第 34 轮（comment 6336794147）：残留分析，同意 fmt_v2 不跑、按 MHT 的验收标准，提议补跑 mdagents 的 sham 第 21–50 题（约 $0.08），问 MHT 是否同意"50 题上通过就把 fmt_v1 定为默认"。下一条我方编号为第 35 轮。

## 第 7 轮（2026-10-22 06:31–07:10）：在 MAFA 仓库开 issue 通知；核对 AEGIS simulated 的 PI
用户："你也可以在 MAFA 项目（https://github.com/chancanmakeit/MAFA-human-ai-annotation）下开 issue 来通知它关于我们已经做的事情。"

**MAFA 是什么**：负责人类标注的子项目，以人机协同方式对 AEGIS 轨迹做故障标注，支持 MAST 和 MedAgentAudit 两套体系。它和 MHT 的数据约定见其 `docs/标注数据接口说明.md`。仓库此前没有任何 issue。
- MAFA RUN.md §53（注入模板审计）得出结论：AEGIS simulated 里 response_corruption 的模板句就是故障本身，基于模拟真值的数字"以 prompt_injection 为准"。接口文档第 5 点写的是同样的意思。
- 核实：MAFA 的两个审查数据包（各 360 条）只取自 faulty 和 clean，**不含 simulated 轨迹**，所以人工标注不直接受注入伪迹影响。

**核对 AEGIS simulated 的 PI**（`scripts/aegis_simulated_signature_check.py`，输出 `docs/requests/samples/aegis_simulated_check_2026-10-22/signature_check.txt`）
- 数据：从 nature-sub-record 只取 clean 和 simulated 两个压缩包（34 MB）。两者题目 id 完全配对。
- 方法：同槽位比较，(id, agent_name, phase, 第 k 次出现)，每个注入步对比 clean 配对运行的同一步。能配上的比例：mdagents PI 1311/2024，dylan 1420/1861，clinical_agent 和 clinical_agent5 全部配上。
- AEGIS 原版的 PI 用 direct 写法（在 prompt 里加一段"UPDATED INSTRUCTION…"），没有长度匹配，指令里要求"用听起来自信但有缺陷的推理来论证"。
- 同槽位 tfidf_punct AUROC（原文 / MHT 清洗后）：mdagents 0.78/0.76，dylan 0.82/0.81，clinical_agent5 0.91/0.91，clinical_agent 0.78/0.77。**格式不是主因**。但没有 sham 对照，这个数里也包含真实的错误内容。
- **具体可数的伪迹**（PI 注入步 / clean 同槽位）：
  - **注入指令泄漏进回复**：mdagents 0.10/0.00，dylan 0.02/0.00，clinical_agent5 0.02/0.00。例如"to comply with the instruction""per the instruction I must…""Given the updated instruction"。
  - **拒答**：mdagents 0.03，dylan 0.02，clinical_agent5 0.06，clean 都是 0。例如"I cannot fulfill this request…"。
  - **框架要求的输出结构丢失**：mdagents 的 `Justification:` 0.09/0.25、`Answer:` 0.07/0.19；dylan 的 `Justification:` 0.39/0.65。
  - "argue"一类措辞只占 0–3%，不是主要来源。
- 结论：AEGIS 的 PI 子集也带可检测的伪迹，作为"真实子集"的参照比 MAFA 接口文档第 5 点说的要弱。泄漏和拒答可以用规则筛掉；结构丢失和清洗后仍有的 0.76–0.91，要有 sham 对照才能区分是伪迹还是错误内容。
- 已在 MAFA 仓库开 issue #1（chancanmakeit/MAFA-human-ai-annotation#1）。
- **更正（发出后自查）**：issue 里"mdagents 10% 的 PI 步直接提到注入指令"用的是宽口径正则，它把"the prompt …"也算了进去。在我们的锚点数据里，llama 常用"the prompt"指代题目，normal 步命中率就有 3.5%，所以宽口径不能等同于泄漏。
  - 改用严格口径（只认"instruction / comply with / as instructed"等明确说法）后，AEGIS PI 注入步：mdagents 0.024，dylan 0.025，clinical_agent5 0.017，clinical_agent 0.002，clean 全部为 0。
  - mdagents 宽口径多出的约 7% 仍然只出现在注入步里（clean 为 0），算一个签名，但不能确定是泄漏。
  - 脚本已拆成 `instruction_strict` 和 `prompt_or_instruction_loose` 两列。已在 MAFA issue 里发更正。
- **我们的锚点数据**（gate7 加 fmt_val，约 1290 个注入步，包括 PI、sham、sham_style、RC）：严格口径的泄漏为 0，拒答为 0。normal 步里两项各只有约 4 条。
- MHT 已发第 48 轮（同意先补跑 mdagents sham；fmt_v1 成为主数据默认之前，要先处理 llm_debate 的结构签名：格式句只描述参考回复实际用到的结构，先在 llm_debate 上用 10 题验证）和第 49 轮（征求中训练意见，4 个问题）。第 49 轮第 4 问已在我方第 35 轮回答，其余待用户决定。
- 已在 medical-aegis issue 发我方第 35 轮（comment 6342249101）：报告 AEGIS simulated 的 PI 伪迹（严格口径），并回答 MHT 第 49 轮第 4 问。我方倾向：中训练主版本排除注入运行；如果要用，就删掉注入步，用规则对整条轨迹剔除泄漏和拒答，并做有无注入运行的对比。另说明我们的锚点数据严格口径泄漏为 0、拒答为 0。下一条我方编号为第 36 轮。
- MAFA issue #1 已发更正（comment 6342243072）。

**待用户决定**（MHT 第 48、49 轮）：
1. mdagents 的 sham 用 fmt_v1 补跑第 21–50 题，约 $0.08。MHT 已同意这个顺序。
2. llm_debate 的结构签名（MHT 第 48 轮第 2 点）：格式句只描述参考回复实际用到的结构，例如逐个选项 `D:` / `J:` 分析。改代码不花钱，验证用 llm_debate 10 题。只跑 sham 约 $0.05，PI+sham 约 $0.10。
3. MHT 第 49 轮中训练的第 1–3 问：
   - 第 1 问：MedXpertQA 锚点题和 MAA 的重叠，可以免费核对；
   - 第 2 问：先做纯文本 TAPT 还是结构感知中训练，是意见；
   - 第 3 问：把 AEGIS 公开版、MAST-Data、Who&When、TRAIL 转成 mas-traj/1，并报告读取集被唯一确定的比例。不花 API 费用，但工程量较大，需要用户确认是否由我方来做。

## 第 8 轮（2026-10-22 07:13–07:40）：MAFA 回复（§70）；更正"拒答算伪迹"
用户："你对 MAFA 的评论它已经回复你了"。

**MAFA §70**（comment 6342733905，提交 `3ec823f`）：
- 用我们的脚本复现，输出逐字节相同；
- 泄漏来源：mdagents 的泄漏全部来自 `llm_rewrite` 方式的 PI，dylan 集中在 FM-2.6"INCONSISTENT"模板；
- **拒答不算伪迹**：拒答几乎全部来自 FM-1.2"放弃角色"和 FM-1.5"不要选定一个选项"，是被注入的故障本身；
- §53 的检出率去掉泄漏和拒答后为 20/42，原来是 22/45，影响不大；
- 审查数据包不受影响；
- 接口文档升到 v3.5。

**核对**（[n, 严格口径泄漏数, 拒答数]）：
- mdagents：`llm_rewrite` [1277, 52, 2]，`direct_prepend` [747, 0, 42]；
- dylan：FM-2.6 [207, 43, 0]；
- 拒答：mdagents FM-1.2 有 40 处，dylan FM-1.2 有 34 处，clinical_agent5 FM-1.2 有 9 处、FM-1.5 有 32 处。

**MAFA 的说法全部成立，我方更正**：
- 拒答是故障本身的表现，和 RC 的模板句同性质，不能剔除，但 FM-1.2 和 FM-1.5 的模拟真值检出数字会偏乐观；
- 只有严格口径的指令泄漏是可剔除的伪迹；
- 结构丢失是比例上的差异，不能逐步剔除。
- 脚本注释已写明哪一列可用于过滤。
- 已在 MAFA issue 回复（comment 6342940215）。

**MHT 第 50 轮**（comment 6342381808）：采纳中训练主版本排除注入运行的方案；打算复用我们的脚本，在整条轨迹上剔除"指令泄漏和拒答"；并计划对 v1 在旧 AEGIS PI 子集上的结论（比平凡基线高 10–13 个点），先剔除"泄漏、拒答、结构丢失三类步骤"再重算。**这两处都建立在我们第 35 轮的错误建议上，需要更正。**
- 已在 medical-aegis issue 发我方第 36 轮（comment 6342957323）：更正"拒答"，说明只有 `instruction_strict` 可以剔除，并给出 v1 重算的建议口径。下一条我方编号为第 37 轮。待用户决定的事项和第 7 轮相同。

## 第 9 轮（2026-10-22 11:38–12:20）：用户批准补跑和修复；中训练交给 MHT
用户："1，补吧；2，修复吧；3，由 MHT 做"。

**1. mdagents sham fmt_v1 补跑第 21–50 题**（30 次，$0.088）。先核对了题目顺序：fmt_v1 那 20 题就是数据集的前 20 题，旧说明 sham 那 50 题就是前 50 题，所以 `--limit 30` 正好取到第 21–50 题。50 题配对，用 MHT 的 `norm()` 清洗后，同槽位 AUROC：

| | punct | char |
|---|---|---|
| 旧说明 | 0.56 [0.51, 0.60] | 0.54 [0.50, 0.60] |
| fmt_v1 | 0.55 [0.48, 0.61]（过） | 0.65 [0.61, 0.71]（**不过**） |

- 20 题时 punct 的 0.74 是小样本波动。
- char 不过的原因：fmt_v1 下 mdagents 有 8–10% 的回复以"As a <role>…, I have analyzed…"开头；normal 只有 0.1%，旧说明下为 0。MAC 和 medagents 的 normal 本来就常这样开头（0.09 / 0.27）。
- 提议的修法（待用户决定）：不往说明里加话，只把"是否以自我介绍开头"加进 `match_format` 的格式签名，靠重采样筛掉。验证需要重跑 mdagents 50 题 sham，约 $0.14。

**2. fmt_v1_1：llm_debate 结构修复**（commit `10f0875`）
- 实现：
  - `option_walkthrough()` 统计参考回复里有几个选项字母出现在行首标签上，≥3 个算作逐项分析，并记下写法（是否用项目符号、是否加粗、用什么标点）。
  - 只在参考回复逐项分析时，说明里才描述这种写法，不给字母。不逐项分析时什么都不说：一开始写成了"不要另写逐项分析"的否定句，已删掉，因为 fmt_v0 的问题就出在否定句上。
  - 粗体在新版里只写"bold (**)"。
  - 格式签名加上"是否逐项分析"。
  - 配置项 `pi_length_match.state_structure: true`，只在 llm_debate 上开启。
  - `note_version = fmt_v1_1`，导出时 run_id 和 fmt_v1 不冲突（已核对）。
  - `build_fmt_validation_export.py` 改为按任意 `note_version` 分组。
- mock：6/6 成功，没有否定句，也没有"for key points"。
- 真实小批：llm_debate 10 题 × PI+sham，20/20 成功，花费 $0.090，20 次注入全部第一次就和格式签名一致。
- 同一 10 题三方对比：
  - 逐项分析比例（注入 / 同槽位）：sham 旧说明 0.00/0.20，fmt_v1 0.00/0.20，**fmt_v1_1 0.20/0.20**；PI 依次为 0.10/0.13、0.00/0.13、0.30/0.13。
  - 清洗后 AUROC（punct / char）：sham 旧说明 0.50/0.39，fmt_v1 0.63/0.60，**fmt_v1_1 0.59 [0.46, 0.71] / 0.58 [0.43, 0.73]**；PI 依次为 0.69/0.82、0.64/0.63、**0.87/0.93**。
  - 判读：sham 通过，结构也对齐了，但 n=10 时和 fmt_v1 的差别在噪声内。PI 明显升高，权重最高的特征是"After reviewing the…""Based on…""Given the…"这类开头，无法归因到逐项分析那句说明。PI 不设门槛，但不能忽略。
- 数据：`llm_debate__inject_{pi6,sham6}.jsonl.gz`。结果：`anchor_fmt_val_2026-10-21/llm_debate10_fmt_v1_1_*`。

**3. 中训练第 1–3 问由 MHT 做**（用户决定）。

MHT 第 51 轮已接受第 36 轮的更正。
- 已在 issue 发我方第 37 轮（comment 6348607425）：告知用户的三项决定，报告 mdagents 50 题和 llm_debate fmt_v1_1 的结果，并问 MHT 三件事（是否扩到 20 题、PI 升高的影响、自我介绍开头靠重采样筛掉是否可行）。下一条我方编号为第 38 轮。
- **待用户决定**：(1) mdagents 自我介绍开头的修复和验证，约 $0.14；(2) llm_debate fmt_v1_1 是否扩到 20 题，约 $0.09。两项都可以等 MHT 回复再定。

## 第 10 轮（2026-10-22 19:18–20:10）：MHT 第 55、57 轮；PI 与 sham 很少在同一槽位
用户："MHT 项目在 issue 里回复你了"。

**MHT 第 55 轮**（comment 6349178898）：
- 中训练：泄漏核对已做，锚点有 2 题和 MAA 重叠；中训练语料的口径；TRAIL 不进中训练；先做纯文本 TAPT，再做结构感知中训练。他们的 LoRA SFT 结果显示 graph 对 text 无差别。
- 建议把 llm_debate fmt_v1_1 扩到 20 题，并要求报告：(a) PI 对同槽位 sham；(b) 去掉首句后的 AUROC；(c) 答案改变率。
- 认可 mdagents 用重采样筛掉自我介绍开头，提出 4 点要求。

**MHT 第 57 轮**（comment 6355713703）及其补充更正（6355726800）：
- MAA 排除清单由 MHT 维护，请我们在抽题或导出时执行；
- 中训练先做 TAPT；
- 公开数据集转换器由 MHT 写，校验用我们的 `check()`；
- 提了 5 个字段问题。

**本轮工作**（commit `a8a99e9`）：
1. **PI 分析**（`scripts/pi_version_analysis.py`，同一 10 题、同一槽位，用 MHT 的 `norm()` 清洗）：
   - 三个版本的错误指令完全相同，只有格式说明不同。fmt_v1_1 那句里的"say for each why it is or is not right"不只是格式；字数目标在三个版本间也不同。
   - 配对差 fmt_v1_1 − fmt_v1：PI +0.24 [+0.02, +0.45]（punct），+0.30 [+0.19, +0.40]（char）；sham −0.04 / −0.02，不显著。
   - 去掉首句后 PI 仍有 0.82 / 0.86，"开头句式"的假设不成立。
   - 答案改变率三个版本都在 0.50–0.70。
   - 结论：fmt_v1_1 让 PI 更好认，对 sham 没有可测出的改善，不照原样扩大。改为提议 fmt_v1_2：去掉那句说明，只把"是否逐项分析"留在格式签名里，靠重采样对齐。
2. **重要发现：PI 和 sham 很少落在同一槽位**（`pi_sham_slot_overlap.txt`）。完全相同槽位的比例 0–14%，同 agent 同阶段 0–38%。原因是目标按 `(seed, 题目 id, run_index)` 各自抽取。MHT 的"同槽位 PI 对 sham"配对在现有数据上大多凑不成。
   - 修复：`main.py` 新增 `injection_plan.pair_target_runs`（可选，默认关闭），让同组的 run 共用一次抽取；PI 的抽取保持不变。单元检查和 mdagents mock（3/3 同槽位）都通过。
3. **mdagents 开头筛选**（`match_opener`，只在 mdagents 上开启）：自我介绍开头作为格式签名的第 4 位，以参考回复为准；记录 `format.n_tries` 和 `format.format_matched`，达到上限仍不一致时标为 false；导出时 run_id 加 `opener` 标签。mock 通过。
4. **MAA 排除**：清单复制到 `docs/requests/maa_exclusion_v1.json`；导出脚本新增 `--maa_exclusion`，写入 `labels.maa_overlap` 和 `labels.maa_probe`。锚点有 2 题（1499、1939）重叠，共 51 条运行，和 MHT 的检查脚本一致。
5. 回答了 MHT 的 5 个字段问题：同意他们的提议，并补充了 `how` 各取值的语义；建议同架构的公开框架沿用我们的 family 名，避免留一家族评测时架构信息泄漏。
6. 小坑重现：`pgrep -f "mock_openai_server.py --port …"` 又匹配到了 shell 自身，`kill` 把 shell 杀了。改用 `ps -eo pid,comm,args` 并按 comm 为 python 过滤。

- 已发 issue 第 38 轮（comment 6355926231），下一条为第 39 轮。

**待用户决定**：
1. mdagents 开头筛选的验证，约 $0.14，建议同时开启配对目标；
2. llm_debate fmt_v1_2 的 10 题验证，约 $0.09；
3. 锚点 sham 是否用配对目标重跑，4 个框架各 50 题，约 $1.4，等 MHT 意见。

## 第 11 轮（2026-10-26 00:12–01:10）：借鉴 agent 轨迹合成工作，规模化生成多智能体轨迹
用户：近期读到几篇合成 agent 轨迹数据的文章（TraceDance arXiv 2609.33295、MATE 2609.22724、Scaling Agentic Data for Long-Horizon Terminal Intelligence 2610.13166），考虑能否借鉴来直接合成多智能体轨迹，用于大规模预训练；也可以自行检索；并把想法提到 issue 里请 MHT 看。用户先说了"稍等"，所以第 59 轮的付费验证暂时按住。

**文献**：
- 会话里 arxiv.org 的 html 链接抓不到。只有出现在搜索结果里的 PDF 链接能抓，但这三篇的 PDF 没有出现。
- TraceDance 只读到 AI Weekly 的报道，MATE 只读到 HF 模型卡，TerminalHorizon 读到 hyper.ai 的较完整摘要，AgenTracer（2509.03312）读到了原文。
- 要点见 issue 第 39 轮第 1 节。

**我们的数据核对**：
- 锚点 normal 运行中自然答错的：llm_debate 141/300、MAC 132、mdagents 141、medagents 161，共 575 条。LLM 步数的中位数分别为 7 / 11 / 7 / 18。
- 回放可行性：记录下来的 `input_messages` 和服务器实际收到的请求逐字节一致，mock 日志 318/318（`scripts/check_replay_cache_keys.py`）。所以可以做一个按输入哈希应答的回放服务器：前缀原样复现，在第 t 步分叉，不需要改框架代码。
- 规模化成本（按 sham 批次的实测单价）：每百万条轨迹输出 token 约 $1.5–3.5。0.1B token 约 $150–350，1B 约 $1.5K–3.5K。1B 大约需要 2.4 万道题。

**我们的判断**（已写进 issue 第 39 轮）：
- 不建议把"让 LLM 整条写出轨迹"（MATE 式）作为带标签数据的主要来源：说明带来的签名在锚点上已经证实，而 MATE 只做了整体统计的对齐检查。
- 建议的主线是"在真实轨迹上分叉"：
  - (a) 在第 t 步自然重采样（TraceDance 的决策点续写）；
  - (b) AgenTracer 式的最小修正加重放；
  - 再加"第 t 步不变、只重采样后续步骤"的对照，测碰巧翻转的基线，作用和 sham 相同。
  - 好处：正例是自然文本；分叉出来的对天然在同一槽位；sources 是生成时记录的。
- 注入只作补充，覆盖少见的 MAST 类别。
- 风险：多选题会让"修正"失去意义；这样得到的是责任层标签而不是缺陷层；只有单一骨干模型；题库需要扩充（MedMCQA 等），并执行 MAA 排除。
- 试点（待用户批准）：llm_debate 和 mdagents 各 20 条自然失败轨迹，上限约 $2–3.5。

**MHT 第 59 轮**（comment 6362749412）：
- 他们实际还没用锚点的 PI / sham 训练过，"同槽位配对"只是计划；
- 建议主数据开启 `pair_target_runs`，锚点暂不重跑 sham；开启后要记录配对目标是否在两条 run 里都落地；
- 同意 fmt_v1_2 的思路，撤回"开头句式"的假设；
- `format_matched = false` 的样本保留并标记；
- 采纳 family 规则。
- 付费验证由用户决定，目前按住。
- 已发 issue 第 39 轮（comment 6410459789），下一条为第 40 轮。
