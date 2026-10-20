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

---

## 第 6 轮（2026-10-20）：用户新决定；6 个旧框架全部迁移到 StructuredFMWrapper

**用户的决定**：
1. cmas、dylan、llm_debate、agentverse：**只迁移和修复，暂不重跑**（它们不算严格意义上的医学多智能体系统；以后需要重跑时用户会再说）。
   - 我的理解：mdagents 和 clinical_agent 是医学专用框架，要重跑。已在 issue 里写明，请用户确认 mdagents 是否在重跑范围内。
2. **文本类 backbone 增加备选 `llama-4-maverick`**（aihubmix）。
3. 在 issue 里和 MedHyperTrace 沟通，听取对方意见。

**核实（只查了模型列表，没有产生生成调用）**：
- aihubmix 上有 `mercury-2.5-preview`、`mercury-2.5`、`llama-4-maverick`。
- 蚂蚁百灵端点可以访问，`Ling-3.0-flash-VL` 在模型列表里。

**issue #1**：
- 发了第 6 轮评论：用户决定；双 backbone 交叉方案；不重跑 4 个通用框架对锚点任务的影响。
- **读到 MedHyperTrace 第 25 轮（早于我们第 5 轮发出）**：
  - 确认 10 个 `framework_family`。名称已对齐为 `modality_fusion` 和 `triage`。
  - 建议锚点任务再加 macnet、autogen、camel 三个通用框架。
  - 他们建议的顺序是：导出器 → 在 medagents_mc 和 triage 上做真实试点 → 迁移旧 wrapper → 补通用框架。
  - 对旧 ClinicalAgent 数据：只用作无标签预训练，他们那边不需要重跑。
- **与用户决定的冲突**：MedHyperTrace 需要更多通用框架做锚点任务，而用户决定通用框架暂不重跑。已交给用户决定。

### 迁移（6 个框架，全部改用 StructuredFMWrapper，prompt 和控制流不变）
| 框架 | 新 wrapper | 方法侧要点 |
|---|---|---|
| mdagents | `fm_mdagents_structured_wrapper` | agent_id 为 recruiter / expert_i / aggregator 等。专家读 Recruiter 的专长描述，标 structured_field。图片注册为 task observation（`image_k`）。`build_sample` 带上 `image_paths`：方法显式传 `images=`，不带的话专家会拿不到图片 |
| clinical_agent | `fm_clinical_agent_structured_wrapper` | placeholder 工具记为 `is_tool` 步骤（`tool:<name>`，stub），lane 读这些工具步骤。structured 字段：score、failure_probability、predicts_failure |
| cmas | `fm_cmas_structured_wrapper` | 检索到的示例注册为 task observation（`demonstrations`）。structured 字段：trfs / scores / entities |
| llm_debate | `fm_llm_debate_structured_wrapper` | 每个 agent 一个累积对话，读取集为"自己的历史 + 历史读过的 + 对手上一轮"。round 从 1 开始 |
| dylan | `fm_dylan_structured_wrapper` | 角色名不变（节点角色名，`role_index = idx % num_agents`）；Ranker 为 `(num_agents)`。peer_scores 按 agent 看到的打乱顺序映射回 step。`final_source_step_ids` 为与最终答案一致的步骤 |
| agentverse | `fm_agentverse_structured_wrapper` | **角色在调用处显式设定**（旧 wrapper 靠关键词猜，例如 prompt 里有 "assessment" 就当成 Evaluator）。读取集按对象身份精确映射：共享 history 的每条记录都对应产生它的步骤 |

- 旧 wrapper 文件加了 DEPRECATED 标记，只用于复现旧数据；已没有 YAML 引用它们。
- 新增 `methods/answer_parsing.py` 的 `mcq_answer`：取回复中最后一个明确的答案表述，结尾在犹豫时返回 None。对工厂的 14 个 MCQ 篡改模板逐一测试，全部解析成篡改后实际声明的答案。

### 迁移中发现并修复的问题
1. **ClinicalAgent 的 Planner 是断开的**：解析出的子问题从来没有传给 lane agent。对照上游（lingyue404/clinical-agent，`algo/solve_problem.py`），每个子问题都应该驱动一次 agent 调用。**已恢复**：每个 lane 收到自己的子问题（先按关键词匹配，否则按顺序），Planner 成为真正的上游节点。**这会改变 clinical_agent 的行为**；它本来就要重跑，所以在重跑前修正。
2. **共享 wrapper 的潜在 bug**：方法按位置传 `messages`（AgentVerse 的 `call_llm(None, None, msgs)`）时，prompt 注入会把 `prompt` 传两次，导致崩溃。已在 `_inject_into_call` 里先把位置参数转成关键字参数。
3. **CMAS 的两个 YAML 指向不存在的 `configs/config_ner.yaml`**：迁移前就跑不起来。已改为 `methods/cmas/configs/config_ner.yaml`。mdagents、clinical_agent、dylan 的 YAML 原本指向 DyLAN 的根配置（无害但容易误导），也已改为各自的方法配置。
4. **导出器**：
   - 没有轨迹的错误记录现在会跳过并报告，不再导出成空记录。
   - 是否属于结构化契约，改为从记录本身判断，不再看框架名。迁移后，同名框架的旧数据仍会被标为 legacy。
5. **读取集检查脚本**：excerpt 探针支持去掉 XML 标签（ClinicalAgent 的 `<subproblem>`）以及 `Label:` 之后的值（AgentVerse 的 `Response:`）。

### 已知但未改动（如实记录）
- **AgentVerse**：只要有一个 critic 不同意，3 轮 criticizing 都会跑完，因为 `nonempty_reviews` 从不重置。另外，配置里的 `role_assigner_advice` 在第 1 轮会以 `[Evaluator]` 消息的形式进入历史。两点都写进了 `framework_description`。
- **DyLAN**：答案是整段回复，共识按 BLEU ≥ 0.9 判定（原版开放式模式）。`structured.answer` 用 `mcq_answer` 作为语义层。
- **NER 注入仍回退到 MCQ 模板**（例如篡改后输出 "A."），按用户之前的决定暂不处理。Evaluator 一类角色被套用 MCQ 篡改模板，在语义上也不太合适，这也是旧行为。

### 全量 mock 回归（零 API 费用）
- 14 个框架 × clean/inject × 2 题 × K=2，共 112 条运行。
- 所有框架的对齐、干净输入、`llm_meta`、`agent_id` 都是 100%。读取集检查 unlisted=0。
- not_found 只出现在 agentverse_inject，共 20 处，**全部来自同一个情况**：被篡改成 "A." 的 evaluator 输出太短，低于探针最短长度。读取集本身是对的。
- 导出 112 条，0 个问题。60 个被 prompt 注入的步骤中，注入文本出现在 steps 里的次数为 0。
- 新样例：`schema_v1_mock_export.jsonl` 共 42 条，覆盖 14 个框架和 10 个家族；原始 mock 样例全部换新。

---

## 第 7 轮（2026-10-20）：mdagents/clinical_agent 是否重跑；为什么要跑通用框架；首次真实模型探测

**用户**：
1. 现有数据对应的 mdagents 和 clinical_agent 需要重跑吗？
2. 锚点任务与"通用框架不重跑"的冲突按推荐处理（通用框架只跑锚点任务）；但不理解为什么要跑通用框架。
3. 可以开始真实试跑。

### 1. 重跑建议
- **clinical_agent：要重新生成。** 旧数据的标签有三处问题：
  - MedHyperTrace 实测，全部注入都是 direct_prepend 的轨迹占 38% / 58%（ca / ca5），这些注入在 probability 任务上基本无效；
  - Planner 是断开的（第 6 轮已修复），所以注入到 Planner 的标签必然是错的；
  - 没有 normal 运行，也没有 K 次重复运行。
  - 数据来源已找到：HF `UUUooUUU/clinical-agents` 里有 `trial_success-200.json` 和完整版，不需要再找用户要 csv。
- **mdagents：不重跑旧配置，保留旧数据，另外按新流程生成新数据。**
  - 旧的注入是 mcq 类型，有效；旧 wrapper 默认只注入一次；干净输入已由 MedHyperTrace 修复。
  - mdagents 的拓扑很简单（专家只读 Recruiter，aggregator 读所有专家），读取集可以从角色确定性地恢复。
  - 但新数据无论如何都要生成：旧数据缺 normal 运行、K 次重复、llm_meta、新 backbone，也缺锚点任务的覆盖。
  - MedXpertQA-MM 的图片仍需用户提供，多模态部分用 Ling-3.0-flash-VL。
  - 旧数据集（AEGIS-custom-dataset-8-13）不在用户的 HF 账号下，无法直接复核。以上判断依据的是 MedHyperTrace 的实测数字，以及本会话核实过的代码事实。

### 2. 为什么要跑通用框架（通用框架只跑锚点任务）
- HGFM 要证明的是"**跨框架**零样本归因"。主要证据是：见过的框架越多，在没见过的框架上效果越好（按家族留一）。
- 医学专用框架几乎各自绑定自己的任务：triage 是分诊，clinical_agent 是试验预测，mam 是音频，consensus 是传感器。所以在原生任务上，"换框架"和"换任务"分不开。
- 锚点任务把任务固定成同样 100 道医学 MCQ，只变化拓扑。能跑医学 MCQ 的医学专用框架只有 mdagents 和 medagents_mc 两个家族，一条曲线只有 2 个点。
- 通用框架跑的仍然是医学题，相当于"把通用拓扑部署到医学任务上"。很多已发表的医学 MAS 本质上就是这样：MedAgents 近似专家共识，辩论也常用于医学 QA。所以领域焦点没有变，通用框架提供的是拓扑多样性。
- 如果只想要医学专用框架，替代方案是：放弃锚点任务上的缩放曲线，在约 7 个医学家族的原生任务上做留一评测，并在论文里承认框架与任务的混杂。代价是"跨框架泛化"的结论会变弱。

### 3. 首次真实模型探测（成本估算用）
- 范围：medagents_mc 和 triage_agent × mercury-2.5-preview 和 llama-4-maverick，各跑 1 道题，只做 clean，K=1，温度 0.7，max_tokens 4096。共 4 条运行、62 次调用。
- **结果**：
  - 62 次调用全部 `finish_reason=stop`，没有空 content；投票、ESI 等级、置信度全部解析成功。
  - triage 两个模型都答对；medagents 的那道 ICD 题两个模型都答错。只有 1 题，不能当准确率看。
  - **mercury 是隐藏推理的模型**：completion token 中 89% 是计费的 reasoning token，但不返回推理文本（`llm_meta.reasoning` 为 null）。所以虽然标价更低，实际成本反而高于 llama。
  - 每次运行的成本按第三方列表价估算（mercury $0.20/$0.75，llama $0.27/$0.85，单位为每百万 token；aihubmix 的实际价格可能不同）：
    - medagents_mc：mercury $0.029，llama $0.011
    - triage：mercury $0.013，llama $0.0026
    - 4 条合计约 $0.056。
- **真实数据暴露的问题（mock 发现不了）**：
  1. **导出器的 `run_id` 跨 backbone 冲突**：同一题、同一 run_index，换模型后 run_id 相同。已把模型名加入 run_id。
  2. **读取集检查脚本在真实数据上报了 13 处 unlisted，全部是误报**：
     - 8 处是传递复制：Reviser 原样引用了 Synthesizer 的文字，而 voter 读的是 Reviser；
     - 5 处是模板撞车：OptionAnalyst 的输出以 "As a medical expert specialized in …" 开头，和 voter 的 prompt 模板相同。
     - 读取集本身是对的。检查脚本已改为从输出正文中段取探针，并排除被已登记来源转载的文字。
     - 用"人为删掉一个真实来源"做反向测试：真实数据上能正确报出（triage、medagents_mc 各 1 处）。mock 的 llm_debate 上报不出，原因是 3 个辩手第 1 轮的输出完全相同，本来就无法区分。
- 样例：`docs/requests/samples/real_probe_2026-10-20/`（4 条原始记录和 schema v1 导出），已确认不含密钥。

### 试点方案（待用户确认成本）
- MedHyperTrace 建议的规模：medagents_mc 和 triage × 2 个 backbone × 20 题 × (K=4 normal + 1 inject)，共 400 条运行。
- 按探测的单价估算约 **$5.6**。medagents 的调用次数在 18 到约 50 之间（最多 3 轮投票），加上 aihubmix 价格的不确定性，**估计区间 $6–12**。

---

## 第 8 轮（2026-10-20）：用户问"你跟 MedHyperTrace 沟通了么"

**核实 issue #1 的时间线（UTC）**：
- 15:47 MedHyperTrace 第 25 轮。这是对方的最新一条，发在我方第 5 轮之前。
- 我方之后发了 4 条：15:55 第 5 轮、16:39 第 6 轮、17:02 第 6 轮（续）、18:10 第 7 轮。
- **对方还没有回复这 4 条。**
- 两个会话之间是异步的：MedHyperTrace 会话只有在用户运行它时才会读 issue、才会回复。

**对方已表态的**（第 25 轮及 spec v1）：
- 10 个家族；
- 锚点任务需要更多通用框架；
- 试点先做 medagents_mc 和 triage；
- 倾向于方案 A。

**仍未回复的**：
- 双 backbone 怎么交叉；
- 不重跑通用框架对缩放曲线的影响（用户已决定只跑锚点任务）；
- Planner 断开对旧 ClinicalAgent 数据的影响；
- 4 条真实样例的格式和泄漏检查结果。

**建议**：400 条运行的试点先等对方核对完这 4 条真实样例再跑，避免格式要改时白跑。

---

## 第 9 轮（2026-10-20）：MedHyperTrace 第 26 轮回复，逐条落实

**对方的回复（issue #1，第 26 轮，回应我方第 5、6、7 轮）**：
1. **注入频率定案**：默认用方案 A，方案 B 只用于单独生成的鲁棒性子集。旧数据中 dylan 和 llm_debate 是按 B 生成的，他们会以最早的注入步作为责任步，并且不和新数据混在一起评测。
2. **双 backbone 交叉方式同意我方方案**：锚点任务上完全交叉；原生任务用主 backbone 全量跑，llama 每个框架抽 20 题；图像组和音频组接受"模态与模型重合"并在报告中标注。另有两条建议：
   - MAM 和 mdagents 中的纯文本步骤可以改用文本 backbone；
   - 各 backbone 的 inject 与 normal 比例要保持一致。
3. **锚点任务**：家族数需要补到 8 个。建议再加 macnet、autogen、camel，同样只跑锚点任务，待用户决定。
4. **response_corruption 步骤的 token 数会泄漏**：mock 上每 token 字符数为 10.06，其他步骤为 7.10。建议把 API 报告的 token 数移到 labels，step 上改用固定 tokenizer 重新计数。
5. **独立审计**：14 个框架都通过了白名单、泄漏、来源和漏记检查。统一轨迹超图已能直接从 mas-traj/1 构建，不需要任何框架专用代码。
6. **纠正我方第 6 轮的说法**：Planner 断开**只发生在 clinical_agent5**（0/1052）。6 agent 版的旧数据里，397/402 条的 Planner 被 orchestrator 读到了。我方第 6 轮核对的是仓库现行代码，也就是 5 agent 版，所以修复本身没问题，但"旧数据里 Planner 是断开的"这个说法应限定在 clinical_agent5。
7. **event_ids**：对方按"同一 (phase, round) 算一个事件"自行派生，请我方指出哪些框架里同一轮的步骤不应算作同一事件。
8. **试点**：设计可行。希望 inject 部分同时包含 RC 和 PI 两种策略。

**本轮落实**：
- **导出器**：API 报告的 token 数从 step 移到 `labels.llm_meta[step_id]`；每个 step 新增 `output_tokens_est`，用 tiktoken `o200k_base` 从存储的 output 统一重新计数，tokenizer 名称写在 `provenance.output_tokenizer`。检查器把 token 字段也列为禁止出现在 step 上的标签键。
  - 复核：用统一 tokenizer 后，每 token 字符数 RC 为 3.56，其他步骤为 2.88。这个差异来自**文本本身**：mock 的普通输出里有十六进制摘要，分词效率低；篡改模板则是普通英语。它已不是元数据侧信道，但说明 direct_prepend 的篡改模板在文风上可以被识别。这一点已提醒对方。
- **consensus_cmd**：每轮辩论里的 agent 被随机分成 2 组，组内互读全文，组间只能看到答案计数。step 的 `event_ids` 由 `["debate<k>"]` 改为 `["debate<k>", "debate<k>_group<g>"]`。mock 回归通过，读取集检查为 0 问题。
- **mdagents**：新增可选的 `mdagents_text_model_name`，默认关闭，让 Recruiter 和 Classifier 这两个不看图的角色改用文本 backbone。mock 验证：recruiter 的 `llm_meta.model` 为文本模型，专家和 aggregator 仍用原模型并带图。
  - MAM 原本就有 `mam_text_model_name`，而且上游本身就是文本模型和音频模型分开，所以给 MAM 的文本步骤用文本 backbone 反而更忠实于原版。
  - **是否启用这两项，需要用户决定**：（更正，见第 10 轮：用户从未规定"一个模态对应一个 backbone"，这是我的误述。）
- 样例已更新：mock 导出、真实探测导出、consensus_cmd 的 mock 原始样例。

---

## 第 10 轮（2026-10-20）：用户决定；试点开跑；三个候选通用框架的核实结果

**用户**：
1. 锚点任务加入 macnet、autogen、camel（按推荐）。
2. **更正**：用户**从未要求"一个模态对应一个 backbone"**。用户给的是一个候选池，包括多模态和全模态大模型，Claude 可以视情况选用，**但每次使用前都必须先问用户**。
   - 这是我的误述。已更正 framework_registry 的注释、HANDOFF、讨论记录，以及 Project 的「api端点」文档。
3. 试点可以开跑。

### 试点（11:49 开始，后台运行）
- 数据：`datasets/data/pilot/`，种子 20261020。从 mmlu_pro_health（818 题，由 HF TIGER-Lab/MMLU-Pro 新转换）中抽 20 题，从 triage_esi 中抽 20 题；每个框架的前 10 题用于 PI，后 10 题用于 RC。
- 注入配置：`experiments/fm_injection/pilot/`。
  - medagents_mc 的目标是 Synthesizer(0)。已确认篡改文本在 cleansing 后仍保留在报告里。
  - triage 的目标是 Doctor(1)，phase classify。
  - 两者都用 FM-2.3、direct_prepend、方案 A。两个 backbone 用完全相同的配置。
- 运行：每个框架、每个 backbone 跑 20 题 × K=4 的 normal，加 10 题 PI 和 10 题 RC，合计 400 条运行。参数为温度 0.7、max_tokens 4096、4 个 worker；4 组并行。
- 运行器只放在 scratch（密钥在权限 600 的 scratch YAML 里）。

### 三个候选通用框架的核实（对照代码，MedHyperTrace 的假设有偏差）
- **autogen**（MASLab 版）：**不是**群聊加管理者动态选发言人，而是 AssistantAgent 与一个 LLM 驱动的 UserProxy 的两人对话。assistant 的 prompt 要求做完就回复 "TERMINATE"，所以在 MCQ 上**通常第一条回复就结束**，轨迹只有 1 次 LLM 调用，是退化拓扑。
- **camel**（MASLab 版）：
  - 自带一个 `call_llm`，绕过了重试、extra_body 和 llm_meta，出错时直接返回 None；
  - 第一步的 task specifier 会**改写用户的任务**，在 MCQ 上可能把题目本身改掉；
  - 返回的是整段对话记录，不是答案。
  - 能改造，但不如预期干净。
- **macnet**（MASLab 版）：**数据流与上游不符**。对照上游 OpenBMB/ChatDev macnet 分支的 `graph.py`：
  - 上游：每条边 u→v 上，由后继 v 针对 u 的方案做 critic + optimize；v 把各条边的结果聚合成自己的方案，**再传给下游**；最终答案是输出节点的聚合方案。
  - 本仓库的 port：每个节点对拼接起来的所有前驱答案只做一次交互；**中间节点的聚合结果写进 `generated_answer` 后无人读取**；输出节点自己的 critic/actor 调用结果被丢弃。
  - 结论：macnet 拓扑本身值得接入，但需要**按上游语义重新移植**（从代码生成改成文本答案），不能直接包装现有 port。
- **可替代 autogen/camel 的候选**：`mav`（Multi-Agent Verification）。多个 solver 独立作答，多个 aspect verifier 分别对每个方案打赞成或反对，选得分最高的方案。这是现有家族里没有的"生成者–验证者"二部拓扑，而且仓库里带 MMLU 版本。
- 已向用户和 MedHyperTrace 报告，待决定。

## 第 11 轮（12:06）
**用户问题**
1. 现有框架代码是否支持并行 worker？
2. MedHyperTrace 在 issue 里回复了锚点任务的建议。

### 回复 1：并行
- 已支持样本级并行：`main.py` 用 ThreadPoolExecutor 处理样本，参数为 `--max_workers`（默认 10）。
- 线程安全依据：
  - 每个样本独立构建 wrapper 和 MAS 实例；
  - `llm_meta` 是 thread-local；
  - `write_to_jsonl` 加锁；
  - 断点续跑按 `(id, run_index)` 去重。
- 同一样本内的调用串行，这是有意为之：要保证调用顺序和 step_id 确定。
- 当前试点用 4 组进程 × 4 worker，共 16 路并发，没有出现 429 或重试失败。
  - medagents_mc 约 26 s/样本（4 worker）；
  - 任务受 I/O 限制，容器只有 2 核也不是瓶颈。
- 正式跑数时可把单进程 worker 提到 8–16，多组合并行，按服务商限流调整。

### 回复 2：MHT 第 27 轮建议（issue comment 6298762272）
- token 修复通过。event_ids 已采纳：自带 event_ids 的记录不再重新推导。
- **主要风险**：注入模板的风格捷径。他们的模板检测器在 ca5 上准确率 0.90。建议为每个模板用 LLM 一次性改写出一个池子。
- **锚点家族 6–8**：
  - macnet：按上游语义重新移植；
  - mav；
  - camel：改用共享 `call_llm`，约束 specifier 不改题干和选项，从对话记录里解析答案。
  - 不用 autogen，magnetic_one 作备选。
  - 锚点合计 8 个家族：mdagents、medagents、dylan、debate、agentverse、macnet、mav、camel。
- 建议启用 `mam_text_model_name`（mdagents 的文本模型可选），需用户确认。
- 待用户决定：上述锚点家族、MAM/mdagents 文本 backbone、改写池（需要调 API，届时先估算成本）。

## 第 11 轮（续，13:05）：试点完成
- 后台任务结束，400 条运行全部跑完，用时 69 分钟。按列表价估算约 $4.50。完整报告：`docs/pilot_2026-10-20_report.md`。
- **mercury 的 PI 全部失败（20/20）**：aihubmix 返回 403，原因是 Inception 上游拦截 `[UPDATED INSTRUCTION ... SUPERSEDES]` 这种覆盖式写法。已新增 `simulation` 包装（如实说明是研究模拟中的角色犯错），mercury 实测 2/2 通过，输出被带偏，也没有提到注入。**重跑约 $0.6，待用户批准。**
- **MedAgents 对 Synthesizer 注入会自我纠正**：注入后第 1 轮所有人都投 NO，修订后第 2 轮全票通过，翻转 0/30。normal 运行 160/160 在第 1 轮就通过，因此"有没有第 2 轮"几乎能完美区分注入与否（拓扑侧信道）。换注入目标或换更难的题，待 MHT 和用户商定。
- triage：PI 能让 Doctor B 10/10 出错，但最终翻转 0/10。RC 的翻转是 llama 3/10、mercury 1/10。
- 读取集修复：medagents 的 Reviser（建议按专科名称覆盖）。检查脚本已改；导出器会跳过 API 失败的运行。修复后 12 个文件全部 not_found=0、unlisted=0；导出 380 条，泄漏 0。

## 第 12 轮（13:12）
**用户建议**
1. 如果锚点加入新的医学框架 MA-RAG（NJU-RL）和 MDTeamGPT（KaiChenNJ，配 HF collection 里的 SLAKE），能否不集成 camel 这类通用框架？
2. mercury 按推荐跑。
3. MAM 和 mdagents 的纯文本步骤统一用多模态模型，例如 mimo-v2.6-flash 或 gemini-2.5-flash-lite-nothink。
4. 改写池按推荐做。

**结果与回复**
- (2) simulation 包装的 PI 补跑完成，40/40 成功，约 $0.60。medagents 翻转 1/10（两个 backbone 各一次），triage mercury 翻转 2/10。
- (4) 改写池脚本和工厂支持已完成。试点覆盖 25 个模板 × 2 个 backbone，花 $0.115；全量估算约 $0.26–0.35，待批准。
- 顺带修复：MCQ 的 RC 一直固定篡改成 "A"；ESI 用循环的"下一级"。细节见 `docs/pilot_2026-10-20_report.md` 第 4 节。
- (1) 子 agent 读代码评估的结论：
  - MA-RAG 在拓扑上约等于 llm_debate 加一个检索/查询节点；
  - MDTeamGPT 约等于 medagents（专科医生 → 主治总结 → 安全审查收敛）；
  - 都替代不了 mav（生成者与验证者的二部结构）和 macnet（DAG）。
  - SLAKE 是开放式 VQA，要用图像，不能放进 100 题的文本锚点，只适合作为图像数据集。
  - 建议见回复正文。
- (3) 回复要点：
  - MAM 上游的文本模型（Medichat-Llama3-8B）和音频模型（Qwen-Audio）是两个不同的模型，保真的关键是两者不同，而不是文本模型能不能处理多模态。文本也用 mimo 就等于不启用。
  - gemini-2.5-flash-lite-nothink 目前在 aihubmix 上不可用，gemini-2.5-flash-lite 可用。
  - mdagents 上游所有 agent 用同一个模型，所以建议不单独设文本模型，全程用同一个多模态 backbone。
