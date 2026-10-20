#!/usr/bin/env python3
"""
将JSONL文件转换为parquet格式，供verl训练使用
增强版本：支持自定义验证集比例和随机划分
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
import argparse
import random

def jsonl_to_parquet_with_split(jsonl_file, output_dir, val_ratio=0.1, random_seed=42):
    """
    将JSONL文件转换为parquet格式，并按比例划分训练集和验证集
    
    Args:
        jsonl_file: 输入的JSONL文件路径
        output_dir: 输出目录
        val_ratio: 验证集比例 (默认0.1，即10%)
        random_seed: 随机种子，确保可重现
    """
    print(f"读取JSONL文件: {jsonl_file}")
    print(f"验证集比例: {val_ratio}")
    print(f"随机种子: {random_seed}")
    
    # 读取JSONL数据
    data = []
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    
    print(f"读取到 {len(data)} 条数据")
    
    if val_ratio > 0:
        # 设置随机种子
        random.seed(random_seed)
        
        # 随机打乱数据
        shuffled_data = data.copy()
        random.shuffle(shuffled_data)
        
        # 计算验证集大小
        val_size = int(len(shuffled_data) * val_ratio)
        
        # 划分训练集和验证集
        val_data = shuffled_data[:val_size]
        train_data = shuffled_data[val_size:]
        
        print(f"划分结果:")
        print(f"  训练集: {len(train_data)} 条 ({len(train_data)/len(data)*100:.1f}%)")
        print(f"  验证集: {len(val_data)} 条 ({len(val_data)/len(data)*100:.1f}%)")
        
        # 更新split标记
        for item in train_data:
            item['extra_info']['split'] = 'train'
        for item in val_data:
            item['extra_info']['split'] = 'val'
    else:
        # 全部作为训练集
        train_data = data
        val_data = []
        print(f"全部数据作为训练集: {len(train_data)} 条")
    
    # 创建输出目录
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 保存训练集
    train_parquet_file = Path(output_dir) / "train.parquet"
    train_df = pd.DataFrame(train_data)
    train_df.to_parquet(train_parquet_file, index=False)
    print(f"训练集保存到: {train_parquet_file}")
    print(f"训练集文件大小: {train_parquet_file.stat().st_size / 1024 / 1024:.2f} MB")
    
    # 保存验证集（如果有）
    if val_data:
        val_parquet_file = Path(output_dir) / "val.parquet"
        val_df = pd.DataFrame(val_data)
        val_df.to_parquet(val_parquet_file, index=False)
        print(f"验证集保存到: {val_parquet_file}")
        print(f"验证集文件大小: {val_parquet_file.stat().st_size / 1024 / 1024:.2f} MB")
    
    return len(train_data), len(val_data)

def check_data_quality(output_dir):
    """检查数据质量和完整性"""
    print("\n=== 数据质量检查 ===")
    
    train_file = Path(output_dir) / "train.parquet"
    val_file = Path(output_dir) / "val.parquet"
    
    # 检查训练集
    if train_file.exists():
        train_df = pd.read_parquet(train_file)
        print(f"训练集数据检查:")
        print(f"  样本数: {len(train_df)}")
        print(f"  列名: {list(train_df.columns)}")
        print(f"  数据源分布: {train_df['data_source'].value_counts().to_dict()}")
        print(f"  能力分布: {train_df['ability'].value_counts().to_dict()}")
        
        # 检查唯一性
        questions = []
        for idx, row in train_df.iterrows():
            extra_info = row['extra_info']
            if isinstance(extra_info, str):
                extra_info = json.loads(extra_info)
            questions.append(extra_info.get('question', ''))
        unique_questions = len(set(questions))
        print(f"  唯一问题数: {unique_questions}/{len(train_df)} ({unique_questions/len(train_df)*100:.1f}%)")
    
    # 检查验证集
    if val_file.exists():
        val_df = pd.read_parquet(val_file)
        print(f"\n验证集数据检查:")
        print(f"  样本数: {len(val_df)}")
        print(f"  数据源分布: {val_df['data_source'].value_counts().to_dict()}")
        print(f"  能力分布: {val_df['ability'].value_counts().to_dict()}")
        
        # 检查与训练集的重叠
        val_questions = []
        for idx, row in val_df.iterrows():
            extra_info = row['extra_info']
            if isinstance(extra_info, str):
                extra_info = json.loads(extra_info)
            val_questions.append(extra_info.get('question', ''))
        
        if train_file.exists():
            train_questions = []
            train_df = pd.read_parquet(train_file)
            for idx, row in train_df.iterrows():
                extra_info = row['extra_info']
                if isinstance(extra_info, str):
                    extra_info = json.loads(extra_info)
                train_questions.append(extra_info.get('question', ''))
            
            overlap = len(set(train_questions) & set(val_questions))
            print(f"  与训练集重叠: {overlap} 个问题")
            if overlap > 0:
                print(f"  ⚠️  警告: 训练集和验证集存在重叠!")

def main():
    parser = argparse.ArgumentParser(description="将JSONL转换为Parquet并划分训练/验证集")
    parser.add_argument("--input", 
                       default="/home/fanqi/verl/data/maserror/converted/train.jsonl",
                       help="输入JSONL文件路径")
    parser.add_argument("--output_dir", 
                       default="/home/fanqi/verl/data/maserror/converted",
                       help="输出目录")
    parser.add_argument("--val_ratio", 
                       type=float, 
                       default=0.15,
                       help="验证集比例 (默认0.15，即15%)")
    parser.add_argument("--random_seed", 
                       type=int, 
                       default=42,
                       help="随机种子")
    parser.add_argument("--check_quality", 
                       action="store_true",
                       help="检查数据质量")
    
    args = parser.parse_args()
    
    # 检查输入文件
    if not Path(args.input).exists():
        print(f"错误: 输入文件不存在 {args.input}")
        return
    
    # 转换数据
    train_count, val_count = jsonl_to_parquet_with_split(
        args.input, 
        args.output_dir, 
        args.val_ratio,
        args.random_seed
    )
    
    # 数据质量检查
    if args.check_quality:
        check_data_quality(args.output_dir)
    
    print(f"\n=== 转换完成 ===")
    print(f"训练集: {train_count} 样本")
    print(f"验证集: {val_count} 样本")
    print(f"总计: {train_count + val_count} 样本")
    
    print(f"\n=== 下一步建议 ===")
    print(f"1. 检查数据质量: python {__file__} --check_quality")
    print(f"2. 调整验证集比例: python {__file__} --val_ratio 0.2")
    print(f"3. 更新训练脚本中的max_length设置")

if __name__ == "__main__":
    main()