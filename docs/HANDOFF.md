# medical-aegis 会话交接文档

> 最后更新：2026-10-19（第 2 轮）。每轮覆盖更新。新会话请按顺序读：本文件 → 最新的 `docs/discussion_log_vN.md` → `docs/HANDOFF_prev_session.md`（上一个代码会话的完整技术交接，包括文件地图、框架细节和典型命令）。

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
- 📨 **来自 MedHyperTrace 项目的轨迹需求（2026-10-19，用户安排两项目统筹）：** `docs/requests/2026-10-19_from_medhypertrace_HGFM_trajectory_spec_v1.md`。要点：方法侧要训跨框架零样本的超图基础模型，需要 ≥8 个框架、normal 每题多次采样（成功 + 自然失败）、干净的注入前 `input_messages`（mdagents / clinical_agent / clinical_agent5 目前缺，且记录的输入含注入指令原文 = 标签泄漏）、`labels` 与 `steps` 分离、拼 prompt 时记录 `sources`。文末有 6 个问题，请在 `docs/requests/` 写回复并推送。方法侧对注入频率倾向方案 A（最终由用户定）。
- 🔴 **最高优先：注入频率的跨框架统一，等用户选择。**
  - dylan / agentverse / llm_debate：同一 agent 每次出现都会注入，没有 `fired_keys` 去重，也没有开关。
  - mdagents / clinical_agent / cmas：有 `inject_every_invocation` 开关，默认只注入第一次。
  - 方案 A（便于归因研究）：全部只注入一次。给前 3 个 wrapper 加 `fired_keys` 和开关，默认 false。
  - 方案 B（便于鲁棒性测试）：全部每次都注入。把后 3 个框架的 YAML 默认值改成 true。
  - 用户选定后：统一实现，验证，并在所有相关 YAML 里写明默认值。
- 🟡 已知局限：ClinicalAgent 和 CMAS 的确定性工具都是 stub，所以论文里的绝对指标复现不了；probability 类任务注入后不一定翻转答案，大约一半样本会翻；MedXpertQA-MM 成本高，要先用 `--limit` 试跑。
