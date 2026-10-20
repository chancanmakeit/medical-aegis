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

---

## 第 4 轮（2026-10-20）：用户问"试点 backbone"是什么意思

**解释**：
- **backbone**：驱动多智能体系统里每个 agent 的底层大模型。框架只规定"谁说话、看到什么、按什么顺序"，每个 agent 实际的输出由 backbone 生成。
- **试点**：在正式批量生成之前，先用真实 API 小规模跑一次。目的是估算成本、检查格式是否可解析、看截断率和准确率，跑完后停下来请用户确认。
- **为什么要用户决定**：backbone 会影响轨迹的错误分布、clean 运行的准确率（关系到 normal 和 error 两类样本的比例）、是否有单独的 reasoning 文本、成本，以及 HGFM 是否会学到"模型风格"而非"故障结构"这一混杂因素。
- 候选（来自 Project 的「api端点」文档）：deepseek-flash、qwen3.8-flash、glm-5.3-flash、mimo-v2.6-flash（MAM 的音频只能用它）、gpt-5.6-sol-disc（可取 logprobs）、claude-opus-5（贵）。此前建议：deepseek-flash + qwen3.8-flash，音频用 mimo。

---

## 第 5 轮（2026-10-20）：用户拍板 4 项；完成 schema v1 导出器和 K 次重复运行

**用户的决定**：
1. 下一步按推荐来：先做 schema v1 导出器和 K 次重复运行。
2. **backbone**：
   - 纯文本数据集与框架：aihubmix 的 `mercury-2.5-preview`；
   - 多模态（文本/图像/视频）：蚂蚁百灵的 `Ling-3.0-flash-VL`，端点 `https://api.ant-ling.com/v1/`；
   - 音频：`mimo-v2.6-flash`。
   - 新密钥只写进了沙箱本地的 `.mht_api.env` 和 Project 的「api端点」文档，没有进仓库。
3. **旧数据重跑**。这里指旧的 ClinicalAgent 注入数据：它的注入本身无效（从没跨过 0.5 阈值，而且用的是 MCQ 指令）。这和 MedHyperTrace 已经修好的"干净输入"是两回事。重跑排在 clinical_agent 迁移到 StructuredFMWrapper 之后。
4. **注入频率**：交给两个项目在 issue 里商定。本轮已在 issue 里提议 A 为默认、B 为可选子集。

### 交付 1：`main.py` 的 K 次重复运行
- 参数：`--num_runs K`、`--run_index_start N`。
- 每条记录写入 `run_index`、`question_id`（`<dataset>/<id>`）、`framework`、`dataset`、`model`（name/temperature/max_tokens）。
- 断点续跑按 `(id, run_index)`（`utils/utils.py`）；旧记录视为 run 0。`--limit` 按题目计数，同一道题的 K 次运行一起保留。
- K>1 且温度为 0 时打印警告。
- 实测：重复执行同一命令会跳过已完成的运行，`--limit` 选的是接下来的 N 道题（语义和以前一样）；`--run_index_start 2` 能给已有的题追加第 2、3 次运行。

### 交付 2：`scripts/export_schema_v1.py`（输出 mas-traj/1）
- step 字段走白名单，标签字段全部进 `labels.injection[]`。
- `labels.paired_normal_run_ids` 跨文件配对。
- `task.observations` 加 `task:obs:<id>` 引用。
- `final.answer` / `source_step_ids`。
- `provenance` 记录 wrapper 契约、输入是否干净、是否记录了 sources。
- 内置检查，`--strict` 时有问题直接失败。
- **`reasoning` 默认不导出**：被 prompt 注入的步骤，其推理文本几乎一定会提到注入指令，等于泄漏标签。`--reasoning keep` 时，注入步的 reasoning 移到 labels。
- `configs/framework_registry.yaml`：14 个框架的 family / modality / description。
  - **描述是对照代码核实后写的。**我先凭论文印象写了一版，核对后改正了 4 处。最重要的一处：按我们的配置（`debate_rounds: 1`），mdagents 的专家之间互相看不到答案。

### 方法侧补齐 v1.1 的 P0 项
- **medagents_mc**：
  - `agent_id`：q_expert_i / o_expert_j / question_classifier / option_classifier / synthesizer / reviser / decider；Voter 和 Advisor 沿用对应专家的 id。
  - `structured`：vote(YES/NO) + on_report_step；Advisor 带 responds_to_vote_step；Decider 带 answer；两个分类器带 domains。
  - `source_how` 标注完整。
- **ConSensus 系列**（`SensingMASBase`）：
  - `agent_id`：`modality:<name>` 或 snake_case 角色名。
  - `structured`：answer / confidence / parse_ok。
  - 特征块注册为 task observation；模态 agent 的 step 带 `observations`，后续轮次通过记忆继承。
- **MAM**：音频注册为 task observation。
- **StructuredFMWrapper**：把方法的 `task_observations` 写进日志。

### 验证（mock，零 API 费用）
- 8 个结构化框架 × clean/inject × 2 题 × K=2，共 64 条运行，**导出 0 个检查问题**。注入文本泄漏进 steps 的次数为 0。
- 读集检查全部 not_found=0、unlisted=0。medagents_mc 的 derived_unverifiable 从 0 变成 88，原因是这些引用现在显式标了 excerpt/structured_field，不再靠检查脚本里的特判。
- 旧版 llm_debate 的记录也能导出，会被标为 legacy。
- 新样例 `docs/requests/samples/schema_v1_mock_export.jsonl`（24 条）；原始 mock 样例已全部换成 K=2 版本。

### 我提出的问题：backbone 和模态完全重合
MedHyperTrace 的 spec §5 建议"至少两种 backbone 交叉"。按现在的分配，在文本类框架内部不存在模型和框架纠缠；但三组框架（文本/传感器、图像、音频）各自只见过一种模型，跨组做留一评测时，"换框架"和"换模型"分不开。已报告给用户，也已在 issue 里请 MedHyperTrace 评估。

### 下一步
1. **(b) 迁移旧 wrapper**：mdagents、clinical_agent、cmas，外加 dylan、llm_debate、agentverse 的注入开关。这是 ClinicalAgent 重跑和统一用方案 A 的前提。
2. **(c) 真实模型试跑**：用 mercury-2.5-preview 等模型小规模估算成本，**跑之前停下来请用户确认**。
