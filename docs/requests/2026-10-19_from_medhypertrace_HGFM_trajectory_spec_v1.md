# 来自 MedHyperTrace 项目的轨迹需求 v1（2026-10-19）

**发件方：** MedHyperTrace 会话（仓库 `chancanmakeit/Medhypertrace`，第 23 轮）
**收件方：** medical-aegis 会话
**用户的统筹安排：** 轨迹语料（模拟故障 + 真实故障）由 medical-aegis 负责；MedHyperTrace 负责故障归因方法。本文说明方法侧需要什么、为什么，以及需要 medical-aegis 回答的问题。
**沟通方式（用户要求两项目走 issue）：** 讨论与回复请在 [issue #1](https://github.com/chancanmakeit/medical-aegis/issues/1) 下评论；本文是该 issue 引用的完整规格，规格有修订时升版本号（v2…）并在 issue 中说明。需要用户拍板的事项请标"待用户决定"。

---

## 1. 方法侧在做什么

用户定的主线是训一个**超图基础模型（HGFM）**：把每条 MAS 轨迹建成文本属性超图，自监督预训练，再微调做故障归因（哪个 agent、哪一步），要求**跨 MAS 框架零样本**，新框架最多做轻量 adapter 适配。设计草案见 Medhypertrace `docs/design/HGFM_design_v0.1.md`。

这对语料提出三点和以前不同的要求：

1. **框架数量比单框架样本数更重要。** "基础模型"的核心证据是"见过的框架越多，在没见过的框架上越好"的缩放曲线，并按留一框架评测。目前只有 5 个医学框架，至少需要 8 个，越多越好。
2. **需要成功轨迹和自然失败轨迹，不只是注入轨迹。** 最有价值的两个自监督目标需要它们：一是结果预测（这条轨迹答对还是答错），二是成对分歧定位（同一题多次运行，对齐成功和失败轨迹，把首个分歧步当伪标签）。现有数据集 `AEGIS-custom-dataset-8-13` 只有注入后的失败轨迹。
3. **需要每次 LLM 调用的真实输入，以及它引用了哪些前序步。** 超图里最主要的超边是"读集超边"：这一步的输入里放进了哪几条前序输出。

## 2. 我们在现有数据上核对到的事实（可复现）

脚本：Medhypertrace `analysis/read_hyperedge_stats.py`，作用于 `AEGIS-custom-dataset-8-13`。

| 框架 | 中位 LLM 步数 / agent 数 | 读到 ≥1 个前序步 | 读到 ≥3 个前序步 | agent 步缺 `input_messages` |
|---|---|---|---|---|
| dylan | 10 / 4 | 63% | 62% | 0% |
| llm_debate | 7 / 4 | 67% | 38% | 0% |
| clinical_agent | 6 / 6 | 38% | 20% | 0% |
| clinical_agent5 | 5 / 5 | 25% | 24% | 0% |
| mdagents | 7 / 3 | 17% | 17% | 0% |

（只统计 LLM 调用步，不含 `is_input=True` 的 User 提示条目。"读到"用分片子串匹配近似，是启发式的，模型改写过的引用会漏。）

**问题 A：注入指令泄漏进了记录的输入。** prompt_injection 步骤里，记录下来的 `input_messages` 含注入指令原文的比例如下：mdagents 748/748，clinical_agent 245/245，clinical_agent5 638/638，dylan 1317/1336，llm_debate 1238/1927。dylan 和 llm_debate 另存了 `original_input_messages`，但 **mdagents、clinical_agent、clinical_agent5 没有保存注入前的原始输入**。归因模型如果读调用输入，会直接看到答案。

**问题 B：标签字段和轨迹内容混在同一个 step 对象里。** 例如 `injection_applied`、`fm_error_type`、`prompt_modified`、`clean_response_before_corruption`、`injection_description`。下游每个使用者都必须记得剥掉它们，漏一个就是泄漏。

**问题 C：读集靠事后子串匹配恢复。** 改写、摘要过的引用会漏，而且只要两步输出有相同前缀就会误连。在拼 prompt 的那一刻记录来源，成本几乎为零。

## 3. 我们需要的轨迹格式：统一 schema v1（建议）

原则如下：

- 一条记录对应一次完整运行。
- **轨迹内容**（`steps`）和**标签**（`labels`）物理分开。
- 每次 LLM 调用一个 step。
- 每个 step 带"干净输入"和"来源"。

```json
{
  "schema_version": "mas-traj/1",
  "run_id": "mdagents|medxpertqa-text|Q123|normal|seed3",
  "question_id": "medxpertqa-text/Q123",          // 跨运行配对用，同一题的所有运行必须相同
  "run_mode": "normal | inject",
  "run_index": 3, "seed": 3,
  "framework": "mdagents",
  "framework_description": "自然语言描述：有哪些角色、谁能看到谁的输出、几轮、如何汇总（2–5 句，每个框架写一次即可复用）",
  "model": {"name": "deepseek-flash", "temperature": 0.7, "max_tokens": 4096},
  "task": {"dataset": "medxpertqa-text", "query": "...", "options": {"A": "..."}, "images": []},

  "steps": [
    {
      "step_id": "s3",
      "order": 3,                                   // 全局时间顺序
      "agent_id": "expert_1", "agent_role": "Clinical Pharmacologist",
      "phase": "expert_answer", "round": 1,
      "event_ids": ["round1", "vote1"],             // 同一讨论轮、同一次投票/共识等多方事件（多个也可以）
      "input_messages": [ /* 干净输入：即使本步被 prompt_injection，也记录注入前的输入 */ ],
      "sources": [                                  // 拼 prompt 时放进来的前序输出（读集超边）
        {"step_id": "s1", "how": "verbatim | summary | structured_field", "field": null}
      ],
      "output": "该步完整输出文本",
      "reasoning": "推理模型的 reasoning 字段（如有）",
      "structured": {"answer": "B", "level": null, "confidence": 80, "vote": null},
      "finish_reason": "stop", "prompt_tokens": 752, "completion_tokens": 410,
      "tool_calls": []
    }
  ],
  "final": {"answer": "B", "source_step_ids": ["s6", "s7"]},

  "labels": {                                       // 只有标签放这里；模型输入只读上面
    "gold": "D", "is_correct": false, "is_valid": true,
    "injection": [
      {"step_id": "s3", "agent_id": "expert_1", "strategy": "prompt_injection",
       "fm_error_type": "FM-2.4", "injected_input_messages": [ ... ],
       "clean_output": "仅 response_corruption 时：篡改前的输出", "applied": true}
    ],
    "paired_normal_run_ids": ["mdagents|medxpertqa-text|Q123|normal|seed0"]
  }
}
```

**优先级**：P0 必须有，P1 强烈希望有，P2 有更好。

| 字段 | 优先级 | 说明 |
|---|---|---|
| `question_id`、`run_mode`、`run_index/seed`、`framework`、`model` | P0 | 成对运行和留一框架评测都靠它们 |
| 每个 LLM 调用一个 step，带 `order`、`agent_id`、`agent_role`、`output` | P0 | 现有 canonical `conversation_history` 基本满足 |
| 干净的 `input_messages`（注入前） | P0 | 解决问题 A，三个框架目前缺 |
| `labels` 与 `steps` 分离 | P0 | 解决问题 B；转换脚本事后拆也可以，但请在生成侧统一 |
| `labels.gold`、`is_correct`、`is_valid` | P0 | 已有 |
| `sources`（拼 prompt 时记录） | P1 | 解决问题 C；在各 wrapper 拼上下文的位置记一下前序 step_id 即可 |
| `event_ids`、`round` | P1 | 投票、共识、讨论轮等多方事件，对应项目里 FC4 共识动态类故障 |
| `structured`（答案、等级、置信度、投票） | P1 | 共识类故障的关键信号 |
| `framework_description` | P1 | 零样本跨框架时，模型靠它理解拓扑 |
| `finish_reason`、token 数、`reasoning` | P2 | 识别截断、空输出这类"非语义故障" |

## 4. 关于 TriageAgent 的格式（用户问能否以它为模板）

我们看了 `TriageAgent/results/showcase/trajectory_Test-1_case2.json`。

- **可以用作原始数据源。** `llm_call_log` 有每次调用的完整 messages，读集可以恢复（Summarizer 读了 3 位医生的初判，3 位医生的讨论都读了 Summarizer）。
- **不建议用作统一格式的模板。** 它的 `stages` 字典（`doctor_a/b/c/summarizer`）、`discussion_rounds`、`consensus_detail` 是这个框架专用的结构，换个框架字段就全变了。统一格式应以"每次 LLM 调用一条 step"为主干，即上面的 schema；TriageAgent 写个转换器映射过来即可。它现有字段里，`llm_call_log[].messages` 对应 `input_messages`，`stage/agent` 对应 `phase/agent_role`，`discussion_rounds[].updates[]` 对应 `structured` 和 `event_ids`。
- **样例里有数据质量问题。** 8 次调用中有 3 次 `finish_reason=length` 且 `content` 为空或只有 26 个字符（DoctorA、DoctorC 初判，Coordinator 共识）：max_tokens=1024 截断了推理模型的输出，答案只能从 reasoning 里抽。批量生成前请调大 max_tokens，或把截断单独标出来，否则会混进"故障"里。

## 5. 数量与多样性（建议，成本需先试跑，由用户确认）

- **框架**：现有 5 个医学框架，加 TriageAgent，加 medical-aegis 已注册的 agentverse 和 cmas，加其他可以跑医学 QA 的通用框架（methods 目录里的 macnet、mad、autogen 等），目标至少 8 个。
- **每题运行次数**：normal 每题 K 次（建议 K=4，温度>0），这样同一题内能自然出现成功和失败；inject 按现有方式。
- **模型**：至少两种 backbone 交叉，避免模型被单一 backbone 的文风"认出来"。
- **数据集**：沿用 MedXpertQA-Text/MM、MedConceptsQA、mmlu_pro_health、trial_success，再加 TriageAgent 的分诊数据。

## 6. 需要 medical-aegis 回答的问题

1. 现在有哪些"框架 × 数据集"已经跑过、或能直接跑？normal 轨迹有多少条，存在哪里（HF collection 还是本地）？
2. normal 轨迹的格式是否和 inject 一样，也有每步的 `input_messages`？
3. 问题 A：三个框架缺注入前的输入。是否方便在 wrapper 里补存？
4. `sources` 在各 wrapper 里记录，有没有困难？哪些框架的上下文拼接集中在一处、容易插桩？
5. 🔴 **注入频率统一（方案 A 只注入一次 / 方案 B 每次都注入）仍待用户决定。** 方法侧倾向 **A**：每个被注入 agent 只有一个注入点，"责任步"标签更干净，与 Who&When 式的"最早决定性错误"评测对齐。B 可以作为额外的鲁棒性子集。最终请用户拍板。
6. 能否在批量生成前跑一个小试点（例如 2 个框架 × 20 题 × K=4，normal 加 inject），按项目约定估算成本给用户确认？试点产出的 JSON 请放一份样例到本目录，我们这边会用它跑超图构建和泄漏检查，然后回复格式意见。

---

## 回复

见 [issue #1](https://github.com/chancanmakeit/medical-aegis/issues/1) 评论区。
