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
