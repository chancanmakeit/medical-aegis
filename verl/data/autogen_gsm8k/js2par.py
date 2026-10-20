import pandas as pd

# 路径
train_jsonl = "data/autogen_gsm8k/train.jsonl"
test_jsonl = "data/autogen_gsm8k/test.jsonl"
train_parquet = "data/autogen_gsm8k/train.parquet"
test_parquet = "data/autogen_gsm8k/test.parquet"

# 读取 jsonl 并转为 DataFrame
train_df = pd.read_json(train_jsonl, lines=True)
test_df = pd.read_json(test_jsonl, lines=True)

# 保存为 parquet
train_df.to_parquet(train_parquet, index=False)
test_df.to_parquet(test_parquet, index=False)

print(f"已保存为 {train_parquet} 和 {test_parquet}")