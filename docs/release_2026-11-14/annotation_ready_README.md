# annotation_ready：交给医生标注的医学多智能体轨迹（MAFA 输入格式）

**数据来源：** medical-aegis 协议 v3 评测集的全部真实（自然）运行，不含 MAM（音频）。
- backbone：gemini-2.5-flash-lite，温度 0.7。
- 按（框架，题目 id，run_index，数据集）去重。
- 生成脚本：medical-aegis `scripts/build_annotation_ready.py`。

| 框架 | 题池 | 答错（`data/faulty/`） | 答对（`data/clean/`） | 有反事实标签的父运行 | 其中有阳性步的 |
|---|---|---|---|---|---|
| agentverse | MedXpertQA-Text | 470 | 330 | 250 | 86 |
| dylan | MedXpertQA-Text | 393 | 306 | 170 | 0（只做了 stage 1） |
| llm_debate | MedXpertQA-Text | 414 | 386 | 300 | 53 |
| mac_groupchat | MedXpertQA-Text | 73 | 67 | 40 | 8 |
| mdagents | MedXpertQA-Text | 456 | 344 | 425 | 72 |
| mdagents | MedXpertQA-MM（图像） | 85 | 115 | 50 | 10 |
| mdagents | PathVQA（图像） | 54 | 146 | 50 | 3 |
| mdagents | SLAKE（图像） | 21 | 179 | 21 | 1 |
| mdagents | Kvasir-VQA-x1（图像） | 22 | 178 | 22 | 2 |
| medagents_mc | MedXpertQA-Text | 60 | 50 | 40 | 10 |
| triage_agent | ESI 分诊（216 题 × 4 次） | 220 | 644 | 220 | 31 |
| **合计** | | **2,268** | **2,745** | **1,588** | **276** |

## 文件

- `data/{faulty,clean}/<framework>__normal_<pool>.jsonl.gz`
  - 内容是 AEGIS 原始 JSONL。MAFA 的加载器按文件名里的框架名匹配 spec。
  - 使用前先 `gunzip`，因为 MAFA 只读 `.jsonl`。
- `images/`：580 张图。
  - 记录里的 `images` 是文件名列表，`image_paths` 是 `images/<文件名>`。
  - MAFA 工具按文件名找图，用前把它们放进 MAFA 的图片目录，或者用 `--images` 指定。
- `specs/`：8 个 MAFA MappingSpec。
  - 新增 6 个：llm_debate、agentverse、medagents_mc、mac_groupchat、triage_agent、mam。
  - 另有 2 个变体：`mdagents_medical_aegis.json`、`dylan_medical_aegis.json`，用文件名标记 `mdagents__normal` / `dylan__normal` 匹配。原来的 mdagents / dylan spec 继续用于 AEGIS 旧数据。
  - 这些 spec 已同步到 MAFA 仓库 `mafa/specs/`。
- `manifest.jsonl`：**只给组织者，不要给标注者。**
  - 每行对应一条运行：所在文件和行号、`run_id`、`is_correct`、步数。
  - 反事实字段：`v3_branch_parent`、`v3_points`、`v3_positive_steps`（control 参照）、`v3_positive_steps_pooled`（对称参照）。
  - 步骤 id 是 `injection_log.conversation_history` 里的 `step_id`。MAFA 加载时会按顺序重新编号为 `s01…`，对照时按记录顺序换算。

## 用 MAFA 自带加载器实测（2026-11-14，MAFA HEAD `745ae59` + 新 spec）

- 5,013 条全部加载成功，阶段名全部映射到 MAFA 的 7 个标准阶段。
- 只剩提示，不影响加载：
  - AgentVerse 792 条报"同伴可见与记录矛盾"。critic 读到的 solver 输出在 assistant 角色消息里，而 MAFA 的上下文只取 user 消息，所以推断不出来。
  - MAC 有 8 条运行含空内容步。

## 注意

- `answer` 字段是标准答案，不是系统答案；系统答案从 `response` 里抽取。MAFA 已处理，标注工具默认隐藏标准答案。
- 这些运行**没有注入**，所以没有注入记录需要隐藏。
- 同一道题有多个 run_index（triage 每题 4 次）。抽样和划分 dev/test 时请按题目分组。
- MAFA 的审查包要求先做 Stage-1 LLM 预标注（`scripts/run_stage1.py`）。这会花钱，需先报价、经用户批准。
