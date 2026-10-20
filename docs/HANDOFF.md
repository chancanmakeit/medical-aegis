# medical-aegis 会话交接文档

> 最后更新：2026-10-20（新会话 v9 第 1 轮：环境已按本文件恢复，mock 冒烟测试通过；内容无实质变化）。
> 新会话按顺序读：**本文件** → `docs/discussion_log_v9.md`（当前会话记录）→ `docs/discussion_log_v8.md`（上一会话，有逐轮细节）→ 需要时再读 `docs/HANDOFF_prev_session.md`（AEGIS 原代码会话的技术交接）和 `docs/requests/`（MedHyperTrace 的需求规格）。
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
| dylan / llm_debate / agentverse | 原 AEGIS | 旧版（fm_dylan / fm_debate / fm_agentverse） | 医学 MCQ | mcq | 可跑；每次调用都会注入，没有开关（A/B 待定） |
| mdagents | 上一个会话 | 旧版 fm_mdagents | 医学 MCQ（含 MedXpertQA-MM 图像） | mcq | 可跑；⚠️ `input_messages` 含注入文本（问题 A） |
| clinical_agent（别名 clinicalagent） | 上一个会话 | 旧版 fm_clinical_agent | trial_success（需要 csv） | probability | **就是原论文的 5 agent 版本**，即 MedHyperTrace 数据里的 `clinical_agent5`；6 agent 的旧版已删除。第 7 轮修复了 probability 注入；⚠️ 存在问题 A |
| cmas | 上一个会话 | 旧版 fm_cmas | wikigold NER | ner | 可跑；⚠️ 存在问题 A；⚠️ `ner` 会回退成 mcq（用户决定暂不处理） |
| **medagents_mc** | 第 5 轮 | StructuredFMWrapper | MedConceptsQA、mmlu_pro_health | mcq | ✅ mock 回归通过 |
| **consensus** | 第 6 轮 | FMConSensusWrapper | `datasets/data/{sleepedf,wesad}.json`（`--test_dataset_name sleepedf/wesad`） | classification | ✅ |
| **consensus_debate / _mad / _reconcile / _cmd** | 第 6 轮（Sonnet 子 agent 移植，已和上游逐条比对消息） | FMConSensusWrapper | 同上 | classification | ✅ |
| **mam** | 第 7 轮 | FMMAMWrapper | `datasets/data/{heartbeat_b,heartbeat_a,sounddr}.json`（音频需要重新生成） | classification（自由文本） | ✅；音频后端是 mimo-v2.6-flash，已做 1 次真实探测，格式可用 |
| MedAgent-Pro | — | — | REFUGE2 | — | **用户决定暂不做**（上游缺少分割工具，plan 在病例之间共享） |

- 实验 YAML：`experiments/fm_injection/{medical,sensing,audio,ner}/<name>_*_{normal,inject}.yaml`。端点和密钥都是占位符。
- 批量生成：`scripts/generate_diverse_dataset.py` 已经包含所有新框架的注入位点池。

## 3. 共享基础设施（新框架要遵守的契约）

- **`aegis_core/agent_systems/fm_structured_wrapper.py`**：
  - `input_messages` 一律记录注入前的输入，注入版本放在 `injected_input_messages`，日志标记 `input_messages_are_clean: true`。
  - 多轮对话（`messages=` 方式调用）的注入只改最后一条 user 消息。
  - 注入目标可以额外指定 `phase` / `round`，每个目标记录 `fired`。
  - `is_tool` 步骤不参与调用对齐。
- **方法侧契约**：
  - 每次 `call_llm` 之前设置 `current_role` / `current_role_index` / `current_phase` / `current_round`。
  - 每次 LLM 调用只往 `conversation_history` 里写一条记录，包含 `step_id`、`sources`，可选 `source_how`（`excerpt` / `structured_field`）、`round`、`event_ids`、`agent_label`、`agent_id`、`observations`、`structured`。
  - ConSensus 系列复用 `methods/consensus/consensus_main.py` 中的 `SensingMASBase` / `SensingAgent`，读取集合会自动累积。
- **注入工厂**（`malicious_factory/` 和 `aegis_core/malicious_factory/` 两份**必须保持一致**，改完一份就 `cp` 到另一份）：
  - 支持的 task_type：mcq、numeric、error_correction、open、**classification**（JSON 和自由文本两种篡改都支持）、**probability**（直接替换标签里的值）。
  - `ner` 仍然会回退成 mcq。
- **verifier**：
  - wesad / sleepedf / heartbeat_* / sounddr 按类别标签匹配，确定性结果优先（authoritative）。自由文本时先看显式答案标记，再看是否只提到一个类别。
  - 显式答案不在类别表里时，视为无法判定。
  - 能识别 `Option: X` 这种写法。
- **`mas_base.call_llm`**：支持单次调用的 `max_tokens`、`audios=`（`input_audio` 的 data URI），以及从 model config 透传 `extra_body`。
- **`main.py`**：`Task.metadata['raw_sample']` 携带完整样本；断点续跑按**样本 id** 判断是否已处理（以前按 query，会漏跑）。
- **verifier 的数据集名**：取 `benchmark_name or --test_dataset_name`。sensing 和 audio 的 YAML 不写 benchmark_name，由命令行决定。

## 4. 待用户决定（按优先级）

1. **旧的 ClinicalAgent 注入数据**（`direct_prepend` 生成的 clinical_agent 和 clinical_agent5）：
   - 已确认：response_corruption **没有一条**能可控地跨过 0.5 阈值；prompt 注入用的是 MCQ 指令。
   - 待定：重跑还是过滤（只保留最终答案相对 clean 运行确实翻转的样本）。
2. **下一步做什么**：
   - (a) schema v1 导出器，同时实现 `main.py` 的 K 次重复运行（MedHyperTrace 在等）；
   - (b) 把 mdagents、clinical_agent、cmas 迁移到 StructuredFMWrapper（解决问题 A）；
   - (c) 用真实模型做小规模成本试跑。
3. **注入频率**：方案 A（全部只注入一次；我们和 MedHyperTrace 都倾向这个）还是方案 B。新框架默认都是 A，注入目标可以按 phase/round 指定。
4. **试点 backbone**：建议 deepseek-flash + qwen3.8-flash；MAM 的音频用 mimo-v2.6-flash。
5. 用户本地还有哪些 normal 轨迹。

## 5. MedHyperTrace 的需求（尚未完成的部分）

规格：`docs/requests/2026-10-19_from_medhypertrace_HGFM_trajectory_spec_v1.md`（含 v1.1 增补），以及 issue #1 第 24 轮的评论。

| 项 | 优先级 | 状态 |
|---|---|---|
| 干净的 `input_messages` | P0 | 新框架 ✅；旧的三个 wrapper ❌（MedHyperTrace 已离线修复旧数据） |
| `labels` 与 `steps` 物理分离 | P0 | ❌ 放在 schema v1 导出器里做 |
| 跨阶段稳定的 `agent_id` | P0 | MAM ✅；medagents_mc（q_expert_i / o_expert_j …）和 consensus 系列（modality:<name> …）放在导出器里做 |
| `structured`（answer / vote / confidence） | P0 | MAM ✅；其他框架放在导出器里做 |
| `framework_family` | P0 | ❌ 初步分组：辩论类 = llm_debate + consensus_debate/reconcile/mad/cmd，需要和 MedHyperTrace 确认 |
| `question_id` / `run_index`，同一题跑 K 次 | P0 | ❌ `main.py` 还不支持 |
| `sources` 及 `how` | P1 | 新框架 ✅（未标注的视为 verbatim）；medagents_mc 的 Classifier 应标 structured_field，Synthesizer 应标 excerpt，尚未补 |
| `task.observations[]` | P1 | MAM 的音频已用 `observations` 标记；传感器特征放在导出器里做 |
| 锚点任务：100 道 MCQ，所有能跑 MCQ 的框架都跑 | 建议 | ❌。注意 ConSensus 系列跑不了 MCQ，MCQ 框架家族目前只有 5 个 |

## 6. 已知坑

- 结束 mock 进程**不要**用 `pkill -f mock_openai_server`，它会匹配到执行命令的 shell 自身（exit 144）。应该用 `ps -eo pid,args | awk '$2 ~ /python3/ && /mock_openai/ {print $1}' | xargs -r kill`。
- 沙箱里**没有** `/usr/bin/time`。
- HF 的 tree API 加 `recursive=true` 时单页最多 1000 条，会截断。要分目录查（第 4 轮曾因此误判 REFUGE2 不完整）。
- `datasets/` 在 `.gitignore` 里，提交数据 JSON 要用 `git add -f`。
- 停止钩子会要求提交所有改动。子 agent 还在编辑的文件，可以用 `git update-index --cacheinfo` 提交占位版本。
- 沙箱每次会话都会重置，`/home/claude/ext_repos`、`/home/claude/data_*` 都需要重新获取。
- 资源：2 个 CPU 核，7 GB 内存，可用磁盘约 28 GB。

## 7. 文件地图（新增和改动）

- 框架：
  - `methods/{medagents_mc, consensus, consensus_baselines, mam}/`
  - 旧框架：`methods/{mdagents, clinical_agent, cmas, dylan, llm_debate, agentverse}/`
- wrapper：`aegis_core/agent_systems/fm_{structured, medagents_mc, consensus, mam}_wrapper.py`
- 数据转换：
  - `data_processing/medical/convert_medical_datasets.py`
  - `data_processing/sensing/convert_consensus_datasets.py`
  - `data_processing/audio/convert_mam_datasets.py`
  - `data_processing/ner/…`
- 数据：`datasets/data/{sleepedf, wesad, heartbeat_b, heartbeat_a, sounddr, wikigold}.json`
- 脚本：
  - `scripts/mock_openai_server.py`：带各框架的规则和通用的 JSON 填充。
  - `scripts/check_trajectory_sources.py`
  - `scripts/generate_diverse_dataset.py`
  - `scripts/build_paired_dataset.py`
  - `scripts/recompute_trial_success_verdicts.py`
- mock 样例：`docs/requests/samples/*_mock_{clean,inject}.jsonl`（共 7 个框架）。
- 讨论记录：`docs/discussion_log_v1..v9.md`。
