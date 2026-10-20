#!/usr/bin/env python3
"""
数据格式转换脚本：将用户的错误检测数据转换为verl可用的SFT格式
从 /home/fanqi/verl/data/maserror/unified_dataset/unified_training_dataset.json
转换为 verl/GSM8K 兼容的格式
"""

import json
import os
from pathlib import Path

def format_conversation_history(input_data):
    """将对话历史格式化为结构化文本"""
    """
    从输入数据中提取完整的对话文本，包括 query 和 conversation_history
    
    Args:
        input_data: 输入数据字典，包含 query 和 conversation_history
        
    Returns:
        格式化的完整对话文本
    """
    query = input_data.get('query', '')
    conversation_history = input_data.get('conversation_history', [])
    
    # 开始构建对话文本
    conversation_text = f"QUERY:\n{query}\n\n"
    conversation_text += "CONVERSATION HISTORY:\n"
    
    for entry in conversation_history:
        step = entry.get('step', '')
        agent_name = entry.get('agent_name', '')
        agent_role = entry.get('agent_role', '')
        content = entry.get('content', '')
        phase = entry.get('phase', '')
        
        conversation_text += f"Step {step} - {agent_name} ({agent_role}) [{phase}]:\n{content}\n\n"
    
    # 添加任务指令
#     PROMPT_TEMPLATE = """## ROLE AND GOAL
# You are a meticulous Multi-Agent System (MAS) Quality Assurance analyst. Your sole purpose is to analyze conversation logs to identify and categorize agent errors based on a strict set of definitions.

# ## ERROR DEFINITIONS WITH EXAMPLES
# You MUST use the exact error codes provided below.

# ### Functional Mistakes (FM-1.x - Task Execution Errors):
# - FM-1.1: **Task specification deviation** - Agent deviates from specified task requirements (e.g., was asked to write code in Python, but used JavaScript).
# - FM-1.2: **Role specification deviation** - Agent acts outside its designated role (e.g., a 'CodeWriter' agent starts criticizing other agents' work, which is the 'Critic's' role).
# - FM-1.3: **Add redundant steps** - Agent adds unnecessary or duplicate steps (e.g., imports a library that was already imported in a previous step).
# - FM-1.4: **Remove conversation history** - Agent ignores or removes important context from previous turns (e.g., ignores a user's correction from the previous message).
# - FM-1.5: **Remove termination conditions** - Agent fails to define proper stopping criteria, leading to loops or unfinished tasks (e.g., writes a recursive function with no base case).

# ### Functional Mistakes (FM-2.x - Communication & Coordination Errors):
# - FM-2.1: **Repeat handled tasks** - Agent redundantly handles already completed tasks (e.g., re-writes a piece of code that was already finalized and approved).
# - FM-2.2: **Make request ambiguous** - Agent provides unclear or confusing instructions to other agents (e.g., asks another agent to "handle the data" without specifying how).
# - FM-2.3: **Deviate from main goal** - Agent pursues objectives unrelated to the main task (e.g., starts discussing the history of programming languages in the middle of a coding task).
# - FM-2.4: **Hide important information** - Agent withholds crucial information needed by other agents (e.g., knows a library has a bug but doesn't mention it).
# - FM-2.5: **Ignore other agents** - Agent fails to consider input, corrections, or questions from other agents.
# - FM-2.6: **Inconsistent reasoning** - Agent's logic contradicts its own previous statements (e.g., in step 2 agent says 'option A is best', but in step 4 says 'option A is a bad choice' without new information).

# ### Functional Mistakes (FM-3.x - Quality & Verification Errors):
# - FM-3.1: **Premature termination** - Agent stops or declares the task complete before all requirements are met.
# - FM-3.2: **Remove verification steps** - Agent skips necessary validation or testing steps (e.g., writes code but doesn't write any unit tests for it).
# - FM-3.3: **Incorrect verification** - Agent performs flawed or wrong verification (e.g., writes a test that doesn't actually check for the correct condition).

# ## ANALYSIS WORKFLOW
# 1.  **Internal Analysis (Chain of Thought)**: First, mentally break down the conversation turn by turn. For each agent's response, critically evaluate its actions against the error definitions. Note down any potential violations, the agent's name, and the corresponding error code.
# 2.  **Compile Final Output**: After completing your analysis, aggregate all identified faults into the required JSON format. If you found no errors, create an empty list for "faulty_agents".

# ## STRICT OUTPUT FORMAT
# Your final response **MUST BE A SINGLE, VALID JSON OBJECT** and nothing else. Do not include any explanatory text, comments, or markdown formatting like ```json.

# **Correct Format:**
# {{"faulty_agents": [{{"agent_name": "XXX", "error_type": "FM-X.X"}}]}}

# **Example for Multiple Errors:**
# {{"faulty_agents": [{{"agent_name": "XXX1", "error_type": "FM-1.1"}}, {{"agent_name": "XXX2", "error_type": "FM-3.2"}}, {{"agent_name": "XXX3", "error_type": "FM-2.5"}}]}}

# **Example for No Errors:**
# {{"faulty_agents": []}}

# ## CONVERSATION TO ANALYZE:
# \"\"\"
# {conversation_text}
# \"\"\"

# ## YOUR ANALYSIS (JSON ONLY):
# """
    COT_PROMPT_TEMPLATE = """
    ## ROLE AND GOAL
You are a meticulous Multi-Agent System (MAS) Quality Assurance analyst. Your sole purpose is to analyze conversation logs to identify and categorize agent errors based on a strict set of definitions.

## ERROR DEFINITIONS WITH EXAMPLES
You MUST use the exact error codes provided below.

### Functional Mistakes (FM-1.x - Task Execution Errors):
- FM-1.1: **Task specification deviation** - Agent deviates from specified task requirements (e.g., was asked to write code in Python, but used JavaScript).
- FM-1.2: **Role specification deviation** - Agent acts outside its designated role (e.g., a 'CodeWriter' agent starts criticizing other agents' work, which is the 'Critic's' role).
- FM-1.3: **Add redundant steps** - Agent adds unnecessary or duplicate steps (e.g., imports a library that was already imported in a previous step).
- FM-1.4: **Remove conversation history** - Agent ignores or removes important context from previous turns (e.g., ignores a user's correction from the previous message).
- FM-1.5: **Remove termination conditions** - Agent fails to define proper stopping criteria, leading to loops or unfinished tasks (e.g., writes a recursive function with no base case).

### Functional Mistakes (FM-2.x - Communication & Coordination Errors):
- FM-2.1: **Repeat handled tasks** - Agent redundantly handles already completed tasks (e.g., re-writes a piece of code that was already finalized and approved).
- FM-2.2: **Make request ambiguous** - Agent provides unclear or confusing instructions to other agents (e.g., asks another agent to "handle the data" without specifying how).
- FM-2.3: **Deviate from main goal** - Agent pursues objectives unrelated to the main task (e.g., starts discussing the history of programming languages in the middle of a coding task).
- FM-2.4: **Hide important information** - Agent withholds crucial information needed by other agents (e.g., knows a library has a bug but doesn't mention it).
- FM-2.5: **Ignore other agents** - Agent fails to consider input, corrections, or questions from other agents.
- FM-2.6: **Inconsistent reasoning** - Agent's logic contradicts its own previous statements (e.g., in step 2 agent says 'option A is best', but in step 4 says 'option A is a bad choice' without new information).

### Functional Mistakes (FM-3.x - Quality & Verification Errors):
- FM-3.1: **Premature termination** - Agent stops or declares the task complete before all requirements are met.
- FM-3.2: **Remove verification steps** - Agent skips necessary validation or testing steps (e.g., writes code but doesn't write any unit tests for it).
- FM-3.3: **Incorrect verification** - Agent performs flawed or wrong verification (e.g., writes a test that doesn't actually check for the correct condition).

## ANALYSIS WORKFLOW
Please follow these steps carefully:

### Step 1: Agent Summary
First, analyze and summarize what each agent has done throughout the conversation:
- List each agent that appears in the conversation
- For each agent, summarize their main actions, decisions, and contributions
- Note any patterns or recurring behaviors

### Step 2: Error Analysis
For each agent identified in Step 1:
- Carefully examine their actions against each error definition
- Look for violations of task requirements, role boundaries, communication issues, or quality problems
- Note any potential errors with specific reasoning

### Step 3: Final Judgment
Based on your analysis in Steps 1 and 2:
- Determine which agents (if any) committed errors
- Assign the appropriate error code(s) to each faulty agent
- Ensure agent names match exactly as they appear in the conversation log

## REQUIRED OUTPUT FORMAT
Your response must contain:

1. **Agent Summary**: A brief analysis of what each agent did
2. **Error Analysis**: Your reasoning for identifying errors
3. **Final Answer**: A valid JSON object with your conclusions

**JSON Format:**
{{"faulty_agents": [{{"agent_name": "XXX", "error_type": "FM-X.X"}}]}}

**Examples:**
- Multiple Errors: {{"faulty_agents": [{{"agent_name": "XXX1", "error_type": "FM-1.1"}}, {{"agent_name": "XXX2", "error_type": "FM-3.2"}}, {{"agent_name": "XXX3", "error_type": "FM-2.5"}}]}}
- No Errors: {{"faulty_agents": []}}

**Important:** Make sure the agent names you output exactly match those in the conversation log. Do not fabricate names.

## CONVERSATION TO ANALYZE:
{conversation_text}

## YOUR ANALYSIS:
"""
    return COT_PROMPT_TEMPLATE.format(conversation_text=conversation_text)

def format_output(output_data):
    """将输出数据格式化为JSON字符串"""
    faulty_agents = output_data.get('faulty_agents', [])
    
    # 只保留agent_role和error_type字段
    formatted_agents = []
    for agent in faulty_agents:
        formatted_agent = {
            'agent_name': agent.get('agent_name', agent.get('agent_role', '')),
            'error_type': agent.get('error_type', '')
        }
        if agent.get('agent_name', agent.get('agent_role', '')) == 'Assistant':
            print(1)
        formatted_agents.append(formatted_agent)
    
    result = {'faulty_agents': formatted_agents}
    return json.dumps(result, ensure_ascii=False, indent=2)

def convert_data_to_verl_format(input_file, output_file):
    """将用户数据转换为verl格式"""
    print(f"开始转换数据...")
    print(f"输入文件: {input_file}")
    print(f"输出文件: {output_file}")
    
    # 读取原始数据 (jsonl)
    with open(input_file, 'r', encoding='utf-8') as f:
        original_data = [json.loads(line) for line in f]
    
    print(f"原始数据条数: {len(original_data)}")
    
    # 转换数据
    converted_data = []
    for i, item in enumerate(original_data):
        try:
            # 提取输入和输出
            input_data = item['input']
            output_data = item['output']
            
            # 格式化为verl格式
            question = format_conversation_history(input_data)
            answer = format_output(output_data)
            
            # 创建verl格式的数据条目
            verl_item = {
                'data_source': 'maserror/agent_detection',
                'prompt': [{'content': question, 'role': 'user'}],
                'ability': 'error_detection',
                'reward_model': {'ground_truth': answer, 'style': 'structured'},
                'extra_info': {
                    'question': question,
                    'answer': answer,
                    'index': i,
                    'split': 'train',
                    'original_id': item.get('id', f'item_{i}')
                }
            }
            
            converted_data.append(verl_item)
            
        except Exception as e:
            print(f"转换第{i}条数据时出错: {e}")
            continue
    
    print(f"成功转换数据条数: {len(converted_data)}")
    
    # 保存转换后的数据（JSONL格式）
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        for item in converted_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"数据转换完成！保存到: {output_file}")
    
    # 显示转换示例
    if converted_data:
        print("\n=== 转换示例 ===")
        sample = converted_data[0]
        print("Question (前200字符):", sample['extra_info']['question'][:200] + "...")
        print("Answer:", sample['extra_info']['answer'])

def main():
    # 文件路径
    input_file = "/home/fanqi/verl/data/maserror/unified_dataset/val.jsonl"
    output_file = "/home/fanqi/verl/data/maserror/converted/val_cot.jsonl"
    
    # 检查输入文件是否存在
    if not os.path.exists(input_file):
        print(f"错误: 输入文件不存在 {input_file}")
        return
    
    # 执行转换
    convert_data_to_verl_format(input_file, output_file)
    
    print("\n=== 下一步 ===")
    print("1. 检查转换后的数据格式")
    print("2. 创建parquet文件（如果需要）")
    print("3. 修改SFT训练脚本使用新数据")

if __name__ == "__main__":
    main()