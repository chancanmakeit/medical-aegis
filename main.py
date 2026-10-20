# file: main_fm.py

import yaml
import argparse
import asyncio
import importlib
import json
import os
import threading
import concurrent.futures
import traceback
from tqdm import tqdm

# Import our framework's components
from core.task import Task
# Assume utility functions for loading/writing data exist
from methods import get_method_class
from utils import reserve_unprocessed_queries, write_to_jsonl, load_model_api_config
from malicious_factory import FMMaliciousFactory, FMMaliciousAgent, FMErrorType, InjectionStrategy
from aegis_core.utils.medical_verifier import verify_answer
from aegis_core.utils.trajectory_normalizer import normalize_log

def import_class(class_path: str):
    """Dynamically imports a class from a string path."""
    module_path, class_name = class_path.rsplit('.', 1)
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"Could not import class '{class_name}' from '{module_path}'. Error: {e}")


# One-time warnings cache so we don't spam the terminal once per sample when a
# whole MM dataset is missing its images directory.
_IMAGE_WARN_CACHE = set()


def _resolve_sample_image_paths(sample: dict, args, exp_config: dict):
    """Resolve a sample's image references to usable absolute paths AT RUNTIME.

    Resolution priority:
      1. `args.images_dir` (CLI) is set     -> <images_dir>/<filename> for each
         entry in sample['images'] (bare filenames). This OVERRIDES any
         `image_paths` baked into the dataset JSON; useful when the JSON was
         converted on a different machine or the project moved.
      2. `exp_config['images_dir']`         -> same behavior, lower priority.
      3. `sample['image_paths']` exists and all files exist on disk -> use them.
      4. `sample['image_paths']` exists but files MISSING            -> warn
         loudly with a hint and fall back to (5).
      5. `sample['images']` (bare filenames) treated as paths relative to cwd
         (last-ditch fallback; usually fails, but error message points at
         --images_dir).
      6. None / text-only sample -> return None.

    Returns: a list of resolved absolute paths (each verified to exist), or
    None if the sample has no images.
    """
    import os as _os

    runtime_dir = (getattr(args, "images_dir", None)
                   or (exp_config or {}).get("images_dir")
                   or None)

    filenames = sample.get("images") or []
    baked_paths = sample.get("image_paths") or []

    # No image refs at all -> text-only.
    if not filenames and not baked_paths:
        return None

    # --- Path 1/2: runtime images_dir takes precedence ---
    if runtime_dir and filenames:
        base = _os.path.abspath(_os.path.expanduser(runtime_dir))
        candidates = [_os.path.join(base, fn) for fn in filenames]
        missing = [p for p in candidates if not _os.path.exists(p)]
        if missing:
            sid = sample.get("id", "<?>")
            for p in missing:
                key = ("missing_runtime", p)
                if key not in _IMAGE_WARN_CACHE:
                    _IMAGE_WARN_CACHE.add(key)
                    print(f"[images] WARNING sample={sid}: image not found under --images_dir: {p}")
        return candidates  # return candidates even with missing files; the
                           # downstream LLM call will raise a clear error.

    # --- Path 3: baked paths all exist ---
    if baked_paths and all(isinstance(p, str) and _os.path.exists(p) for p in baked_paths):
        return list(baked_paths)

    # --- Path 4: baked paths exist in JSON but files are missing ---
    if baked_paths:
        sid = sample.get("id", "<?>")
        first_missing = next((p for p in baked_paths if not _os.path.exists(p)), None)
        key = ("missing_baked",)
        if key not in _IMAGE_WARN_CACHE:
            _IMAGE_WARN_CACHE.add(key)
            print(f"[images] WARNING: sample {sid} has image_paths baked into the dataset "
                  f"but the file does not exist: {first_missing}")
            print(f"[images] HINT: this happens when the dataset JSON was converted on "
                  f"another machine / cwd. Re-run main.py with "
                  f"`--images_dir /absolute/path/to/medxpertqa_images`")

        # Try to recover via filenames (path 5) before giving up.
        if filenames:
            # Try interpreting bare filenames relative to a few sensible defaults.
            for fallback_base in (_os.getcwd(),
                                  _os.path.join(_os.getcwd(), "datasets", "medxpertqa_images"),
                                  _os.path.join(_os.getcwd(), "datasets", "data", "images")):
                candidates = [_os.path.join(fallback_base, fn) for fn in filenames]
                if all(_os.path.exists(p) for p in candidates):
                    key2 = ("recovered_via_fallback", fallback_base)
                    if key2 not in _IMAGE_WARN_CACHE:
                        _IMAGE_WARN_CACHE.add(key2)
                        print(f"[images] recovered image files under fallback dir: {fallback_base}")
                    return candidates
        # Give up: return baked paths so the call_llm site raises with the
        # original (clear) "Image not found at <path>" error.
        return list(baked_paths)

    # --- Path 5: only filenames, no images_dir hint at all ---
    if filenames:
        key = ("no_images_dir",)
        if key not in _IMAGE_WARN_CACHE:
            _IMAGE_WARN_CACHE.add(key)
            sid = sample.get("id", "<?>")
            print(f"[images] WARNING: sample {sid} has image filenames ({filenames}) but no "
                  f"--images_dir was provided. Pass --images_dir /path/to/images to enable "
                  f"multimodal mode. Running text-only.")
        return None

    return None

async def process_sample(args, sample: dict, lock: threading.Lock, output_path: str, exp_config: dict = None):
    """
    This function contains the core logic of our FM Malicious Injection framework.
    It processes a single data sample against a full FM injection experiment configuration.
    """
    if exp_config is None:
        print(f"--- Loading Experiment Config: {args.experiment_config} ---")
        with open(args.experiment_config, 'r', encoding='utf-8') as f:
            exp_config = yaml.safe_load(f)
    
    general_config = vars(args).copy()
    model_api_config = load_model_api_config(args.model_api_config, args.model_name)
    general_config.update({"model_api_config": model_api_config})
    general_config.update({"experiment_config": exp_config})
    save_data = sample.copy()
    try:
        # 1. Load method-specific config
        method_config_path = exp_config['system_under_test']['method_config_path']
        
        if exp_config.get('macnet_config'):
            print(f"🤖 [MacNet] 使用自动生成的配置，type: {exp_config['macnet_config']['type']}")
            method_config = exp_config['macnet_config']
        else:
            with open(method_config_path, 'r', encoding='utf-8') as f:
                method_config = yaml.safe_load(f)

        # For simplicity, we create the LLM config here. This can be expanded.
        llm_config = exp_config["llm_config"]

        # 2. Instantiate the Task from the benchmark sample
        task = Task(
            query=sample['query'],
            ground_truth=sample.get('answer') or sample.get('ground_truth'),
            metadata={'dataset': exp_config.get('benchmark_name'), 'id': sample.get('id')},
            image_paths=_resolve_sample_image_paths(sample, args, exp_config),
        )

        WrapperClass = import_class(exp_config['system_under_test']['wrapper_class_path'])
        system_wrapper = WrapperClass(
            general_config=general_config,
            method_config=method_config
        )

        # Decide run mode: clean (no-injection / normal trajectory) vs inject (error trajectory).
        # Priority: CLI --no_inject flag > experiment_config run_mode > presence of injection_plan.
        run_mode = exp_config.get('run_mode', None)
        if getattr(args, 'no_inject', False):
            run_mode = 'clean'
        if run_mode is None:
            run_mode = 'clean' if 'injection_plan' not in exp_config else 'inject'

        if run_mode == 'clean':
            # ---- Normal trajectory: run the MAS with NO error injection ----
            final_output, log = system_wrapper.run_with_multi_injection(
                task=task,
                malicious_agents=[],
                injection_targets=[]
            )
            malicious_agents = []
            save_data['run_mode'] = 'clean'
        else:
            # ---- Error trajectory: run the FM injection experiment ----
            # injection_method: "direct_prepend" (default, reliable),
            #                   "llm_rewrite" (legacy AEGIS-paper),
            #                   "llm_rewrite_strong" (paper + jailbreak meta-prompt wrapping).
            # task_type: "mcq" / "numeric" / "error_correction" / "open" — selects
            #            which template family the factory uses.
            # prompt_wrapper_style: "direct" (visible [UPDATED INSTRUCTION] block) or
            #                      "jailbreak" (covert role-play wrapper for the target agent).
            # factory_llm_config: optional dedicated LLM for the rewriter (use a
            #                     less-aligned model to bypass RLHF refusals).
            inj_method = exp_config.get('injection_method', 'direct_prepend')
            task_type = exp_config.get('task_type', 'mcq')
            wrapper_style = exp_config.get('prompt_wrapper_style', 'direct')

            factory_llm = system_wrapper.llm
            if exp_config.get('factory_llm_config'):
                try:
                    from utils.async_llm import create_llm_instance
                    factory_llm = create_llm_instance(exp_config['factory_llm_config'])
                    print(f"[factory] Using dedicated factory_llm: {exp_config['factory_llm_config'].get('model_name','?')}")
                except Exception as _e:
                    print(f"[factory] could not build factory_llm_config LLM ({_e}); falling back to MAS LLM.")

            fm_factory = FMMaliciousFactory(
                llm=system_wrapper.llm,
                injection_method=inj_method,
                task_type=task_type,
                prompt_wrapper_style=wrapper_style,
                factory_llm=factory_llm,
            )

            # Parse injection configuration - support both single and multi-target formats
            injection_plan = exp_config['injection_plan']

            # Determine if we have single target (legacy) or multiple targets (new format)
            if 'target' in injection_plan:
                target = injection_plan['target']
                attack_spec = injection_plan.get('attack_spec', {})
                if 'attack_spec' not in target:
                    target = target.copy()
                    target['attack_spec'] = attack_spec
                injection_targets = [target]
            else:
                injection_targets = injection_plan['targets']

            # Create malicious agents for each target
            malicious_agents = []
            for target in injection_targets:
                target_attack_spec = target.get('attack_spec', {})
                fm_error_type = target_attack_spec.get('fm_error_type', 'FM-2.3')
                injection_strategy = target_attack_spec.get('injection_strategy', 'prompt_injection')

                malicious_agent = await fm_factory.create_agent(
                    task_query=task.query,
                    target_agent_role=target.get('role', 'Assistant'),
                    target_agent_index=target.get('role_index', 0),
                    fm_error_type=fm_error_type,
                    injection_strategy=injection_strategy
                )
                malicious_agents.append(malicious_agent)

            # Run the full FM injection experiment with multiple agents
            final_output, log = system_wrapper.run_with_multi_injection(
                task=task,
                malicious_agents=malicious_agents,
                injection_targets=injection_targets
            )
            save_data['run_mode'] = 'inject'

        # 6. Collate results
        if isinstance(final_output, dict) and 'response' in final_output:
            save_data['response'] = final_output['response']
            for key, value in final_output.items():
                if key != 'response':
                    save_data[key] = value
        else:
            save_data['response'] = final_output

        # Normalize the framework-specific log into ONE unified trajectory schema
        # (conversation_history with step/agent_name/phase/input_messages/content/response),
        # so saved jsonl is structurally identical across dylan/agentverse/llm_debate/etc.
        log = normalize_log(
            log,
            framework=args.method_name,
            fold_user_inputs=exp_config.get('llm_debate_fold_user_inputs', False),
        )
        # Surface the actual round settings used in this run (per-framework concept).
        rs = getattr(system_wrapper, '_round_settings', None)
        if rs:
            log['round_settings'] = rs
        save_data['injection_log'] = log

        # Record injection metadata (only meaningful in inject mode)
        if len(malicious_agents) == 1:
            save_data['fm_error_type'] = malicious_agents[0].fm_error_type.value
            save_data['injection_strategy'] = malicious_agents[0].injection_strategy.value
        elif len(malicious_agents) > 1:
            save_data['fm_error_types'] = [agent.fm_error_type.value for agent in malicious_agents]
            save_data['injection_strategies'] = [agent.injection_strategy.value for agent in malicious_agents]
            save_data['num_injected_agents'] = len(malicious_agents)

        # MAST taxonomy inline: only the descriptions of the FM types USED in
        # this sample. The full 14-FM taxonomy is shipped as a standalone file
        # at the repo root: mast_taxonomy.json.
        if malicious_agents:
            try:
                from aegis_core.utils.injection_describer import FM_GLOSSARY
            except Exception:
                FM_GLOSSARY = {}
            mast_used = {}
            for a in malicious_agents:
                fm = a.fm_error_type.value
                if fm not in mast_used and fm in FM_GLOSSARY:
                    mast_used[fm] = FM_GLOSSARY[fm]
            if mast_used:
                save_data['mast_taxonomy_used'] = mast_used

        # 6a. Detect whether the MAS run was disrupted by an LLM API failure
        # (tenacity retries exhausted, the framework returned None, our
        # LLMAPIFailure was raised in the wrapper). When that happens, the
        # trajectory is structurally broken and there's nothing meaningful for
        # the verifier or the LLM describer to look at — so we short-circuit:
        # mark status='llm_api_failure', skip the LLM judge, skip per-turn
        # descriptions, and write the record so the user can see the failure
        # rather than spending more LLM tokens auditing garbage.
        _exec_err = (log.get('execution_error') if isinstance(log, dict) else None) or ''
        _llm_api_failed = isinstance(_exec_err, str) and _exec_err.startswith('llm_api_failure')

        if _llm_api_failed:
            print(f"[verify] id={save_data.get('id','<?>')} SKIPPING verifier+describer "
                  f"because of LLM API failure: {_exec_err[:120]}")
            save_data['is_correct'] = False
            save_data['verification'] = {
                'final_verdict': False,
                'decision_path': 'skipped/llm_api_failure',
                'llm_judge_called': False,
                'llm_api_failure_detail': _exec_err,
            }
            if save_data['run_mode'] == 'clean':
                save_data['is_valid_normal'] = False
            else:
                save_data['is_valid_error'] = False
            save_data['status'] = 'llm_api_failure'
            # write_to_jsonl is called below at the function's tail, so just
            # fall through past verifier/describer by raising-and-handling.
            # Set a flag that skips them.
            _skip_remaining = True
        else:
            _skip_remaining = False

        # 6b. Verify correctness -> drives the normal vs error split.
        #     normal trajectory := is_correct True  (and run_mode == 'clean')
        #     error  trajectory := is_correct False (and run_mode == 'inject')
        if not _skip_remaining:
            gt = sample.get('ground_truth')
            if not isinstance(gt, dict):
                gt = {'correct_answer': sample.get('answer') or sample.get('ground_truth')}
            verifier_dataset = exp_config.get('benchmark_name') or args.test_dataset_name
            # Resolve the LLM used for LLM-as-a-judge. Priority:
            #   1. exp_config['judge_llm_config']  (full llm_config block for the judge)
            #   2. exp_config['judge_model_name']  (reuse llm_config but override the model)
            #   3. the MAS's own llm (default)
            judge_llm = getattr(system_wrapper, 'llm', None)
            try:
                from utils.async_llm import create_llm_instance
                if exp_config.get('judge_llm_config'):
                    judge_llm = create_llm_instance(exp_config['judge_llm_config'])
                elif exp_config.get('judge_model_name'):
                    _jc = dict(exp_config.get('llm_config', {}))
                    _jc['model_name'] = exp_config['judge_model_name']
                    judge_llm = create_llm_instance(_jc)
            except Exception as _e:
                print(f"[judge] could not build dedicated judge LLM ({_e}); using MAS LLM.")
            from aegis_core.utils.medical_verifier import verify_answer_with_details
            from aegis_core.utils.ner_verifier import NER_DATASETS, verify_ner_with_details
            verification_audit = None
            _vd_name = (verifier_dataset or "").strip().lower()
            try:
                if _vd_name in NER_DATASETS:
                    # NER task: entity-level micro-F1 with exact (span, type) match.
                    # A sample is "correct" iff its F1 >= f1_threshold (default 1.0,
                    # i.e. a perfect prediction). No LLM judge is used — the match
                    # is deterministic. Override the threshold via exp_config.
                    is_correct, verification_audit = verify_ner_with_details(
                        response=save_data.get('response', ''),
                        ground_truth=gt,
                        f1_threshold=float(exp_config.get('ner_f1_threshold', 1.0)),
                    )
                else:
                    is_correct, verification_audit = verify_answer_with_details(
                        dataset_name=verifier_dataset,
                        response=save_data.get('response', ''),
                        ground_truth=gt,
                        query=task.query,
                        llm=judge_llm,
                        use_llm_fallback=exp_config.get('use_llm_judge', True),
                        judge_mode=exp_config.get('judge_mode', 'llm_primary'),
                    )
            except Exception as _ve:
                is_correct = False
                verification_audit = {"final_verdict": False, "decision_path": f"exception:{_ve}"}
            save_data['is_correct'] = bool(is_correct)
            save_data['verification'] = verification_audit
            # Compact, machine-greppable one-line terminal log so users can SEE per-sample
            # how is_correct was decided, in particular whether the LLM judge was invoked.
            _sid = save_data.get('id', '<?>')
            _path = (verification_audit or {}).get('decision_path', 'n/a')
            _judged = (verification_audit or {}).get('llm_judge_called', False)
            _raw = (verification_audit or {}).get('llm_judge_raw_output')
            _raw_short = (str(_raw)[:60] + '...') if _raw and len(str(_raw)) > 60 else _raw
            print(f"[verify] id={_sid} is_correct={is_correct} path={_path} "
                  f"llm_judge_called={_judged} judge_raw={_raw_short!r}")

            # Convenience flag: does this sample qualify for its intended split?
            if save_data['run_mode'] == 'clean':
                save_data['is_valid_normal'] = bool(is_correct)
            else:
                save_data['is_valid_error'] = (not bool(is_correct))

            # 6c. LLM-powered injection descriptions (per-turn and sample-level).
            #     Only runs in inject mode and when injection metadata is present.
            #     Picks the description LLM in this priority:
            #       1. exp_config['description_llm_config']  (dedicated full block)
            #       2. exp_config['description_model_name']  (reuse llm_config but override model)
            #       3. judge_llm  (reuse the verification LLM)
            if save_data['run_mode'] == 'inject' and exp_config.get('generate_injection_descriptions', True):
                description_llm = judge_llm
                try:
                    from utils.async_llm import create_llm_instance
                    if exp_config.get('description_llm_config'):
                        description_llm = create_llm_instance(exp_config['description_llm_config'])
                    elif exp_config.get('description_model_name'):
                        _dc = dict(exp_config.get('llm_config', {}))
                        _dc['model_name'] = exp_config['description_model_name']
                        description_llm = create_llm_instance(_dc)
                except Exception as _e:
                    print(f"[describer] could not build dedicated description LLM ({_e}); using judge LLM.")
                try:
                    from aegis_core.utils.injection_describer import annotate_record
                    annotate_record(
                        save_data,
                        llm=description_llm,
                        per_turn=exp_config.get('describe_per_turn', True),
                        sample_summary=exp_config.get('describe_sample_summary', True),
                    )
                    # Refresh the normalized conversation_history in injection_log:
                    # annotate_record mutates entries in place, so injection_log.conversation_history
                    # already reflects the new injection_description fields. Nothing else to do.
                    _n_desc = sum(
                        1 for t in (save_data.get('injection_log') or {}).get('conversation_history', [])
                        if isinstance(t, dict) and t.get('injection_description')
                    )
                    _has_summary = 'injection_summary' in save_data
                    print(f"[describe] id={save_data.get('id','<?>')} per_turn_descriptions={_n_desc} sample_summary={_has_summary}")
                except Exception as _de:
                    print(f"[describer] failed: {_de}")

            save_data['status'] = 'success'

    except Exception:
        save_data["error"] = f"Processing Error: {traceback.format_exc()}"
        save_data['status'] = 'error'
    
    # 7. Write results to file incrementally and safely
    write_to_jsonl(lock, output_path, save_data)

async def main(args):
    """Main entry point to load configs and orchestrate the FM experiment batch."""
    
    # Determine dataset file path
    if args.dataset_file:
        dataset_path = args.dataset_file
        print(f"--- Loading Dataset from custom file: {dataset_path} ---")
    else:
        dataset_path = f"./datasets/data/{args.test_dataset_name}.json"
        print(f"--- Loading Dataset: {args.test_dataset_name} ---")
    
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    # Load experiment config to get injection information
    print(f"--- Loading Experiment Config: {args.experiment_config} ---")
    with open(args.experiment_config, 'r', encoding='utf-8') as f:
        exp_config = yaml.safe_load(f)
    
    # Extract injection information for filename - support both single and multi-target
    injection_plan = exp_config.get('injection_plan', {})

    # Clean (no-injection) mode: short-circuit the injection filename logic.
    clean_mode = args.no_inject or exp_config.get('run_mode') == 'clean' or not injection_plan
    if clean_mode:
        agent_identifier = "clean"
        fm_error_type = "none"
        injection_strategy = "none"
        multi_agent_suffix = ""
        injection_targets = []
    elif 'target' in injection_plan:
        # Single target format
        injection_target = injection_plan['target']
        attack_spec = injection_plan.get('attack_spec', injection_target.get('attack_spec', {}))
        
        target_role = injection_target.get('role', 'unknown')
        target_index = injection_target.get('role_index', injection_target.get('call_index', 0))
        fm_error_type = attack_spec.get('fm_error_type', 'unknown')
        injection_strategy = attack_spec.get('injection_strategy', 'unknown')
        
        # Create agent identifier for filename.
        # Naming convention: <role-lowered>_idx<role_index>. The number is the
        # 0-based role_index that appears in injection_plan AND in the saved
        # trajectory's conversation_history entries — so the filename matches
        # the data verbatim. (Previous convention used role_index+1, which
        # made `physician1` correspond to role_index=0 — confusing.)
        if target_role == 'unknown':
            agent_identifier = f"agent_idx{target_index}"
        else:
            agent_identifier = f"{target_role.lower()}_idx{target_index}"
            
        multi_agent_suffix = ""
    else:
        # Multi-target format
        injection_targets = injection_plan['targets']
        
        # Create compound identifier for multiple targets
        agent_identifiers = []
        fm_error_types = []
        injection_strategies = []
        
        for target in injection_targets:
            target_role = target.get('role', 'unknown')
            target_index = target.get('role_index', target.get('call_index', 0))
            target_attack_spec = target.get('attack_spec', {})
            
            # Same 0-based "<role>_idx<n>" convention as the single-target branch.
            if target_role == 'unknown':
                target_identifier = f"agent_idx{target_index}"
            else:
                target_identifier = f"{target_role.lower()}_idx{target_index}"
            
            agent_identifiers.append(target_identifier)
            fm_error_types.append(target_attack_spec.get('fm_error_type', 'unknown'))
            injection_strategies.append(target_attack_spec.get('injection_strategy', 'unknown'))
        
        # For multi-agent, create compound identifiers
        agent_identifier = "multi_" + "-".join(agent_identifiers)
        fm_error_type = "-".join(fm_error_types)
        injection_strategy = "-".join(injection_strategies)
        multi_agent_suffix = f"_n{len(injection_targets)}"
    
    # Determine dataset name for output path
    if args.dataset_file:
        # Extract dataset name from file path
        dataset_name = os.path.splitext(os.path.basename(args.dataset_file))[0]
        # If it's a subset file like "HumanEval+dylan", keep the full name
        if '+' in dataset_name:
            base_dataset = dataset_name.split('+')[0]
        else:
            base_dataset = dataset_name
    else:
        dataset_name = args.test_dataset_name
        base_dataset = args.test_dataset_name
    
    # Determine output path, using a default if not provided
    import time
    if args.output_path is not None:
        output_path = args.output_path
    else:
        # Enhanced filename with FM injection information (without timestamp for consistency)
        filename = f"{args.method_name}_fm_{agent_identifier}_{fm_error_type}_{injection_strategy}{multi_agent_suffix}.jsonl"
        output_path = f"./results_inj/{base_dataset}/{args.model_name}/{filename}"
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
    print(f"--- Output will be saved to: {output_path} ---")
    
    # Display injection information
    if clean_mode:
        print(f"--- CLEAN run (no injection) for normal trajectories ---")
    elif 'target' in injection_plan:
        print(f"--- FM Injection: {target_role} {target_index+1}, Type: {fm_error_type}, Strategy: {injection_strategy} ---")
    else:
        print(f"--- Multi-Agent FM Injection ({len(injection_targets)} targets): ---")
        for i, target in enumerate(injection_targets):
            t_role = target.get('role', 'unknown')
            t_index = target.get('role_index', target.get('call_index', 0))
            t_attack_spec = target.get('attack_spec', {})
            t_fm_error = t_attack_spec.get('fm_error_type', 'unknown')
            t_strategy = t_attack_spec.get('injection_strategy', 'unknown')
            print(f"    Target {i+1}: {t_role} {t_index+1}, Type: {t_fm_error}, Strategy: {t_strategy}")

    # Filter out already processed samples to allow resuming runs
    unprocessed_samples = reserve_unprocessed_queries(output_path, dataset)
    
    # Apply limit if specified
    if args.limit is not None and len(unprocessed_samples) > args.limit:
        unprocessed_samples = unprocessed_samples[:args.limit]
        print(f">> Applied limit: Processing only {args.limit} samples")
    
    print(f">> Total samples: {len(dataset)} | Unprocessed: {len(unprocessed_samples)}")

    if not unprocessed_samples:
        print("All samples have already been processed. Exiting.")
        return

    # Create a lock for thread-safe file writing
    lock = threading.Lock()

    # Define a wrapper for asyncio compatibility with ThreadPoolExecutor
    def run_async_process(sample):
        asyncio.run(process_sample(args, sample, lock, output_path, exp_config))

    if args.sequential or args.debug:
        for sample in tqdm(unprocessed_samples, desc="Processing sequentially"):
            await process_sample(args, sample, lock, output_path, exp_config)
    else:
        if args.max_workers > 1:
            print(f"  Warning: Running with {args.max_workers} workers in parallel.")
            print("   Each thread will create its own wrapper instance to ensure thread safety.")
            print("   Make sure your LLM provider supports concurrent requests.")
        
        # Use ThreadPoolExecutor for parallel execution, similar to MASLab
        max_workers = args.max_workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(tqdm(executor.map(run_async_process, unprocessed_samples), total=len(unprocessed_samples), desc=f"Processing in parallel (max_workers={max_workers})"))
    
    print(f"\n--- FM EXPERIMENT BATCH COMPLETE ---")
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FM Malicious Injection & Evaluation Pipeline.")
    parser.add_argument("--method_name", type=str, default="dylan", help="MAS name.")
    parser.add_argument("--experiment_config", type=str, default="./experiments/fm_injection/test_fm_dylan_math.yaml", help="Path to the experiment YAML configuration file.")
    parser.add_argument("--model_api_config", type=str, default="model_api_configs/model_api_config.json")
    parser.add_argument("--model_name", type=str, default="gpt-4o-mini-azure", help="The agent backend to be used for inference.")
    parser.add_argument("--method_config_name", type=str, default=None, help="The config file name. If None, the default config file will be used.")
    parser.add_argument("--model_temperature", type=float, default=0, help="Temperature for sampling.")
    parser.add_argument("--model_max_tokens", type=int, default=2048, help="Maximum tokens for sampling.")
    parser.add_argument("--model_timeout", type=int, default=600, help="Timeout for sampling.")
    parser.add_argument("--test_dataset_name", type=str, default="MATH")
    parser.add_argument("--dataset_file", type=str, default=None, help="Path to custom dataset file. If provided, overrides test_dataset_name.")
    parser.add_argument("--output_path", type=str, default=None, help="Path to save the output .jsonl file.")
    parser.add_argument("--max_workers", type=int, default=10, help="Maximum number of parallel workers.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of samples to process.")
    parser.add_argument("--images_dir", type=str, default=None,
                        help="(Multimodal datasets only) Directory containing the image files referenced by "
                             "sample['images']. When set, image filenames in the dataset are resolved to "
                             "<images_dir>/<filename> AT RUNTIME, overriding any absolute `image_paths` baked "
                             "into the dataset JSON. Set this if you moved the project or originally converted "
                             "the dataset on a different machine.")
    parser.add_argument("--sequential", action="store_true", help="Run experiments sequentially instead of in parallel.")
    parser.add_argument("--no_inject", action="store_true", help="Run in CLEAN mode (no error injection) to collect normal trajectories.")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode (currently same as sequential).")
    
    args = parser.parse_args()

    asyncio.run(main(args)) 