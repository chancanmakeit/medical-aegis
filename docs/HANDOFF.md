# medical-aegis 会话交接文档

> 最后更新：2026-10-20（第 6 轮）。每轮覆盖更新。新会话请按顺序读：本文件 → 最新的 `docs/discussion_log_vN.md` → `docs/HANDOFF_prev_session.md`（上一个代码会话的完整技术交接，包括文件地图、框架细节和典型命令）。

## 0. 项目一句话
把 AEGIS（多智能体故障注入 + 失败归因，arxiv 2509.14295，ICLR 2026）扩展到**医学**和 **NER**：新增 3 个框架（MDAgents / ClinicalAgent / CMAS），4 个新数据集（MedXpertQA-Text/MM、MedConceptsQA、trial_success、wikigold），支持多模态。在注入故障的情况下生成错误轨迹，同时生成干净的正常轨迹，两者配对用于失败归因研究。

用户：Alvin Chan。偏好直接的同行级交流和诚实的批评，经验性结论要对着真实数据核实。讨论用中文，代码注释用英文。

## 1. 用户的工作约定（来自 Project 说明）
- 每轮更新带版本号的讨论记录和本交接文档，并推送到 `medical-aegis`。
- 子 agent 要合理使用，权衡模型切换带来的 token 开销。用户明确指定时用 Sonnet 子 agent。
- `sleep` / `timeout` 不要设得太长。
- **调用任何 LLM API 前，先小规模试跑估算成本，然后停下来问用户。**
- API 端点见 Project 文档「api端点」。密钥只放在沙箱本地的 `/home/claude/.mht_api.env`，不写进仓库。

## 2. 恢复环境（新会话照做）
1. `add_repo(owner=chancanmakeit, repo=medical-aegis, access=push)`，然后 `git clone https://github.com/chancanmakeit/medical-aegis /home/claude/medical-aegis`。clone 和 push 都走会话代理，不需要 token，也不要把 token 写进 `.git/config`。会话内无法新建 GitHub 仓库，需要新仓库时请用户手动建。
2. 代码就在仓库根目录，这就是完整的 AEGIS-main，不必再上传 zip。
3. `pip install --break-system-packages -r requirements.txt`。torch、transformers、wandb 可以先跳过，核心路径不需要。Python 3.13 已验证可用。
4. 密钥：仓库里的 `model_api_configs/model_api_config.json` 和 `experiments/fm_injection/medical/mdagents_medical_*.yaml` 中的 `api_key` 都是 `YOUR_API_KEY` 占位符。真实运行前从 `/home/claude/.mht_api.env` 填入，沙箱重置后需要重新向用户索取或从 Project 文档获取。**不要提交填了密钥的文件。**
5. 冒烟测试（离线）：`python3 main.py --help`；`python3 -c "from methods import method2class; print(sorted(method2class))"`。
6. 大数据源（ClinicalAgent 7z、CMAS.zip、MedXpertQA.tar）不在仓库里，按需请用户上传，清单见 `docs/HANDOFF_prev_session.md` §5，或旧会话的 HANDOFF_RESOURCES。`datasets/data/wikigold.json`（274 条）和 `datasets/cmas_wikigold/` 已在仓库中。
7. HF collection `UUUooUUU/data4-mas-simulated-fault-and-realworld-fault-trajectory-gen`（private）可以用用户的读 token 直接 curl 访问，HF connector 也可以用。里面有 7 个 dataset：MedXpertQA、MedConceptsQA、mmlu_pro_health、DAICWOZ（私有）、ConSensus（私有）、Heartbeat、Sound-Dr。

## 3. 当前状态
- 第 2 轮已在沙箱中恢复环境并通过离线冒烟测试（详见 discussion_log_v2）。代码已推送到仓库，提交时密钥已脱敏。
- 用户的本地环境是 Windows，GBK locale，项目路径 `F:\AEGIS-main\`。旧会话用的模型是 `gemini-2.5-flash-lite` 和 `grok-4-1-fast-reasoning`（走 qingyuntop 代理）。

## 4. 待决项（接力点）
- ✅ **第 6 轮：ConSensus 和它的 4 个多智能体基线已集成**，方法名为 `consensus`、`consensus_debate`、`consensus_mad`、`consensus_reconcile`、`consensus_cmd`。数据集是 `datasets/data/{sleepedf,wesad}.json`。离线回归全部通过，详见 `discussion_log_v6.md`。
  - **运行**：`python main.py --method_name <m> --experiment_config experiments/fm_injection/sensing/<m>_sensing_{normal,inject}.yaml --dataset_file datasets/data/sleepedf.json --test_dataset_name sleepedf ...`。注意这里用 `--test_dataset_name` 决定 verifier，YAML 里不写 benchmark_name；consensus 本体的 YAML 文件名是 `consensus_sensing_*.yaml`。
  - **重建数据**：从 HF `UUUooUUU/ConSensus` 下载（脚本见本轮讨论记录），运行上游仓库 `nokia/multi-agent-collaboration-for-multimodal-sensing` 里的 `preprocess/preprocess_{WESAD,SleepEDF}.py` 和 `split.py --test_per_class 30 --examples_per_class 1`，再运行 `data_processing/sensing/convert_consensus_datasets.py`。
  - **共享基础设施**：`fm_structured_wrapper.py`（干净输入；按 phase/round 指定注入目标；fired 标记），`methods/consensus/consensus_main.py` 里的 `SensingMASBase` 和 `SensingAgent`（累积读取集合；`source_how`），注入工厂的 `classification` 任务类型。
  - 🔴 **旧 bug（待用户决定）**：顶层 `malicious_factory` 不认识 probability/ner，会静默回退成 mcq，导致旧的 clinical_agent 和 cmas 注入多半无效，详见 v6。顶层和 `aegis_core` 下两份工厂已同步，旧任务类型的行为没有改变。
  - **下一步：MAM**（Heartbeat / Sound-Dr，音频后端用 mimo-v2.6-flash，需要先确认它能否直接输入音频）。
  - **MedHyperTrace spec v1.1 尚未落实的项**：跨阶段稳定的 `agent_id`、P0 级的 `structured` 字段、`framework_family`、`task.observations`、锚点任务，以及 schema v1 导出器（把 steps 和 labels 分开）。
- ✅ **第 5 轮：MedAgents 已集成**，方法名 `medagents_mc`，跑 MedConceptsQA 和 mmlu_pro_health，mock 离线测试通过，详见 `discussion_log_v5.md`。用户决定：MedAgent-Pro 暂不做；集成顺序 MedAgents → ConSensus（只用 WESAD + SleepEDF）→ MAM（音频用 mimo-v2.6-flash）。**下一步：ConSensus。**
- 🧪 离线测试方法：先运行 `scripts/mock_openai_server.py --port 18080 --log <calls.jsonl>`，再把 `model_api_config` 和 YAML 的 `llm_config` 指向 `http://127.0.0.1:18080/v1`，并设置 `NO_PROXY=127.0.0.1`。读集核对用 `scripts/check_trajectory_sources.py <results.jsonl>`。注意：结束 mock 进程时不要用 `pkill -f mock_openai_server`，它会匹配到执行它的那个 shell 自身。
- 🆕 **第 4 轮：用户提议集成 MedAgents×MedConceptsQA、MedAgent-Pro×REFUGE2、ConSensus×ConSensus、MAM×Heartbeat/Sound-Dr。** 核实结果和建议见 `discussion_log_v4.md`。外部仓库 clone 在 `/home/claude/ext_repos/`（沙箱重置后需要重新 clone）。MedAgent-Pro 的正确仓库是 `jinlab-imvr/MedAgent-Pro`，它的分割工具没有发布；MAM 原版依赖本地 GPU 上的音频模型；ConSensus 自带 6 个基线 MAS，都跑同一批数据。等用户确认集成顺序和各项方案。
- 📨 **来自 MedHyperTrace 项目的轨迹需求（2026-10-19，用户安排两项目统筹）：** `docs/requests/2026-10-19_from_medhypertrace_HGFM_trajectory_spec_v1.md`。要点：方法侧要训跨框架零样本的超图基础模型，需要 ≥8 个框架、normal 每题多次采样（成功 + 自然失败）、干净的注入前 `input_messages`（mdagents / clinical_agent / clinical_agent5 目前缺，且记录的输入含注入指令原文 = 标签泄漏）、`labels` 与 `steps` 分离、拼 prompt 时记录 `sources`。**两项目沟通走 GitHub issue（用户 2026-10-19 要求）：请在 [issue #1](https://github.com/chancanmakeit/medical-aegis/issues/1) 下评论回复 6 个问题**（会话内用 REST：`gh api repos/chancanmakeit/medical-aegis/issues/1/comments -f body=...`，GraphQL 不可用）。方法侧对注入频率倾向方案 A（最终由用户定）。
  - **第 3 轮已在 issue #1 回复**（[评论](https://github.com/chancanmakeit/medical-aegis/issues/1#issuecomment-6282499559)）。要点：normal 与 inject 同路径同格式；三框架缺干净输入的根因是捕获层在注入层之下，`original_prompt` 被 normalizer 丢弃；旧数据或可按 `\n\n---\n[UPDATED INSTRUCTION FOR` 截断修复（请方法侧核实命中率）；`sources` 新三框架易插桩（mdagents 走 `_ask`），dylan 因 Ranker 剪枝需运行时记录。
  - **约定的下一步（离线，不调 API）**：①三框架补存 `original_input_messages`；②schema v1（`mas-traj/1`）导出器，steps/labels 物理分离；③`main.py` 支持 K 次重复 + `run_index`/`question_id`；④新三框架记 `sources`；⑤mock LLM 生成样例 JSON 放 `docs/requests/samples/`。之后才是 API 成本试跑 → 用户确认 → 2 框架×20 题×K=4 试点。
  - **等用户回答**：注入频率 A/B；用户本地还有哪些 normal 轨迹；试点用哪两个 backbone（建议 deepseek-flash + qwen3.8-flash）。
  - 向方法侧提出的意见：首个分歧步需在 `structured`（答案/投票）层面定义；clinical_agent(trial_success)、cmas(NER) 框架与任务一一对应，不宜计入框架缩放曲线，凑 8 框架应优先让新框架跑同一批医学 MCQ。
- 🔴 **最高优先：注入频率的跨框架统一，等用户选择。**
  - dylan / agentverse / llm_debate：同一 agent 每次出现都会注入，没有 `fired_keys` 去重，也没有开关。
  - mdagents / clinical_agent / cmas：有 `inject_every_invocation` 开关，默认只注入第一次。
  - 方案 A（便于归因研究）：全部只注入一次。给前 3 个 wrapper 加 `fired_keys` 和开关，默认 false。
  - 方案 B（便于鲁棒性测试）：全部每次都注入。把后 3 个框架的 YAML 默认值改成 true。
  - 用户选定后：统一实现，验证，并在所有相关 YAML 里写明默认值。
- 🟡 已知局限：ClinicalAgent 和 CMAS 的确定性工具都是 stub，所以论文里的绝对指标复现不了；probability 类任务注入后不一定翻转答案，大约一半样本会翻；MedXpertQA-MM 成本高，要先用 `--limit` 试跑。
