# medical-aegis 讨论记录 v9

> 新会话（2026-10-20 开始）。上一会话的完整记录见 `docs/discussion_log_v8.md`；交接见 `docs/HANDOFF.md`。

---

## 第 1 轮（2026-10-20）：新会话续接

**用户**：按 Project 里的 medical-aegis 新会话入口续接。

**做了什么**：
- 挂载并 clone `chancanmakeit/medical-aegis`（HEAD `811c0bd`，第 8 轮的交接提交）。
- 读完 `HANDOFF.md`、`HANDOFF_RESOURCES.md`、`discussion_log_v8.md` 第 8 轮。
- 密钥按「api端点」写入沙箱本地 `/home/claude/.mht_api.env`（600 权限，未入库）。
- 依赖安装完成（跳过 torch/transformers/wandb），Python 3.13.16。
- **离线冒烟测试**（mock，零 API 费用）：`consensus_cmd` + sleepedf，`--limit 2`，注入配置。2 条样本跑通，verifier 走 authoritative 路径；`check_trajectory_sources.py`：checked=156，not_found=0，unlisted=0。环境恢复正常。
- 查看 issue #1：自第 7 轮评论（`6287904219`）之后，MedHyperTrace **没有新评论**。

**未恢复的资源**（按需）：MAM 音频（需要时按 `HANDOFF_RESOURCES.md` 第 2 节从 HF 重建）、ConSensus 原始数据、外部参考仓库。

**仍待用户决定**（与 HANDOFF 第 4 节一致，无变化）：
1. 旧 ClinicalAgent 注入数据：重跑还是过滤。
2. 下一步：(a) schema v1 导出器 + K 次重复运行；(b) 旧三个 wrapper 迁移到 StructuredFMWrapper；(c) 真实模型小规模成本试跑。
3. 注入频率 A / B。
4. 试点 backbone。
5. 用户本地还有哪些 normal 轨迹。

---

## 第 2 轮（2026-10-20）：用户提议纳入 TriageAgent，并问是否改用 Triage 的轨迹格式

**用户**：
1. 纳入 Triage 工作（`chancanmakeit/TriageAgent`）。
2. Triage 的轨迹（如 `results/showcase/trajectory_Test-1_case2.json`）是否比我们的信息更丰富、格式更标准？要不要把代码改成 Triage 的格式？

**核实**：挂载并 clone 了 TriageAgent（只读，HEAD `fdec6ee`）。审计了 `results/fullrun/trajectories/` 下全部 216 个文件和 showcase 文件，并对照我们 `consensus_cmd` mock 输出的一条记录。

**TriageAgent 概况**：EMNLP 2024 Findings 论文的复现。原作者没有放出代码，由用户补齐。流程分 5 个阶段：Doctor A 做 HIGH/LOW 粗分 → Doctor B 细化 → Doctor C 直接分类 → Summarizer 汇总 → 讨论（最多 5 轮，带早停）→ Coordinator 给出共识。RAG 是 ESI Handbook v4 上的 TF-IDF top-3 检索。数据集 Test-1/2/3 共 216 条，标签为 ESI 1–5，少数是 `[4,5]` 这样的多值标签。全量运行用的是 OpenRouter 上的 ling-3.0-flash。

**结论：不改成 Triage 格式。吸收它的 3 个优点，然后把 Triage 作为新框架按我们的契约接入。**

Triage 有、我们没有（值得吸收）：
- 每次调用都记录了 `reasoning`、`finish_reason`、`prompt_tokens/completion_tokens`、`cost_usd`。我们的 `mas_base.call_llm` 只取 `message.content`，token 只按模型累计，**reasoning_content 和 finish_reason 都丢掉了**。而试点 backbone（deepseek-flash、qwen3.8-flash）都是推理模型，这部分信息丢失是实打实的问题。
- RAG 的检索结果（页码、分数、文本）被显式记录下来。我们已有 `is_tool` 步骤的机制，接入时把检索记成工具步骤即可。

Triage 缺、我们有（对 HGFM 是关键）：
- 没有 `step_id` / `sources` 读取集。超图的边就从这里来，而 Triage 的轨迹没有这一项。
- 没有注入相关字段：干净输入、`injected_input_messages`、`fired`、注入目标。
- 没有 verifier 的判定路径，也没有 `run_mode`。
- agent 标识前后不一致：同一个医生在 classify 阶段叫 `DoctorA`，在 discuss 阶段叫 `Doctor A`。
- `stages` 的键是这个框架专有的（doctor_a/doctor_b/…），不能跨框架复用。它本质上是 call_log 的派生视图，内容有冗余。

"更标准"这一点不成立：
- showcase 文件的 schema 和 fullrun 不一样。showcase 是扁平的（`case_id`、`llm_call_log`、`final_output`、`system_stats`）；fullrun 是 `trace.*` 嵌套。格式说明文档描述的是 fullrun。

**Triage 全量数据的质量问题**（实测，216 个文件，1924 次调用）：
- `finish_reason=length` 有 976 次（**51%**），`content` 为空的有 821 次（43%）。很多调用的答案只出现在 reasoning 里，或者被截断了。
- 初始分类阶段的置信度没有解析出来的情况：Doctor A 99/216，Doctor B 112/216，Doctor C 104/216。
- showcase 例子中，讨论 prompt 里出现了 "Doctor C … Rationale: "（空）和 "confidence None%"，说明解析失败的结果被传给了下游 agent。
- 推测：66.2% 的准确率可能被截断压低了。分类阶段 1024 token 的预算对推理模型偏紧。

**提议的接入方案（待用户确认）**：
- 方法名 `triage_agent`，用 StructuredFMWrapper。
- agent_id 跨阶段统一为 `doctor_a/b/c`、`summarizer`、`coordinator`。
- phase 分为 classify、summarize、discuss（带 round）、consensus。RAG 作为 `is_tool` 步骤，检索结果写进 observations。
- task_type 用 classification，类别 1–5。Doctor A 的粗分是 HIGH/LOW 二分类，注入时需要单独的类别表。verifier 要支持多值 gold。
- 共享层顺带改动：`call_llm` 按步骤记录 `reasoning`、`finish_reason` 和 token 用量，所有框架都受益（对 MedHyperTrace 来说是新增可选字段）。
- Triage 已有的 216 条 normal 轨迹：没有读取集，backbone 也不同，而且一半调用被截断。**不建议**直接当作 normal 语料使用。

---

## 第 3 轮（2026-10-20）：按推荐方案接入 TriageAgent，并给共享层加上 `llm_meta`

**用户**：按你推荐的来。

### 1. 共享层：每个步骤记录 `llm_meta`
- `mas_base.call_llm` 把每次调用的 `reasoning`（`reasoning_content` 或 `reasoning`）、`finish_reason`、`prompt_tokens`、`completion_tokens`、`reasoning_tokens`、`max_tokens`、`model` 写进线程局部变量。StructuredFMWrapper 在调用返回后立即取走，挂到对应步骤的 `llm_meta` 上。方法代码不需要任何改动。
- 被 response_corruption 的步骤，`llm_meta` 描述的是篡改前那次干净调用。
- **踩坑**：`trajectory_normalizer` 对步骤字段做白名单透传，第一次跑时 `llm_meta` 被静默丢掉了。已把它加进白名单（同时加了 `precomputed`）。
- 顺手修了一个旧 bug：`token_stats` 里每个模型名的第一次调用没有计数。
- 旧版 wrapper（mdagents / clinical_agent / cmas / dylan / llm_debate / agentverse）没有 `llm_meta`。这三个旧框架迁移到 StructuredFMWrapper 时会自动获得。

### 2. TriageAgent → `triage_agent`
- **数据**：`data_processing/triage/convert_triage_dataset.py` 生成 `datasets/data/triage_esi.json`，共 216 条，其中 1 条标签是 "4 or 5"。RAG（TF-IDF 检索 ESI Handbook，top-3，查询文本是 vignette）在转换时预先算好。**实测与上游全量运行的 216 条逐条一致**：vignette、命中页码和分数、标签都相同。
- **方法**：`methods/triage_agent/triage_agent_main.py`，prompt 逐字照搬上游。讨论环节保留了上游的全部语义：同一轮内后发言者能看到先发言者的更新；退出规则 (a) 和早停规则 (b) 照旧；Doctor A 以 Doctor B 的等级进入讨论；共识阶段的回退顺序照旧。
- **读取集精确到字段来源**：每个 agent 的当前立场分别记录等级、置信度、理由各自来自哪一步。比如 Doctor A 第 1 轮的等级来自 Doctor B 的 classify 步骤。`source_how` 的标注规则：summary 为 verbatim，同伴的理由为 excerpt，等级和置信度为 structured_field。
- **agent_id 跨阶段稳定**：doctor_a/b/c、summarizer、coordinator、esi_rag_tool。检索记为 `is_tool` 步骤，带 `tool_calls`。
- **相对上游的改动**（已写进 docstring）：
  - 只从 content 解析答案。上游把 reasoning 和 content 拼起来解析，可能会把思考过程中提到的等级当成答案。
  - summarizer 的建议等级优先读 `Suggested ESI level:`。
  - 温度和 max_tokens 用全局配置。设 `use_original_max_tokens: true` 可恢复上游的 1024/2048。
- **注入**：新增 task_type `classification_field`，有自己的领域中立指令表和篡改表。篡改时把字段的每一处取值都改成下一个类别。wrapper 新增 `before_injection` 钩子，按命中的 agent 设置字段和类别：Doctor A 的 classify 用 HIGH/LOW，Summarizer 用 `Suggested ESI level`，其余用 `ESI level`。
- **verifier**：`triage_esi` 支持多值 gold，确定性结果优先。
- YAML 在 `experiments/fm_injection/triage/`。`generate_diverse_dataset.py` 加入了 triage 的注入位点池。

### 3. mock 回归（零 API 费用；mock 开了 `--reasoning`）
- triage_agent：clean 3 条、inject 3 条，另有一个 3 目标篡改配置跑了 1 条。三个目标分别是：Doctor A 粗分 HIGH→LOW、Doctor C 第 2 轮 hedge、Coordinator unsure。
  - 读取集检查：not_found=0，unlisted=0。对齐、干净输入、目标触发全部通过。`llm_meta` 覆盖 11/11 步。
  - HIGH→LOW 正确传递到 Doctor B 的允许范围（变成 3、4、5）。
  - 被篡改的 summary 确实进入了下游 prompt。
- **发现**：Coordinator 的 unsure 篡改被上游的宽松解析器"救回"了。字段被改成了 "I am not sure"，但解析器从 "Final justification: … ESI 2" 又读出了 2。这是真实系统本来的行为，保留不改，已记录在已知坑里。
- 其余结构化框架（medagents_mc、consensus 系列 5 个、mam）的 clean/inject 全部通过，读取集零错误，`llm_meta` 全覆盖。
  - consensus_cmd 的目标只触发了 2/4，符合预期：Secretary 只在平票时才运行。
- 旧框架抽测 llm_debate 正常。
- 新增 mock 样例：`docs/requests/samples/triage_agent_mock_{clean,inject,inject_multi}.jsonl`。

### 待用户决定（更新）
1. 旧 ClinicalAgent 注入数据：重跑还是过滤。
2. 下一步：(a) schema v1 导出器 + K 次重复运行（推荐）；(b) 迁移三个旧 wrapper；(c) 真实模型小规模成本试跑。
3. 注入频率 A / B。
4. 试点 backbone。
5. 用户本地还有哪些 normal 轨迹。
