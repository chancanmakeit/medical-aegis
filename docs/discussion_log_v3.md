# medical-aegis 讨论记录 v3

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
