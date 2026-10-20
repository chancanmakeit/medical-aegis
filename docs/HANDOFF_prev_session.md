# AEGIS-Medical/NER 扩展 — 会话交接文档

> 面向新会话的 Claude。本文件是接续工作的唯一权威上下文。用户是 Alvin Chan(清华合作的 ML/NLP 研究者,研究多智能体系统失败归因),偏好直接的同行级技术交流、要诚实批评而非附和、经验性结论要对着真实数据核实而不是假设。中英皆可,代码注释英文、讨论中文为主。

---

## 0. 一句话背景

把 AEGIS(多智能体错误注入 + 失败归因框架,原论文 arxiv 2509.14295,ICLR 2026)从通用任务扩展到**医学**和**NER**领域:新集成了 3 个多智能体框架(MDAgents / ClinicalAgent / CMAS)、4 个新数据集(MedXpertQA-Text/MM、MedConceptsQA、trial_success、wikigold),并打通了**多模态**(图像)端到端支持。

AEGIS 的核心机制:对一个多智能体框架的某些 agent 在推理时**注入故障**(14 种 FM 错误类型 × prompt_injection / response_corruption 两种策略),生成"错误轨迹";同一框架不注入则生成"正常轨迹"。两者配对用于下游的失败归因 / 对比学习研究。

---

## 1. 当前代码状态(都在 AEGIS-main.zip 里)

### 已集成的 6 个框架

| 框架 | method 名 | 任务 | wrapper | 结构(可注入 agent) |
|---|---|---|---|---|
| DyLAN | `dylan` | 医学 MCQ | fm_dylan_wrapper.py | 多轮,panel 成员 + Ranker(聚合) |
| LLM-Debate | `llm_debate` | 医学 MCQ | fm_debate_wrapper.py | 多轮 debater + Aggregator |
| AgentVerse | `agentverse` | 医学 MCQ | fm_agentverse_wrapper.py | Solver / Critic(多轮) / Evaluator |
| **MDAgents** | `mdagents` | 医学 MCQ(多模态) | fm_mdagents_wrapper.py | Recruiter + Expert_0..4 |
| **ClinicalAgent** | `clinical_agent` | 临床试验结局预测(二分类/概率) | fm_clinical_agent_wrapper.py | **Planner + SafetyAgent + EfficacyAgent + EnrollmentAgent + Reasoner(共 5 个)** |
| **CMAS** | `cmas` | 零样本 NER | fm_cmas_wrapper.py | TRFExtractor + Discriminator + OverallPredictor |

前 3 个是原 AEGIS 自带;后 3 个(加粗)是本轮工作新加的。

### 已集成的数据集

| 数据集 | task_type | 转换器 | verifier | 评分方式 |
|---|---|---|---|---|
| MedXpertQA-Text | mcq | data_processing/medical/convert_medical_datasets.py | medical_verifier.py | A-J 字母 MCQ |
| MedXpertQA-MM | mcq | 同上(`--images_dir`) | 同上 | A-J MCQ + **多模态图像** |
| MedConceptsQA | mcq | 同上(16 子集) | 同上 | A-D MCQ |
| trial_success | **probability** | 同上(`--csv_path`) | medical_verifier.py `_verify_probability` | `<final_result>0.X</final_result>` 阈值 0.5 二分类 |
| wikigold | **ner** | **data_processing/ner/convert_ner_datasets.py** | **aegis_core/utils/ner_verifier.py** | 实体级 micro-F1(精确匹配) |

### 关键基础设施改动(本轮做的,都已验证)

1. **多模态端到端**(5 层):`core/task.py` 加 `image_paths` → `main.py` 的 `_resolve_sample_image_paths()`(运行时解析,`--images_dir` 优先,多层回退)→ 各 wrapper 的 `_attach_task_images()`(装在 capture/injection 之前)→ `mas_base.call_llm(images=)` → `_attach_images_to_messages()` 转 OpenAI 多模态格式。**MDAgents 的 Recruiter/Classifier 显式传 `images=None` 跳过图片**(省 token)。

2. **诊断日志**:`methods/utils.py:handle_retry_error` 现在打印真实异常类+消息(以前只打 "Retry failed",吞了真相);`mas_base.call_llm` 的 API 失败带 `model/has_images/payload_bytes` 上下文。`AEGIS_RETRY_VERBOSE=full` 看完整 traceback。

3. **`reasoning_effort` bug 修复**:以前子串匹配 `"gemini-2.5-flash" in model_name` 会给 `gemini-2.5-flash-lite` 也加 `reasoning_effort="none"`(非法值,导致 400)。现在只对非 lite 且 config 显式设置时才加。

4. **verifier bug 修复(重要)**:`trial_success` 这类 probability 二分类,以前 `llm_primary` 模式下 LLM judge 会覆盖确定性阈值判断(judge 不懂 0.5 阈值,把 0.72 vs gold=1 判成 INCORRECT)。现在加了 `DETERMINISTIC_AUTHORITATIVE` 集合,这类任务**确定性判断优先**,只有无法提取答案时才问 judge。**影响极大**:用户的 clean 文件 200 条里 126 条被错判,修复后准确率 7.5%→70.5%,有效样本 15→141。

5. **离线重算脚本** `scripts/recompute_trial_success_verdicts.py`:给 verifier 修复**之前**跑的旧结果文件用,不重新调模型,直接读 `predicted_probability` 重算 `is_correct` / `is_valid_normal` / `is_valid_error` / 所有 `verification` 子字段。支持 `--dry_run` / `--no_backup` / 递归 `--glob`。

6. **Windows MAX_PATH**:`generate_diverse_dataset.py` 的 config_label 做过缩短(abbreviation + hash),缓解 260 字符限制。用户已把项目移到短路径 `F:\AEGIS-main\` 规避。

### ClinicalAgent 本轮的重大修正(用户提的 5 点)

用户看轨迹日志发现问题,已全部修复(新会话若再问,这是最新状态):
- **删掉了 ClinicalAgent orchestrator agent** → 现在 5 个 agent(原论文本就是 5 个,协调职责并入 Planner)。
- **子 agent 不再越界**:每个子 agent 只收它那一维需要的背景(Safety/Efficacy 只拿药+病,Enrollment 只拿 criteria),**不再传完整 question**;system prompt 明确 "SOLE responsibility ... Do NOT analyze [其他维度]"。
- **子 agent 输出维度分数**:`<safety_score>` / `<efficacy_score>` / `<enrollment_score>`。
- **Reasoner 做加权计算**:公式 `p = 0.30*safety + 0.40*efficacy + 0.30*enrollment`(权重在 config `dimension_weights` 可配),显式展示算术。

---

## 2. 待解决 / 待确认(接力点)

### 🔴 最高优先:注入频率的跨框架不一致(用户正在决策)

用户最后问的问题,已给出完整分析,**等用户选方案**。核心发现:

| 框架 | 同一 agent 多次出现? | 默认注入行为 | 有 `inject_every_invocation` 开关 |
|---|---|---|---|
| DyLAN | 是(跨轮) | **每次出现都注入** | ❌ 无 |
| AgentVerse | 是(Critic 跨轮) | **每次出现都注入** | ❌ 无 |
| LLM-Debate | 是(debater 跨轮) | **每次出现都注入** | ❌ 无 |
| MDAgents | 可能(若开 debate_rounds) | **默认只第一次** | ✅ 有 |
| ClinicalAgent | 否(线性) | 只第一次(实为 no-op) | ✅ 有 |
| CMAS | 否(线性) | 只第一次(实为 no-op) | ✅ 有 |

**不一致根源**:3 个原 AEGIS 框架(dylan/agentverse/llm_debate)用 `role_index = node_idx % num_agents` 把 round 消掉,keying 在 `(role, role_index)` 上且**无 `fired_keys` 去重**,所以每轮都注入;我新加的 3 个框架有 `fired_keys` + `inject_every_invocation` 开关,默认只第一次。对线性框架(CA/CMAS)无影响,但**跨框架对比时是混淆变量**。

两个待选方案(用户选哪个,就做哪个):
- **方案 A(归因研究友好)**:全部只注入一次。需给 dylan/agentverse/llm_debate 三个 wrapper 加 `fired_keys` 去重 + `inject_every_invocation` 开关(默认 false)。
- **方案 B(鲁棒性测试友好)**:全部每次都注入。把 mdagents/clinical_agent/cmas 的 YAML 默认改成 `inject_every_invocation: true`。

**新会话第一件事:问用户选 A 还是 B,然后统一实现 + 验证 + 在所有相关 YAML 写清默认值。**

### 🟡 已知局限(非 bug,如实告知用户过)

- **确定性工具全部 stub**:ClinicalAgent 的 DrugBank/Hetionet/risk_model/enrollment 用固定占位字符串替代;CMAS 的 GPTEmb KNN 检索用 stub_topk(取前 N 条 demo)替代。所以**论文的 PR-AUC / F1 绝对指标复现不了**,只有多智能体轨迹结构是真的。用户知情接受(他要的是注入轨迹,不是复现 SOTA)。
- **probability 注入不保证翻车**:factory 注入时不知道 gold,只能让 LLM"输出相反概率",约一半样本会真翻。
- **MedXpertQA-MM 成本**:每样本每个非规划 agent 都发图,MDAgents intermediate 模式 4 次/样本,2000 题全集 ≈ 8000 次多模态调用,先 `--limit` 试。
- **responses.create() 状态管理**:用户问过能否用 OpenAI Responses API 做服务端上下文管理。结论:**不能**,因为 (a) AEGIS 全线 chat.completions 架构,换了要重写注入引擎;(b) 用户用的 grok/gemini 走 OpenAI 兼容代理,不支持 previous_response_id/Conversations API;(c) 服务端状态会破坏注入的可控性。用现有的 messages 手动传递已达到等价的"总-分-总"信息流。

---

## 3. 用户环境 & 跑法

- Windows,GBK locale(代码里到处强制 UTF-8),项目在 `F:\AEGIS-main\`。
- 模型:`gemini-2.5-flash-lite`、`grok-4-1-fast-reasoning`,走 OpenAI 兼容代理。
- 沙盒每轮重置;新会话需从 `AEGIS-main.zip` 恢复(`cd /home/claude && unzip -q .../AEGIS-main.zip`)。

典型命令(API key / model_url 要用户自己填进 YAML):
```bash
# 转数据集
python data_processing/medical/convert_medical_datasets.py --dataset trial_success --csv_path <path>/trial_success.csv --limit 200
python data_processing/ner/convert_ner_datasets.py --dataset wikigold --data_dir <path>/CMAS/data/wikigold --split test

# 单跑 clean / inject
python main.py --method_name clinical_agent --experiment_config experiments/fm_injection/medical/clinical_agent_medical_normal.yaml --dataset_file ./datasets/data/trial_success.json --test_dataset_name trial_success --model_name grok-4-1-fast-reasoning --no_inject

# 多样化批量(注意 cmas 用 ner 目录的 yaml)
python scripts/generate_diverse_dataset.py --frameworks clinical_agent --num_configs 15 --targets_per_config random --dataset_file ./datasets/data/trial_success.json --test_dataset_name trial_success --model_name grok-4-1-fast-reasoning --workers 8 --seed 1234 --output_root results_diverse/<model>

# 配对(clean valid + inject valid 交集)
python scripts/build_paired_dataset.py --clean <clean.jsonl> --inject_root <dir> --output_dir <out>

# MM 多模态要加 --images_dir
python main.py --method_name mdagents ... --images_dir F:/AEGIS-main/datasets/medxpertqa_images
```

---

## 4. 关键文件地图(VERBATIM)

- 框架:`methods/{mdagents,clinical_agent,cmas}/{__init__.py,*_main.py,configs/*.yaml}`;注册在 `methods/__init__.py:method2class`
- wrapper:`aegis_core/agent_systems/fm_{mdagents,clinical_agent,cmas}_wrapper.py`
- 数据转换:`data_processing/medical/convert_medical_datasets.py`、`data_processing/ner/convert_ner_datasets.py`
- verifier:`aegis_core/utils/{medical_verifier.py,ner_verifier.py}`
- 实验 YAML:`experiments/fm_injection/medical/{mdagents,clinical_agent}_medical_{inject,normal}.yaml`、`experiments/fm_injection/ner/cmas_ner_{inject,normal}.yaml`
- 脚本:`scripts/{generate_diverse_dataset.py,build_paired_dataset.py,recompute_trial_success_verdicts.py}`
- 注入引擎:`aegis_core/malicious_factory/fm_malicious_system.py`(`_WRONG_ANSWER_FOR_TASK` 含 mcq/numeric/error_correction/open/probability/ner)
- 核心:`main.py`、`core/task.py`、`methods/mas_base/mas_base.py`

---

## 5. 需要上传给新会话的资源清单

见同目录 `HANDOFF_RESOURCES.md`。最关键的是 `AEGIS-main.zip`(完整最新代码)。
