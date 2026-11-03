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
