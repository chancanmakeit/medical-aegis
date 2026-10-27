# medical-aegis 会话交接文档

> 最后更新：2026-10-26（会话 v10 讨论第 14 轮，issue 我方第 42 轮）。**先读下面的"当前状态"**，第 0 节以后是累积的背景，部分内容已过时，以"当前状态"、discussion_log_v10 和 discussion_log_v9 的最新几轮为准。

## 当前状态（v10 讨论第 16 轮，2026-10-26）

逐轮细节见 `docs/discussion_log_v10.md`（第 1–16 轮）。

**第 16 轮（本轮）：三项付费任务已准备好，等用户确认（合计约 $0.46）**
1. **分叉试点**（约 $0.31；MHT 第 62 轮续：中训练试点已有结果，请我们启动）。
   - 代码：`scripts/branch_replay_server.py`、`scripts/branch_pilot.py`。工作目录 `/home/claude/branch_pilot`，不入库，候选点文件 `{fw}_candidates.jsonl` 已生成并带 D(t)。
   - 设计：1 分叉 + 1 对照。第 t 步：分叉臂按 0.7 请求真实 API，对照臂返回记录；D(t) 里的步骤两臂都按温度 0 生成；其余从记录返回。D(t) 用记录 sources 的传递闭包。同输入请求按到达顺序区分。没翻转 = 未判定，不当负例；翻转点全部补跑对照（`run --arm control --rep 1 --only <qids>`），未翻转点抽一部分补跑。
   - 命令：每个框架 `run --arm branch|control --pass 0|1|2 --upstream real`，然后 `analyze`。
   - 已花：2+2 点真实试跑 $0.015（结果在 runs/ 下，正式跑会覆盖）。
   - 报告项（MHT 第 60、61 轮）：翻转 / 未判定比例、对照复跑不一致率、位置分布、第 t 步原文对其重采样的同槽位 AUROC、每次调用的 model（服务商不返回 `system_fingerprint`）、一个贪心续写导致一边倒的例子。第 3 个点基本都是 aggregation（D(t) 为空），要单独列。
2. **fmt_v1_2 验证**（约 $0.06）：`CFGNAME=llm_debate_inject_fmt_v1_2 SUFFIX=_v12 EXTRA="--num_runs 2 --run_index_start 1" bash scripts/runners/anchor_run.sh llm_debate inject 10`。报告：fmt_v1_2 − fmt_v1（`_pi5` / `_sham5`）的配对差（PI 和 sham，按题 bootstrap）、去掉首句后的结果、重采样拒收率。配对后 sham 的槽位与 `_sham5` 不同，要说明。
3. **mdagents 开头筛选**（约 $0.09）：`CFGNAME=mdagents_inject_opener_paired SUFFIX=_op EXTRA="--num_runs 1 --run_index_start 2" bash scripts/runners/anchor_run.sh mdagents inject 50`。报告：同槽位 AUROC（punct / char）、`format_matched = false` 比例、重试次数分布、配对目标在两条 run 里都落地的比例（PI 只有 `_pi5` 前 20 题）。
- 两项验证的 1 题试跑在 `/home/claude/anchor_runs_trial/`（共 $0.007）。

**第 16 轮做完的（不花钱）**
- 核对 MHT r61 的 A–E 修复：全部和 MHT 说的一致（`docs/requests/samples/public_spotcheck_2026-10-26/r61_recheck/`）。第 15 轮的 C 有一半错了：政策提示在 `task.observations` 里，抽查脚本已改。
- `phase_canonical` **v1 已采用**（用户决定，MHT 第 62 轮转达）：`configs/phase_canonical_v1.yaml`（magentic_one `instruction` → `plan`），导出器默认写入（`--phase_canonical none` 关闭）。MHT 的转换器直接 import 我们的 `scripts/phase_canonical.py`，**改接口要先通知 MHT**。
- fmt_v1_2：`pi_length_match.match_structure`（结构只进签名，note_version `fmt_v1_2`）。
- 服务商响应的 model 字段是 `google/gemma-4-31B-it-turbo`，与记录的 mdagents 运行相同；用户早已说明 backbone 就是 llama-4-maverick，不再核实。

**第 15 轮的结论（仍有效）**
- 回放：1,200 条真实 normal 运行重跑，13,379 次请求 100% 命中（`scripts/replay_openai_server.py`）。
- 公开数据抽查（140 条）逐字一致、无标签泄漏；`kind: "environment"` + `env_type` 已写进 `docs/mas_traj_schema_notes.md` 和 `check()`。
- 原始公开数据在 `/home/claude/public_mas/raw`（不入库；AgentRx 用用户的私有 HF 镜像 `UUUooUUU/AgentRx`，与 gated 原版一致，下载要 HF 令牌，取自 private-documents 的 `huggingface/` 文件，只放 `/home/claude/.hf_token`）；MHT r61 转换器在 `/home/claude/mht_ref/p2m_r61`，结果在 `/home/claude/public_mas/mas_traj_r61`。

**MHT 中训练试点 v1**（第 62 轮续）：纯文本 TAPT 在 MAA 上没有可测提升 → 不为纯文本中训练扩数据；结构感知中训练待用户决定。

**合成路线**：在真实轨迹上分叉为主，注入为辅，不让 LLM 整条写轨迹；不用 LLM 改写 agent 发言；人工真值（MAA、MAFA）永不用我们的流程重新标注。

**锚点数据**（只用 llama-4-maverick；用户说明它就是 llama，不用再核实）
- 4 个家族：medagents_mc、mac_groupchat（MAC）、llm_debate、mdagents；题目 `datasets/data/anchor_medxpertqa100.json`（MedXpertQA-Text 100 题），轮次上限 2。
- 已有：normal 100 题 × K=3；run 0 = RC（100 题）；旧说明的 `_pi4` / `_sham` / `_shamstyle`（不进训练）各前 50 题；fmt_v1 的 `_pi5` / `_sham5` 前 20 题 × 4 框架（mdagents sham 50 题）；fmt_v1_1（只 llm_debate）`_pi6` / `_sham6` 前 10 题。自然答错 575 条。
- 原始结果 `data_runs/anchor_llama_2026-10-21/*.jsonl.gz`（命令见该目录 README；导出加 `--maa_exclusion docs/requests/maa_exclusion_v1.json`）；本地解压副本 `/home/claude/anchor_runs/`。
- 运行器 `scripts/runners/anchor_run.sh <fw> <normal|inject> [limit]`（环境变量 OUT / SUFFIX / EXTRA / CFGNAME；用 `bash` 调用）。密钥 `/home/claude/.mht_api.env` 从 Project 文档「api端点」重建，**不要提交**。
- 单次运行：llm_debate 约 $0.0046，MAC 约 $0.0096，mdagents 约 $0.0024，medagents 约 $0.0117（`scripts/run_cost.py`）。

**注入说明的版本**：旧说明；fmt_v1（4 个锚点 YAML 已开启）；fmt_v1_1（只 llm_debate，PI 更好认，不推广）；fmt_v1_2（待验证）；match_opener（只 mdagents，待验证）。原则：能靠格式签名重采样解决的，不往说明里加话。

**验收标准**（MHT 第 47 轮）：MHT `norm()` 清洗后，同槽位 sham 对 normal 在 punct 和 char 下 CI 覆盖 0.5，或不超过 RC 上限 0.62；PI 不设门槛。fmt_v1：MAC、medagents 通过；mdagents char 0.65 不通过（自我介绍开头）；llm_debate 不通过（逐项分析结构）。工具：`quality_gate.py`、`pi_version_analysis.py`、`sham_residual_analysis.py`、`sameslot_format_scan.py`、`build_fmt_validation_export.py`。

**其他约定**：`pair_target_runs` 主数据开启（MHT 第 59 轮）；AEGIS simulated 只有 `instruction_strict` 泄漏可剔除，拒答是故障本身；MAA 重叠 2 题（1499、1939）51 条运行不进训练；补齐 A–D（$6.0）不批；style_v1 不进训练。

**沟通**
- MHT：medical-aegis issue #1（REST：`gh api repos/chancanmakeit/medical-aegis/issues/1/comments?per_page=100&page=N`）。我方最新一条是**第 44 轮**（comment 6434273919），下一条为第 45 轮；MHT 最新一条是第 62 轮续（comment 6432028012）。
- MHT 仓库按单文件用 `gh api repos/chancanmakeit/Medhypertrace/contents/<path>` 读，不 clone。
- MAFA：MAFA 仓库 issue #1，暂无待办。**不往 MAFA 仓库提交代码。**
- 先读对方最新评论，读完再单独发帖。正则统计先在 normal 步上查误报率。
- 不要用 `pkill -f` / `pgrep -f`；用 `ps -eo pid,comm,args` 过滤后 kill。
- 修改本节时整节重写，不要原地字符串替换。

**待用户决定**
1. **确认三项付费运行**（分叉试点约 $0.31、fmt_v1_2 约 $0.06、开头筛选约 $0.09）。MHT 第 62 轮转达了用户对后两项和试点时机的决定，但按 Project 约定，开跑前仍要用户本人确认估算。
2. 结构感知中训练做不做（MHT 那边的决定）。
3. 主数据（其他框架、正式配置）的生成方案。

---

> 新会话按顺序读：**本文件**（顶部的"当前状态"） → `docs/discussion_log_v10.md`（当前会话记录）→ `docs/discussion_log_v9.md`（上一会话，锚点和门槛的逐轮细节）→ `docs/discussion_log_v8.md`→ 需要时再读 `docs/HANDOFF_prev_session.md`（AEGIS 原代码会话的技术交接）和 `docs/requests/`（MedHyperTrace 的需求规格）。
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
