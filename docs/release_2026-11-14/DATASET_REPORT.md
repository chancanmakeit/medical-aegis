# 数据集详细清单（2026-11-14）

总览见仓库根目录 `README.md`。本文给出各部分的来源、口径和核对方法。medical-aegis 部分的逐文件数字见 `medical_aegis_inventory.md`（及机器可读的 `.json`），这里不再重复全部表格。

**核对方式**
- medical-aegis：直接读取 `chancanmakeit/medical-aegis` 的 `data_runs/`、`docs/requests/samples/` 和本地工作目录，用脚本逐文件计数（`is_correct`、注入是否触发、标签判定）。
- MedHyperTrace：读取 `chancanmakeit/Medhypertrace`（HEAD `77efab3`）的文件和文档；v1 归档解压后计数。
- MAFA：读取 `chancanmakeit/MAFA-human-ai-annotation`（HEAD `745ae59`），并于 2026-11-14 查询在线标注工具的数据库（`labels` 集合）。
- 公开数据：读取各数据集卡片（HF Hub）。

标注"未核实"的项目只来自文档，没有用数据核对过。

---

## A. medical-aegis：协议 v3 反事实分叉评测集（`medical_aegis/eval_v3_branch/`）

- **backbone：** gemini-2.5-flash-lite，温度 0.7。
- **父运行：** 5,471 条真实运行，2,950 条答对 / 2,521 条答错。按框架见 README 1.2 节。
- **标签：** 14,688 个步级标签点，来自 1,789 条答错父运行，依据 79,976 次分叉 / 对照回放。
  - 标注者字段为 `annotator: {kind: program, version: branch_v3_analysis}`。
  - 不是 LLM 判断，也不是人工标注。
  - 结果：379 个 positive、14,023 个 undetermined、286 个 needs_stage2（全部是 DyLAN）。
- **统计字段（第 11 轮起）：**
  - `pooled_reference`、`p_value_pooled`：对称参照，用 12 个答案的合并众数；
  - `perm_p`：924 种分配上的精确置换检验；
  - `p_null_positive`：完整流程下的置换零假设概率，求和得到期望假阳性数 E0。
- **上下文字段：**
  - `dt_empty`：按 `sources` 声明的 D(t) 为空；
  - `is_last_llm_step`；
  - `downstream_regenerated`：某次分叉运行重生成了 t 之后的步骤，包括 `sources` 漏掉的依赖。
- **报告与审计：** `docs/requests/samples/eval_v3_2026-11-04/REPORT.md`（medical-aegis 仓库）。
  - 对称参照下 303 个阳性，E0 约 49。
  - "只反映末次调用"的阳性 36 个（D(t) 声明为空，且 t 之后没有重生成任何步）。
  - 平凡基线：同轨迹内阳性对其余点的 AUROC。

| 框架 | 步长 AUROC | 相对位置 AUROC |
|---|---|---|
| AgentVerse | 0.740 | 0.358 |
| LLM-Debate | 0.815 | 0.284 |
| MDAgents | 0.534 | 0.517 |
| MAC | 0.973 | 0.108 |
| MedAgents | 0.684 | 0.280 |
| MAM | 0.743 | 0.416 |
| TriageAgent | 0.577 | 0.297 |
| MDAgents 多模态 | 0.593 | 0.417 |

- **文件：**
  - `parents/`：原始运行；`*_x` 是扩充批次，重复包含第一批未用到的 run-0 记录。
  - `parents_mastraj/`：mas-traj/1 导出，source 带 `collection`，provenance 带 `sources_complete`。
  - `<job>/labels_v3.jsonl.gz`。
  - `<job>/branch_records_compact.jsonl.gz`：每次分叉运行的身份块、最终答案、对错，以及重生成步骤的文本。回放步与父运行相同，已由前缀 sha1 和请求 key 核对。
  - `<job>/summary.md`、`*_candidates.jsonl.gz`、`*_stage2_plan.txt`。

## B. medical-aegis：语料题池自然运行（`medical_aegis/corpus_v1/`）

- **运行：** 4 个框架 × 1,449 题，每题 1 次，gemini-2.5-flash-lite（duckcoding 端点），共 5,796 条：2,492 条答对 / 3,304 条答错。
- **标签：** 只有结局，没有步级标签。
- **题目：** 与 eval 池、锚点题、MAA 题都不重叠。
- **用途：** MedHyperTrace 的 interaction-CPT 训练语料。

| 框架 | 答对 | 答错 |
|---|---|---|
| LLM-Debate | 653 | 796 |
| MAC | 610 | 839 |
| MDAgents | 620 | 829 |
| MedAgents | 609 | 840 |

## C. medical-aegis：试点与试跑（`medical_aegis/pilot_and_trials/`）

- **`pilot_2026-10-20`**：440 条原始运行。
  - backbone：mercury-2.5-preview 和 llama-4-maverick。
  - 框架与任务：MedAgents（MedConceptsQA）和 TriageAgent（ESI）。
  - 内容：正常运行（20 题 × 4 次）+ RC 10 + PI 10 + PI（simulation 包装）10。
  - mercury 的 20 条 PI（direct）因上游 403 全部失败。
  - 标签来自注入日志（程序）。
- **`gemini_trial_2026-11-03/natural`**：381 条真实运行。
  - 框架：AgentVerse、DyLAN、LLM-Debate、MAC、MDAgents、MedAgents，以及 MDAgents 在 4 个图像数据集上的运行（各 10 条）。
  - 其中 55 条 DyLAN 运行因全局随机数无法回放，已被替代。
  - 多模态文件的 dataset 标签已于 2026-11-14 修正。
- **分叉试点：** 都没有单独的标签文件，结论在各 REPORT 里。

| 目录 | backbone | 内容 | 分叉 / 对照运行数 |
|---|---|---|---|
| `branch_pilot_2026-10-26` | llama | LLM-Debate、MDAgents | 264 |
| `branch_planA_2026-11-03` | llama | LLM-Debate，180 个点 | 426 |
| `gemini_trial/branch_cal` | gemini，协议 v2 校准 | — | 529 |
| `gemini_trial/branch_cal2` | gemini，协议 v2 校准 | 4 个框架 | 2,121 |

## D. medical-aegis：锚点运行（`medical_aegis/anchor_llama/`）

- **配置：**
  - backbone：llama-4-maverick（aihubmix；返回的 model 字段写的是 `google/gemma-4-31B-it-turbo`，用户说明不再核实）。
  - 温度 0.7；题目为 MedXpertQA-Text 难度区间内的 100 题；轮次上限 2。
- **文件后缀：**

| 后缀 | 含义 |
|---|---|
| `__normal` | 正常运行，每题 3 次 |
| `__inject` | run 0 = RC，run 1 = 旧 PI（不建议用于训练；MDAgents 只有 RC） |
| `_pi4` / `_pi5` / `_pi6` / `_v12` | 各版 PI 说明：长度匹配 / fmt_v1 / fmt_v1_1 / fmt_v1_2 |
| `_sham*` | 安慰剂注入（`_shamstyle` 是旧措辞，不建议用于训练） |
| `_op` | MDAgents 的 match_opener 版本 |

- **合计：**
  - 正常 1,200 条（625 答对 / 575 答错）；
  - 故障注入 1,000 条（454 / 546；990 条触发，10 条 MAC 未触发）；
  - sham 580 条（262 / 318；571 条触发）。
- **注意：**
  - 注入触发后仍答对的约占 45%。
  - 有 2 道锚点题与 MAA 重叠（1499、1939），共 51 条运行；导出时记为 `labels.maa_overlap`。
- 逐文件数字见 `medical_aegis_inventory.md` 第 D 节。

## E. 不包含的内容

- **mock 样例**（`docs/requests/samples/*_mock_*.jsonl`）：假 LLM 生成，覆盖 14 个框架，每个文件 4 条运行，只用于回归测试。
- **难度筛选** `screen_2026-10-21`：单个 LLM 答题，不是多智能体系统。
- **失败运行**：语料运行中因额度用完而失败的 640 条（`llm_api_failure`）。
- **本地中间文件**：完整未压缩的分叉输出和调用日志（约 11 GB）只在 medical-aegis 的工作容器里。归档版已足够重建：父运行加上重生成步骤。

## F. AEGIS-medical 定制数据（用户团队，`GuihaiChen1998/nature-sub-record`）

- **性质：** 是用户团队早期用 "AEGIS-medical-v23" 代码在医学任务上跑的数据，不是 arXiv AEGIS 的公开发布版。
  - 记录里没有 backbone 字段（未核实）。
  - MAFA 用 `scripts/fetch_data.sh` 从这个公开仓库下载它。
  - 私有 HF `UUUooUUU/medical-aegis-workspace/aegis_data.tar` 只有 clean 和 simulated 两部分。

| 框架 | 任务 | clean（真实，全部答对） | faulty（真实，全部答错） | simulated（注入，全部答错） |
|---|---|---|---|---|
| MDAgents | MedXpertQA-MM 图像选择题 | 49 | 682 | 1,003（PI 149 / RC 102 / PI+RC 752） |
| DyLAN | MMLU-Pro 健康 | 66 | 269 | 1,062（PI 127 / RC 404 / PI+RC 531） |
| ClinicalAgent5 | 临床试验成败（概率） | 192 | 102 | 1,052（PI 52 / RC 534 / PI+RC 466） |
| ClinicalAgent | 临床试验成败 | 133 | 59 | 402（PI 173 / RC 55 / PI+RC 174） |
| **合计** | | **440** | **1,112** | **3,519** |

- **计数来源：**
  - faulty 各框架的数字由 MAFA 记录的各框架总数（MDAgents 1,734、DyLAN 1,397、ClinicalAgent5 1,346、ClinicalAgent 594）减去 clean 和 simulated 推出；总数 1,112 与 MAFA 一致。
  - clean 和 simulated 是逐文件计数。
- **标签：** simulated 的标签来自注入日志（程序；MAST-14 失败码，`multi_injection_info`）。clean 和 faulty 没有步级标签。
- **已知问题：**
  - RC 用的是模板句；PI 有泄漏和拒答特征（MAFA RUN §53、§70；medical-aegis `aegis_simulated_check_2026-10-22`）。
  - clean 只收了答对的运行，simulated 只收了注入成功（答错）的运行，因此是按结局筛选过的集合。
- **MedHyperTrace v1 的 `AEGIS-custom-dataset-8-13.7z`（Medhypertrace 仓库）：**
  - 共 5,231 条注入运行，全部答错；`is_valid_error=True`。
  - 包含上表 simulated 的 4 个框架，再加 LLM-Debate（MMLU-Pro 健康）1,712 条。
  - 共 12,857 次注入，覆盖 MAST 全部 14 个码。
  - 每条另有 LLM 判分（`verification`）和 LLM 写的 `injection_summary`。

## G. MAFA 人机协同标注（私有 `chancanmakeit/MAFA-human-ai-annotation`）

- **审查数据包（p2，已冻结）：**
  - `review_packages/mast_v1.json`（MAST 14 码）和 `medagentaudit_v1.json`（MedAgentAudit 10 码）。
  - 两个包是同样的 360 条轨迹：MDAgents、DyLAN、ClinicalAgent、ClinicalAgent5 各取 45 条答错（来自 faulty）和 45 条答对（来自 clean），都是真实运行。
  - 预注册划分 dev 120 / test 240；盲审 63 条；图片 122 张。
- **LLM 标签：**
  - 每条轨迹都有两个标注模型的 Stage-1 结果：主 mimo-v2.6-flash，副 glm-5.3-flash。
  - `results/runs_snapshot/` 里约有 37 次 Stage-1 运行，用到 mimo、glm、deepseek、gpt，多数是 180 条。
- **"类人"标签：** 都是 LLM 扮演专家，`kind=llm`，不能当作真值。

| 版本 | 模型 | 规模 |
|---|---|---|
| human-like v1 | claude-fable-5-1 | 20 行，17 条答错轨迹 |
| human-like v2 | claude-haiku-5-5 | 19 条 |
| closest-human-like v1 | gemini-4-argon | 19 条 |
| closest-human-like v2 | gemini-4-argon | 39 条 |

- **人类专家标签：0 条完成。**
  - 在线标注工具（claude.ai artifact）的 `labels` 集合在 2026-11-14 查询时只有 1 条记录：MedAgentAudit MM-51，状态 `in_progress`，最后更新 2026-10-22。
  - 仓库里没有导入任何人工标签。
  - `results/runs_snapshot/human_gold.json` 里有 400 条人工标签，但来自外部 MedAgentAudit 发布，不是 MAFA 的医生标的。
- **人工标签格式**（工具导出 `labels_*.json`，再用 `import_review_labels.py` 导入）：
  - 缺陷层：每个码判为有 / 无 / 不确定，并给出涉及的智能体和首次出现的步骤；另有"无对应码的缺陷"一行，须写出最接近的码。
  - 责任层：只在答错轨迹上，判断每处缺陷是否促成了错误答案。
  - 详见 MAFA `docs/标注数据接口说明.md`。

## H. MedAgentAudit（MAA，外部发布）

- **运行：** 14,370 条真实运行。6 个系统（ColaCare、HealthcareAgent、MAC、MDAgents、MedAgent、ReConcile）× 6 个数据集（MedQA、MedXpertQA-Text、PathVQA、PubMedQA、SLAKE、VQA-RAD）。
  - 文档说用了 4 个 LLM；人工集里实际出现 6 个模型名（gpt-5.2、gemini-3-flash-preview、deepseek-reasoner、qwen3-8b、qwen3-vl-8b-thinking、glm-4.6v）。
- **LLM 审计员标签：** 10 个 MAA 码的二分类，约 26.6 万项。审计员看到了标准答案；审计员模型未核实。
- **人工标签（目前整个生态里唯一的人类故障标签）：**
  - 400 例，每例 3 人投票，多数票 158 是 / 242 否。
  - 10 个码 × 40 例；来自 285 题、391 条运行。
  - 各系统：MedAgent 107、ColaCare 92、HealthcareAgent 71、MAC 67、ReConcile 49、MDAgents 14。
  - 只有缺陷层，没有责任层。
- **在 MedHyperTrace 里的用法：**
  - 维护排除清单 `maa_exclusion_v1.json`：600 个题干，用于防止训练数据泄漏到评测。
  - 打分表 `c6_scores.csv`：399 例。
  - 位置：数据在 `GuihaiChen1998/nature-sub-record`；MedHyperTrace 用 `scripts/prepare_maa.sh` 获取。
- **各系统运行数、答对答错：** 未核实，数据不在本机。

## I. 公开的非医学 MAS 故障数据（MedHyperTrace 转换为 mas-traj/1）

- **位置：** 私有 HF `UUUooUUU/mht-session-data/public_mas/`，以及 `UUUooUUU/medical-aegis-workspace/public_mas/`。
- **转换口径：** 全部按 normal 运行转换，跳过注入子集；医学条目已剔除（ARIA 2,231 条、MAST 12 条）。

| 数据集 | 转换后条数 | 框架 | 标签与标注者（依据数据集卡片） |
|---|---|---|---|
| Who&When | 184 | CaptainAgent 126、Magentic-One 58 | 出错智能体、步骤、原因。卡片只写 "fine-grained annotations"；论文称人工标注（卡片里未核实） |
| MAST-Data | 1,630 | AG2、ChatDev、MetaGPT、Magentic-One 等 8 个 | MAST-14 轨迹级码。卡片明确写 "produced by an LLM judge, not by human labelling"；另有 19 条人工一致性样本未下载 |
| ARIA | 22,237 | OpenManus、MetaGPT、AG2、Magentic-One | 定位与归因；卡片写 "model-generated" |
| AFTraj | 1,548 | 4 个 | 1,162 条安全运行 + 386 条自然失败（多 LLM 判分流水线）；728 条注入运行已跳过 |
| TraceElephant | 220 | CaptainAgent、Magentic-One、SWE-agent | 出错智能体、步骤；卡片为空，标注者未核实 |
| MAScope | 260 | LangGraph ×4、AutoGen、CrewAI、debate | 只收了无注入子集 |
| AgentRx τ-retail | 29 | τ-bench agent | 失败类别、根因；标注者未核实。gated 数据，CC-BY-4.0 |

- **另有只做了统计、未转换的数据：**
  - Fancylalala/AEGIS：9,533 条，全部注入，gpt-4o-mini。
  - CORRECT-Error：2,226 条，全部注入。
  - TRAIL：148 条；许可不允许再分发。

## J. MedHyperTrace 自己生成的数据

- **训练语料**（私有 HF `UUUooUUU/mht-midtrain-pilot`）：

| 语料 | 规模 / 内容 |
|---|---|
| tapt_pilot_v1 | 2,446 万 token，12,874 条运行（公开数据 + medical-aegis 锚点正常运行） |
| stage0 | 3,440 万 token |
| icpt/corpus | LM 4,000 万 / ICPT 4,030 万 token |
| samt_v1 | 11,987 条训练 + 591 条探针；自监督目标，由程序生成 |

- **模型预测**（Medhypertrace 仓库）：
  - `MedHyperTrace-v1/eval_mafa/out_pkg/medhypertrace_pred*.jsonl`：MAFA 360 条轨迹 × 2 个体系，各 720 行；
  - 嵌入缓存。
- **TracerTraj**（AgenTracer data-v1.0.0）：3,998 条，只在 MedHyperTrace 的 GPU 服务器上；标签大多由构造产生。
- **结论：** MedHyperTrace 没有生成新的人工标签。

## K. 人类标注现状与建议

1. **现状：**
   - 医学多智能体轨迹上，目前唯一的人类故障标签是 MAA 的 400 例。这些来自外部发布；只有缺陷层，6 个系统里只有 MAC 和 MDAgents 与我们的框架重合。
   - MAFA 的医生试标还没有完成任何一条。
   - medical-aegis 的数据没有任何人工标签。
2. **建议优先标注**：`annotation_ready/` 中有反事实阳性的答错运行，以及同题的答对运行。这样可以同时得到人工故障步、LLM 预标注、反事实敏感步三种标签，互相对照。
   - MDAgents 文本（72 条父运行有阳性）、AgentVerse（86）、LLM-Debate（53）样本最多。
   - TriageAgent（31）可以覆盖非选择题任务。
3. **前置条件：** MAFA 的审查包要求先做 Stage-1 LLM 预标注，这会花钱，需要先报价、经用户批准。
