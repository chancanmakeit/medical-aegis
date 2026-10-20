# medical-aegis 会话交接文档

> 最后更新：2026-10-19（第 1 轮）。每轮覆盖更新。新会话请先读本文件，再读最新的 `docs/discussion_log_vN.md`。

## 项目
- claude.ai Project：「医学多智能体系统模拟故障轨迹以及真实故障轨迹获取」
- 方向：把 AEGIS 多智能体故障归因扩展到医学多智能体系统，生成模拟故障轨迹，并获取真实故障轨迹。
- 结果同步仓库：https://github.com/chancanmakeit/medical-aegis（private，`main`）。旧仓库 `Medhypertrace` 不再作为同步目标。

## 用户的工作约定（来自 Project 说明）
- 每轮更新带版本号的讨论记录，以及本交接文档，并推送到 `medical-aegis`。
- 子 agent 要合理使用，考虑模型切换带来的 token 开销。
- `sleep` / `timeout` 不要设得太长。
- 调用任何 LLM API 前，先小规模试跑估算成本，然后停下来问用户是否接受。
- API 端点和密钥见 Project 文档「api端点」。密钥只放在沙箱本地 `/home/claude/.mht_api.env`，不写进仓库。

## 环境要点（新会话需重做）
- GitHub：会话代理只允许访问已挂载的仓库。新会话需先 `add_repo(owner=chancanmakeit, repo=medical-aegis, access=push)`，再 `git clone https://github.com/chancanmakeit/medical-aegis`。clone 和 push 走会话代理，不需要 token，也不要把 token 写进 `.git/config`。
- 会话内无法新建 GitHub 仓库（`POST /user/repos` 返回 403），需要新仓库时请用户手动创建。
- Hugging Face：用户的读 token 在 Project 同步源里，shell 里 curl 可直接访问 huggingface.co；也可用 HF connector（已认证为 `UUUooUUU`）。

## 数据：HF collection
`UUUooUUU/data4-mas-simulated-fault-and-realworld-fault-trajectory-gen`（private），共 7 个 dataset，均非 gated：

| repo | private |
|---|---|
| TsinghuaC3I/MedXpertQA | 否 |
| ofir408/MedConceptsQA | 否 |
| ywchoi/mmlu_pro_health | 否 |
| UUUooUUU/DAICWOZ | 是 |
| UUUooUUU/ConSensus | 是 |
| UUUooUUU/Heartbeat | 否 |
| UUUooUUU/Sound-Dr | 否 |

## 当前状态
- 已完成：仓库创建与挂载、写权限验证、HF collection 访问验证、文档初始化。
- 仓库中暂时只有 `docs/`，还没有代码或数据。
- 下一步：等用户给出本会话的具体任务。如果需要旧会话的上下文（例如旧仓库 `Medhypertrace` 里的交接文档），先向用户确认是否挂载该仓库。
