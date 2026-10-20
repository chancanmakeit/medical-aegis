from .mas_base import MAS
from .cot import CoT
from .agentverse import AgentVerse_HumanEval, AgentVerse_MGSM, AgentVerse_Main
from .llm_debate import LLM_Debate_Main, LLM_Debate_Enhanced
from .dylan import DyLAN_HumanEval, DyLAN_MATH, DyLAN_MMLU, DyLAN_Main
from .autogen import AutoGen_Main
from .camel import CAMEL_Main
from .evomac import EvoMAC_Main
from .chatdev import ChatDev_SRDD
from .macnet import MacNet_Main, MacNet_SRDD
from .mad import MAD_Main
from .mapcoder import MapCoder_HumanEval, MapCoder_MBPP
from .self_consistency import SelfConsistency
from .mav import MAV_GPQA, MAV_HumanEval, MAV_Main, MAV_MATH, MAV_MMLU
from .mdagents import MDAgents_Main
from .medagents_mc import MedAgentsMC_Main
from .consensus import ConSensus_Main
from .mam import MAM_Main
from .triage_agent import TriageAgent_Main
from .consensus_baselines import SensingDebate_Main, SensingMAD_Main, SensingReconcile_Main, SensingCMD_Main
from .clinical_agent import ClinicalAgent_Main
from .cmas import CMAS_Main

method2class = {
    "vanilla": MAS,
    "cot": CoT,
    "agentverse_humaneval": AgentVerse_HumanEval,
    "agentverse_mgsm": AgentVerse_MGSM,
    "agentverse": AgentVerse_Main,
    "llm_debate": LLM_Debate_Main,
    "llm_debate_enhanced": LLM_Debate_Enhanced,
    "dylan_humaneval": DyLAN_HumanEval,
    "dylan_math": DyLAN_MATH,
    "dylan_mmlu": DyLAN_MMLU,
    "dylan": DyLAN_Main,
    "autogen": AutoGen_Main,
    "camel": CAMEL_Main,
    "evomac": EvoMAC_Main,
    "chatdev_srdd": ChatDev_SRDD,
    "macnet": MacNet_Main,
    "macnet_srdd": MacNet_SRDD,
    "mad": MAD_Main,
    "mapcoder_humaneval": MapCoder_HumanEval,
    "mapcoder_mbpp": MapCoder_MBPP,
    "self_consistency": SelfConsistency,
    "mav_gpqa": MAV_GPQA,
    "mav_humaneval": MAV_HumanEval,
    "mav_main": MAV_Main,
    "mav_math": MAV_MATH,
    "mav_mmlu": MAV_MMLU,
    "mdagents": MDAgents_Main,
    "medagents_mc": MedAgentsMC_Main,
    "consensus": ConSensus_Main,
    "mam": MAM_Main,
    "triage_agent": TriageAgent_Main,
    "triageagent": TriageAgent_Main,
    "consensus_debate": SensingDebate_Main,
    "consensus_mad": SensingMAD_Main,
    "consensus_reconcile": SensingReconcile_Main,
    "consensus_cmd": SensingCMD_Main,
    "clinical_agent": ClinicalAgent_Main,
    "clinicalagent": ClinicalAgent_Main,
    "cmas": CMAS_Main
}

def get_method_class(method_name, dataset_name=None):
    
    # lowercase the method name
    method_name = method_name.lower()
    
    all_method_names = method2class.keys()
    matched_method_names = [sample_method_name for sample_method_name in all_method_names if method_name in sample_method_name]
    
    if len(matched_method_names) > 0:
        if dataset_name is not None:
            # lowercase the dataset name
            dataset_name = dataset_name.lower()
            # check if there are method names that contain the dataset name
            matched_method_data_names = [sample_method_name for sample_method_name in matched_method_names if sample_method_name.split('_')[-1] in dataset_name]
            if len(matched_method_data_names) > 0:
                method_name = matched_method_data_names[0]
                if len(matched_method_data_names) > 1:
                    print(f"[WARNING] Found multiple methods matching {dataset_name}: {matched_method_data_names}. Using {method_name} instead.")
    else:
        raise ValueError(f"[ERROR] No method found matching {method_name}. Please check the method name.")
    
    return method2class[method_name]