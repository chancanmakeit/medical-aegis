# 新会话资源清单（2026-10-20，第 8 轮）

**不需要再上传 zip。** 代码、文档、数据 JSON 都在 `chancanmakeit/medical-aegis` 仓库里，按 `docs/HANDOFF.md` 第 1 节恢复即可。下面只列出仓库里**没有**、按需重建的资源。

## 1. 密钥（必须）
- 来源：Project 文档「api端点」（aiberm、aihubmix、deepseek、阿里云 qwen、智谱、MiMo）。
- 写入 `/home/claude/.mht_api.env`，权限设为 `chmod 600`。不要提交。

## 2. MAM 音频（跑 `mam` 时需要）
数据来自 HF `UUUooUUU/Heartbeat` 和 `UUUooUUU/Sound-Dr`，可以直接用 curl 加读 token 下载（网络可达）。在仓库根目录执行：

```bash
H="Authorization: Bearer <HF读token>"; B=https://huggingface.co/datasets/UUUooUUU
mkdir -p /home/claude/data_mam/{zips,sounddr/cough} && cd /home/claude/data_mam
for z in Atraining_normal Atraining_murmur Atraining_extrahs Atraining_artifact Btraining_normal Btraining_murmur Btraining_extrasystole; do
  curl -sSL -H "$H" -o zips/$z.zip $B/Heartbeat/resolve/main/$z.zip; unzip -q -o zips/$z.zip -d heartbeat_raw; done
curl -sSL -H "$H" -o sounddr/data.csv $B/Sound-Dr/resolve/main/data.csv
cd /home/claude/medical-aegis
python3 data_processing/audio/convert_mam_datasets.py --dataset sounddr --sounddr_csv /home/claude/data_mam/sounddr/data.csv --list_only > /tmp/wanted.txt
(cd /home/claude/data_mam/sounddr && while read f; do curl -sSL -H "$H" -o "$f" $B/Sound-Dr/resolve/main/$f; done < /tmp/wanted.txt)
for d in heartbeat_b heartbeat_a; do python3 data_processing/audio/convert_mam_datasets.py --dataset $d --heartbeat_dir /home/claude/data_mam/heartbeat_raw --out datasets/data/$d.json; done
python3 data_processing/audio/convert_mam_datasets.py --dataset sounddr --sounddr_csv /home/claude/data_mam/sounddr/data.csv --sounddr_dir /home/claude/data_mam/sounddr --out datasets/data/sounddr.json
```

使用默认参数（`--seed 0 --per_class 30`）时，生成的 JSON 和仓库里已提交的一致。抽样是确定性的，音频路径为 `datasets/audio/<ds>/<id>.wav`。

## 3. ConSensus 原始数据（一般不需要）
`datasets/data/{sleepedf,wesad}.json` 已经提交。只有要换 split 或做缺失模态实验时才需要重建：
1. 从 HF `UUUooUUU/ConSensus` 下载：
   - `processed/SleepEDF/expanded_paper_subset/*.edf`（约 2 GB）
   - `processed/WESAD/WESAD/S*/S*.pkl`（约 13.8 GB）
2. clone `nokia/multi-agent-collaboration-for-multimodal-sensing`，运行 `preprocess/preprocess_{SleepEDF,WESAD}.py --num_workers 2`。在沙箱里，SleepEDF 约 25 分钟，WESAD 约 3 分钟。
3. 运行 `split.py --test_per_class 30 --examples_per_class 1`。
4. 运行 `data_processing/sensing/convert_consensus_datasets.py`。

## 4. 只有用户能提供的资源
| 文件 | 用途 |
|---|---|
| full-clinical-agent.7z（其中的 `trial_success.csv`） | 跑 clinical_agent。转换：`convert_medical_datasets.py --dataset trial_success --csv_path <csv>`。HF 上也有 `UUUooUUU/full-clinical-agent`，可以先试着从 HF 取 |
| MedXpertQA.tar（MM 图片） | 跑 mdagents 的多模态部分 |
| 旧结果文件（clinical_agent clean 等） | 只在分析旧数据时需要 |
| 用户本地的 normal 轨迹 | 还没确认是否存在 |

## 5. 外部仓库（按需 clone，沙箱可以直接 `git clone --depth 1`）
- gersteinlab/MedAgents
- nokia/multi-agent-collaboration-for-multimodal-sensing
- yczhou001/MAM
- ReML-AI/Sound-Dr（标签定义见 `SoundDr_BaselineSystem.py`）
- jinlab-imvr/MedAgent-Pro（暂不做）
