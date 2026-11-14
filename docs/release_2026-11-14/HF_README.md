---
license: other
license_name: mixed-research-use
pretty_name: Medical Multi-Agent System Trajectories (medical-aegis × MedHyperTrace × MAFA)
language:
- en
- zh
tags:
- multi-agent-systems
- failure-attribution
- medical
- llm-agents
- counterfactual
size_categories:
- 10K<n<100K
---

# 医学多智能体系统轨迹数据集（medical-aegis 整理版，2026-11-14）

**English summary.** Trajectories of medical multi-agent systems (MAS) produced by the `medical-aegis` project (real LLM runs with gemini-2.5-flash-lite / llama-4-maverick / mercury-2.5-preview; fault-injected runs; counterfactual branch replays with protocol-derived step labels), plus a doctor-annotation-ready subset in the input format of the `MAFA-human-ai-annotation` tool, and an inventory of the related datasets held by the sister projects (MedHyperTrace, MAFA) and of public MAS failure datasets. **No human step-level labels exist yet for any medical-aegis trajectory**; the only human failure labels in the ecosystem are the 400 MedAgentAudit human-evaluation instances (external release). Every count below was computed from the files (scripts listed in `docs/`).

本仓库把三个项目目前所有的医学多智能体轨迹数据整理到一处，说明每份数据**是什么系统、多少条、真实运行还是模拟注入、答对答错多少、有没有标签、标签是谁标的**，并准备了可直接交给人类医生标注的子集（`annotation_ready/`，MAFA 标注工具的输入格式）。

- 详细清单：`docs/DATASET_REPORT.md`（逐文件、逐框架的数字）、`docs/medical_aegis_inventory.{md,json}`。
- 生成本仓库的代码：GitHub `chancanmakeit/medical-aegis`（`scripts/build_annotation_ready.py` 等）。
- 隐私与授权：题目来自公开基准（MedXpertQA、PathVQA、SLAKE、Kvasir-VQA-x1、PASCAL 心音、Sound-Dr、ESI 分诊案例）。轨迹由大模型生成，不含真实病人信息。各来源数据保留其原有许可；**本仓库请保持私有**，对外发布前需逐项核对来源许可。

---

## 1. 一页总览

### 1.1 本仓库里的数据（medical-aegis 生成，医学任务）

| 目录 | 内容 | 类型 | backbone | 条数 | 答对 / 答错 | 标签（谁标的） |
|---|---|---|---|---|---|---|
| `medical_aegis/eval_v3_branch/parents/` | 协议 v3 评测集的父运行（自然运行，全部运行，含答对的） | **真实运行**，无注入 | gemini-2.5-flash-lite | **5,471** | 2,950 / 2,521 | 只有结局（答对与否，自动判分） |
| `medical_aegis/eval_v3_branch/<job>/` | 反事实分叉标签：在 1,789 条答错父运行的每个 LLM 步上重采样该步、回放其余步 | **反事实回放**（79,976 次分叉 / 对照运行） | 同上 | **14,688 个步级标签点** | — | **程序 / 统计检验**（Fisher 检验，非 LLM、非人工）：379 阳性（对称参照下 303），14,023 未定，286 待 stage 2（DyLAN） |
| `medical_aegis/corpus_v1/` | 语料题池自然运行（给 MedHyperTrace 训练用） | **真实运行**，无注入 | gemini-2.5-flash-lite | **5,796** | 2,492 / 3,304 | 只有结局 |
| `medical_aegis/anchor_llama/` | 锚点 100 题：正常运行 + 注入故障 + 安慰剂注入（sham） | **真实运行 1,200 + 模拟注入 1,000 + sham 580** | llama-4-maverick | **2,780** | 正常 625/575；注入 454/546；sham 262/318 | 注入日志（**程序**：注入位置、方式） |
| `medical_aegis/pilot_and_trials/` | 早期试点：mercury / llama 试点（含注入）、gemini 试跑、分叉试点 | 真实 + 注入 + 分叉 | mercury-2.5-preview、llama-4-maverick、gemini-2.5-flash-lite | 试点 440；gemini 试跑 381；分叉 3,340 | 见 `docs/DATASET_REPORT.md` | 注入日志（程序）；分叉试点无标签文件 |
| `medical_aegis/audio/` | MAM 运行引用的音频（心音 A/B、Sound-Dr 咳嗽音） | 输入素材 | — | 3 个数据集 | — | — |
| `annotation_ready/` | **交给医生标注的候选集**（eval_v3 父运行的子集，见第 3 节） | 真实运行 | gemini-2.5-flash-lite | **5,013** | 2,745 / 2,268（答对 clean / 答错 faulty） | 结局；v3 反事实阳性步放在 `manifest.jsonl`（**对标注者隐藏**） |

### 1.2 按多智能体系统统计（本仓库，真实运行）

| 多智能体系统 | 任务 / 模态 | eval_v3 父运行（答对/答错） | 其中做过反事实标注的父运行 → 标签点 / 阳性 | corpus_v1（答对/答错） | anchor（正常 / 注入 / sham） |
|---|---|---|---|---|---|
| AgentVerse | MedXpertQA-Text 选择题 | 800（330/470） | 250 → 2,087 / **99** | — | — |
| MDAgents | MedXpertQA-Text | 800（344/456） | 425 → 2,975 / **97** | 1,449（620/829） | 300 / 170 / 200 |
| MDAgents | 图像：MedXpertQA-MM / PathVQA / SLAKE / Kvasir-VQA-x1 | 各 200（115/85，146/54，179/21，178/22） | 50 / 50 / 21 / 22 → 1,001 / **21** | — | — |
| LLM-Debate | MedXpertQA-Text | 800（386/414） | 300 → 2,100 / **61** | 1,449（653/796） | 300 / 290 / 140 |
| DyLAN | MedXpertQA-Text | 699（306/393） | 170 → 566 / 0（286 待 stage 2） | — | — |
| MedAgents | MedXpertQA-Text | 110（50/60） | 40 → 741 / **16** | 1,449（609/840） | 300 / 270 / 120 |
| MAC（群聊） | MedXpertQA-Text | 140（67/73） | 40 → 387 / **8** | 1,449（610/839） | 300 / 270 / 120 |
| TriageAgent | ESI 急诊分诊（1–5 级） | 864（644/220） | 220 → 1,760 / **32** | — | — |
| MAM | 音频：心音 A / 心音 B / Sound-Dr | 218（106/112） / 180（69/111） / 60（30/30） | 65 / 111 / 25 → 3,071 / **45** | — | — |
| **合计** | | **5,471（2,950/2,521）** | **1,789 → 14,688 / 379** | **5,796（2,492/3,304）** | **1,200 / 1,000 / 580** |

注：anchor 的"注入"含 RC（篡改回复）和 PI（提示注入）各版本；10 条 MAC 注入、9 条 MAC sham 没有触发。注入触发不等于答错：约 45% 触发了注入的运行仍然答对。

### 1.3 相关数据（不在本仓库，给出位置和数字）

| 数据 | 维护方 / 位置 | 医学？ | 条数 | 真实 / 模拟 | 标签与标注者 |
|---|---|---|---|---|---|
| **AEGIS-medical 定制数据**（clean / faulty / simulated） | 用户团队；GitHub `GuihaiChen1998/nature-sub-record`（公开）；私有 HF `UUUooUUU/medical-aegis-workspace/aegis_data.tar`（clean + simulated） | 是 | clean 440（全部答对）；faulty 1,112（全部答错）；simulated 3,519（全部答错） | clean、faulty 为**真实运行**；simulated 为**注入故障** | simulated：注入日志（程序）；clean/faulty：无步级标签 |
| 同上，按框架 | | | MDAgents（MedXpertQA-MM）49 / 682 / 1,003；DyLAN（MMLU-Pro 健康）66 / 269 / 1,062；ClinicalAgent5（临床试验成败）192 / 102 / 1,052；ClinicalAgent 133 / 59 / 402 | | |
| AEGIS-custom-8-13（MedHyperTrace v1 训练数据） | GitHub `chancanmakeit/Medhypertrace`：`MedHyperTrace-v1/data/AEGIS-custom-dataset-8-13.7z` | 是 | 5,231（上表 simulated 4 个框架 + LLM-Debate 1,712） | 全部**注入故障**、全部答错 | 注入日志（程序，MAST-14 失败码）；另有 LLM 判分和 LLM 写的注入摘要 |
| **MAFA 审查数据包** | 私有 GitHub `chancanmakeit/MAFA-human-ai-annotation`：`review_packages/mast_v1.json`、`medagentaudit_v1.json` | 是 | 每个体系 360 条（4 个框架 × 45 答错 + 45 答对，取自 AEGIS-medical clean/faulty） | 真实运行 | **LLM 标注**：mimo-v2.6-flash（主）+ glm-5.3-flash（副），约 37 次 Stage-1 运行；"类人"LLM 标签 claude-fable-5-1 20 行、claude-haiku-5-5 19 行、gemini-4-argon 19 / 39 行（均 `kind=llm`）。**人类专家标签：0 条完成**（在线工具数据库里只有 1 条未完成的试标，2026-10-22，今天核对过） |
| **MedAgentAudit（MAA）** | 外部发布：`GuihaiChen1998/nature-sub-record`；MedHyperTrace 维护排除清单和打分 | 是 | 14,370 条真实运行（6 个系统：ColaCare、HealthcareAgent、MAC、MDAgents、MedAgent、ReConcile × 6 个数据集） | 真实运行 | LLM 审计员二分类约 26.6 万项（10 个 MAA 码）；**人工 400 例（每例 3 人投票；多数票 158 是 / 242 否）**——目前整个生态里唯一的人类故障标签 |
| 公开非医学 MAS 故障数据（7 个） | 私有 HF `UUUooUUU/mht-session-data`、`medical-aegis-workspace/public_mas`（MedHyperTrace 转换为 mas-traj/1） | **否**（医学条目已剔除） | 26,108 | 真实运行（注入子集已跳过） | Who&When 184（论文称人工，卡片未写明）、MAST-Data 1,630（**LLM 判分**）、ARIA 22,237（**模型生成**）、AFTraj 1,548（多 LLM 判分）、TraceElephant 220（未写明）、MAScope 260（无注入子集）、AgentRx τ 29（未写明） |
| MedHyperTrace 自产 | 私有 HF `UUUooUUU/mht-midtrain-pilot`、`mhb-artifacts`；Medhypertrace 仓库 | 混合 | 训练语料（TAPT 约 2,446 万 token 等）、模型预测（MAFA 360 条 × 2 体系） | 衍生数据 | 无新的人工标签 |

---

## 2. 关键概念

- **真实运行（natural / normal）**：多智能体系统用真实大模型完整跑一遍，不做任何干预。答错的运行含有"真实故障"，但哪一步出错没有人工标注。
- **模拟故障（injected / simulated）**：在指定智能体的某一步注入错误（RC：直接篡改该步输出；PI：在该步提示词里加入误导指令）。标签来自注入日志，是**程序生成的"构造真值"**。已知问题：RC 是模板句，PI 有表面特征（见 MAFA RUN §53/§70），不宜直接当作真实故障分布。
- **sham（安慰剂注入）**：注入一段不要求出错的说明，用来控制"被注入"这件事本身的影响；按构造，sham 步的真值是"无故障"。
- **反事实分叉标签（协议 v3）**：对答错运行的第 t 步，用温度 0.7 重采样该步、以温度 0 重生成依赖它的后续步、其余步回放（branch 臂），与"回放第 t 步、同样重生成后续步"（control 臂）比较；2+2 次（stage 1），结果不一致时扩到 6+6（stage 2）；Fisher 单侧 p<0.05 记为 `positive`（"最终答案对该步敏感"），否则 `undetermined`，**从不判为 negative**。阳性 ≠ "该步导致了错误"。MedHyperTrace 的置换零假设审计：FDR 约 0.11–0.17；除 MDAgents 外，阳性与步长、位置相关（同轨迹内步长 AUROC：AgentVerse 0.74、MAM 0.74、LLM-Debate 0.82、MAC 0.97；TriageAgent 0.58 但阳性偏早；MDAgents 0.53）。详见 `medical_aegis/eval_v3_branch/` 与 `docs/DATASET_REPORT.md`。

---

## 3. `annotation_ready/`：交给医生标注的候选集

- **来源**：`medical_aegis/eval_v3_branch/parents/` 中除 MAM（音频，MAFA 工具不能播放）以外的全部真实运行，去重后 **5,013 条**：答错（`data/faulty/`）2,268 条、答对（`data/clean/`）2,745 条；图像题需要的 580 张图在 `images/`。
- **格式**：AEGIS 原始 JSONL（每行一条运行，`query`、`ground_truth`、`is_correct`、`response`、`injection_log.conversation_history[*]`，后者每步有 `agent_name`、`role_index`、`phase`、`round`、`content`、`input_messages`）。这正是 MAFA 加载器读取的格式。文件名 `<framework>__normal_<pool>.jsonl.gz`，用前解压。
- **`specs/`**：8 个 MAFA MappingSpec（llm_debate、agentverse、medagents_mc、mac_groupchat、triage_agent、mam，以及针对本数据的 mdagents / dylan 变体），已同步到 MAFA 仓库 `mafa/specs/`。用 MAFA 自己的加载器实测：5,013 条全部加载成功，阶段名全部映射到 7 个标准阶段。剩余提示：AgentVerse 的 critic 读到的 solver 输出在 assistant 消息里，MAFA 的上下文推断看不到，所以"同伴可见"能力会被报"与记录矛盾"（792 条，仅提示）；MAC 有少量空内容步。
- **`manifest.jsonl`**（**不要给标注者看**）：每条运行一行：所在文件和行号、`run_id`、是否答对、步数，以及是否做过反事实分叉、标签点数、阳性步 `v3_positive_steps`（control 参照）和 `v3_positive_steps_pooled`（对称参照）。1,588 条父运行带反事实标签，共 334 个阳性步。医生标完后可以用它比较"人工定位的故障步"和"反事实敏感步"。
- **建议的首批标注**：优先标有反事实阳性的答错运行（每个框架 10–20 条）和同题的答对运行，便于人机、人和反事实标签三方对照。抽样脚本可按 `manifest.jsonl` 过滤。
- **使用步骤**（在 MAFA 仓库）：见 MAFA 仓库 `docs/medical-aegis数据导入说明.md`。简要：下载本目录 → 解压到 MAFA 的 `data/faulty`、`data/clean` → `scripts/run_stage1.py`（**付费的 LLM 预标注，需先报价、经用户批准**）→ `export_review_package.py` → `build_review_sidecar.py` → `build_review_tool.py` → 医生用离线工具标注 → `import_review_labels.py`。

---

## 4. 目录结构

```
README.md                       本文件
docs/DATASET_REPORT.md          详细清单（含 MedHyperTrace、MAFA、公开数据部分）
docs/medical_aegis_inventory.md / .json   medical-aegis 数据逐文件统计
medical_aegis/eval_v3_branch/   协议 v3：parents/（原始运行）、parents_mastraj/（mas-traj/1 导出）、
                                <job>/labels_v3.jsonl.gz（步级标签）、branch_records_compact.jsonl.gz（每次分叉运行的身份块 + 重生成步骤文本）、summary.md、candidates
medical_aegis/corpus_v1/        raw/ + mastraj/ + README
medical_aegis/anchor_llama/     锚点运行（*.jsonl.gz；文件名后缀说明见 DATASET_REPORT §D）
medical_aegis/pilot_and_trials/ gemini_trial_2026-11-03、branch_pilot_2026-10-26、branch_planA_2026-11-03、pilot_2026-10-20
medical_aegis/audio/            MAM 用到的 wav（路径与运行记录里的 datasets/audio/... 对应）
annotation_ready/               data/{faulty,clean}/*.jsonl.gz、images/、specs/、manifest.jsonl、README.md
```

## 5. 已知问题

- `answer` 字段存的是**标准答案**，系统答案要从 `response` 里抽取（MAFA `mafa/final_answer.py`）。
- 同一道题有多个 `run_index`（triage 每题 4 次、MAM 每题 2 次、anchor 每题 3 次），彼此相关；评测或划分时请按题目分组。
- eval_v3 的 DyLAN 只做了 stage 1；其 `sources` 读集已知不完整（导出时 `provenance.sources_complete=false`）。
- `medical_aegis/eval_v3_branch/parents/*_x.jsonl.gz` 重复包含了第一批未用到的 run-0 记录，按 `run_id` 去重。
- anchor 的旧 PI（`__inject` 的 run 1）和旧 `_shamstyle` 措辞不建议用于训练。
- 用量计数器高估了花费（同一 API key 有别的调用方）；成本按 token 估算见各 REPORT。
