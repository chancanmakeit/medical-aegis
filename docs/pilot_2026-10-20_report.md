# 试点报告（2026-10-20）

**范围：** medagents_mc（mmlu_pro_health）与 triage_agent（triage_esi）× 两个 backbone（mercury-2.5-preview、llama-4-maverick）。每个组合包括：
- normal：20 题 × K=4；
- PI（prompt injection）：10 题；
- RC（response corruption）：10 题。

合计 400 条运行。注入设置为 FM-2.3、direct_prepend、方案 A：medagents 的目标是 Synthesizer，triage 的目标是 Doctor B 的 classify 步骤。温度 0.7，max_tokens 4096，4 组并行 × 每组 4 个 worker，用时 69 分钟。

**数据：** `docs/requests/samples/pilot_2026-10-20/`
- `pilot_export.jsonl.gz`：schema mas-traj/1，380 条。20 条 API 失败的运行已跳过。
- `pilot_raw_results.tar.gz`：main.py 的原始结果，medagents 的 Reviser 读取集已修复。

## 1. 结果

| 框架 | backbone | normal 准确率 | 调用数/运行 | PI：目标步错 / 最终错 / 翻转 | RC：目标步错 / 最终错 / 翻转 | 估算成本 |
|---|---|---|---|---|---|---|
| medagents_mc | llama | 0.76 | 18（normal）/ 31–33（注入） | – / 2 / 0 | – / 2 / 0 | $1.06 |
| medagents_mc | mercury | 0.84 | 18 / 31 | **10/10 API 失败** | – / 1 / 0 | $2.08 |
| triage | llama | 0.82 | 8 | 10 / 1 / 0 | 8 / 4 / 3 | $0.24 |
| triage | mercury | 0.79 | 8 | **10/10 API 失败** | 7 / 3 / 1 | $1.12 |

列的含义：
- "翻转"：注入后最终答案错误，而同一题在 normal 的 4 次运行里至少一半答对。
- "最终错"：即 `is_valid_error`。它不区分这道题本来就答错的情况。
- 成本按第三方列表价估算：mercury 输入 $0.20、输出 $0.75，llama 输入 $0.27、输出 $0.85，单位为每百万 token。合计约 **$4.50**，低于事先估计的 $6–12。aihubmix 的实际计费未核实。

## 2. 发现

### 2.1 mercury 拒绝 "direct" 注入包装（PI 20/20 失败）
- 原因：aihubmix 返回 `{"error": {"code": 403, "message": "Upstream error from Inception: I can't set aside my guidelines or take on a persona meant to bypass them..."}}`。这是 Inception 上游对 `[UPDATED INSTRUCTION ... SUPERSEDES ALL EARLIER INSTRUCTIONS]` 这种覆盖式写法的拦截。同一 prompt 去掉注入块后正常返回。
- 新增 `prompt_wrapper_style: simulation`。它如实说明这是研究用的临床团队模拟，本轮你扮演某角色，该角色会犯以下错误；不声称覆盖指令，也不冒充权威。用 mercury 实测 2 次都通过，输出 ESI 1（正确答案是 2），理由看似可信，也没有提到注入。
- 注入文本只出现在标签侧的 `injected_input_messages`，导出的 steps 里没有（mock 检查：泄漏 0）。
- **待用户批准：** 用 simulation 包装重跑 mercury 的 PI。为了两个 backbone 一致，建议 llama 的 PI 也一起重跑。估算约 $0.6。

### 2.2 MedAgents 对 Synthesizer 注入会自我纠正（翻转 0/30）
- normal 运行：160/160 都在第 1 轮全票 YES，每次 18 步。
- 注入运行：除 1 次外，第 1 轮全部投 NO → 专家给修改建议 → Reviser 修正 → 第 2 轮全票 YES。最终错误只出现在 normal 下本来就会答错的题上。
- 带来两个问题：
  1. **最终结果标签几乎不会翻转**。注入轨迹记录的是"错误被检测并修复"，而不是"错误导致最终失败"。
  2. **拓扑侧信道**：有没有第 2 轮投票（步数 18 还是 31–33），几乎能完美区分注入和 normal。因为 normal 运行在 MMLU-Pro health 上从不出现自然分歧。
- 可选方案（需要和 MHT 商定）：
  - (a) 换注入目标：例如最后一轮的 Reviser、Decider，或某个 q/o 专家的分析（后者更隐蔽）；
  - (b) 用更难的题（例如 MedXpertQA），让 normal 运行也出现自然的投票分歧；
  - (c) 保留现状，并把"被检测并修复"作为一种单独的标签类别。

### 2.3 Triage：PI 能可靠地让目标步出错，但多数被其他医生和协调员纠正
- PI（llama）：Doctor B 10/10 被带偏（例如 ESI 5，置信度 100），最终只翻转 0 次。
- RC：llama 翻转 3/10，mercury 翻转 1/10。

### 2.4 读取集问题（已修复）
- medagents_mc：上游按专科名称作为键存储修改建议。问题专家和选项专家同属一个专科、又都投 NO 时，后一条建议会覆盖前一条，Reviser 实际只看到一条，但旧代码把两条都列为来源。
  - 试点中涉及 44 个来源（llama PI 14、RC 18，mercury RC 12）。
  - 代码已修复：按专科只保留最后一条。旧结果用 `scripts/repair_medagents_advice_sources.py` 按同一规则修复。被覆盖的那条建议现在成为没有下游读取者的步骤，这符合实际情况。
- triage：协调员读到的是去掉多余空白、截断到 400 字符的 rationale。读取集本身是对的；检查脚本的 excerpt 匹配已改为先规范化空白再比较。
- 修复后检查结果：全部 12 个文件 not_found=0、unlisted=0。导出 380 条，问题 0，注入文本泄漏 0。

### 2.5 其他
- 截断：共 5,454 次调用中只有 1 次（mercury，o_expert，3955 个 completion token，其中 2423 是 reasoning）。另有 1 次 `finish_reason=error`，内容完整。
- mercury 的 completion token 约为 llama 的 4 倍（medagents 1.88M 对 0.44M），主要是隐藏的 reasoning。
- 解析：所有成功运行都得到了答案（答案为空 0 次）。
- 限流：16 路并发下，0 次 429。

## 3. 补跑：simulation 包装的 PI（13:12–13:30，用户已批准）
- 配置：`experiments/fm_injection/pilot/*_pilot_pisim.yaml`。与 `*_pilot_pi.yaml` 相同，只是 `prompt_wrapper_style: simulation`；同样 10 题，两个 backbone 都跑。
- 40/40 成功。实际成本按列表价约 $0.60（事先估计约 $0.6）。

| 框架 | backbone | 目标步错 | 最终错 | 翻转 | 步数 |
|---|---|---|---|---|---|
| medagents_mc | llama | – | 3 | 1 | 18×2，27–33×8 |
| medagents_mc | mercury | – | 3 | 1 | 18×2，27–33×8 |
| triage | llama | 10/10 | 1 | 0 | 9 |
| triage | mercury | 10/10 | 3 | 2 | 9 |

- 和 direct 包装比：medagents 有 2/10 的注入运行第 1 轮就全票通过，翻转 1/10（direct 为 0/10）。triage mercury 翻转 2/10。
- 检查结果：读取集 not_found=0、unlisted=0；导出 420 条，问题 0，泄漏 0。
- 导出器的 run_id 现在也区分注入变体：wrapper 不是 direct，或者用了改写池时，计入 `inject-<签名>`。这样 direct 与 simulation 跑同一题时 run_id 不会冲突，原有 id 保持不变（用旧 mock 样例核对过，42/42 一致）。

## 4. 本轮发现并修复的工厂问题
1. **MCQ 的 RC 总是篡改成 "A"**：`_WRONG_ANSWER_FOR_TASK["mcq"] = "A"`。
   - 正确答案是 A 时，注入后答案反而是对的；而且 "A" 本身就是一个捷径特征。
   - 已改：从题目实际的选项字母中随机抽一个，排除原回复所选的字母和正确答案。用 `injection_seed` 和回复内容做种子，可以复现。
2. **分类任务的错误标签是"下一个标签"（循环）**：triage 会出现 ESI 5 变 1 这种跳跃。
   - 已改：有序数字标签改为相邻的一级（±1）；其他标签集在剩余标签中均匀抽取。两种情况都不会抽到正确答案。
3. 正确答案只用来保证篡改后的答案确实是错的，不会进入轨迹。
4. 篡改后的答案、所选模板变体等信息都记在标签侧的 `injection_process` 里。

## 5. 改写池试点（用户已同意做，按"先小批量试跑、再估算成本"执行）
- 脚本：`scripts/build_rewrite_pool.py`。每个模板调用一次 LLM，生成 30 个改写。
- 筛选规则（不通过的改写会被丢弃）：
  - 占位符与原模板一致，`{orig}` 的位置不变；
  - 不能写死答案（字母、数字、标签）；
  - MCQ 用 `mcq_answer` 解析，结果必须与原模板一致；
  - 长度在原模板的 0.4–3 倍之间；
  - 不能提到模拟、模板或注入。
- MCQ 的改写必须以明确的作答短语结尾（"the answer is X" / "Final answer: X" 等 8 种），这样各框架的解析器都能读到篡改后的答案。这类短语在正常回复里也常见，不构成捷径。
- 改写池按 backbone 分别生成（用哪个模型跑的轨迹，就用哪个模型的措辞）。工厂用 `template_pool`、`template_pool_model`、`injection_seed` 三个配置项启用。
- 试点范围：DIRECT_MCQ + CLASSIFICATION_FIELD，共 25 个模板，mercury 和 llama 各生成一份，实花 **$0.115**。
  - 改写数：mercury 697 条，llama 680 条。
  - llama 的 MCQ FM-1.4 三次都 0 条通过，原因是占位符不对；该模板会回退为原文。
- 文件：`docs/requests/samples/rewrite_pool_trial_2026-10-20.json`，每个列表的第 0 条是原模板。
- **全量**：7 张表共 89 个模板 × 2 个 backbone，估算约 **$0.26**，算上重试约 $0.35。**待用户批准。**
- 局限：改写去掉了固定措辞，但"结尾突然改口"这一结构特征还在（MHT 已指出）。
