# medical-aegis 讨论记录 v11

上一会话的记录见 `docs/discussion_log_v10.md`（第 1–18 轮）。

## 第 1 轮（2026-10-27 00:55–）：新会话续接；MHT 第 64 轮续；位置与选点的离线检查
用户：新会话续接，按入口文档恢复环境，读 HANDOFF、v10 第 15–18 轮和 round16 报告，看 MHT 有没有贴 SAMT v1 结果。

- **环境**：挂载 medical-aegis（push）、Medhypertrace、private-documents（read）；clone 到 `f532a8d`；密钥从 Project「api端点」写入 `/home/claude/.mht_api.env`，HF 只读令牌写入 `/home/claude/.hf_token`（均 600，不入库）；`restore_workspace.sh`（hf 模式）一次成功，约 30 秒下载，目录与 HANDOFF 一致，已删 `/home/claude/hf_workspace`。
- **MHT 第 64 轮续**（comment 6436721040）：SAMT v1 结果**还没出**（中训练在 Linux #2 上 05:37 UTC 开始、预计 07:35 结束，后面自动导出、探针、SFT；他们到 Linux #2 的连接器断开，结果出来再贴）。其余：转换器写 `phase_canonical_table.version`；同意 llm_debate 保持 fmt_v1、mdagents 保留 match_opener，`format_matched=false` 的 7/50 训练时排除，请导出保留该标签；同意按重试率修正估算。对分叉扩大提两点：(a) 翻转集中在第 1 轮 / 专家，归因模型会学到位置先验，评测要报告只用位置的平凡基线，翻转率按（轮次, 发言顺序）分层；(b) 候选点只取"字母错"的步骤，标签与可见特征混在一起，建议按同样的（轮次, 位置）分布加一层对照候选点（字母正确或没有字母的步骤）。
- **离线核实**（`scripts/branch_position_analysis.py`，报告 `docs/requests/samples/position_check_2026-10-27/REPORT.md`，不花钱）：
  - llm_debate 第 2 轮有很强的**近因效应**：自己和第一条他人一致、最后一条不同时，56% 改成最后一条；自己和最后一条一致时，第一条只拉走 20%；三方都不同时 51% 跟最后一条。呈现顺序与 `sources` 在 900 步上全部一致。agent 0 对谁都不是最后一条，所以**第 45 轮"agent 0 决定性"的说法要更正**（2287 是少见情形）。mdagents 没有明显的顺序效应。
  - 试点翻转主要取决于**同伴支持度**（同伴里已有几人说出正确字母）：llm_debate 第 1 轮 0 人 2/16、≥1 人 3/4；mdagents 0–1 人 1/28、≥2 人 6/12。"首/中/末个错误步"的选点规则把票差编码进了位置，而且从没选到第 1 轮 agent 2。
  - 平凡基线 AUROC（79 点，留一题外 / 样本内）：轮次 × 位置 0.76 / 0.88，同伴支持度 0.78 / 0.89。MHT 的 (a)(b) 都成立。
  - 对照候选池：答错运行里字母正确的步骤每层 17–36 个，答对运行里每层 100 个以上，够用。
- **扩大方案估算**（单价来自试点按层实测）：A 约 $1.2（只 llm_debate 第 1 轮，按位置分层 + 两类对照候选点，检验近因效应的干预证据）；B 约 $2.1（两框架分层扩大）。等用户决定。
- 已发 issue 第 46 轮（comment 6436904644）。下一条为第 47 轮。

## 第 2 轮（2026-11-03 05:39–）：#4（ADP 对 schema 的借鉴）点名 medical-aegis 的三个问题；#1 的分叉身份与 bootstrap
用户："你的 issue#4 里有智能体向你求助了，你看看并给出你的看法"。期间（10-27 → 11-03）新开了 #2（CDE × Jev）、#3（中训练动机）、#4（ADP），GPT 和 Muse 加入讨论。本轮全部离线。
- **#4 正文**（MHT 第 80 轮）：借鉴 ADP 定 mas-traj/1.1（动作类型、思考分离、typed 标签 sidecar、task_group_id / split、分叉链接），问我方三个问题。GPT、Muse 补充：ATIF v1.7 有子智能体（包含关系，不是读集）；claim 枚举 injected_at / local_defect / outcome_sensitive_under_protocol / decisive_step 不得互推；格式诊断用同一目标内容的条件 NLL 差（GPT 反对比值门槛）。
- **核实与回答**（#4 comment 6605421826，第 47 轮）：
  - 更正 #4 正文：`how` 是变换语义（verbatim / excerpt / structured_field / summary / control），`inferred` 是采集方式（protocol / text_match；缺失 = runtime）；建议显式化为 `collection`。
  - 问 1：锚点 13,379 步无代码、无工具调用，决策都在 `structured`（框架固定键），可确定性派生 `actions[]`，一步可兼有消息和决策（MAC discussion 1,229 步）。公开数据：工具调用位置因转换器而异（AFTraj 在 llm 步，ARIA 在 tool 步）；`kind: tool`（32,933）与 `environment/tool_output`（402）并存，应合并；代码只以代码块出现（ARIA 8,722、MAST 6,387 步），无执行对齐时标 `code_unverified`。
  - 问 2：导出器有 `--reasoning keep`（注入步移到标签）；llama-4-maverick 无思考输出（MAC 4 步残缺 `<thought` 为伪迹）；公开数据 reasoning_exported 全 False。
  - 问 3：没有关联字段。核实 264 条记录按导出身份只有 40 组、最多重复 8 次（GPT、Muse 在 #1 指出）。接受四步：源头打戳 → 全量回填 → 导出器重复 run_id 默认失败 → 单元测试；等用户确认。
- **bootstrap bug**（GPT 在 #1 指出）：属实，已修 `branch_pilot.py`；AUROC 区间 llm_debate [0.394, 0.542]、mdagents [0.430, 0.563]，结论不变；其他脚本无此问题。round16 REPORT 加勘误；复测改为分层报告（翻转 0/12、未判定 0/16）。
- 已发 #4 第 47 轮（6605421826）、#1 第 48 轮（6605424424）。下一条第 49 轮。
- 未处理：#3 第四节请 medical-aegis 做阶段 1 医学自然运行（约 $5–15，需复核单价和剩余题库），待用户决定。

## 第 3 轮（2026-11-03 06:04–）：按推荐继续：分叉身份四步完成；方案 A 准备好，等用户批准付费
用户："按你推荐的继续吧"。本轮离线，未调用付费 API。
- **分叉身份**（#1 的四步，全部完成）：
  - `scripts/branch_identity.py`：`branch` 块（experiment_id、protocol_id、parent_run_id、candidate_step_id + candidate_index{t, base 0, sequence llm_steps}、pair_id = 父运行|t_step_id|协议、arm、repetition、descendant / regenerated / replayed 步、每个重生成步的调用标签 + 温度 + 文本 sha1、selection）。
  - 源头打戳：`branch_pilot.py run` 结束后把 `branch` 写进每条输出记录（mock 试跑通过）。
  - 回填：`data_runs/branch_pilot_2026-10-26/branch_sidecar.jsonl`，264 条；用完整调用日志核对，264/264 的重生成集合等于 {t}∪D(t)（branch）/ D(t)（control），每个上游调用恰好对应一步。264 个唯一身份、118 组完整 rep0、28 条 rep1（翻转 12、随机未判定 16）。
  - 导出器：读 .gz；`--branch_sidecar`；分叉记录 `run_mode: "branch"`、`run_id = pair_id|arm|repk`、`labels.branch`（不进 steps），不算 normal；无身份的 branch_pilot 输出直接拒绝；重复 run_id 默认停止、不写输出（`--allow_duplicate_run_ids` 覆盖）；问题明细写 `<out>.problems.json`；`check()` 校验分叉块。原有导出回归逐字节一致（670 条）。
  - 测试 `tests/test_branch_identity.py` 6 项通过（含：无 sidecar 失败、重复 run_id 停止、父运行存在、两臂前缀与父运行一致）。说明写进 `docs/mas_traj_schema_notes.md` 第 3 节。
- **方案 A 准备**（`docs/requests/samples/planA_2026-11-03/`，预注册）：`branch_pilot.py` 支持 K=3 全部运行（批次 = 一个 run_index、题目不重复）和 `select_strat`。180 个点：每个位置 主点 15+15、对照候选 1（答错运行里字母对）7+8、对照候选 2（答对运行里字母对）5+10（同伴说对 0 / ≥1），同伴支持度在位置间平衡。预测：主点翻转率 位置 2 > 1 > 0。功效有限（每位置 30 点，模拟单侧功效约 0.6）。mock 试跑（run_index 1）通过。
- **估算**（按这 180 个点记录的 token）：两臂 $1.30 + 对照复跑约 $0.14 → **约 $1.45**（上限约 $1.6），比 10-27 说的 $1.2 高：run 1–2 的题更长。等用户批准。
- 已发 #1 第 49 轮（comment 6606051071）。下一条第 50 轮。

## 第 4 轮（2026-11-03 06:15–）：用户批准，方案 A 跑完
用户："可以"（批准方案 A，约 $1.45，上限约 $1.6）。实际 **$1.528**：两臂 $1.299（估算 $1.30）、对照复跑 $0.229（翻转 29%，多于估算假设的 15%）；另有约 $0.0003 的确定性探针。报告 `docs/requests/samples/planA_2026-11-03/REPORT.md`，分析脚本 `scripts/branch_planA_analysis.py`，原始输出 `data_runs/branch_planA_2026-11-03/`（426 条，全部带 `branch` 身份；导出 0 问题）。
- **预注册预测不成立：** 主点标准化翻转率 位置 0 / 1 / 2 = 0.37 / 0.37 / 0.23；位置 2 − 0 为 −0.13 [−0.35, +0.08]；确认的翻转 4 / 11 / 5。第 2 轮的采纳近因效应没有变成第 1 轮位置的因果效应（功效约 0.6）。决定翻转的是 t 的字母是否改变（24/51 对 5/39）。由错变对 11、换成别的错答案 18。
- **温度 0 不确定：** control rep0 与 rep1 的重生成文本 264/264 不同（试点也 55/55 不同）；直接探针：温度 0、带或不带 seed，5 次 5 个不同文本。最终答案：翻转点 13/53 的第二次对照不一致，随机未判定点 0/13；加权噪声底约 7%。对照 rep0 与原记录不同 20/180。round16 报告加勘误。
- **同伴支持度：** 主点原始 19/45 对 10/45，确认后 10 对 10，9 个未确认翻转都在"同伴 ≥1"层，第 46 轮的结论在主点上收回。**唯一说对的 agent 是关键人物：** 答对运行里同伴 0 人说对时 12/15 翻成错（11 确认），≥1 人时 0/30。
- 建议协议 v2（自适应确认：翻转点补 1 次 control，两次一致且不同于 branch 才算 confirmed），待用户和 MHT 确认。
- 已发 #1 第 50 轮（comment 6606528394）。下一条第 51 轮。

## 第 5 轮（2026-11-03 10:24–）：MHT 第 83 轮；评测集报价与多框架意见
用户："issue 有新动静了，你先看，然后回复。若被要求运行不同的医学多智能体框架以获取轨迹数据的话，可以使用上下文 api 端点文档里 xiaojingai 端点的 `gemini-2.5-flash-lite` 模型（它作为多模态模型性价比高）"。
- **注意：** Project 的「api端点」文档里目前**没有 xiaojingai 端点**（7 个端点：aiberm、aihubmix、deepseek、阿里云、智谱、MiMo、Ant Ling）。已请用户提供 baseurl 和 key。
- **MHT 第 83 轮**（4 条）：
  - #1 6611680037：用户已批准协议 v2；他们的入口按 `run_mode == "normal"` 白名单，自动排除分叉记录；他们用过的 12 个试点翻转在 v2 下都算 confirmed；请我们为"医学分叉责任层评测集"报价（只作评测；每条父运行 ≥4 个候选点；≥200 confirmed，也给 100 的价；按框架报价；backbone 建议；先测温度 0 噪声底）。
  - #3 6611680396：阶段 0 改为按题目聚类重算区间，结论不变；征求我们对"由 medical-aegis 运行多个框架产出轨迹"的意见（5 个问题）。
  - #4 6611681144：收回比值门槛，改用 GPT 的条件 NLL 估计对象；同意 `collection` 显式化、工具输出合并、`code_unverified`、read-set 多对多。
  - #2：与我方无关。
- **我方回复**（#1 第 51 轮 6612193880，#3 第 52 轮 6612194217）：
  - 锚点 100 题已在 MHT 的 TAPT 语料里，不能用作评测集；评测集要用新题、新父运行，分叉与父运行同一 backbone 和端点。
  - 锚点 "llama-4-maverick" 实际返回 `gemma-4-31B-it-turbo`，按实际名字记。
  - backbone：评测集用 gemini-2.5-flash-lite（用户指定），与锚点 gemma 构成两个 backbone。
  - 候选点：llm_debate、mdagents 全 7 步（末步保留作噪声基线）；medagents_mc、MAC 分层 6 点。未翻转点抽 10% 补 control 估噪声底。可选加项（未翻转点再补 branch，约 +35%）先不加。
  - 报价（gemini 按 Google 列表价，每 100 个 confirmed）：llm_debate ~$2.7，mdagents ~$0.8，medagents_mc / MAC ~$3–6（产出率待测）；llm_debate + mdagents 各 100 个约 $3.5。锚点 backbone 约 2.5 倍。
  - 第一步试跑（≤ $1，待用户批准）：噪声探针；6 个 MCQ 框架各 10 道新题 normal；llm_debate、mdagents 各 20 条答错父运行做全步分叉，测确认产出率。
  - #3：真实端点验证情况（4 个锚点已验证，dylan / agentverse 等只过 mock）；每千条成本表；非 MCQ 排序（triage 第二批；clinical_agent 价值较低；mam、consensus 不进第一批；cmas 不用）；预算分配 分叉 55% / 自然 35% / 注入 10% 或暂停；两个 backbone。
- 下一条第 53 轮。

## 第 6 轮（2026-11-03 10:35–）：用户补了 xiaojingai 端点；gemini 试跑
用户："我已更新上下文 api 端点文档"。端点文档现在是 Project 同步的 private-documents `任务基础上下文/api端点.txt`（用 `gh api ... contents/任务基础上下文/api端点.txt` 读）。xiaojingai：base_url `https://open.xiaojingai.com/v1`，gemini 系列低价 key；价目表 gemini-2.5-flash-lite ¥0.036 / ¥0.144（单位待确认）。key 写进 `/home/claude/.mht_api.env`（`XIAOJINGAI_GEMINI_API_KEY`、`XIAOJINGAI_BASE_URL`）。按第 51 轮 ≤ $1 方案试跑；按 Google 列表价约 **$0.48**（上界）。报告 `docs/requests/samples/gemini_trial_2026-11-03/REPORT.md`。
- **端点：** 返回 model 一直是 `gemini-2.5-flash-lite`；温度 0 不确定（5 次 5 个文本，含 seed）；同一请求有两个计费通道（prompt token n 或 n+253，约各一半）。
- **题池** `datasets/data/pools_v1/`（`scripts/build_question_pools.py`）：去掉锚点 100 和 MAA 101，Jaccard ≥ 0.3 分组，eval 400 / corpus 1,849。
- **自然运行**（`scripts/runners/gemini_run.sh`，YAML `experiments/fm_injection/gemini/`）：6 个 MCQ 框架都跑通（准确率 0.42–0.70）。
- **DyLAN 修复：** `config_medical.yaml` 的 `num_rounds: 2` 违反 DyLAN 的 `> 2` 断言，10-21 起每条运行都是空轨迹且 status success。改为 3。structured wrapper 记录异常类型和 traceback；`main.py` 对无步骤的框架崩溃记 `status: framework_error`；导出器跳过。
- **分叉代码：** `branch_pilot.py` 加 `--backbone {anchor,gemini}`（记录文件、模型、YAML、端点、key、价格、题集）和 `select_all`（答错运行的全部 LLM 步）。`branch_identity.stamp_file` 改为在整个文件内按文本匹配上游调用（重采样招募者后，服务器把 miss 记到了错误的 qid），并容许判分调用（CORRECT/INCORRECT）。校准分析 `scripts/branch_eval_calibration.py`。
- **校准结果：** confirmed / 父运行 llm_debate 0.39（7 个 / 18 条），mdagents 0.29（5 / 17）；gemini 重采样改字母更少（第 1 轮 12/54）。报价（列表价）每 100 confirmed：llm_debate 约 $3.3，mdagents 约 $2.3；两个框架各 100 约 $5.6。eval 池在 K=1 下不够，建议扩到 800 题。
- 已发 #1 第 53 轮（comment 6612871277）。下一条第 54 轮。

## 第 7 轮（2026-11-03 11:42–）：用户三项决定；另外 4 个框架校准；多模态数据
用户："首先，可以把其他框架也加进来；其次，若存在某些框架是针对多模态问答 case 的话，那么除了 medxpertqa 数据集之外，也可以用类似于 pathvqa、SLAKE、Kvasir-VQA 数据集（SimulaMet/Kvasir-VQA-x1）；最后，关于评测题池，按你推荐来。"
- **eval 池扩到 800**（原 400 是前缀）。
- **实测价格：** xiaojingai `/v1/dashboard/billing/usage`（单位 ¥0.01，`/home/claude/posts/xj_usage.sh` 已不入库，命令见报告）与 token 吻合：价目表是每百万 token，约 Google 列表价 1/20。今天合计约 ¥2.5。
- **4 个框架校准**（20 条父运行、全步、v2）：confirmed 超出噪声预期：AgentVerse +8，DyLAN +12，MedAgents +3，MAC −1.5（llm_debate +6，mdagents +4）。噪声底 d：AgentVerse 0.136，DyLAN 0.150，MedAgents 0.095，MAC 0.056，llm_debate / mdagents 约 0.016。**v2 只在下游稳定的框架够用。** 提议协议 v3（2+2 起步，有分歧扩到 6+6，Fisher 单侧 p<0.05）。
- **修复：** DyLAN 改用私有 RNG（之前全局 random 被线程共享，回放 85/220 → 599/599）；分叉身份按请求 key 匹配，新增 `t_step_id_in_run`、`branch.structure`（含 `hidden_dependency_step_ids`：DyLAN 221/350 条有 `sources` 漏掉的依赖）；回放 key 忽略图像部分。
- **多模态：** 子 agent 建 `datasets/data/mm_v1/`（`scripts/build_mm_datasets.py`；图片在 `/home/claude/mm_data`，不入 git）：MedXpertQA-MM 1,998、PathVQA 3,354、SLAKE 412、Kvasir-VQA-x1 1,124（CC-BY-NC）；各 eval 200。mdagents 是唯一原生图像框架，各 10 题试跑通过，回放 70/70。
- 报价（v3，实测价格）：llm_debate / mdagents / AgentVerse / DyLAN 各 100 阳性 + MedAgents / MAC 各 40 父运行 + mdagents 多模态 4×50 父运行，约 $3.5（¥25）。
- 已发 #1 第 54 轮（comment 6615225277）。下一条第 55 轮。

## 第 8 轮（2026-11-03 16:34–）：用户批准协议 v3 和规模（约 $3.5），开始正式运行
用户："可以"。
- **实现：** `branch_pilot.py --protocol v3`（分叉臂也可重复；`--skip_done` 可续跑；`--recorded` / `--dataset` 覆盖；`--max_workers`）；`branch_identity` 增加 `PROTOCOL_ID_V3` 与重复说明（rep 1 = stage1，rep ≥2 = stage2_disagreement）；`scripts/branch_v3_analysis.py`（plan：stage-2 名单；label：Fisher 单侧、typed 标签记录）；`scripts/runners/branch_v3.sh`（单框架两阶段）；`scripts/runners/eval_v3_all.sh`（全部框架依次、可续跑）。
- **自然父运行**：eval 800 题 × llm_debate / mdagents / AgentVerse（各 800）、DyLAN（772，私有 RNG）、MedAgents 110、MAC 140；mdagents 多模态：MedXpertQA-MM 200、PathVQA 200、SLAKE 200、Kvasir 75（被中断，主脚本里补跑）。父运行冻结在 `/home/claude/gemini_frozen/`（分叉期间不再变动）。
- **事故：** 同时开 6 个框架 × 4 条 lane 导致容器内存（7 GB / 2 核）OOM，杀掉了部分进程，随后会话环境重启（文件都在）。改为一个框架一次、4 条 lane、每条 6 个 worker，批次完成即跳过，可续跑。
- 规模：父运行 llm_debate 300、mdagents 425、AgentVerse 250、DyLAN 170、MedAgents 40、MAC 40、多模态各 ≤50（答错父运行不足时全用）。
- 进展（截至 20:45）：llm_debate 300 父运行 / 2,100 点，61 阳性（20 个 aggregator），噪声底 7.8%；mdagents 425 / 2,975，97 阳性（15 aggregator），噪声 6.4%；MedAgents 40 / 741，16 阳性，噪声 7.0%；mdagents 多模态 MedXpertQA-MM 13、PathVQA 3、SLAKE 1、Kvasir 4。
- **修复：** 无字母的最终答案作为一个结果 "NONE"（以前当成未完成）；Kvasir 有文本相同、图像不同的题 → 回放 key 加图像 sha1，批次内题目文本互不相同；PathVQA / SLAKE / Kvasir 重跑后身份问题 0。
- 用户提醒："执行命令时若用到 sleep 命令或者 timeout 命令之类的需要等待的命令，不要设置 sleep 500 这种让人等太久"（我之前用了 580–595 s）→ 之后等待一律 ≤ 60 s。
- 用户："你可以创建自动定时任务来查看并自动运行任务" → `scripts/runners/eval_v3_watchdog.sh [--restart]` + 每 25–30 分钟一次的 `send_later` check-in（id 记在 `/home/claude/posts/checkin_triggers.txt`），容器被回收后自动续跑。

## 第 9 轮（2026-11-03 21:00–）：为什么是这 6 个框架；补 triage_agent 和 MAM
用户："我有个疑问，为何要使用的是这6个框架而不是别的医学多智能体框架，你之前不是已经集成了很多种医学多智能体框架吗"。回答要点：评测集按"有客观答案、能在 gemini 上跑通并能离线回放"选；6 个 MCQ 框架共用 MedXpertQA 题池；其余框架要么任务不是选择题（clinical_agent 等，需要另定结果比较），要么需要专门数据 / 模态（triage_agent：ESI 分诊；MAM：音频），要么之前已决定不用（cmas）。推荐优先补 triage_agent 和 MAM（报价各约 ¥1–3，先试跑 + 校准）。
用户："我建议补triage_agent和mam框架"。
- **MAM 音频：** 子 agent 重新生成 `datasets/audio/<ds>/`（gitignored），JSON 与之前逐字节一致。gemini YAML `experiments/fm_injection/gemini/mam_normal.yaml`（文本、音频都用 gemini）；3 题试跑通过（音频确实附上；工具步 WebSearch）。
- **triage_agent：** gemini YAML（benchmark triage_esi）；10 题试跑 7/10 正确；216 条自然运行（72 题 × K=3）完成并冻结；v3 已开（53 条答错父运行，424 个点）。
- **最终答案抽取 `final_answer`：** ESI 等级 / 类别名或别名 / 字母。
- **回放 key 支持音频和样本 id：** MAM 不同录音的文字 prompt 完全一样，只靠音频 sha1 区分不够稳（同一音频多次出现），改为可选的样本 id 请求头（`mas_base` 在 `AEGIS_SAMPLE_HEADER=1` 时发 `X-Aegis-Sample`；structured wrapper 设 `_aegis_sample_id`；两个回放服务器和 `branch_identity` 的请求 key 都支持；`branch_pilot.py --sample_keys`）。验证：MAM 回放 38/40（2 个 miss 是 LLM 判分请求），最终回答 3/3 一致；triage 80/80。
- 看门狗加 triage_agent 和 MAM 三个数据集（job 名 `mam_<ds>`，目录 `/home/claude/eval_v3/mam_<ds>`，`--sample_keys`，每数据集最多 25 父运行，按 MAM 每次运行约 ¥0.0006 估算，3 个数据集上界约 ¥3.7、实际约 ¥2）。
- 提交 `aac964b`。花费：v3 开始以来约 ¥19.1（22:16），含 triage / MAM 自然运行。
- **11-03 22:38 起容器多次被回收（会话空闲几分钟后后台进程被杀）。** 对策：check-in 时保持会话活跃（每次 sleep ≤ 60 s 轮询）；`branch_v3.sh` 每个阶段跑两遍（第二遍只补崩溃的批次）；MAM 自然运行改为可续跑（只跑缺的 id、保留中断的部分结果）并纳入看门狗；看门狗支持 `PAUSED` 标记。
- **修复：** (1) MAC stage-2 的 control rep3/5 在我编辑 `branch_pilot.py` 时崩溃（缺 `sample_keys` 参数的中间状态），分析器把这些点判为 needs_stage2（没有错判），补跑后 MAC 8 个阳性。(2) MAM 按文本分批导致 376 个单题批次 → `--sample_keys` 时同文本可同批（17–20 批）。(3) `stamp_file` 只看上游调用判断是否用样本 key，只有判分调用上游的批次（D(t) 为空）因此找不到 control 臂的步 t（`t_step_id_in_run` 为空，身份问题 66/114/106 条）→ 改为看全部调用；`scripts/branch_restamp.py` 离线重盖章，问题清零，不花钱。
- **DyLAN 限额：** 按实测每次运行约 ¥0.0016，170 父运行的 v3 约 ¥10–14，超出批准 → 改为 40 个父运行（pass 0 = 步 0 的 170 个点已在跑，保留）；stage 1 噪声底 0.254（其他框架 0.04–0.09），566 点中 286 需要 stage 2。**v3 花费到约 ¥29.5（已到批准总额），DyLAN stage 2（约 ¥2.5）暂停，待用户决定。**
- 结果（v3 阳性 / 点数 / 噪声底）：llm_debate 61 / 2,100 / 0.078；mdagents 97 / 2,975 / 0.064；MedAgents 16 / 741 / 0.070；MAC 8 / 387 / 0.044；triage_agent 10 / 424 / 0.064；MAM heartbeat_a 3 / 376 / 0.064，heartbeat_b 9 / 377 / 0.088，sounddr 0 / 402 / 0.000；mdagents 多模态 MedXpertQA-MM 13 / 350，PathVQA 3 / 350，SLAKE 1 / 147，Kvasir 4 / 154；DyLAN stage 1 only（0 / 566，286 待 stage 2）；AgentVerse stage 2 进行中。

## 第 10 轮（2026-11-04 03:48–）：把进展发到 issue
用户："目前的进展提入issue里了么，可以在issue里让MHT项目或其他智能体看看。" 我之前打算等 DyLAN 决定后再发 → 先读 #1–#4（第 54 轮之后对方没有新回复），发 #1 第 55 轮（comment 6629822563）：v3 结果表、阳性集中的步类型、实现变化（回放 key、`final_answer`、紧凑归档格式、两处修复）、花费与待定事项，并请方法侧回答 4 个问题（阳性数量和分布是否够用；DyLAN 是否需要；紧凑格式还是完整 mas-traj；stage-1 全一致点是否作弱负例）。DyLAN stage 2 和 llm_debate 追加仍待用户决定。下一条第 56 轮。

## 第 11 轮（2026-11-04 04:21–）：MHT 审计；扩充 triage_agent 和 MAM
用户："issue有新动静，你看看，其他智能体貌似说triage_agent和mam框架阳性太少，我建议对这俩个框架想办法扩充阳性的话，是否有用？如果可能有用的话那就扩充。"
- **MHT 第 84 轮（#1 6630061863）：** (1) v3 的参照取自 control 众数，偏向判阳性；用置换零假设估计 E0 = 46.8 / 324，FDR ≈ 0.14；建议附置换 p，以后用对称参照。(2) 平凡基线：除 mdagents 外，阳性偏长、偏早（步长 AUROC 0.76–0.81）；标签与步长相关，主评测要报控制后的数字。(3) 文本 MCQ 部分（AgentVerse / mdagents / llm_debate）够做主评测；MAC、MedAgents、triage、MAM、多模态只作描述；要追加的话优先 mdagents，其次 llm_debate。(4) DyLAN 不补 stage 2。(5) 紧凑格式够用；请修多模态和 MAM 父运行的 dataset 字段，并在 label 里显式标注 D(t) 是否为空。(6) 不导出弱负例。#3 6630062229：同意第一批安排；DyLAN 的 sources 标为不完整。
- **我的判断（已告诉用户）：** 扩充有中等价值。两个框架各有约 40 个非末步阳性后，可作为跨任务（非选择题 / 音频）的留出框架；但对主评测，扩 mdagents / llm_debate 更值。报价约 ¥5（±50%），**用户选择两个都扩**。
- **实现：** `branch_v3_analysis.py` 新增 `pooled_reference`、`p_value_pooled`、`perm_p`（924 种分配的精确置换）、`p_null_positive`（完整流程的置换零假设，求和得 E0），以及 `--reference pooled`；context 新增 `dt_empty`、`is_last_llm_step`、`downstream_regenerated`。复核结果：合并参照下的阳性数与 MHT 完全一致（248），E0 为 43.0（MHT 46.8）。"只有末次调用"的阳性 36 个。AgentVerse 有 4 个 criticism 阳性：按 sources 其 D(t) 为空，但 branch 运行实际重生成了后续步骤，属于 sources 漏边。
- `scripts/fix_dataset_tag.py` 修正归档里多模态 / MAM 的 dataset 标签（同时改写 run_id 等）；`export_schema_v1.py` 的 source 加 `collection`（runtime），provenance 加 `sources_complete` / `sources_known_gaps`（dylan、agentverse、triage_agent、mdagents 观察到缺口）；`parents_mastraj/` 下是父运行的 mas-traj 导出，每个 label 的 run_id 都能对上。
- **扩充：** triage 每题再跑 3 次（run_index 1–3，648 条，167 条答错）；MAM heartbeat_a / b 用第一批没用到的 run-0 父运行，并每题再跑 1 次（`scripts/build_expansion_parents.py`），父运行 heartbeat_a 40 条、heartbeat_b 86 条；新 job `triage_agent_x`、`mam_heartbeat_a_x`、`mam_heartbeat_b_x`，用合并参照。
- 已发 #1 第 56 轮（6631056926）：复核结果、三处修复、扩充计划。扩充结果在第 57 轮汇报。
- 用户（05:56）："采用sleep命令时最高设置20s，否则等太慢了" → 之后每次 sleep ≤ 20 s。
- **扩充完成（08:20）：** triage_agent_x 22 个阳性（167 条父运行 / 1,336 个点，E0 2.5），mam_heartbeat_a_x 8 个（40 / 625），mam_heartbeat_b_x 25 个（86 / 1,291，E0 2.9）。合计 triage 32 个、MAM 45 个，全部是非末步阳性。花费按 token 约 ¥5.0。用量计数器同期涨了约 ¥11.2，但空闲时它也以每小时约 ¥1.1 上涨（同一个 key 有别的调用方）。中途因计数器超出报价暂停过一次，问用户后**用户选择跑完 heartbeat_b 的 stage 2**；改用 8 条 lane 加速。
- 已发 #1 第 57 轮（6635858960）：扩充结果，并请 MHT 回答 triage / MAM 能否作留出框架、追加的优先级。下一条第 58 轮。

## 第 12 轮（2026-11-04 09:06–）：用户："继续"
- 第 57 轮之后对方还没有回复。离线做了平凡基线（`scripts/branch_v3_baselines.py`，复现 MHT 第 84 轮第 2 节，并扩展到全部 job）：文本 MCQ 与 MHT 的数字一致（AgentVerse 0.740、llm_debate 0.815、mdagents 0.534、MAC 0.973）；MAM 受步长混杂（0.743）；triage 的步长混杂不明显（0.577，CI 含 0.5），但阳性偏早（相对位置 0.297）；多模态 mdagents 0.593（CI 宽）。写进 REPORT。
- 已发 #1 第 58 轮（补充）。下一条第 59 轮。

## 第 13 轮（2026-11-04 10:37–）：MHT 请求语料题池自然运行
- **MHT 第 86 轮（#3 6637475561）：** 用户批准三臂方案（base / LM-CPT / interaction-CPT），预注册 `MedHyperTrace-v2/docs/design/InteractionCPT_prereg_v1.md`。公开 mas-traj 没有运行时读集，所以需要我们在 corpus 池（1,449 题，K = 1）上跑 llm_debate、mdagents、MedAgents、MAC、DyLAN 的自然运行。AgentVerse、triage、MAM 是"未见框架"评测层，不进训练。导出 mas-traj，带 `sources`、`collection`、`sources_complete`。请按框架报价并给出渲染 token 估计。
- **报价**（eval 池同配置运行 × 1,449，按 token 计，含 15% 余量）：llm_debate ¥1.0、mdagents ¥0.6、MedAgents ¥3.3、MAC ¥1.7、DyLAN ¥2.6，合计约 ¥9.2。渲染 token（只渲染输出，o200k）合计约 27.8M，不含 DyLAN 约 18.9M。读集核对：5 个框架有历史的步中，50–94% 只读历史的真子集，不是广播式的。llm_debate 的 `sources_complete` 无法用分叉检验核验（结构编号变化）。mdagents 的缺口很少（6/8,157），改为 `sources_complete: true` 并附说明。对评测设计的意见：已见框架层的非末步阳性主要来自 mdagents，建议用实际聚类数复核功效。已发 #3 第 59 轮（6638967512）。
- **用户选择：跑 4 个框架，不跑 DyLAN（约 ¥6.6）。** 已开跑（`/home/claude/posts/run_corpus.sh`，输出在 `/home/claude/corpus_runs/`，可续跑）；开始时用量计数器为 8247.08。
- **11:05 中止：** xiaojingai 账户余额用完（403 "用户额度不足, 剩余额度: ¥-0.011574"）。4 个框架已写出的约 600 条全是 `llm_api_failure`，已移到 `/home/claude/corpus_runs/failed_quota/`，否则续跑时会被当成已完成而跳过。用量计数器停在 8247.08（11-01 以来累计约 ¥82.5）。等用户充值或另给 key 后重跑（`run_corpus.sh` 可直接续跑）。
- 11:19 用户：API 文档已更新，duckcoding 端点（`https://api.duckcoding.ai/v1`）也提供 gemini-2.5-flash-lite。key 已写入 `.mht_api.env`（`DUCKCODING_API_KEY` / `DUCKCODING_BASE_URL`）。试调 1 次返回 403 insufficient_user_quota（剩余 $-0.000622；usage 接口 total_usage 100.06）。xiaojingai 仍是 ¥-0.011574。两个端点都没有余额，语料运行继续暂停。
