import pandas as pd

# 读取 parquet 文件
df = pd.read_parquet("data/gsm8k/test.parquet")

# 保存为 jsonl 格式
df.to_json("data/gsm8k/test.jsonl", orient="records", lines=True, force_ascii=False)