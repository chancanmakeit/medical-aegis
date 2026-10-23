# medical-aegis 会话交接文档

> 最后更新：2026-10-22 晚（会话 v10 讨论第 10 轮，issue 我方第 38 轮）。**先读下面的"当前状态"**，第 0 节以后是累积的背景，部分内容已过时，以"当前状态"、discussion_log_v10 和 discussion_log_v9 的最新几轮为准。

## 当前状态（v10 讨论第 1 轮，2026-10-21 晚）

**v10 第 1 轮新增**：`_shamstyle2` 的 mock 冒烟测试已通过（4 框架 × 3 题：`sham_variant = style_v2_<i>`，导出后 run_id 全部唯一，`--new_sham_style_only` 正确剔除 `style_v1`），细节见 discussion_log_v10 第 1 轮。**v10 第 2 轮**：用户让先问 MHT 意见，已发我方第 31 轮（comment 6332128581），列方案 A $6.0 / B $5.75 / C $4.25 / D $3.0，等 MHT 回复；下一条我方编号为第 32 轮。**v10 第 3 轮**：MHT 第 43 轮（comment 6332274175）发现带说明的注入（PI、sham、sham_style）会抑制 markdown，TF-IDF 门槛看不到；我方已复算确认，RC 无此差异。MHT 建议补齐 A–D 都先不批，先修生成端，再做小样本验证，我方同意。我方第 30 轮的“MAC 约 3400 步”有误，实际是总步数，可填充的只有几百步。待用户决定：是否先改生成端（零费用），以及验证小样本跑 sham（约 $0.3）还是 sham+PI（约 $0.6）。**v10 第 10 轮**（commit `a8a99e9`，issue 第 38 轮）：
- **PI 和 sham 很少落在同一槽位**（完全相同槽位 0–14%）：目标按 `(seed, 题目 id, run_index)` 各自抽取。新增可选配置 `injection_plan.pair_target_runs: [[1,2,3]]`，默认关闭，PI 的抽取保持不变。
- llm_debate 的 fmt_v1_1 让 PI 更好认（配对差 +0.24 / +0.30，CI 不覆盖 0），对 sham 没有改善，不照原样扩大。提议 fmt_v1_2：只靠格式签名重采样，不加说明文字。
- mdagents 的 `match_opener` 已实现（记录 n_tries 和 format_matched）。
- MAA 排除：导出时用 `--maa_exclusion docs/requests/maa_exclusion_v1.json`。
- 已回答 MHT 的 5 个字段问题。
- 待用户决定：mdagents 开头筛选验证约 $0.14（建议开启配对）；llm_debate fmt_v1_2 10 题约 $0.09；锚点 sham 用配对目标重跑约 $1.4（等 MHT 意见）。

**锚点数据（只用 llama-4-maverick；用户说明它就是 llama，不用再核实，`served_model` 只作元数据）**
- 4 个锚点家族：medagents_mc、mac_groupchat（MAC）、llm_debate、mdagents。MA-RAG、KAMAC 已放弃，TAO 不推荐。
- 题目：`datasets/data/anchor_medxpertqa100.json`（100 题，取自 MedXpertQA-Text 难度区间）。所有框架的轮次上限为 2（主数据也一样）。
- 已完成：normal 100 题 × K=3（4 个框架）；注入 run 0 = RC inplace（100 题）；run 1 = PI（长度匹配版）、run 2 = sham、run 3 = sham_style，**各只做了前 50 题**。
- 配置：`experiments/fm_injection/anchor/<fw>_{normal,inject}.yaml`（`strategy_cycle: [response_corruption, prompt_injection, sham, sham_style]`）。
- **原始结果已入库**：`data_runs/anchor_llama_2026-10-21/*.jsonl.gz`（40 MB）。恢复、续跑、导出、门槛的完整命令见该目录的 `README.md`。
  - 门槛用的导出（2192 条运行）：`docs/requests/samples/anchor_gate_2026-10-21/gate7_export.jsonl.gz`，由 `scripts/build_anchor_gate_export.py` 从全量导出（2500 条）中筛出。
- 运行器：`scripts/runners/anchor_run.sh <fw> <normal|inject> [limit]`（环境变量 OUT / SUFFIX / EXTRA）。它从 `/home/claude/.mht_api.env` 读密钥，生成的 api config 和 YAML 都在 OUT 目录，权限 600，**不要提交**。
- 密钥文件 `/home/claude/.mht_api.env` 在新会话里需要重建：从 Project 文档「api端点」读取，至少要有 `AIHUBMIX_API_KEY`。

**质量门槛**（`scripts/quality_gate.py`，`--features tfidf|minilm`，以 CI 判读）
- RC inplace 全部 pass；sham 全部 pass；sham_style 在 medagents 上 FAIL（旧措辞里的 firmly、colleague 被照抄），已改为 6 种措辞轮换，并记录 `sham_variant`（尚未重跑）。
- PI 对自然答错：llm_debate、MAC 仍 FAIL；mdagents、medagents pass。PI 对 sham：medagents、mdagents、MAC 的 CI 覆盖 0.5；llm_debate 分得开。
- MHT 决定：llm_debate 的 PI 不进训练，只作压力测试子集；不做对抗过滤；PI 只作训练信号，评测只用自然失败和 RC 的 flipped。

**来源（sources）分析**（`scripts/sources_provenance_analysis.py`，结果在 `docs/requests/samples/anchor_gate_2026-10-21/sources_analysis.txt`）
- 锚点数据的 sources 都是生成时由代码记录的，没有任何推断出来的来源。
- 注入不改变 sources：注入运行与 normal 的一致率和两次 normal 之间的一致率相同。
- 读取集有变化的只有 MAC（发言者由 LLM 选择）和 medagents 的 revision/decision；llm_debate、mdagents 的读取集完全由协议决定。

**待办**
1. **待用户批准（约 $6.0）**：
   - 补齐剩下 50 题的 PI 和 sham（4 个框架，约 $3.0）；
   - sham_style 用新措辞跑全部 100 题，写到新文件 `_shamstyle2`（约 $3.0）。
   - llm_debate 的 PI 只作压力测试，不补可省约 $0.25。
   - 明细见 discussion_log_v9 第 24 轮。
   - 小提示：两个门槛不要同时跑到同一个输出文件；`pgrep -f` 会匹配到等待循环自身。
   - mock 冒烟测试已完成（v10 第 1 轮），批准后不必再做。
2. 补齐后重新导出，用 `build_anchor_gate_export.py --new_sham_style_only` 筛选，跑两种门槛（TF-IDF + MiniLM），把结果和导出提交到 `docs/requests/samples/`，在 issue 里通知 MHT。
   - issue 最新：我方第 31 轮（comment 6332128581，v10 第 2 轮），就补齐预算征求 MHT 意见。下一个我方编号是第 32 轮。
3. 主数据（其他框架、正式配置 `experiments/fm_injection/formal/`）的生成方案还没开始，等锚点定稿。

---

> 新会话按顺序读：**本文件** → `docs/discussion_log_v10.md`（当前会话记录）→ `docs/discussion_log_v9.md`（上一会话，锚点和门槛的逐轮细节）→ `docs/discussion_log_v8.md`→ 需要时再读 `docs/HANDOFF_prev_session.md`（AEGIS 原代码会话的技术交接）和 `docs/requests/`（MedHyperTrace 的需求规格）。
> 资源清单见 `docs/HANDOFF_RESOURCES.md`。

---

## 0. 项目与用户

- **项目**：claude.ai Project「医学多智能体系统模拟故障轨迹以及真实故障轨迹获取」。在 AEGIS（多智能体故障注入 + 失败归因，arxiv 2509.14295，ICLR 2026）的基础上，为**医学多智能体系统**生成两类轨迹：注入故障的错误轨迹，以及不注入的正常轨迹。语料供姊妹项目 **MedHyperTrace** 训练超图基础模型（HGFM），做跨框架零样本的故障归因。
- **用户**：Alvin Chan。偏好直接的同行级交流和诚实的批评；经验性结论要对着真实数据或代码核实，不要假设。讨论用中文，代码注释用英文。
- **用户的工作约定**（Project 说明）：
  - 每轮更新带版本号的讨论记录（`docs/discussion_log_vN.md`），并更新本文件，推送到 `medical-aegis`。
  - 子 agent 要合理使用，考虑模型切换带来的 token 开销；用户点名时用 Sonnet 子 agent。
  - `sleep` / `timeout` 不要设得太长。
  - **调用 LLM API 前，先小规模试跑估算成本，然后停下来问用户**。
  - 密钥只放在沙箱本地的 `/home/claude/.mht_api.env`，**不写进仓库**。
- **两个项目之间的沟通**：通过 GitHub issue：https://github.com/chancanmakeit/medical-aegis/issues/1 。
  - 会话里只能用 REST：`gh api repos/chancanmakeit/medical-aegis/issues/1/comments -F body=@file.md`。GraphQL 被禁用，`gh issue list` 不能用。
  - 每次回复开头写"发件方 / 依据（commit）"；需要用户拍板的事项标"待用户决定"。
  - 用户要求：有重要进展就在 issue 里通知 MedHyperTrace。

## 1. 恢复环境（新会话照做）

1. `add_repo(owner="chancanmakeit", repo="medical-aegis", access="push")`，然后 `git clone https://github.com/chancanmakeit/medical-aegis /home/claude/medical-aegis`。
   - clone 和 push 都走会话代理，**不需要 token**，也**不要**把 token 写进 `.git/config`。
   - 会话内无法新建 GitHub 仓库（`POST /user/repos` 返回 403）。
2. `cd /home/claude/medical-aegis && pip install --break-system-packages -r requirements.txt`。torch、transformers、wandb 可以跳过。只有重新预处理 ConSensus 原始数据时才需要额外的 `neurokit2 mne fire datasets`。Python 3.13 已验证可用。
3. **密钥**：从 Project 文档「api端点」中读取，写入 `/home/claude/.mht_api.env`（权限 600）。
   - 仓库里的 YAML 和 `model_api_configs/model_api_config.json` 只有 `YOUR_API_KEY` 占位符。真实运行时另建一份 api config（放在仓库之外或 scratch 目录），**不要提交**。
   - MiMo 的条目示例：`{"model_name": "mimo-v2.6-flash", "model_url": "https://api.xiaomimimo.com/v1", "api_key": "...", "extra_body": {"thinking": {"type": "disabled"}}}`。
4. **MAM 的音频文件**（没有提交到仓库）：按 `docs/HANDOFF_RESOURCES.md` 第 2 节，用 `data_processing/audio/convert_mam_datasets.py` 从 HF 重新生成。**所有运行都要在仓库根目录下执行**，因为音频路径是相对路径。
5. **离线自检**（不花 API 费用）：先运行 `python3 scripts/mock_openai_server.py --port 18080 --log <calls.jsonl> &`，再把 `model_api_config` 和 YAML 的 `llm_config` 指向 `http://127.0.0.1:18080/v1`，并设置 `NO_PROXY=127.0.0.1,localhost`。读集核对用 `python3 scripts/check_trajectory_sources.py <results.jsonl>`。

## 2. 框架清单（`main.py --method_name <name>`）

| 方法名 | 来源 | wrapper | 任务 / 数据集 | task_type | 状态 |
|---|---|---|---|---|---|
| dylan | 原 AEGIS，v9 第 6 轮迁移 | FMDyLANStructuredWrapper | 医学 MCQ | mcq | ✅；角色为节点角色名，`role_index = idx % num_agents`；Ranker 的 index 为 `num_agents` |
| llm_debate | 原 AEGIS，v9 第 6 轮迁移 | FMLLMDebateStructuredWrapper | 医学 MCQ | mcq | ✅；Agent(0..2)，round 从 1 开始；Aggregator(0) |
| agentverse | 原 AEGIS，v9 第 6 轮迁移 | FMAgentVerseStructuredWrapper | 医学 MCQ | mcq | ✅；角色显式设定（RoleAssigner / Solver / Critic(j) / Evaluator）；读取集按对象身份精确映射 |
| mdagents | 上一个会话，v9 第 6 轮迁移 | FMMDAgentsStructuredWrapper | 医学 MCQ（含 MedXpertQA-MM 图像） | mcq | ✅；图片是 task observation |
| clinical_agent（别名 clinicalagent） | 上一个会话，v9 第 6 轮迁移 | FMClinicalAgentStructuredWrapper | trial_success（需要 csv） | probability | ✅；即原论文的 5 agent 版本（数据里叫 clinical_agent5）。**v9 第 6 轮恢复了 Planner → lane 的子问题传递**（与上游一致；此前 Planner 是断开的）。工具是 stub 的 `is_tool` 步骤 |
| cmas | 上一个会话，v9 第 6 轮迁移 | FMCMASStructuredWrapper | wikigold NER | ner | ✅；⚠️ `ner` 注入仍回退到 mcq（用户决定暂不处理） |
| **medagents_mc** | 第 5 轮 | StructuredFMWrapper | MedConceptsQA、mmlu_pro_health | mcq | ✅ mock 回归通过 |
| **consensus** | 第 6 轮 | FMConSensusWrapper | `datasets/data/{sleepedf,wesad}.json`（`--test_dataset_name sleepedf/wesad`） | classification | ✅ |
| **consensus_debate / _mad / _reconcile / _cmd** | 第 6 轮（Sonnet 子 agent 移植，已和上游逐条比对消息） | FMConSensusWrapper | 同上 | classification | ✅ |
| **mam** | 第 7 轮 | FMMAMWrapper | `datasets/data/{heartbeat_b,heartbeat_a,sounddr}.json`（音频需要重新生成） | classification（自由文本） | ✅；音频后端是 mimo-v2.6-flash，已做 1 次真实探测，格式可用 |
| MedAgent-Pro | — | — | REFUGE2 | — | **用户决定暂不做**（上游缺少分割工具，plan 在病例之间共享） |
| **triage_agent**（别名 triageagent） | v9 第 3 轮，移植自用户仓库 `chancanmakeit/TriageAgent`（HEAD `fdec6ee`） | FMTriageAgentWrapper | `datasets/data/triage_esi.json`（Test-1/2/3，216 条；`--test_dataset_name triage_esi`） | **classification_field**（字段式答案：`ESI level: N` / `Coarse class: HIGH\|LOW`） | ✅ mock 回归通过。RAG 检索结果预先算好，存在数据里，和上游运行的结果逐条一致（216/216） |

- 实验 YAML：`experiments/fm_injection/{medical,sensing,audio,ner,triage}/<name>_*_{normal,inject}.yaml`。端点和密钥都是占位符。
- 批量生成：`scripts/generate_diverse_dataset.py` 已经包含所有新框架的注入位点池。
- **所有 14 个框架都已使用结构化契约**。旧 wrapper（`fm_{mdagents,clinical_agent,cmas,debate,dylan,agentverse}_wrapper.py`）带 DEPRECATED 标记，只用于复现旧数据。注入默认只触发一次（方案 A），`inject_every_invocation: true` 为方案 B。
- 共享的 MCQ 答案解析：`methods/answer_parsing.py` 的 `mcq_answer`。

## 3. 共享基础设施（新框架要遵守的契约）

- **`aegis_core/agent_systems/fm_structured_wrapper.py`**：
  - `input_messages` 一律记录注入前的输入，注入版本放在 `injected_input_messages`，日志标记 `input_messages_are_clean: true`。
  - 多轮对话（`messages=` 方式调用）的注入只改最后一条 user 消息。
  - 注入目标可以额外指定 `phase` / `round`，每个目标记录 `fired`。
  - `is_tool` 步骤不参与调用对齐。
  - **每个 LLM 步骤都带 `llm_meta`**（v9 第 3 轮新增）：`reasoning`（供应商单独返回的推理文本：`reasoning_content` 或 `reasoning`；没有则为 null）、`finish_reason`、`prompt_tokens`、`completion_tokens`、`reasoning_tokens`、`max_tokens`、`model`。被 response_corruption 的步骤，`llm_meta` 描述的是篡改前那次干净调用。实现方式：`mas_base.call_llm` 把这些信息写进线程局部变量，wrapper 在调用返回后立即取走。**旧版 wrapper（mdagents / clinical_agent / cmas / dylan / llm_debate / agentverse）没有 `llm_meta`**。
  - 新增钩子 `before_injection(role, role_index, phase, round_)`：注入触发前调用，用来按 agent 设置工厂的答案字段和类别（Triage 在用）。
- **方法侧契约**：
  - 每次 `call_llm` 之前设置 `current_role` / `current_role_index` / `current_phase` / `current_round`。
  - 每次 LLM 调用只往 `conversation_history` 里写一条记录，包含 `step_id`、`sources`，可选 `source_how`（`excerpt` / `structured_field`）、`round`、`event_ids`、`agent_label`、`agent_id`、`observations`、`structured`。
  - ConSensus 系列复用 `methods/consensus/consensus_main.py` 中的 `SensingMASBase` / `SensingAgent`，读取集合会自动累积。
- **注入工厂**（`malicious_factory/` 和 `aegis_core/malicious_factory/` 两份**必须保持一致**，改完一份就 `cp` 到另一份）：
  - 支持的 task_type：mcq、numeric、error_correction、open、**classification**（JSON 和自由文本两种篡改都支持）、**probability**（直接替换标签里的值）、**classification_field**（v9 第 3 轮新增）。
  - `classification_field` 的篡改方式：把字段（`classification_field_regex`）的**每一处**取值都改成下一个类别（循环）；hedge 模式写成 "错误值 or 原值"，unsure 模式写成 "I am not sure"，label_only 模式只输出字段那一行。
  - `classification_field` 有自己的指令表和篡改表，措辞与领域无关。`classification` 的表里写的是 "sensor features"，不适合临床场景。
  - `ner` 仍然会回退成 mcq。
- **verifier**：
  - wesad / sleepedf / heartbeat_* / sounddr 按类别标签匹配，确定性结果优先（authoritative）。
  - triage_esi：读取 `ESI level: N`，N 在 `acceptable_answers` 里即算正确（有 1 条标签是 "4 or 5"）；确定性结果优先。自由文本时先看显式答案标记，再看是否只提到一个类别。
  - 显式答案不在类别表里时，视为无法判定。
  - 能识别 `Option: X` 这种写法。
- **`mas_base.call_llm`**：支持单次调用的 `max_tokens`、`audios=`（`input_audio` 的 data URI），以及从 model config 透传 `extra_body`。
  - 第 3 轮修了一个统计 bug：某个模型名的第一次调用以前只登记、不计数。
  - ⚠️ 推理模型如果 `content` 为 None（例如 token 用完时只返回了 reasoning），仍然按原逻辑抛错并重试。真实试跑时 max_tokens 要留足。
- **schema v1 导出器**：`python3 scripts/export_schema_v1.py <clean.jsonl> <inject.jsonl> ... --out x.jsonl [--reasoning omit|keep] [--strict]`。clean 和 inject 文件要一起传，才能配对。框架元数据来自 `configs/framework_registry.yaml`，**新增框架时要同时在这里登记 family、modality 和 description（描述要对照代码核实）**。`reasoning` 默认不导出，因为注入步的推理文本会泄漏标签。
- **方法侧可选字段 `task_observations`**：方法把共享观测注册为 `self.task_observations=[{id,type,...}]`，step 用 `observations: [id]` 引用；StructuredFMWrapper 会把它写进日志。
- **`trajectory_normalizer`**：步骤字段是**白名单透传**的。新增步骤字段时必须同时加进 `aegis_core/utils/trajectory_normalizer.py` 里的那个列表，否则会被静默丢掉（第 3 轮的 `llm_meta` 就踩了这个坑）。
- **`main.py`**：`Task.metadata['raw_sample']` 携带完整样本；断点续跑按**样本 id** 判断是否已处理（以前按 query，会漏跑）。
- **verifier 的数据集名**：取 `benchmark_name or --test_dataset_name`。sensing 和 audio 的 YAML 不写 benchmark_name，由命令行决定。

## 4. 决定与待办

**用户已决定（2026-10-20，v9 第 5 轮）**：
- **backbone（v9 第 10 轮更正）**：用户给的是一个**候选池**，并没有规定"一个模态对应一个 backbone"。候选包括 aihubmix 的 `mercury-2.5-preview` 和 `llama-4-maverick`（文本）、蚂蚁百灵的 `Ling-3.0-flash-VL`（多模态）、`mimo-v2.6-flash`（全模态），以及「api端点」文档里的其他模型。可以视情况选用，**但每次使用前都必须先问用户**。目前已获批：试点用 mercury-2.5-preview 和 llama-4-maverick。各框架能处理的模态记录在 `configs/framework_registry.yaml`。
- **旧 ClinicalAgent 注入数据：重跑**。需要先把 clinical_agent 迁移到 StructuredFMWrapper，并拿到 `trial_success.csv`（见 HANDOFF_RESOURCES）。
- **注入频率**：由两个项目在 issue 里商定。我方在 v9 第 5 轮提议：方案 A（每个目标只注入一次）为默认，方案 B 作为可选的鲁棒性子集。等 MedHyperTrace 回复。
- 下一步先做导出器和 K 次重复运行：**已完成**。

**用户新决定（v9 第 6 轮）**：
- cmas、dylan、llm_debate、agentverse 只迁移不重跑（已迁移）；mdagents 和 clinical_agent 要重跑（mdagents 是否包含在内待用户确认）。
- 文本 backbone 备选增加 aihubmix 的 `llama-4-maverick`（已核实存在）。

**MedHyperTrace 第 25 轮**：确认 10 个家族；建议锚点任务再加 macnet、autogen、camel；建议先做真实试点（medagents_mc + triage）。**冲突**：锚点任务需要通用框架的新数据，而用户决定通用框架暂不重跑，待用户决定。

**v9 第 7 轮的决定与发现**：
- 通用框架（dylan、llm_debate、agentverse 等）**只跑锚点任务**（100 道固定医学 MCQ），用户已同意。
- clinical_agent 要重新生成，数据用 HF `UUUooUUU/clinical-agents/trial_success-200.json`。mdagents 保留旧数据，另外按新流程生成新数据（详见 discussion_log_v9 第 7 轮）。
- 真实探测（`docs/requests/samples/real_probe_2026-10-20/`）：
  - mercury-2.5-preview 隐藏推理，89% 的 completion 是计费的 reasoning token，不返回推理文本；
  - 每条运行的成本：medagents_mc 用 mercury $0.029、用 llama $0.011；triage 用 mercury $0.013、用 llama $0.0026。价格按第三方列表价，aihubmix 实价未核实。
- 真实运行的脚手架（只放在 scratch，不入库）：
  - `real_api.json`：用 aihubmix 的 key 生成，权限 600；
  - 运行器：用 sed 把 YAML 的占位符替换成真实 key 和 URL，写成 scratch 下的 YAML，权限 600；
  - 参数：`--model_temperature 0.7 --model_max_tokens 4096`。

**v9 第 11 轮（2026-10-20 12:06–13:05）：试点完成**，报告见 `docs/pilot_2026-10-20_report.md`，数据见 `docs/requests/samples/pilot_2026-10-20/`：
- 400 条运行，估算成本约 $4.50。
- mercury 的 PI 20/20 失败：Inception 上游返回 403，拦截 "direct" 包装。已新增 `prompt_wrapper_style: simulation`（如实说明是研究模拟），实测可通过。**用 simulation 重跑 PI（约 $0.6）待用户批准。**
- MedAgents 对 Synthesizer 注入会自我纠正，翻转 0/30。有拓扑侧信道：normal 永远 1 轮，注入时 2 轮。注入目标的选择待与 MHT、用户商定。
- 修复：medagents 的 Reviser 读取集（专科名称冲突时后一条建议覆盖前一条）。另有 `scripts/repair_medagents_advice_sources.py`；导出器跳过 `llm_api_failure`；检查脚本的 excerpt 匹配先规范化空白。
- 并行：main.py 已支持样本级线程池（`--max_workers`），线程安全。试点 16 路并发，0 次 429。
- MHT 第 27 轮：锚点用 8 个家族（加 macnet 重移植、mav、camel 改造；不用 autogen）；模板风格捷径有风险，建议做改写池；建议启用 `mam_text_model_name`。**这三项都待用户决定。**

**v9 第 12 轮（13:12–13:50）**：
- 用户决定：
  - mercury 按推荐用 simulation 重跑：已完成，40/40 成功，约 $0.60；
  - 改写池按推荐做：已试点，$0.115；全量约 $0.26–0.35，待批准；
  - MAM 和 mdagents 的文本步骤考虑用 mimo-v2.6-flash 或 gemini-2.5-flash-lite-nothink，我方已回复意见，待用户确认。
- 修复：MCQ 的 RC 不再固定篡改成 "A"，而是随机抽取，并排除原答案和正确答案；ESI 改为相邻一级；导出器 run_id 区分 wrapper 和改写池。
- MA-RAG / MDTeamGPT（子 agent 只读评估，代码在 `/home/claude/ext_repos/{MA-RAG,MDTeamGPT}`）：
  - MA-RAG ≈ llm_debate + 检索：MMLU-Pro 题目格式现成可用，但依赖 logprobs、`n=` 采样和 MedCorp/BM25；
  - MDTeamGPT ≈ medagents：是 Streamlit/LangGraph 演示版，带知识库（必须冻结或关闭）和联网工具（要关），输出是自由文本；
  - 两者都没有 LICENSE 文件。
- SLAKE 不在 HF 账户 UUUooUUU 的 datasets 里，也没有可见的 collection，需要用户给链接。
- 可用性：aihubmix 的 gemini-2.5-flash-lite-nothink 目前返回 no_available_channel；gemini-2.5-flash-lite 可用。

**v9 第 13 轮（2026-10-21）**：见 discussion_log_v9 第 13 轮。下一会话的重点：
- **待用户批准**：MedXpertQA-Text 难度筛选（500 题 × K=4 × 2 个 backbone，约 $4.5）。批准后运行：
  `python3 scripts/screen_difficulty.py --dataset datasets/data/medxpertqa_text.json --model <m> --base_url https://aihubmix.com/v1 --api_key_env AIHUBMIX_API_KEY --n_questions 500 --k 4 --out <scratch>/screen_<m>.jsonl`
  然后用 `--select` 选出难度区间内的题。
- **待用户决定**：是否纳入 KAMAC 和 MAC（我方推荐两个都纳入，TAO 不要），以及锚点组合（现有 5 个 + mav + macnet + MA-RAG + KAMAC + MAC，MDTeamGPT 可选）。
- 正式生成的配置：`experiments/fm_injection/formal/*_pool.yaml`，包含 targets_pool、simulation 包装、`rc_mode: inplace`、`rc_fallback: pi` 和 PI 改写池。**每种配置先跑一小批，过 `scripts/quality_gate.py`（自然答错 AUROC ≤ 0.7）。**
- MAM：文本模型用 Ling-3.0-flash（Ant Ling 端点），音频模型用 mimo-v2.6-flash。model_api_config 里要有这两个模型。容器里缺 `datasets/audio/`，需要从 HF UUUooUUU/Heartbeat 等仓库重新下载。
- 外部仓库（只读）：`/home/claude/ext_repos/{MA-RAG,MDTeamGPT,KAMAC,tao,Multi-agent-conversation-for-disease-diagnosis}`。KAMAC 是 GPL-3.0，必须自己重写，不能拷贝代码。

**v9 第 14 轮（MHT 第 29 轮）**：
- 门槛 CI、`effective_strategy`、干扰项加权抽取、打乱选项的污染检查都已实现。
- **KAMAC / MAC 移植时的契约要求**（MHT 第 29 轮第 4 节）：
  - 被选中、路由或招募的步骤，在 sources 里把决策步标为 `how: "control"`；
  - MAC：选择发言者的调用记成 step，带 `structured.next_speaker`；supervisor 的步骤带 `structured.terminate`；
  - KAMAC：招募步带 `structured.recruits=[{agent_id, specialty}]` 和 `knowledge_gap`；定向消息每条一个 step，带 `structured.to=[...]`，只有真正的接收者在后续步骤里把它列为来源；
  - 新招募的 agent 的 id 为 `recruit_<k>`；注入目标池要支持角色模式（例如"第 k 个被招募专家的第一次作答"），解析不到就是 not_fired；
  - 家族名：MAC 为 `groupchat`，KAMAC 为 `kamac`。
- 锚点（两个项目一致的方案，等用户确认）：10 个家族，即 mdagents、medagents、dylan、debate、agentverse、mav、macnet（重新移植）、MA-RAG（`retrieval_debate`）、KAMAC、MAC；MDTeamGPT 可选。

**v9 第 15–17 轮（2026-10-21）**：
- 用户决定：锚点用 4 个家族（mdagents、medagents、KAMAC、MAC），不用 MA-RAG；省钱方案"性价比高就用"，等 MHT 意见（我方倾向只用 llama、K=4）。
- 难度筛选完成（$4.58）：没有背题迹象；区间内的题共 217 道，见 `datasets/data/medxpertqa_text_band.json`；锚点 100 题草案为 `datasets/data/anchor_medxpertqa100.json`（取自 llama 的区间内题目）。
- KAMAC（`--method_name kamac`）和 MAC（`--method_name mac_groupchat`）已移植并通过 mock 测试，配置在 `experiments/fm_injection/anchor/` 和 `formal/`。待用户决定：KAMAC 的初始专家数（上游默认 1）和消息投递方式（upstream / inbox）。
- 下一步：小规模真实试跑，估算 4 个锚点家族在 llama 上的单价，**先问用户**。
- 远端残留一个 `wip-kamac-mac` 分支：代理不允许删除，内容已全部合并进 main，可以在 GitHub 网页上手动删掉。
- mock 服务器：`scripts/mock_openai_server.py` 会加载 `scripts/mock_rules/*.py` 里的插件规则。不要用 `pkill -f mock_openai_server`，它会把当前 shell 也杀掉。

**待办（按顺序）**：
1. ~~(b) 迁移旧 wrapper~~：v9 第 6 轮完成（6 个框架，全部 mock 通过）。
2. **(c) 真实模型试跑**：先小规模估算成本，**停下来请用户确认**。注意推理模型的 max_tokens 要留足。
3. **待 MedHyperTrace 确认**：`framework_family` 分组（debate 家族 = llm_debate + 4 个 consensus 基线）；注入频率；backbone 和模态完全重合的问题（spec §5 建议 ≥2 个 backbone 交叉）。
4. **待用户提供**：本地还有哪些 normal 轨迹；`trial_success.csv`；MedXpertQA 的图片。

## 5. MedHyperTrace 的需求（尚未完成的部分）

规格：`docs/requests/2026-10-19_from_medhypertrace_HGFM_trajectory_spec_v1.md`（含 v1.1 增补），以及 issue #1 第 24 轮的评论。

| 项 | 优先级 | 状态 |
|---|---|---|
| 干净的 `input_messages` | P0 | 新框架 ✅；旧的三个 wrapper ❌（MedHyperTrace 已离线修复旧数据） |
| `labels` 与 `steps` 物理分离 | P0 | ✅ `scripts/export_schema_v1.py`（step 字段走白名单） |
| 跨阶段稳定的 `agent_id` | P0 | ✅ 所有结构化框架都在方法侧记录（v9 第 5 轮补齐 medagents_mc 和 consensus 系列）；旧版框架由导出器生成 `<role>_<idx>` |
| `structured`（answer / vote / confidence） | P0 | ✅ 所有结构化框架（medagents_mc 的投票带 on_report_step；Advisor 带 responds_to_vote_step） |
| `framework_family` | P0 | ✅ 写在 `configs/framework_registry.yaml`；debate 家族的分组待 MedHyperTrace 确认 |
| `question_id` / `run_index`，同一题跑 K 次 | P0 | ✅ `main.py --num_runs K [--run_index_start N]` |
| `sources` 及 `how` | P1 | 新框架 ✅（未标注的视为 verbatim）；medagents_mc 的 Classifier 应标 structured_field，Synthesizer 应标 excerpt，尚未补 |
| `task.observations[]` | P1 | ✅ ConSensus 系列的特征块和 MAM 的音频，由导出器转成 `task:obs:<id>` 引用 |
| 锚点任务：100 道 MCQ，所有能跑 MCQ 的框架都跑 | 建议 | ❌。注意 ConSensus 系列跑不了 MCQ，MCQ 框架家族目前只有 5 个 |

## 6. 已知坑

- **TriageAgent 的上游解析器很宽松**：它先找 `ESI level: N`，找不到再找 "final … ESI N"，再找 "ESI N"。所以在 Coordinator 上做 "unsure" 一类的篡改时，可能会被正文其他地方提到的等级"救回来"（mock 中实测到过）。这是真实系统本来的行为，有意保留，没有改。
- TriageAgent 的 mock 回归需要 `scripts/mock_openai_server.py --reasoning`，这样才会返回 `reasoning_content`。
- **全量 mock 回归的做法**（v9 第 6 轮）：
  - MCQ 用 medagents_mc 的 mock 样例拼一个小数据集；mdagents 再加一道带 2×2 PNG 的题。
  - clinical_agent 用 2 条合成的 trial 记录；cmas 用 2 句 NER 加一个 2 条的示例池，需要 YAML 里写 `cmas_demo_pool_path`。
  - MAM 需要占位 wav，跑完要删掉 `datasets/audio`。
  - 汇总脚本的思路见 discussion_log_v9 第 6 轮。
- AgentVerse 在 inject 时，被篡改成 "A." 的 evaluator 输出太短，读取集检查会报 not_found。这是检查脚本最短探针长度造成的假阳性。
- 真实模型会在输出开头复述 prompt 里的人设，也会原样转引上游内容。读取集检查的 unlisted 判定（v9 第 7 轮）因此改为：从输出正文的第 60–140 个字符取探针，并排除已登记来源转载的文字。
- 导出器的 `run_id` 中包含模型名（v9 第 7 轮修复了跨 backbone 冲突）。
- 方法按位置传 `messages` 时，StructuredFMWrapper 现在会自动转成关键字参数（v9 第 6 轮修复了 prompt 被传两次的 bug）。
- 重建 Triage 数据需要 TriageAgent 的 clone 和 `pdftotext`（沙箱里已有）。用的是 numpy 版 TF-IDF，不需要额外安装依赖。

- 结束 mock 进程**不要**用 `pkill -f mock_openai_server`，它会匹配到执行命令的 shell 自身（exit 144）。应该用 `ps -eo pid,args | awk '$2 ~ /python3/ && /mock_openai/ {print $1}' | xargs -r kill`。
- 沙箱里**没有** `/usr/bin/time`。
- HF 的 tree API 加 `recursive=true` 时单页最多 1000 条，会截断。要分目录查（第 4 轮曾因此误判 REFUGE2 不完整）。
- `datasets/` 在 `.gitignore` 里，提交数据 JSON 要用 `git add -f`。
- 停止钩子会要求提交所有改动。子 agent 还在编辑的文件，可以用 `git update-index --cacheinfo` 提交占位版本。
- 沙箱每次会话都会重置，`/home/claude/ext_repos`、`/home/claude/data_*` 都需要重新获取。
- 资源：2 个 CPU 核，7 GB 内存，可用磁盘约 28 GB。

## 7. 文件地图（新增和改动）

- 框架：
  - `methods/{medagents_mc, consensus, consensus_baselines, mam, triage_agent}/`
  - 旧框架：`methods/{mdagents, clinical_agent, cmas, dylan, llm_debate, agentverse}/`
- wrapper：`aegis_core/agent_systems/fm_{structured, medagents_mc, consensus, mam, triage_agent}_wrapper.py`
- 数据转换：
  - `data_processing/medical/convert_medical_datasets.py`
  - `data_processing/sensing/convert_consensus_datasets.py`
  - `data_processing/audio/convert_mam_datasets.py`
  - `data_processing/triage/convert_triage_dataset.py`（需要 `--triage_repo <TriageAgent clone>`）
  - `data_processing/ner/…`
- 数据：`datasets/data/{sleepedf, wesad, heartbeat_b, heartbeat_a, sounddr, wikigold, triage_esi}.json`
- 脚本：
  - `scripts/mock_openai_server.py`：带各框架的规则和通用的 JSON 填充。
  - `scripts/check_trajectory_sources.py`
  - `scripts/generate_diverse_dataset.py`
  - `scripts/build_paired_dataset.py`
  - `scripts/recompute_trial_success_verdicts.py`
- mock 样例：`docs/requests/samples/*_mock_{clean,inject}.jsonl`（共 8 个框架；triage_agent 另有 `_mock_inject_multi`，含 3 个篡改目标）。
- 讨论记录：`docs/discussion_log_v1..v9.md`。
- 框架注册表：`configs/framework_registry.yaml`。导出器：`scripts/export_schema_v1.py`。schema v1 样例：`docs/requests/samples/schema_v1_mock_export.jsonl`。
