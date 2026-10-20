import pandas as pd

# 路径
train_jsonl = "data/dylan_debate_gsm_math/train.jsonl"
test_jsonl = "data/dylan_debate_gsm_math/test.jsonl"
train_parquet = "data/dylan_debate_gsm_math/train.parquet"
test_parquet = "data/dylan_debate_gsm_math/test.parquet"

# 读取 jsonl 并转为 DataFrame
train_df = pd.read_json(train_jsonl, lines=True)
test_df = pd.read_json(test_jsonl, lines=True)

# 保存为 parquet
train_df.to_parquet(train_parquet, index=False)
test_df.to_parquet(test_parquet, index=False)

print(f"已保存为 {train_parquet} 和 {test_parquet}")