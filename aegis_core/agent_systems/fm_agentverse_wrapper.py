# file: agent_systems/fm_agentverse_wrapper.py

from .base_wrapper import SystemWrapper, _override_rounds, _llm_response_or_raise, LLMAPIFailure, _attach_task_images
from malicious_factory import FMMaliciousFactory, FMMaliciousAgent, InjectionStrategy
from typing import Any, Dict, Tuple
from methods import get_method_class

class FMAgentVerseWrapper(SystemWrapper):
    """
    A wrapper for the AgentVerse system using the new FM malicious injection system.
    Supports 28 different malicious injection methods.
    """
    def __init__(self, general_config: Dict[str, Any], method_config: Dict[str, Any]):
        from utils.async_llm import create_llm_instance
        exp_config = general_config.get('experiment_config', {})
        llm_config = exp_config.get('llm_config', {})
        if not llm_config:
            raise ValueError("No LLM configuration found for the specified model name.")
        
        self.llm = create_llm_instance(llm_config)
        method_name = exp_config['system_under_test']['name']  # "agentverse"
        dataset_name = exp_config.get('benchmark_name', None)
        MAS_CLASS = get_method_class(method_name, dataset_name)
        av_config_name = exp_config.get('agentverse_config_name') \
            or (method_config.get('agentverse_config_name') if isinstance(method_config, dict) else None)
        self.agentverse_instance = MAS_CLASS(general_config, method_config_name=av_config_name)
        # Apply per-experiment round overrides (max_rounds / max_turn / max_criticizing_rounds).
        self._round_settings = _override_rounds(self.agentverse_instance, exp_config, framework="agentverse")
        
        self.fm_factory = FMMaliciousFactory(
            llm=self.llm,
            injection_method=exp_config.get('injection_method', 'direct_prepend'),
            task_type=exp_config.get('task_type', 'mcq'),
            prompt_wrapper_style=exp_config.get('prompt_wrapper_style', 'direct')
        )
        
        self.call_count = 0
        self.conversation_history = []
        self.current_phase = "init"
        self.role_descriptions = []
        
        print(f"FMAgentVerseWrapper initialized with {MAS_CLASS.__name__}.")

    def run_with_multi_injection(
        self,
        task: Any,
        malicious_agents: list,
        injection_targets: list
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Run AgentVerse experiment with multiple malicious agent injections.
        """
        if len(malicious_agents) == 1 and len(injection_targets) == 1:
            # Fall back to single injection for backward compatibility
            return self.run_with_injection(task, malicious_agents[0], injection_targets[0])
        
        # Create a mapping from role to malicious agent
        injection_map = {}
        for agent, target in zip(malicious_agents, injection_targets):
            role = target['role']
            role_index = target.get('role_index', 0)
            key = (role, role_index)
            injection_map[key] = {
                'agent': agent,
                'target': target
            }
        
        print(f"[FMAgentVerseWrapper] Multi-injection targets: {list(injection_map.keys())}")
        
        # Multimodal: install image-auto-attach layer FIRST so every LLM call
        # made by this instance during inference carries the task's image(s).
        # No-op for text-only tasks (image_paths is None or []).
        _attach_task_images(self.agentverse_instance, getattr(task, 'image_paths', None))

        # Store the original call_llm method
        original_llm_call = self.agentverse_instance.call_llm
        self.call_count = 0
        self.conversation_history = []
        self.current_phase = "init"
        self.role_descriptions = []
        
        def fm_multi_malicious_call_llm(*args, **kwargs):
            self.call_count += 1
            print(f"[FMAgentVerseWrapper Multi] call_llm count: {self.call_count}")
            
            messages = args[2] if len(args) > 2 else kwargs.get('messages', [])
            current_role, current_role_index = self._determine_current_role_and_phase(messages)
            
            self._record_conversation_entry(current_role, current_role_index, messages)
            
            injection_key = (current_role, current_role_index)
            if injection_key not in injection_map:
                response = original_llm_call(*args, **kwargs)
                # If the API exhausted retries we get None here — raise an
                # explicit LLMAPIFailure so the outer try/except marks this as
                # an API failure, not as an "injection disrupted the system".
                response = _llm_response_or_raise(response, where=f"agentverse:{current_role}")
                self._record_response(current_role, current_role_index, response)
                return response
            
            injection_info = injection_map[injection_key]
            malicious_agent = injection_info['agent']
            target = injection_info['target']
            
            print(f"*** FM Multi-Malicious Agent Activated on '{current_role}' (index {current_role_index}) ***")
            print(f"    Error Type: {malicious_agent.fm_error_type.value}, Strategy: {malicious_agent.injection_strategy.value}")
            
            mock_agent = self._create_mock_agent(current_role, current_role_index)
            agent_context = self.fm_factory.extract_agent_context(
                mock_agent,
                {"name": current_role, "description": f"AgentVerse {current_role}"}
            )
            
            malicious_agent.agent_context = agent_context
            
            task_input = messages[-1]['content'] if messages else ""
            
            # Annotate the recorded entry so the trajectory shows injection ground truth.
            current_entry = self.conversation_history[-1] if self.conversation_history else None
            if current_entry is not None:
                current_entry['injection_applied'] = True
                current_entry['fm_error_type'] = malicious_agent.fm_error_type.value
                current_entry['injection_strategy'] = malicious_agent.injection_strategy.value
                # Snapshot of the original (pre-injection) messages for diffing later.
                current_entry['original_input_messages'] = [dict(m) for m in messages]

            try:
                if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                    modified_prompt = self.fm_factory.inject_prompt(task_input, malicious_agent.fm_error_type, malicious_agent.agent_context)
                    print(f"[FMAgentVerseWrapper Multi] Original prompt length: {len(task_input)}, Modified prompt length: {len(modified_prompt)}")
                    
                    modified_messages = messages.copy()
                    if modified_messages and len(modified_messages) > 0:
                        modified_messages[-1] = modified_messages[-1].copy()
                        modified_messages[-1]['content'] = modified_prompt
                    
                    # Overwrite the recorded input_messages so the trajectory reflects
                    # what was ACTUALLY sent to the LLM (not the pre-injection version).
                    if current_entry is not None:
                        current_entry['input_messages'] = [dict(m) for m in modified_messages]
                        current_entry['prompt_modified'] = (modified_prompt != task_input)
                        # Snapshot the factory's full injection process for auditing:
                        # for direct_prepend mode this is the instruction_template used;
                        # for llm_rewrite mode it includes the full modification_prefix
                        # sent to the rewriter LLM and the raw_llm_output it returned.
                        current_entry['injection_process'] = dict(self.fm_factory.last_injection_meta)

                    # Handle the case where we have positional args instead of kwargs
                    if len(args) >= 3:
                        # AgentVerse calls: call_llm(None, None, messages)
                        response = original_llm_call(args[0], args[1], modified_messages)
                    else:
                        modified_kwargs = kwargs.copy()
                        modified_kwargs['messages'] = modified_messages
                        response = original_llm_call(*args, **modified_kwargs)
                    
                elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                    clean_response = original_llm_call(*args, **kwargs)
                    if clean_response:
                        response = self.fm_factory.corrupt_response(clean_response, malicious_agent.fm_error_type, malicious_agent.agent_context)
                        if current_entry is not None:
                            current_entry['clean_response_before_corruption'] = clean_response
                            current_entry['response_corrupted'] = (response != clean_response)
                            # Same auditing snapshot: for response_corruption this contains
                            # the corruption_template (direct_prepend) or the full
                            # response_modification_prefix (llm_rewrite). NOTE: this is NOT
                            # the same as input_messages, because response_corruption does
                            # NOT modify the prompt sent to the target agent — it only
                            # alters the OUTPUT after the call. So input_messages here
                            # legitimately equals original_input_messages.
                            current_entry['injection_process'] = dict(self.fm_factory.last_injection_meta)
                    else:
                        print(f"[FMAgentVerseWrapper Multi] Warning: clean_response is None, skipping corruption")
                        response = clean_response
                else:
                    response = original_llm_call(*args, **kwargs)
                
                # Ensure response is not None
                if response is None:
                    print(f"[FMAgentVerseWrapper Multi] Warning: Injection resulted in None response, calling original again")
                    response = original_llm_call(*args, **kwargs)
                    
            except Exception as e:
                print(f"[FMAgentVerseWrapper Multi] Error during injection: {e}, falling back to original call")
                if current_entry is not None:
                    current_entry['injection_error'] = str(e)
                response = original_llm_call(*args, **kwargs)
            
            self._record_response(current_role, current_role_index, response)
            return response
        
        # Apply monkey patch
        self.agentverse_instance.call_llm = fm_multi_malicious_call_llm
        print(f"[FMAgentVerseWrapper] Multi-injection monkey-patch applied for {len(malicious_agents)} targets.")
        
        # Execute with error handling
        sample = {"query": task.query}
        final_output = None
        execution_error = None
        
        try:
            final_output = self.agentverse_instance.inference(sample)
            print("[FMAgentVerseWrapper] Inference completed successfully")
        except LLMAPIFailure as e:
            execution_error = f"llm_api_failure: {e}"
            print(f"[FMAgentVerseWrapper] LLM API FAILURE (not an injection effect): {e}")
            final_output = {"response": f"LLM API failure: {e}"}
        except Exception as e:
            execution_error = str(e)
            print(f"[FMAgentVerseWrapper] Inference failed due to injection effects: {e}")
            # Create a fallback response indicating the injection was successful in disrupting the system
            final_output = {"response": f"AgentVerse execution disrupted by malicious injection: {execution_error}"}
        
        # Cleanup
        self.agentverse_instance.call_llm = original_llm_call
        print("[FMAgentVerseWrapper] Original `call_llm` method restored.")
        
        # Create comprehensive log
        log = {
            "final_output": final_output,
            "call_count": self.call_count,
            "conversation_history": self.conversation_history,
            "role_descriptions": self.role_descriptions,
            "multi_injection_info": [
                {
                    "injected_role": target['role'],
                    "injected_role_index": target.get('role_index', 0),
                    "fm_error_type": agent.fm_error_type.value,
                    "injection_strategy": agent.injection_strategy.value,
                    "malicious_action_description": agent.description,
                }
                for agent, target in zip(malicious_agents, injection_targets)
            ],
            "num_injected_agents": len(malicious_agents),
            # Distinct speakers observed in this trajectory, in first-seen order.
            # AgentVerse assigns roles dynamically via RoleAssigner. Our internal
            # `self.conversation_history` entries use the key "role" (not
            # "agent_name" — that rename happens later in the normalizer), so
            # we read "role" here. We exclude RoleAssigner since it's a
            # meta-orchestrator that produces role descriptions, not a
            # task-solving agent (you can re-include it by changing the filter).
            "agent_names": list(dict.fromkeys(
                h.get("role") for h in self.conversation_history
                if h.get("role") and h.get("role") not in ("User",)
            )),
            # Add execution status information for multi-agent injection
            "execution_successful": execution_error is None,
            "execution_error": execution_error,
            "injection_disrupted_system": execution_error is not None,
        }
        
        return final_output, log

    def run_with_injection(
        self,
        task: Any,
        malicious_agent: FMMaliciousAgent,
        injection_target: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any]]:
        
        target_role = injection_target['role']
        target_role_index = injection_target.get('role_index', 0)
        print(f"[FMAgentVerseWrapper] Target role: {target_role}, index: {target_role_index}")
        
        # Store the original call_llm method
        original_llm_call = self.agentverse_instance.call_llm
        self.call_count = 0
        self.conversation_history = []
        self.current_phase = "init"
        self.role_descriptions = []
        
        def fm_malicious_call_llm(*args, **kwargs):
            self.call_count += 1
            print(f"[FMAgentVerseWrapper] call_llm count: {self.call_count}")
            
            messages = args[2] if len(args) > 2 else kwargs.get('messages', [])
            current_role, current_role_index = self._determine_current_role_and_phase(messages)
            
            self._record_conversation_entry(current_role, current_role_index, messages)
            
            should_inject = (current_role == target_role and current_role_index == target_role_index)
            
            if not should_inject:
                response = original_llm_call(*args, **kwargs)
                self._record_response(current_role, current_role_index, response)
                return response
            
            print(f"*** FM Malicious Agent Activated on '{current_role}' (index {current_role_index}) ***")
            print(f"    Error Type: {malicious_agent.fm_error_type.value}, Strategy: {malicious_agent.injection_strategy.value}")
            
            mock_agent = self._create_mock_agent(current_role, current_role_index)
            agent_context = self.fm_factory.extract_agent_context(
                mock_agent,
                {"name": current_role, "description": f"AgentVerse {current_role}"}
            )
            
            malicious_agent.agent_context = agent_context
            
            task_input = messages[-1]['content'] if messages else ""
            
            try:
                if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                    modified_prompt = self.fm_factory.inject_prompt(task_input, malicious_agent.fm_error_type, malicious_agent.agent_context)
                    print(f"[FMAgentVerseWrapper] Original prompt length: {len(task_input)}, Modified prompt length: {len(modified_prompt)}")
                    
                    modified_messages = messages.copy()
                    if modified_messages and len(modified_messages) > 0:
                        modified_messages[-1] = modified_messages[-1].copy()
                        modified_messages[-1]['content'] = modified_prompt
                    
                    # Handle the case where we have positional args instead of kwargs
                    if len(args) >= 3:
                        # AgentVerse calls: call_llm(None, None, messages)
                        response = original_llm_call(args[0], args[1], modified_messages)
                    else:
                        modified_kwargs = kwargs.copy()
                        modified_kwargs['messages'] = modified_messages
                        response = original_llm_call(*args, **modified_kwargs)
                    
                elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                    clean_response = original_llm_call(*args, **kwargs)
                    if clean_response:
                        response = self.fm_factory.corrupt_response(clean_response, malicious_agent.fm_error_type, malicious_agent.agent_context)
                    else:
                        print(f"[FMAgentVerseWrapper] Warning: clean_response is None, skipping corruption")
                        response = clean_response
                else:
                    response = original_llm_call(*args, **kwargs)
                
                # Ensure response is not None
                if response is None:
                    print(f"[FMAgentVerseWrapper] Warning: Injection resulted in None response, calling original again")
                    response = original_llm_call(*args, **kwargs)
                    
            except Exception as e:
                print(f"[FMAgentVerseWrapper] Error during injection: {e}, falling back to original call")
                response = original_llm_call(*args, **kwargs)
            
            self._record_response(current_role, current_role_index, response)
            return response
        
        self.agentverse_instance.call_llm = fm_malicious_call_llm
        print(f"[FMAgentVerseWrapper] Monkey-patch applied. Target: {target_role} (index {target_role_index})")
        print(f"[FMAgentVerseWrapper] Injection: {malicious_agent.fm_error_type.value} via {malicious_agent.injection_strategy.value}")
        
        # Execute with error handling
        sample = {"query": task.query}
        final_output = None
        execution_error = None
        
        try:
            final_output = self.agentverse_instance.inference(sample)
            print("[FMAgentVerseWrapper] Single-agent inference completed successfully")
        except Exception as e:
            execution_error = str(e)
            print(f"[FMAgentVerseWrapper] Single-agent inference failed due to injection effects: {e}")
            # Create a fallback response indicating the injection was successful in disrupting the system
            final_output = {"response": f"AgentVerse execution disrupted by malicious injection: {execution_error}"}
        
        self.agentverse_instance.call_llm = original_llm_call
        print("[FMAgentVerseWrapper] Original `call_llm` method restored.")
        
        log = {
            "final_output": final_output,
            "injected_role": target_role,
            "injected_role_index": target_role_index,
            "call_count": self.call_count,
            "conversation_history": self.conversation_history,
            "role_descriptions": self.role_descriptions,
            "fm_error_type": malicious_agent.fm_error_type.value,
            "injection_strategy": malicious_agent.injection_strategy.value,
            "malicious_action_description": malicious_agent.description,
            # Add execution status information
            "execution_successful": execution_error is None,
            "execution_error": execution_error,
            "injection_disrupted_system": execution_error is not None,
        }
        return final_output, log
    
    def _determine_current_role_and_phase(self, messages: list) -> tuple:
        """
        根据消息内容判断当前的角色和阶段
        AgentVerse的调用顺序：
        1. Role Assigner (分配角色)
        2. Solver (初始解决方案 + 后续修订)
        3. Critics (评审，可能有多个)
        4. Evaluator (最终评估)
        """
        if not messages:
            return "Unknown", 0
        
        content = ""
        for msg in messages:
            content += msg.get('content', '') + " "
        content = content.lower()
        
        if self.call_count == 1:
            self.current_phase = "role_assignment"
            return "RoleAssigner", 0
        
        if any(keyword in content for keyword in ["evaluate", "score", "correctness", "assessment"]):
            self.current_phase = "evaluation"
            return "Evaluator", 0
        
        if any(keyword in content for keyword in ["review", "critic", "feedback", "opinion", "assessment"]):
            critic_index = self._calculate_critic_index()
            self.current_phase = "criticism"
            return "Critic", critic_index
        
        solver_index = self._calculate_solver_index()
        self.current_phase = "solving"
        return "Solver", solver_index
    
    def _calculate_critic_index(self) -> int:
        """计算当前批评者的索引"""
        cnt_agents = getattr(self.agentverse_instance, 'cnt_agents', 3)
        return (self.call_count - 2) % (cnt_agents - 1) if cnt_agents > 1 else 0
    
    def _calculate_solver_index(self) -> int:
        """计算当前解决者的索引（通常只有一个解决者，索引为0）"""
        return 0
    
    def _create_mock_agent(self, role: str, role_index: int):
        """创建模拟的agent对象"""
        class MockAgent:
            def __init__(self, role_name, role_index, agentverse_instance):
                self.role_name = role_name
                self.role_type = f"AgentVerse {role_name}"
                self.agent_id = f"agentverse_{role_name.lower()}_{role_index}"
                self.role_index = role_index
                self.agentverse_instance = agentverse_instance
                self.tool_dict = {}
                self.model_type = "LLM"
                self.chat_history = []
                
                if role_name == "RoleAssigner":
                    self.system_message = "You are a role assigner responsible for assigning appropriate roles to agents based on the given query."
                elif role_name == "Solver":
                    self.system_message = f"You are agent {role_index + 1}, a problem solver responsible for generating solutions."
                elif role_name == "Critic":
                    self.system_message = f"You are agent {role_index + 1}, a critic responsible for reviewing and providing feedback on solutions."
                elif role_name == "Evaluator":
                    self.system_message = "You are an evaluator responsible for assessing the quality and correctness of solutions."
                else:
                    self.system_message = f"You are agent {role_index + 1} in the AgentVerse system."
        
        return MockAgent(role, role_index, self.agentverse_instance)
    
    def _record_conversation_entry(self, role: str, role_index: int, messages: list):
        """记录对话条目"""
        entry = {
            "phase": self.current_phase,
            "role": role,
            "role_index": role_index,
            "call_count": self.call_count,
            "input_messages": messages.copy(),
            "timestamp": "current"
        }
        self.conversation_history.append(entry)
    
    def _record_response(self, role: str, role_index: int, response: str):
        """记录响应"""
        for entry in self.conversation_history:
            if entry["call_count"] == self.call_count:
                entry["response"] = response
                
                if role == "RoleAssigner":
                    try:
                        role_descriptions = self.agentverse_instance.extract_role_descriptions(response)
                        self.role_descriptions = role_descriptions
                        entry["parsed_roles"] = role_descriptions
                    except:
                        pass
                break