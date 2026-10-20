import random

input_path = "verl/data/dylan_debate_gsm_math/detector_debate_gsm8k_converted.jsonl"
train_path = "verl/data/dylan_debate_gsm_math/train.jsonl"
test_path = "verl/data/dylan_debate_gsm_math/test.jsonl"
split_ratio = 0.8  # 80% train, 20% test

# 先统计总行数
with open(input_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

total = len(lines)
indices = list(range(total))
random.shuffle(indices)
split = int(total * split_ratio)
train_indices = set(indices[:split])

with open(train_path, "w", encoding="utf-8") as train_f, open(test_path, "w", encoding="utf-8") as test_f:
    for idx, line in enumerate(lines):
        if idx in train_indices:
            train_f.write(line)
        else:
            test_f.write(line)

print(f"Total: {total}, Train: {split}, Test: {total - split}")