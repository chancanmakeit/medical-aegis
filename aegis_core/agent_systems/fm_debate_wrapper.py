# DEPRECATED (2026-10-20): superseded by aegis_core.agent_systems.fm_llm_debate_structured_wrapper.FMLLMDebateStructuredWrapper
# (structured contract: clean input_messages, read sets, agent ids, llm_meta,
# inject-once). Kept only to reproduce data generated before the migration.
# file: agent_systems/fm_debate_wrapper.py

from .base_wrapper import SystemWrapper, _override_rounds, _llm_response_or_raise, LLMAPIFailure, _attach_task_images
from malicious_factory import FMMaliciousFactory, FMMaliciousAgent, InjectionStrategy
from typing import Any, Dict, Tuple
from methods import get_method_class

class FM_Debate_Wrapper(SystemWrapper):
    """
    A wrapper for the LLM Debate system supporting FM Malicious injection (prompt_injection/response_corruption).
    """
    def __init__(self, general_config: Dict[str, Any], method_config: Dict[str, Any]):
        from utils.async_llm import create_llm_instance
        exp_config = general_config.get('experiment_config', {})
        llm_config = exp_config.get('llm_config', {})
        if not llm_config:
            raise ValueError("No LLM configuration found for the specified model name.")
        self.llm = create_llm_instance(llm_config)
        method_name = exp_config['system_under_test']['name']  # "llm_debate"
        dataset_name = exp_config.get('benchmark_name', None)
        MAS_CLASS = get_method_class(method_name, dataset_name)
        debate_config_name = exp_config.get('llm_debate_config_name') \
            or (method_config.get('llm_debate_config_name') if isinstance(method_config, dict) else None)
        self.debate_instance = MAS_CLASS(general_config, method_config_name=debate_config_name)
        # Allow per-experiment override of round counts without editing the method config.
        _override_rounds(self.debate_instance, exp_config, framework="llm_debate")
        self.fm_factory = FMMaliciousFactory(
            llm=self.llm,
            injection_method=exp_config.get('injection_method', 'direct_prepend'),
            task_type=exp_config.get('task_type', 'mcq'),
            prompt_wrapper_style=exp_config.get('prompt_wrapper_style', 'direct')
        )
        print(f"FM_Debate_Wrapper initialized with {MAS_CLASS.__name__}.")

    def run_with_multi_injection(
        self,
        task: Any,
        malicious_agents: list,
        injection_targets: list
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Run LLM Debate experiment with multiple malicious agent injections.
        """
        if len(malicious_agents) == 1 and len(injection_targets) == 1:
            # Fall back to single injection for backward compatibility
            return self.run_with_injection(task, malicious_agents[0], injection_targets[0])
        
        # Create a mapping from agent index to malicious agent
        injection_map = {}
        for agent, target in zip(malicious_agents, injection_targets):
            target_agent_index = target.get('role_index', 0)
            injection_map[target_agent_index] = {
                'agent': agent,
                'target': target
            }
        
        print(f"[FM_Debate_Wrapper] Multi-injection targets: {list(injection_map.keys())}")
        
        # Start capturing real LLM inputs/outputs for true input_messages.
        # Multimodal: install image-auto-attach layer FIRST (before capture & injection)
        # so every LLM call this instance makes during inference carries the task's
        # image(s). No-op for text-only tasks (image_paths is None or []).
        _attach_task_images(self.debate_instance, getattr(task, 'image_paths', None))
        llm_capture = self._start_llm_capture(self.debate_instance)

        # Store the original call_llm method (now the capturing wrapper)
        original_call_llm = self.debate_instance.call_llm
        agents_num = getattr(self.debate_instance, 'agents_num', 3)
        rounds_num = getattr(self.debate_instance, 'rounds_num', 2)
        call_count = {'count': 0}
        # Per-response-text injection metadata, used to annotate agent_contexts[] later.
        injection_meta_by_response = {}
        # Aggregator turn capture (the aggregator call is NOT in agent_contexts).
        aggregator_capture = {
            "happened": False,
            "input_prompt": None,
            "system_prompt": None,
            "clean_response": None,   # what the aggregator would have said w/o corruption
            "actual_response": None,  # what was actually returned (post-corruption if any)
            "injection_meta": None,
        }

        def fm_multi_malicious_call_llm(*args, **kwargs):
            idx = call_count['count'] % agents_num
            call_count['count'] += 1
            # Detect aggregator step: it runs AFTER all (agents_num * rounds_num) debate calls.
            is_aggregator_step = call_count['count'] > agents_num * rounds_num
            
            # Check if this agent should be injected
            should_inject = False
            injection_info = None
            
            # Check for debate agents injection (during rounds)
            if call_count['count'] <= agents_num * rounds_num:
                if idx in injection_map:
                    target = injection_map[idx]['target']
                    if target.get('role', 'Agent') == 'Agent':
                        should_inject = True
                        injection_info = injection_map[idx]
            
            # Check for aggregator injection (after rounds)
            elif call_count['count'] > agents_num * rounds_num:
                # Look for Aggregator role in injection map
                for map_idx, injection_data in injection_map.items():
                    target = injection_data['target']
                    if target.get('role', 'Agent') == 'Aggregator':
                        should_inject = True
                        injection_info = injection_data
                        break
            
            if should_inject and injection_info:
                malicious_agent = injection_info['agent']
                target = injection_info['target']
                
                # Check if this is an aggregator injection
                is_aggregator = target.get('role', 'Agent') == 'Aggregator'
                
                if is_aggregator:
                    print(f"*** FM Multi-Malicious Aggregator Activated [Type {malicious_agent.fm_error_type.value}, Strategy {malicious_agent.injection_strategy.value}] ***")
                else:
                    print(f"*** FM Multi-Malicious Agent Activated on index {idx} [Type {malicious_agent.fm_error_type.value}, Strategy {malicious_agent.injection_strategy.value}] ***")
                
                messages = kwargs.get('messages', [])
                task_input = ""
                if messages:
                    for msg in reversed(messages):
                        if msg.get('role') == 'user':
                            task_input = msg.get('content', '')
                            break
                # For aggregator calls (prompt=... not messages=...), task_input is in kwargs['prompt'].
                if not task_input and is_aggregator:
                    task_input = kwargs.get('prompt', '') or (args[0] if args else '')
                
                # Create mock agent for context extraction
                class MockAgent:
                    def __init__(self, idx, is_aggregator=False):
                        if is_aggregator:
                            self.role_name = "Aggregator"
                            self.role_type = "Debate Aggregator"
                            self.agent_id = "debate_aggregator"
                            self.system_message = "You are the Aggregator responsible for synthesizing all agent responses into a final answer."
                        else:
                            self.role_name = f"Agent {idx+1}"
                            self.role_type = "Debate Agent"
                            self.agent_id = f"debate_{idx}"
                            self.system_message = f"You are Agent {idx+1} in a debate."
                        self.tool_dict = {}
                        self.model_type = "LLM"
                        self.chat_history = []
                        self.agent_index = idx
                
                mock_agent = MockAgent(idx, is_aggregator=is_aggregator)
                agent_context = self.fm_factory.extract_agent_context(
                    mock_agent,
                    {"name": mock_agent.role_name, "description": mock_agent.system_message}
                )
                malicious_agent.agent_context = agent_context
                
                _meta = {
                    "injection_applied": True,
                    "fm_error_type": malicious_agent.fm_error_type.value,
                    "injection_strategy": malicious_agent.injection_strategy.value,
                    "original_input_messages": [dict(m) for m in messages] if messages else [],
                }

                if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                    modified_prompt = self.fm_factory.inject_prompt(task_input, malicious_agent.fm_error_type, malicious_agent.agent_context)
                    modified_messages = messages.copy()
                    if modified_messages and len(modified_messages) > 0:
                        modified_messages[-1] = modified_messages[-1].copy()
                        modified_messages[-1]['content'] = modified_prompt
                    modified_kwargs = kwargs.copy()
                    modified_kwargs['messages'] = modified_messages
                    response = original_call_llm(*args, **modified_kwargs)
                    _meta["prompt_modified"] = (modified_prompt != task_input)
                    _meta["injected_input_messages"] = [dict(m) for m in modified_messages]
                    _meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
                elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                    clean_response = original_call_llm(*args, **kwargs)
                    response = self.fm_factory.corrupt_response(clean_response, malicious_agent.fm_error_type, malicious_agent.agent_context)
                    _meta["clean_response_before_corruption"] = clean_response
                    _meta["response_corrupted"] = (response != clean_response)
                    _meta["injection_process"] = dict(self.fm_factory.last_injection_meta)
                else:
                    response = original_call_llm(*args, **kwargs)

                # Index injection metadata by the response text so the post-hoc
                # history builder can attach it to the right assistant turn.
                if response:
                    injection_meta_by_response[str(response)] = _meta

                # If this was the aggregator step, capture it so we can add a
                # synthetic Aggregator turn to the trajectory (agent_contexts
                # only records the per-Agent debate turns, NOT the aggregator).
                if is_aggregator_step:
                    aggregator_capture["happened"] = True
                    aggregator_capture["input_prompt"] = kwargs.get('prompt') or (args[0] if args else None)
                    aggregator_capture["system_prompt"] = kwargs.get('system_prompt')
                    aggregator_capture["clean_response"] = _meta.get('clean_response_before_corruption', response)
                    aggregator_capture["actual_response"] = response
                    aggregator_capture["injection_meta"] = _meta

                return response
            
            # Passthrough: not an injection target. Still capture the aggregator call.
            resp = original_call_llm(*args, **kwargs)
            resp = _llm_response_or_raise(resp, where=f"llm_debate:idx{idx}{'_aggregator' if is_aggregator_step else ''}")
            if is_aggregator_step and not aggregator_capture["happened"]:
                aggregator_capture["happened"] = True
                aggregator_capture["input_prompt"] = kwargs.get('prompt') or (args[0] if args else None)
                aggregator_capture["system_prompt"] = kwargs.get('system_prompt')
                aggregator_capture["clean_response"] = resp
                aggregator_capture["actual_response"] = resp
            return resp

        # Apply monkey patch
        self.debate_instance.call_llm = fm_multi_malicious_call_llm
        print(f"[FM_Debate_Wrapper] Multi-injection monkey-patch applied for {len(malicious_agents)} targets.")
        
        # Execute
        sample = {"query": task.query}
        execution_error = None
        try:
            final_output = self.debate_instance.inference(sample)
        except LLMAPIFailure as e:
            execution_error = f"llm_api_failure: {e}"
            print(f"[FM_Debate_Wrapper] LLM API FAILURE (not an injection effect): {e}")
            final_output = {"response": f"LLM API failure: {e}"}
        except Exception as e:
            execution_error = str(e)
            print(f"[FM_Debate_Wrapper] Inference failed during multi-injection: {e}")
            final_output = {"response": f"LLM-Debate execution disrupted by malicious injection: {execution_error}"}
        
        # Cleanup
        self.debate_instance.call_llm = original_call_llm
        self._stop_llm_capture(self.debate_instance)
        print("[FM_Debate_Wrapper] Original call_llm restored.")

        # Record conversation history
        full_history = []
        agent_contexts = getattr(self.debate_instance, 'agent_contexts', None)
        if agent_contexts is not None:
            for agent_index, context in enumerate(agent_contexts):
                for msg_index, message in enumerate(context):
                    is_user_input = (message["role"] != "assistant")
                    entry = {
                        "role": f"Agent {agent_index+1}" if not is_user_input else "User",
                        "role_index": agent_index,
                        "content": message["content"],
                        "msg_index": msg_index,
                        # Mark User turns as INPUTS to the next agent call, not as
                        # standalone speaking turns. Helps downstream tools (and humans)
                        # avoid mistaking inputs for agent statements.
                        "is_input": is_user_input,
                    }
                    # Attach injection metadata if this assistant turn was injected.
                    if message["role"] == "assistant":
                        meta = injection_meta_by_response.get(str(message["content"]))
                        if meta:
                            entry.update(meta)
                    full_history.append(entry)

        # Append a synthetic Aggregator turn (it is NOT in agent_contexts).
        # The aggregator is the LLM-Debate framework's final synthesis step:
        # it reads all per-Agent answers and produces the final response.
        if aggregator_capture["happened"]:
            agg_entry = {
                "role": "Aggregator",
                "role_index": 0,
                "content": aggregator_capture["actual_response"],
                "is_input": False,
                "is_aggregator": True,
            }
            # Synthesize an input_messages snapshot from the prompt+system_prompt
            # (aggregator uses call_llm(prompt=...) not call_llm(messages=...)).
            agg_input = []
            if aggregator_capture.get("system_prompt"):
                agg_input.append({"role": "system", "content": aggregator_capture["system_prompt"]})
            if aggregator_capture.get("input_prompt") is not None:
                agg_input.append({"role": "user", "content": aggregator_capture["input_prompt"]})
            if agg_input:
                agg_entry["input_messages"] = agg_input
            # Attach injection metadata if the aggregator was injected.
            agg_meta = aggregator_capture.get("injection_meta")
            if agg_meta:
                agg_entry.update(agg_meta)
            full_history.append(agg_entry)

        # Attach real input_messages to the assistant turns (matched by output text);
        # "User" turns are inputs themselves and keep input_messages=None.
        full_history = self._attach_input_messages(full_history, llm_capture)

        # Create comprehensive log with multi-agent information
        log = {
            "final_output": final_output,
            "full_history": full_history,
            "multi_injection_info": [
                {
                    "injected_role_index": target.get('role_index', 0),
                    # Label Aggregator targets as "Aggregator", not "Agent N".
                    "injected_role": (
                        "Aggregator" if target.get('role') == 'Aggregator'
                        else f"Agent {target.get('role_index', 0) + 1}"
                    ),
                    "fm_error_type": agent.fm_error_type.value,
                    "injection_strategy": agent.injection_strategy.value,
                    "malicious_action_description": agent.description,
                }
                for agent, target in zip(malicious_agents, injection_targets)
            ],
            "num_injected_agents": len(malicious_agents),
            # Agent_names enumerates every distinct speaker in the trajectory.
            # LLM-Debate has N debating agents + 1 Aggregator that synthesizes the
            # final answer. "User" turns in conversation_history are inputs (not
            # speakers), so they are NOT listed here.
            "agent_names": [f"Agent {i+1}" for i in range(agents_num)] + ["Aggregator"],
            "execution_successful": execution_error is None,
            "execution_error": execution_error,
        }
        
        return final_output, log

    def run_with_injection(
        self,
        task: Any,
        malicious_agent: FMMaliciousAgent,
        injection_target: Dict[str, Any]
    ) -> Tuple[Any, Dict[str, Any]]:
        target_agent_index = injection_target.get('role_index', 0)
        target_agent_role = injection_target.get('role', 'Assistant')
        print(f"[FM_Debate_Wrapper] Target agent index: {target_agent_index}")
        original_call_llm = self.debate_instance.call_llm
        agents_num = getattr(self.debate_instance, 'agents_num', 3)
        rounds_num = getattr(self.debate_instance, 'rounds_num', 2)
        call_count = {'count': 0}

        def fm_malicious_call_llm(*args, **kwargs):
            idx = call_count['count'] % agents_num
            call_count['count'] += 1
            if (idx == target_agent_index and target_agent_role == 'Assistant' and call_count['count'] <= agents_num * rounds_num) or \
               (idx == 0 and target_agent_role == 'Aggregator' and call_count['count'] > agents_num * rounds_num):
                print(f"*** FM Malicious Agent Activated on index {idx} [Type {malicious_agent.fm_error_type.value}, Strategy {malicious_agent.injection_strategy.value}] ***")
                messages = kwargs.get('messages', [])
                task_input = ""
                if messages:
                    for msg in reversed(messages):
                        if msg.get('role') == 'user':
                            task_input = msg.get('content', '')
                            break
                class MockAgent:
                    def __init__(self, idx):
                        self.role_name = f"Assistant {idx+1}"
                        self.role_type = "Debate Agent"
                        self.agent_id = f"debate_{idx}"
                        self.system_message = f"You are Assistant {idx+1} in a debate."
                        self.tool_dict = {}
                        self.model_type = "LLM"
                        self.chat_history = []
                        self.agent_index = idx
                mock_agent = MockAgent(idx)
                agent_context = self.fm_factory.extract_agent_context(
                    mock_agent,
                    {"name": mock_agent.role_name, "description": mock_agent.system_message}
                )
                malicious_agent.agent_context = agent_context
                if malicious_agent.injection_strategy == InjectionStrategy.PROMPT_INJECTION:
                    modified_prompt = self.fm_factory.inject_prompt(task_input, malicious_agent.fm_error_type, malicious_agent.agent_context)
                    modified_messages = messages.copy()
                    if modified_messages and len(modified_messages) > 0:
                        modified_messages[-1] = modified_messages[-1].copy()
                        modified_messages[-1]['content'] = modified_prompt
                    modified_kwargs = kwargs.copy()
                    modified_kwargs['messages'] = modified_messages
                    response = original_call_llm(*args, **modified_kwargs)
                elif malicious_agent.injection_strategy == InjectionStrategy.RESPONSE_CORRUPTION:
                    clean_response = original_call_llm(*args, **kwargs)
                    response = self.fm_factory.corrupt_response(clean_response, malicious_agent.fm_error_type, malicious_agent.agent_context)
                else:
                    response = original_call_llm(*args, **kwargs)
                return response
            return original_call_llm(*args, **kwargs)

        # --- Monkey patch ---
        self.debate_instance.call_llm = fm_malicious_call_llm
        print(f"[FM_Debate_Wrapper] Monkey-patch applied. Target index: {target_agent_index}.")
        print(f"[FM_Debate_Wrapper] Injection: {malicious_agent.fm_error_type.value} via {malicious_agent.injection_strategy.value}")
        sample = {"query": task.query}
        final_output = self.debate_instance.inference(sample)
        self.debate_instance.call_llm = original_call_llm
        print("[FM_Debate_Wrapper] Original call_llm restored.")

        full_history = []
        agent_contexts = getattr(self.debate_instance, 'agent_contexts', None)
        if agent_contexts is not None:
            for agent_index, context in enumerate(agent_contexts):
                for msg_index, message in enumerate(context):
                    full_history.append({
                        "role": f"Assistant {agent_index+1}" if message["role"] == "assistant" else "User",
                        "role_index": agent_index,
                        "content": message["content"],
                        "msg_index": msg_index,
                    })

        log = {
            "final_output": final_output,
            "injected_role_index": target_agent_index,
            "injected_role": f"Assistant {target_agent_index + 1}",
            "fm_error_type": malicious_agent.fm_error_type.value,
            "injection_strategy": malicious_agent.injection_strategy.value,
            "malicious_action_description": malicious_agent.description,
            "agent_names": [f"Assistant {i+1}" for i in range(agents_num)],
            "full_history": full_history,
        }
        return final_output, log 