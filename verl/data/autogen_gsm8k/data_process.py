import json
import random

input_path = "data/autogen_gsm8k/detection_results.jsonl"
train_path = "data/autogen_gsm8k/train.jsonl"
test_path = "data/autogen_gsm8k/test.jsonl"
split_ratio = 0.8  # 80% train, 20% test

# 1. 读取所有数据
with open(input_path, "r", encoding="utf-8") as f:
    data = [json.loads(line) for line in f]

# 2. 随机划分
random.shuffle(data)
split_idx = int(len(data) * split_ratio)
train_data = data[:split_idx]
test_data = data[split_idx:]

def convert_item(item):
    # prompt: detector_prompt -> content, role=user
    prompt = [{"content": item["detector_prompt"], "role": "user"}]
    # reward_model
    reward_model = {
        "ground_truth": item["ground_truth_injected_role"],
        "style": "rule"
    }
    # extra_info
    extra_info = {
        "index": item.get("index", None),
        "split": item.get("split", None),
        "question": item.get("query", None)
    }
    # ability
    ability = "math"
    return {
        "data_source": "autogen_gsm8k",
        "prompt": prompt,
        "ability": ability,
        "reward_model": reward_model,
        "extra_info": extra_info
    }

# 3. 转换格式
train_data = [convert_item(item) for item in train_data]
test_data = [convert_item(item) for item in test_data]

# 4. 写出为 jsonl
with open(train_path, "w", encoding="utf-8") as f:
    for item in train_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

with open(test_path, "w", encoding="utf-8") as f:
    for item in test_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"转换完成！训练集：{train_path}，测试集：{test_path}")