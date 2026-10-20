# medical-aegis 讨论记录 v6

每轮讨论追加一节；内容有实质变化时升版本号（v2、v3…），旧版本保留在仓库里。

---

## 第 1 轮（2026-10-19）：新会话续接，环境与权限检查

**用户需求**
1. 新建 GitHub private 仓库 `medical-aegis`
2. 测试对该仓库的写权限
3. 测试能否访问 HF collection `UUUooUUU/data4-mas-simulated-fault-and-realworld-fault-trajectory-gen`
4. 之后每轮结果同步到 `medical-aegis`（不再同步到 `Medhypertrace`）

**过程与结果**（三项均由 Sonnet 子 agent 执行）
- 会话代理只放行已挂载仓库的 repo 级接口，`POST /user/repos` 返回 403，无法从会话内建仓库。用户改为在网页上手动创建。
- 仓库挂载（add_repo，push 权限）成功。仓库为 private，默认分支 `main`，admin/push 权限均为 true。
- 写权限测试通过：两次真实 push，一次添加 `.write_test`（`e440b6c`），一次删除（`8f60252`）。git push 经会话代理完成，不需要 token。
- HF collection 访问通过：读 token 直接 curl 即可。collection 为 private，含 7 个 dataset（详见交接文档）。抽查了私有的 `ConSensus` 和公开的 `Heartbeat`，文件列表和 README 均可读。

**决定**
- 结果同步仓库：`chancanmakeit/medical-aegis`
- 文档：`docs/discussion_log_vN.md`（带版本号的讨论记录）和 `docs/HANDOFF.md`（交接文档，每轮覆盖更新）

---

## 第 2 轮（2026-10-19）：从旧会话恢复 AEGIS 代码环境

**用户提供**：旧会话的 `HANDOFF.md`、`HANDOFF_RESOURCES.md`、`AEGIS-main.zip`

**恢复过程**
- 解压 `AEGIS-main.zip`（约 44 MB）。包内的 `HANDOFF.md` 与单独上传的那份内容一致。
- 安装依赖（不含 torch、transformers，核心路径不依赖它们）。原 `requirements.txt` 缺了 `tenacity`、`sacrebleu`、`Wikipedia-API`、`termcolor`、`tiktoken`，已补上。
- 冒烟测试，全部离线、不调 API：
  - 核心代码 `compileall` 通过。
  - `method2class` 能正常导入，6 个目标框架（dylan / llm_debate / agentverse / mdagents / clinical_agent / cmas）都已注册。
  - `main.py` 和 5 个脚本（generate_diverse_dataset / build_paired_dataset / recompute_trial_success_verdicts / 两个数据转换器）的 `--help` 都正常。
  - NER verifier：对 wikigold 第 0 条，完全匹配得 F1=1.0，漏一个实体得 F1=0.667，符合预期。
  - trial_success verifier：让一个总是回答 INCORRECT 的假 judge 参与，0.72 判为正确、0.30 判为错误，judge 调用 0 次。说明旧会话修复的 `DETERMINISTIC_AUTHORITATIVE` 生效。
- 安全处理：代码里有 3 个文件写着真实的 qingyuntop 代理密钥（`model_api_configs/model_api_config.json` 和 `mdagents_medical_{inject,normal}.yaml`）。推送到仓库的版本已替换为 `YOUR_API_KEY`，原密钥只保存在沙箱本地的 `/home/claude/.mht_api.env`（`QINGYUN_API_KEY`）。
- 完整代码已推送到 `medical-aegis` 仓库根目录。旧交接文档存为 `docs/HANDOFF_prev_session.md`，要点合并进了 `docs/HANDOFF.md`。

**沿用的待决项**
- 🔴 注入频率跨框架不一致：方案 A（全部只注入一次）或方案 B（全部每次都注入），等用户选择。

---

## 第 3 轮（2026-10-19）：回复 MedHyperTrace 的轨迹需求（issue #1）

**来源**：MedHyperTrace 会话在本仓库提交了 `docs/requests/2026-10-19_from_medhypertrace_HGFM_trajectory_spec_v1.md`，并开了 issue #1。方法侧要训跨框架零样本的超图基础模型（HGFM），需要：≥8 个框架；normal 每题采样 K=4 次；干净的注入前输入；`labels` 与 `steps` 物理分离；拼 prompt 时记录 `sources`。

**对照代码核实的结论**（已回复到 issue #1）：
- normal 与 inject 走同一条代码路径（`base_wrapper.run_clean` → `run_with_multi_injection([], [])`），格式一致。缺的是 `main.py` 层面的 K 次重复、`run_index` 和 `question_id`。
- mdagents / clinical_agent / cmas 缺干净输入，根因是捕获层在注入层之下。干净的 prompt 其实以 `original_prompt` 存过，但被 `trajectory_normalizer` 丢弃了。修复改动很小。
- 旧数据也许能离线修复：`direct_prepend` + `direct` 风格是在 prompt 末尾追加固定块，从 `\n\n---\n[UPDATED INSTRUCTION FOR` 处截断即可。请方法侧核实命中率。
- `sources`：新加的三个框架容易插桩（mdagents 统一经过 `_ask` 和显式 join）；dylan 因为有 Ranker 剪枝，必须在运行时记录。
- 当前可直接跑的组合：dylan、llm_debate、agentverse、mdagents 跑医学 MCQ；clinical_agent 只跑 trial_success；cmas 只跑 NER。本会话没有现成的轨迹文件。

**向方法侧提出的意见**：
- "首个分歧步"需要在 `structured` 层面定义，因为温度大于 0 时文本在第 1 步就会不同。
- clinical_agent 和 cmas 的框架与任务一一对应，不适合计入框架缩放曲线。凑够 8 个框架应优先补通用框架的 wrapper，让它们跑同一批医学 MCQ。
- 推测 `clinical_agent` 和 `clinical_agent5` 是同一框架改造前后的两个版本，不应该当成两个独立框架。

**待用户决定**：
- 注入频率选 A 还是 B（两边都倾向 A）。
- 用户本地还有哪些 normal 轨迹。
- 试点用哪两个 backbone。

**计划的下一步**（离线，不调 API）：补存干净输入 → 写 schema v1 导出器 → 支持 K 次重复 → 新三框架加 `sources` → 用 mock 生成样例 JSON。之后再做成本试跑，请用户确认。

---

## 第 4 轮（2026-10-19）：用户提议集成 4 个新框架及其数据集

**用户提议**：
- MedAgents 配 MedConceptsQA
- MedAgent-Pro 配 REFUGE2
- ConSensus 配 ConSensus 数据集
- MAM 配 Heartbeat 或 Sound-Dr

**核实结果**（4 个仓库均已 clone 到沙箱 `/home/claude/ext_repos/`，数据集通过 HF API 查看）：

| 框架 | 仓库 | 代码情况 | 模型后端 | 数据集情况 |
|---|---|---|---|---|
| MedAgents（ACL'24 Findings） | gersteinlab/MedAgents | 共 730 行，旧版 openai<1.0 接口；五阶段流程：召集专家 → 各自分析 → 汇总报告 → 迭代协商 → 决策 | 纯文本 API | MedConceptsQA 已有转换器 |
| MedAgent-Pro（ICLR'26） | **jinlab-imvr/MedAgent-Pro**（用户给的链接有误，指向了 MedAgents） | 任务级：RAG + Planner **每种疾病只生成一次 plan，所有病例共用**；病例级：VLM 定性分析 + CodingAgent 生成的代码 + Decider。**分割工具的实现没有发布**：`Glaucoma.tools` 不存在，`tools/MedSAM` 为空 | 需要 VLM API，另需分割模型 | REFUGE2 完整（train / val / test 各 400 张，带 mask）。**只有 train 有青光眼标签**，从文件名前缀 g/n 读出：40 例青光眼、360 例非青光眼 |
| ConSensus（ACL'26 Findings） | nokia/... | 每个模态一个 agent 并行解读 → 语义融合 → 统计融合 → 混合融合；**仓库自带 6 个 MAS 基线**（debate、MAD、reconcile、CMD、self-refine、self-consistency），都跑同一批数据 | 纯文本（传感器特征序列化成文本，上下文约 15K）；langchain，异步 | HF 上约 26 GB 原始数据，要用仓库的 preprocess 脚本提取特征。和医学相关的子集是 WESAD（压力检测）和 SleepEDF（睡眠分期），其余是动作识别 |
| MAM（ACL'25 Findings） | yczhou001/MAM | 全科医生分诊 → 生成角色 → 多轮讨论（最多 3 轮）、汇总、投票 → 诊断；包含 Google 搜索检查 | 原版用**本地 GPU 模型**：音频用 Qwen-Audio-Chat，文本用 Medichat-Llama3-8B；**讨论时每个专家角色都直接调用音频模型** | Heartbeat：A 组 4 类、B 组 3 类，带标签。Sound-Dr：`data.csv` 1310 条，二分类标签（453 条阳性） |

**注意**：HF 递归列目录单页最多返回 1000 条，第一次查看时 REFUGE2 被截断，看起来不完整。逐个目录查过后确认数据是完整的。

**判断与建议**（详见本轮回复）：
- 建议的集成顺序：MedAgents → ConSensus（连同它的基线）→ MAM → MedAgent-Pro。
- MedAgent-Pro 有两个设计问题要先定：分割工具怎么实现，plan 被所有病例共用时注入怎么处理。
- MAM 要先确认有没有能直接输入音频的 API 端点，否则就得在用户的服务器上跑本地模型。

**待用户决定**：见本轮回复（集成顺序；MedAgent-Pro 的分割工具方案；MAM 用哪个音频后端；ConSensus 选哪些子集）。另外，第 3 轮留下的三项决定（注入频率 A/B、本地 normal 轨迹、backbone）仍未回复。

---

## 第 5 轮（2026-10-20）：用户决定集成范围，完成 MedAgents 集成

**用户决定**：
- MedAgents 跑 MedConceptsQA 和 mmlu_pro_health 两个数据集。
- MedAgent-Pro 暂不做。
- 集成顺序：MedAgents → ConSensus → MAM。
- MAM 的音频后端用 mimo-v2.6-flash。
- ConSensus 只用 WESAD 和 SleepEDF 两个子集。

**MedAgents 集成**（方法名 `medagents_mc`，和 `mdagents`（MDAgents）区分开）：
- `methods/medagents_mc/`：复现原版 `syn_verif` 五阶段流程，prompt 原文照抄。原版两处怪异行为也保留：选项块在循环里重复拼接；Key Knowledge 因为用列表做成员判断而几乎总被丢掉。
- 必要的适配：
  - 所有调用改走 `call_llm`。
  - temperature 用全局配置，原版写死为 0，这里为了能对 normal 重复采样。
  - 原版各阶段的 max_tokens（30/50/300/500/2500）放在开关 `use_original_max_tokens` 后面，默认关闭，因为会截断推理模型。
  - 答案解析支持 A–J；原版只认 A–E，处理不了 MMLU-Pro 的 10 个选项。
  - 汇总报告里缺少 "Total Analysis:" 时不再崩溃。
- 题干和选项从 AEGIS 的 query 字符串解析出来，两种转换器格式都支持，不需要改 `main.py` 或转换器。
- `aegis_core/agent_systems/fm_medagents_mc_wrapper.py`：
  - **`input_messages` 一律记录注入前的干净输入**，注入后的版本只放在 `injected_input_messages`；日志里标记 `input_messages_are_clean: true`。这修正了 MedHyperTrace 指出的问题 A。
  - 每个注入目标单独记录 `fired`，说明它这次是否真的触发了。
  - 默认只注入一次，可用 `inject_every_invocation` 开关改成每次都注入。
- 方法层在拼 prompt 时记录每一步的 `step_id`、`sources`、`round`、`event_ids`，对应 MedHyperTrace 的问题 C。`trajectory_normalizer` 已改为透传这些字段（原来会丢掉）。
- `mas_base.call_llm` 新增单次调用的 `max_tokens` 覆盖参数。这是增量改动，其他框架行为不变。
- `scripts/generate_diverse_dataset.py` 加入了 medagents_mc 的注入位点池，只收必定会触发的位点。Advisor 和 Reviser 只有在有人投 NO 时才会被调用，所以不参与随机抽样。
- 新增实验 YAML：`medagents_mc_medical_{normal,inject}.yaml`。端点留空待填；judge 用 `regex_first`，只有提取不到答案字母时才调用 LLM judge；注入描述生成默认关闭。

**离线验证**（新增 `scripts/mock_openai_server.py`，本地 mock，不花 API 费用）：
- `main.py` 端到端跑通 clean 和 inject 两种模式。每个样本 27 次调用，和"第一轮有人投 NO → 第二轮全票通过"的路径一致。
- 两个数据集格式都解析正确。mmlu_pro_health 的 10 个选项按 A–J 判分正常。
- `scripts/check_trajectory_sources.py`：114 条 `sources` 全部能在真实输入里找到，没有漏记的读取。注意 mock 让几位分析者输出了相同文本，反向检查（有没有漏记）在 mock 上偏弱，真实模型跑出来后要复核。
- inject 模式：所有步骤的 `input_messages` 里都没有注入文本；注入版本只出现在 `injected_input_messages`；response_corruption 步骤保存了篡改前的原始输出；两个目标都触发了。
- 打开原版 token 预算开关后，各阶段的 max_tokens 和原版一致。
- mock 样例已放到 `docs/requests/samples/medagents_mc_mock_{clean,inject}.jsonl`，供 MedHyperTrace 检查格式。

**尚未完成**：
- 标签类字段（`fm_error_type` 等）仍挂在 step 上，等 schema v1 导出器统一拆分（问题 B）。
- `main.py` 还不支持同一题重复运行 K 次。
- MedAgents 还没用真实模型跑过，需要先估算成本，并请用户确认用哪个 backbone。

**仍待用户决定**：注入频率选 A 还是 B；用户本地还有哪些 normal 轨迹；试点用哪个 backbone。

**下一步**：集成 ConSensus（WESAD + SleepEDF）。要先从 HF 下载原始数据，跑仓库自带的预处理脚本提取特征，再接入它自身和 6 个基线框架。

---

## 第 6 轮（2026-10-20）：集成 ConSensus 及其 4 个多智能体基线（WESAD + SleepEDF）

### 数据
- 数据来自 HF `UUUooUUU/ConSensus`：WESAD 的 15 个原始 pkl（13.8 GB），以及 SleepEDF `expanded_paper_subset` 中 39 条记录的 PSG 和 Hypnogram（约 2 GB）。
- 预处理全部用原版脚本（`preprocess_*.py` 和 `split.py`），参数为 `test_per_class=30`、`examples_per_class=1`、`seed=0`。示例样本取自同一受试者，每个类别 1 条。
- 用 `data_processing/sensing/convert_consensus_datasets.py` 转成 AEGIS 格式，**并去掉 `consensus.test` 里的金标准标签**。
  - `datasets/data/sleepedf.json`：150 个样本（W/N1/N2/N3/REM 各 30），来自 20 名受试者，5 个模态。处理前的窗口总数 42,308。
  - `datasets/data/wesad.json`：90 个样本（baseline/stress/amusement 各 30），来自 15 名受试者，10 个模态。处理前的窗口总数 513。
- 沙箱里 WESAD 的原始 pkl 已删除（HF 上有备份）；处理后的 `*_output/` 保留在 `/home/claude/data_consensus/`。

### 框架（mock 下全部通过离线测试，见下文）

| 方法名 | 来源 | 每个样本的流程 | 最终答案 |
|---|---|---|---|
| `consensus` | ConSensus 本体 | N 个模态 agent → 语义融合 → 统计融合（被要求站在多数票一方）→ 混合融合 | 混合融合的输出 |
| `consensus_debate` | baselines/debate | 各自解读 → 2 轮全员辩论 | 第 2 轮多数票 |
| `consensus_reconcile` | baselines/reconcile | 同上，每个回答多带一个 CONFIDENCE 字段 | 按重新校准后的置信度加权投票 |
| `consensus_mad` | baselines/mad | 各自解读 → 裁判 → 辩论 → 裁判 → 辩论 → 裁判 | 第 3 次裁判的输出 |
| `consensus_cmd` | baselines/cmd | 各自解读 → 2 轮分组辩论（本组看完整回复，另一组只看计数） | 多数票；平票时由秘书裁决 |

- 单智能体基线（single_agent、self_consistency、self_refine）不纳入，因为它们不是多智能体系统。
- MAD/CMD 和 debate/ReConcile 由两个 Sonnet 子 agent 并行移植，并且**都用真实的上游代码配合假 LLM 逐条比对过发给模型的消息，结果完全一致**：
  - MAD/CMD：14 个样本。
  - debate/ReConcile：随机注入各种 JSON 错误，各跑了 40 多个种子，包括重试和中止分支。
- 偏差记录在各文件的 docstring 里。主要有：
  - 原版用 asyncio 并发，这里改为按顺序执行。因为同一轮的 prompt 只依赖轮前快照，两者的轨迹是等价的。
  - CMD 的分组随机数原版用的是全局种子，这里改为每个样本用确定性的种子。
  - ReConcile 原版在没有任何合法答案时会抛 ValueError，这里改为中止该样本。

### 共享代码的改动
- `aegis_core/agent_systems/fm_structured_wrapper.py`：新的通用 wrapper 基类，供 MedAgents、ConSensus 和各基线使用。
  - `input_messages` 一律记录注入前的输入。
  - 多轮对话中的注入只作用在最后一条 user 消息上。
  - 注入目标可以额外指定 `phase` 和 `round`，从而打到后续轮次。
  - 每个目标单独记录 `fired`。
  - medagents_mc 改用这个基类后，输出和改之前逐字段一致。
- `methods/consensus/consensus_main.py` 里的 `SensingMASBase` 和 `SensingAgent`：
  - 读取集合会累积：包括 agent 自己之前的输出，以及之前每一轮读到的内容，因为这些内容都还留在对话记忆里。
  - 新增 `source_how`：例如 CMD 中另一组的回答只以计数形式进入 prompt，标为 `structured_field`。这对应 MedHyperTrace spec v1.1 的 `sources.how`。
- 注入工厂新增 `classification` 任务类型：
  - prompt 注入使用面向类别标签的指令。
  - response 篡改会重写 JSON，换成另一个类别，并保留 CONFIDENCE 等其他字段。原有的追加式模板对 JSON 框架完全无效，因为下游只解析第一个 `{...}`。
- verifier：WESAD/SleepEDF 按类别标签精确匹配，并且确定性结果优先；另外能识别 `Option: X` 这种写法。
- `main.py`：通过 `Task.metadata['raw_sample']` 把结构化的样本字段传给 wrapper。
- **修复断点续跑**：`reserve_unprocessed_queries` 原来按 query 文本判断是否已处理。ConSensus 的所有样本共用同一段 query，重复运行同一题时 query 也相同，这样会把未处理的样本也跳过。现在优先按样本 id 判断。

### 🔴 发现的旧 bug：clinical_agent 和 cmas 的注入没有按任务类型生效（已核实，**尚未修复，待用户决定**）
- 仓库里有两份 `malicious_factory`：
  - 顶层那份：`main.py` 和所有 wrapper 实际导入的是它。它不认识 `probability` 和 `ner`，构造时会**静默回退成 mcq**。
  - `aegis_core/malicious_factory` 那份：带有 probability/ner 的条目，但没有任何地方导入它。
- 已用代码确认：用 `task_type='probability'` 构造工厂，得到的 `task_type` 是 `mcq`；对 `<final_result>0.70</final_result>` 做 FM-2.3 篡改，结果只是在后面追加一句"the answer is actually A."，概率值没有变。
- 影响：
  - 旧会话生成的 clinical_agent 和 cmas 注入轨迹中，response_corruption 大多没有改变最终答案；只有 FM-1.2 这类整段替换输出的模板例外。
  - prompt 注入用的是"选项字母"那套 MCQ 指令。
- 这次只把两份工厂同步成同一份内容，旧任务类型的行为保持不变。

### 离线回归
见本轮回复和 `docs/requests/samples/`。

**离线回归结果**（本地 mock，不调 API；SleepEDF 样本，clean 跑 3 条，inject 跑 2 条）：

| 运行 | 每样本步数 | 对齐 | 注入文本泄漏到 `input_messages` | 读取关系检查 | 注入触发情况 |
|---|---|---|---|---|---|
| medagents_mc clean / inject | 27 / 27 | ✓ | 0 | 114/114 | 2 个目标都触发 |
| consensus clean / inject | 9 / 9 | ✓ | 0 | 54 / 36 全部找到，无漏记 | 2 个都触发；SemanticFusion 被篡改为 N2→N3，HybridFusion 读到了 |
| consensus_debate clean / inject | 16 / 15 | ✓ | 0 | 234 / 150 | 2 个都触发 |
| consensus_mad clean / inject | 19 / 19 | ✓ | 0 | 378 / 252 | 2 个都触发；Judge 被篡改为 N2→N3，之后 12 步都读到了 |
| consensus_reconcile clean / inject | 16 / 16 | ✓ | 0 | 234 / 156 | 2 个都触发 |
| consensus_cmd clean / inject | 16 / 16 | ✓ | 0 | 234 / 156（另一组的计数读取按 structured_field 核对） | ModalityAgent 触发；Secretary 只在平票时运行，这次未触发，符合预期 |
| debate 第 2 轮的注入目标（`phase: debate, round: 2`） | 16 | ✓ | 0 | 156 | 在第 2 轮触发，W→N1 |
| MAD 第 2 次裁判的注入目标（`round: 2`） | 19 | ✓ | 0 | 252 | 在 judge2 触发，N2→N3，之后 6 步读到 |
| ReConcile 第 1 轮辩论的篡改 | 16 | ✓ | 0 | 156 | 触发，W→N1；CONFIDENCE 字段保留，篡改结果没有被重试覆盖 |

说明：
- 回归中途发现 `trajectory_normalizer` 会丢掉 `source_how`，已修复。
- 样例记录（每个框架各一条 clean 和一条 inject）在 `docs/requests/samples/`。
- mock 的回答内容没有意义，这些测试只验证控制流程和记录是否正确。

**待用户决定**：
1. 旧 bug 怎么处理：是否修复 clinical_agent 和 cmas 的任务类型，以及旧注入数据如何处理。
2. 注入频率选 A 还是 B。目前所有新框架都默认只注入一次；现在注入目标可以指定 phase/round，B 的需求可以按目标单独开启。
3. 用真实模型试跑之前，先选定 backbone。
