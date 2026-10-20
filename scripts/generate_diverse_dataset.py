#!/usr/bin/env python3
# file: scripts/generate_diverse_dataset.py
"""
Generate a diverse error-injected dataset by running MANY randomized inject
experiments in parallel.

For each random configuration we:
  1. Pick `injection_method`        in {direct_prepend, llm_rewrite}
  2. Pick `prompt_wrapper_style`    in {direct, jailbreak}
  3. Pick `injection_plan.targets`  — N distinct (agent, role_index) pairs
     valid for the chosen framework, each with a random
     (fm_error_type, injection_strategy).
  4. Spawn `main.py` as a subprocess with the randomized YAML.
  5. Save results to a subdir whose name encodes the config, so you can
     immediately tell what each result file came from.

Parallelism
-----------
We use a thread pool that spawns subprocesses; each subprocess is a full
main.py run, and main.py itself processes samples concurrently inside its
own async pool. So real concurrency = `--workers` × `main.py.max_workers`.

Recommended starting point: --workers 2 or 3 (each main.py is already
heavy-weight; too much outer parallelism can rate-limit your API).

Usage examples
--------------
# 5 random configs per framework, 2 targets each, run all 3 frameworks
python scripts/generate_diverse_dataset.py \\
    --frameworks dylan llm_debate agentverse \\
    --num_configs 5 --targets_per_config 2 \\
    --dataset_file ./datasets/data/medqa.json \\
    --test_dataset_name medqa --model_name gpt-4o-mini \\
    --workers 2

# Reproducible: --seed
# Limit samples per run: --sample_limit 20
# Cheaper: --no_descriptions (skips per-turn LLM injection_description)
# Plan-only (no execution): --dry_run
"""

import argparse
import copy
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

import yaml


# --------------------------------------------------------------------------- #
# Per-framework agent pool (taken from the medical method configs).
#
# Each slot is a dict {role, role_index, agent_key}:
#   - role + role_index  identify the INJECTION SLOT (what we write into the YAML)
#   - agent_key          identifies the LOGICAL AGENT (used for dedup)
#
# Why two layers? In some frameworks the same logical agent can be hit at
# multiple injection sites:
#   - AgentVerse's Critic is one agent that gets called once per criticizing
#     round (role_index 0, 1, 2 ...). All those slots share agent_key="Critic"
#     so that a single random config injects Critic at most once — even if it
#     could pick either invocation slot.
# In DyLAN and LLM-Debate, each role_index corresponds to a different concrete
# agent (different panel member / different debater), so agent_key embeds the
# index too (e.g. "Physician_0", "Agent_1").
# --------------------------------------------------------------------------- #
FRAMEWORK_AGENT_POOL: Dict[str, List[Dict]] = {
    # DyLAN config_medical.yaml roles list, role_index = panel position. Each
    # panel slot is a distinct medical expert → distinct logical agent.
    "dylan": [
        {"role": "Physician",          "role_index": 0, "agent_key": "Physician_0"},
        {"role": "Pharmacologist",     "role_index": 1, "agent_key": "Pharmacologist_1"},
        {"role": "Pathologist",        "role_index": 2, "agent_key": "Pathologist_2"},
        {"role": "Medical_Researcher", "role_index": 3, "agent_key": "Medical_Researcher_3"},
    ],
    # LLM-Debate: N=agents_num distinct debaters + 1 Aggregator. Each role_index
    # is a different concrete debater (Agent 0 ≠ Agent 1 ≠ Agent 2).
    "llm_debate": [
        {"role": "Agent",      "role_index": 0, "agent_key": "Agent_0"},
        {"role": "Agent",      "role_index": 1, "agent_key": "Agent_1"},
        {"role": "Agent",      "role_index": 2, "agent_key": "Agent_2"},
        {"role": "Aggregator", "role_index": 0, "agent_key": "Aggregator"},
    ],
    # AgentVerse: Solver and Evaluator are singletons; Critic is called once per
    # criticizing round (role_index 0, 1, ...). Each invocation is treated as a
    # DISTINCT injection slot here (per user preference), so a single config CAN
    # inject Critic_0 and Critic_1 simultaneously.
    "agentverse": [
        {"role": "Solver",    "role_index": 0, "agent_key": "Solver"},
        {"role": "Critic",    "role_index": 0, "agent_key": "Critic_0"},
        {"role": "Critic",    "role_index": 1, "agent_key": "Critic_1"},
        {"role": "Evaluator", "role_index": 0, "agent_key": "Evaluator"},
    ],
    # MDAgents has dynamic agent recruitment, but the call SITES per difficulty
    # mode are deterministic. We expose stable structural roles here. Different
    # configurations target different difficulty modes — see methods/mdagents/
    # configs/config_medical.yaml's `difficulty` knob.
    #
    # In "intermediate" mode (the default for medical): one Recruiter that picks
    # the panel, then 5 dynamically-named experts. We inject by their structural
    # slot (Expert_0 ... Expert_4) rather than the LLM-given specialty name.
    "mdagents": [
        {"role": "Recruiter", "role_index": 0, "agent_key": "Recruiter"},
        {"role": "Expert",    "role_index": 0, "agent_key": "Expert_0"},
        {"role": "Expert",    "role_index": 1, "agent_key": "Expert_1"},
        {"role": "Expert",    "role_index": 2, "agent_key": "Expert_2"},
        {"role": "Expert",    "role_index": 3, "agent_key": "Expert_3"},
        {"role": "Expert",    "role_index": 4, "agent_key": "Expert_4"},
    ],
    # ClinicalAgent: linear 6-agent pipeline for clinical-trial-outcome
    # prediction. All singletons (idx=0), no runtime role renaming, so the
    # pool exactly mirrors the framework's structural graph.
    "clinical_agent": [
        {"role": "Planner",         "role_index": 0, "agent_key": "Planner"},
        {"role": "SafetyAgent",     "role_index": 0, "agent_key": "SafetyAgent"},
        {"role": "EfficacyAgent",   "role_index": 0, "agent_key": "EfficacyAgent"},
        {"role": "EnrollmentAgent", "role_index": 0, "agent_key": "EnrollmentAgent"},
        {"role": "Reasoner",        "role_index": 0, "agent_key": "Reasoner"},
    ],
    # MedAgents (MC): only call sites that ALWAYS fire are listed. Advisor_i and
    # Reviser run only when some voter says NO, so they are left out of random
    # sampling (they can still be targeted by hand in a YAML). Domain expert i
    # analyses (QuestionAnalyst/OptionAnalyst) and later votes (Voter) as the
    # same logical agent, so they share an agent_key.
    "medagents_mc": (
        [{"role": "QuestionClassifier", "role_index": 0, "agent_key": "QuestionClassifier"},
         {"role": "OptionClassifier",   "role_index": 0, "agent_key": "OptionClassifier"}]
        + [{"role": "QuestionAnalyst", "role_index": i, "agent_key": f"QExpert_{i}"} for i in range(5)]
        + [{"role": "OptionAnalyst",   "role_index": j, "agent_key": f"OExpert_{j}"} for j in range(2)]
        + [{"role": "Synthesizer",     "role_index": 0, "agent_key": "Synthesizer"}]
        + [{"role": "Voter", "role_index": i, "agent_key": f"QExpert_{i}"} for i in range(5)]
        + [{"role": "Voter", "role_index": 5 + j, "agent_key": f"OExpert_{j}"} for j in range(2)]
        + [{"role": "Decider",         "role_index": 0, "agent_key": "Decider"}]
    ),
    # CMAS: 3-agent per-sample zero-shot NER pipeline (self-annotator is offline).
    # All singletons (idx=0), no runtime role renaming.
    "cmas": [
        {"role": "TRFExtractor",     "role_index": 0, "agent_key": "TRFExtractor"},
        {"role": "Discriminator",    "role_index": 0, "agent_key": "Discriminator"},
        {"role": "OverallPredictor", "role_index": 0, "agent_key": "OverallPredictor"},
    ],
}

FM_ERROR_TYPES = [
    "FM-1.1", "FM-1.2", "FM-1.3", "FM-1.4", "FM-1.5",
    "FM-2.1", "FM-2.2", "FM-2.3", "FM-2.4", "FM-2.5", "FM-2.6",
    "FM-3.1", "FM-3.2", "FM-3.3",
]

INJECTION_STRATEGIES = ["prompt_injection", "response_corruption"]
INJECTION_METHODS = ["direct_prepend", "llm_rewrite"]
PROMPT_WRAPPER_STYLES = ["direct", "jailbreak"]


# Base YAML templates for each framework.
BASE_YAML_TEMPLATE = {
    "dylan": "experiments/fm_injection/medical/dylan_medical_inject.yaml",
    "llm_debate": "experiments/fm_injection/medical/llm_debate_medical_inject.yaml",
    "agentverse": "experiments/fm_injection/medical/agentverse_medical_inject.yaml",
    "mdagents": "experiments/fm_injection/medical/mdagents_medical_inject.yaml",
    "clinical_agent": "experiments/fm_injection/medical/clinical_agent_medical_inject.yaml",
    "cmas": "experiments/fm_injection/ner/cmas_ner_inject.yaml",
    "medagents_mc": "experiments/fm_injection/medical/medagents_mc_medical_inject.yaml",
}


# --------------------------------------------------------------------------- #
# Config randomization
# --------------------------------------------------------------------------- #
def randomize_config(base_cfg: dict, framework: str, num_targets: int,
                     rng: random.Random,
                     enable_descriptions: bool) -> dict:
    """Return a NEW config dict with randomized injection_method,
    prompt_wrapper_style, and injection_plan.targets.

    Targets are picked so that NO LOGICAL AGENT is injected more than once
    per config (see FRAMEWORK_AGENT_POOL[*].agent_key). Concretely:
      - DyLAN: each panel slot is a distinct agent (Physician_0,
        Pharmacologist_1, ...); up to 4 distinct agents can be targeted.
      - LLM-Debate: Agent_0, Agent_1, Agent_2 are distinct debaters, plus the
        single Aggregator; up to 4 distinct agents.
      - AgentVerse: Solver, Critic, Evaluator are 3 distinct logical agents.
        Critic invocations across rounds share agent_key="Critic", so a config
        injects Critic AT MOST ONCE (the script picks a random round for it).
    """
    cfg = copy.deepcopy(base_cfg)
    cfg["injection_method"] = rng.choice(INJECTION_METHODS)
    cfg["prompt_wrapper_style"] = rng.choice(PROMPT_WRAPPER_STYLES)

    pool = FRAMEWORK_AGENT_POOL[framework]
    # Group slots by agent_key so dedup happens at the LOGICAL-AGENT layer,
    # not at the (role, role_index) slot layer.
    by_key: Dict[str, List[Dict]] = {}
    for slot in pool:
        by_key.setdefault(slot["agent_key"], []).append(slot)

    distinct_agent_keys = list(by_key.keys())
    n_targets = min(num_targets, len(distinct_agent_keys))
    if num_targets > len(distinct_agent_keys):
        print(f"[warn] {framework}: requested {num_targets} targets but only "
              f"{len(distinct_agent_keys)} distinct agents available "
              f"({distinct_agent_keys}); capping to {n_targets}.")

    # Pick N distinct logical agents, then for each pick a random slot.
    chosen_keys = rng.sample(distinct_agent_keys, k=n_targets)
    targets = []
    for key in chosen_keys:
        slot = rng.choice(by_key[key])  # for AgentVerse Critic, picks round
        targets.append({
            "role": slot["role"],
            "role_index": slot["role_index"],
            "attack_spec": {
                "fm_error_type": rng.choice(FM_ERROR_TYPES),
                "injection_strategy": rng.choice(INJECTION_STRATEGIES),
            },
        })

    # Defensive: explicitly verify the constraint the user asked for —
    # no logical agent should appear twice in the produced targets.
    keys_used = [_logical_agent_key(framework, t["role"], t["role_index"]) for t in targets]
    assert len(keys_used) == len(set(keys_used)), \
        f"Internal bug: agent dedup violated for {framework}: {keys_used}"

    cfg["injection_plan"] = {"targets": targets}

    # Descriptions can be disabled to save LLM tokens during bulk generation.
    if not enable_descriptions:
        cfg["generate_injection_descriptions"] = False

    return cfg


def _logical_agent_key(framework: str, role: str, role_index: int) -> str:
    """Resolve a (role, role_index) target back to its agent_key for verification."""
    for slot in FRAMEWORK_AGENT_POOL.get(framework, []):
        if slot["role"] == role and slot["role_index"] == role_index:
            return slot["agent_key"]
    return f"{role}_{role_index}"


def _resolve_num_targets(spec: str, framework: str, rng: random.Random) -> int:
    """Resolve --targets_per_config (which can be 'N', 'MIN-MAX', or 'random')
    into a concrete count for a single config of the given framework."""
    pool = FRAMEWORK_AGENT_POOL[framework]
    distinct_agents = len({s["agent_key"] for s in pool})
    if spec == "random":
        return rng.randint(1, distinct_agents)
    if "-" in spec:
        a, b = spec.split("-", 1)
        lo, hi = int(a), int(b)
        # Clamp to what the framework actually offers.
        lo = max(1, min(lo, distinct_agents))
        hi = max(lo, min(hi, distinct_agents))
        return rng.randint(lo, hi)
    # Fixed integer
    return max(1, min(int(spec), distinct_agents))
    """Resolve a (role, role_index) target back to its agent_key for verification."""
    for slot in FRAMEWORK_AGENT_POOL.get(framework, []):
        if slot["role"] == role and slot["role_index"] == role_index:
            return slot["agent_key"]
    return f"{role}_{role_index}"


def config_label(framework: str, cfg: dict) -> str:
    """Human-readable label string that encodes the config (used as dir name)."""
    method = cfg["injection_method"]
    wrap = cfg["prompt_wrapper_style"]
    targets = cfg["injection_plan"]["targets"]
    tgt_strs = []
    for t in targets:
        role = str(t["role"]).lower()
        idx = t["role_index"]
        fm = t["attack_spec"]["fm_error_type"].replace(".", "_")
        strat = "pi" if t["attack_spec"]["injection_strategy"] == "prompt_injection" else "rc"
        tgt_strs.append(f"{role}{idx}-{fm}-{strat}")
    label = f"{framework}__{method}__{wrap}__{'_'.join(tgt_strs)}"
    # Filesystems vary in path-length limits; cap and append a short hash so
    # collisions can't merge results from different configs.
    if len(label) > 120:
        h = hashlib.md5(label.encode("utf-8")).hexdigest()[:8]
        label = label[:110] + "_" + h
    return label


# --------------------------------------------------------------------------- #
# Worker: one subprocess = one randomized config
# --------------------------------------------------------------------------- #
def run_one_config(job: dict) -> dict:
    """Worker function invoked by ThreadPoolExecutor.

    Each `job` describes one randomized config. We:
      1. Write the randomized YAML to disk under <output_root>/configs/.
      2. Build the main.py command with --output_path pointing at the
         per-config result dir.
      3. subprocess.run main.py and capture stdout/stderr.
    """
    framework = job["framework"]
    cfg = job["cfg"]
    label = job["label"]
    output_root = Path(job["output_root"])
    base_dataset = job["base_dataset"]
    model_name = job["model_name"]
    dataset_file = job["dataset_file"]
    test_dataset_name = job["test_dataset_name"]
    sample_limit = job["sample_limit"]
    sequential = job["sequential"]
    extra_main_args = job["extra_main_args"]

    # 1. Write randomized YAML
    cfg_dir = output_root / "configs" / framework
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / f"{label}.yaml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    # 2. Per-config result file path.
    #    We put each config's output in its own subdir named by the label,
    #    so you can spot at-a-glance which configuration produced what.
    results_dir = output_root / "results" / framework / label
    results_dir.mkdir(parents=True, exist_ok=True)
    results_file = results_dir / "trajectories.jsonl"

    cmd = [
        sys.executable, "main.py",
        "--method_name", framework,
        "--experiment_config", str(cfg_path),
        "--test_dataset_name", test_dataset_name,
        "--model_name", model_name,
        "--output_path", str(results_file),
    ]
    if dataset_file:
        cmd += ["--dataset_file", dataset_file]
    if sample_limit:
        cmd += ["--limit", str(sample_limit)]
    if sequential:
        cmd += ["--sequential"]
    if extra_main_args:
        cmd += list(extra_main_args)

    print(f"[start] {framework}/{label[:80]}...")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        elapsed = time.time() - t0
    except Exception as e:
        return {
            "framework": framework, "label": label, "cfg_path": str(cfg_path),
            "results_file": str(results_file),
            "returncode": -1, "elapsed_s": time.time() - t0,
            "error": f"subprocess failed: {e}",
        }

    # 3. Log a short summary
    rc = proc.returncode
    log_dir = output_root / "logs" / framework
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / f"{label}.stdout.log", "w", encoding="utf-8") as f:
        f.write(proc.stdout or "")
    with open(log_dir / f"{label}.stderr.log", "w", encoding="utf-8") as f:
        f.write(proc.stderr or "")

    n_records = 0
    if results_file.exists():
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                for ln in f:
                    if ln.strip():
                        n_records += 1
        except Exception:
            pass

    print(f"[done]  {framework}/{label[:80]}  rc={rc} elapsed={elapsed:.1f}s records={n_records}")
    return {
        "framework": framework, "label": label, "cfg_path": str(cfg_path),
        "results_file": str(results_file), "returncode": rc,
        "elapsed_s": elapsed, "n_records": n_records,
        "stderr_tail": (proc.stderr or "")[-400:],
    }


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frameworks", nargs="+",
                    default=["dylan", "llm_debate", "agentverse"],
                    choices=list(FRAMEWORK_AGENT_POOL.keys()),
                    help="Which MAS frameworks to randomize and run.")
    ap.add_argument("--num_configs", type=int, default=5,
                    help="How many random configs per framework.")
    ap.add_argument("--targets_per_config", type=str, default="random",
                    help="How many injection targets per config. Either a fixed "
                         "integer (e.g. '2'), an inclusive range 'MIN-MAX' "
                         "(e.g. '1-4'), or 'random' (default; uses 1..N where "
                         "N is the framework's agent-pool size — different "
                         "per framework).")
    ap.add_argument("--dataset_file", type=str,
                    default="./datasets/data/medqa.json",
                    help="Path to dataset jsonl/json fed to main.py --dataset_file.")
    ap.add_argument("--test_dataset_name", type=str, default="medqa",
                    help="Dataset name used by main.py for verifier & output dir.")
    ap.add_argument("--model_name", type=str, default="gpt-4o-mini",
                    help="LLM backend name (must exist in your model_api_configs).")
    ap.add_argument("--sample_limit", type=int, default=None,
                    help="Max samples per random config (passed to main.py --limit).")
    ap.add_argument("--workers", type=int, default=2,
                    help="Parallel subprocess workers (each runs a full main.py). "
                         "Total LLM concurrency = workers x main.py max_workers; "
                         "keep small to avoid rate-limiting.")
    ap.add_argument("--seed", type=int, default=None,
                    help="Random seed for reproducibility (default: time-based).")
    ap.add_argument("--output_root", type=str,
                    default="./results_diverse",
                    help="Root directory for generated YAMLs, results, and logs.")
    ap.add_argument("--no_descriptions", action="store_true",
                    help="Disable LLM-powered injection_description / sample summary "
                         "(saves money during bulk generation).")
    ap.add_argument("--sequential_main", action="store_true",
                    help="Pass --sequential to each main.py (debug mode; per-config "
                         "samples run serially inside main.py).")
    ap.add_argument("--dry_run", action="store_true",
                    help="Print the plan (configs to be generated) and exit without "
                         "spawning any subprocess. Useful to validate randomization.")
    ap.add_argument("--main_extra_args", nargs=argparse.REMAINDER,
                    default=[],
                    help="Anything after `--` is forwarded to each main.py call "
                         "(e.g. --model_temperature 0.7).")
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else int(time.time())
    rng = random.Random(seed)
    print(f"[seed] {seed}")

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    # Build the full job list across all frameworks first.
    jobs = []
    for framework in args.frameworks:
        base_path = BASE_YAML_TEMPLATE[framework]
        if not Path(base_path).exists():
            print(f"[skip] base template missing: {base_path}")
            continue
        with open(base_path, "r", encoding="utf-8") as f:
            base_cfg = yaml.safe_load(f)
        for i in range(args.num_configs):
            n_targets = _resolve_num_targets(args.targets_per_config, framework, rng)
            cfg = randomize_config(
                base_cfg, framework=framework,
                num_targets=n_targets,
                rng=rng,
                enable_descriptions=not args.no_descriptions,
            )
            label = config_label(framework, cfg)
            jobs.append({
                "framework": framework, "cfg": cfg, "label": label,
                "output_root": str(output_root),
                "base_dataset": args.test_dataset_name,
                "dataset_file": args.dataset_file,
                "test_dataset_name": args.test_dataset_name,
                "model_name": args.model_name,
                "sample_limit": args.sample_limit,
                "sequential": args.sequential_main,
                "extra_main_args": args.main_extra_args or [],
            })

    print(f"[plan] {len(jobs)} configurations across {len(args.frameworks)} frameworks")
    plan_path = output_root / "plan.jsonl"
    with open(plan_path, "w", encoding="utf-8") as f:
        for j in jobs:
            f.write(json.dumps({
                "framework": j["framework"],
                "label": j["label"],
                "injection_method": j["cfg"].get("injection_method"),
                "prompt_wrapper_style": j["cfg"].get("prompt_wrapper_style"),
                "targets": j["cfg"]["injection_plan"]["targets"],
            }, ensure_ascii=False) + "\n")
    print(f"[plan] saved to {plan_path}")

    if args.dry_run:
        # Pretty-print first few configs and exit
        for j in jobs[:6]:
            print(f"  {j['framework']:<10}  {j['label']}")
        if len(jobs) > 6:
            print(f"  ... +{len(jobs)-6} more")
        return 0

    # Execute the job list with a thread pool. Each thread launches one
    # main.py subprocess and waits for it to finish. The subprocess itself
    # runs main.py's async loop, which already parallelizes samples internally
    # via asyncio + --max_workers.
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one_config, j): j for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"framework": j["framework"], "label": j["label"],
                     "returncode": -1, "error": str(e)}
            results.append(r)

    elapsed = time.time() - t0
    summary = {
        "seed": seed,
        "elapsed_s": elapsed,
        "n_jobs": len(jobs),
        "n_ok": sum(1 for r in results if r.get("returncode") == 0),
        "n_fail": sum(1 for r in results if r.get("returncode") != 0),
        "total_records": sum(r.get("n_records", 0) for r in results),
        "results": results,
    }
    with open(output_root / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n[done] {summary['n_ok']}/{summary['n_jobs']} succeeded, "
          f"{summary['total_records']} records, {elapsed:.1f}s total")
    print(f"[done] summary -> {output_root / 'summary.json'}")
    return 0 if summary["n_fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
