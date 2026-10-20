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
