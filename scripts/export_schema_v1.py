#!/usr/bin/env python3
"""
Export main.py result files to the MedHyperTrace trajectory schema
"mas-traj/1" (docs/requests/2026-10-19_from_medhypertrace_HGFM_trajectory_spec_v1.md,
incl. the v1.1 additions).

  python3 scripts/export_schema_v1.py results_a.jsonl [results_b.jsonl ...] \
      --out export.jsonl [--reasoning omit|keep] [--registry configs/framework_registry.yaml]

One output record = one run. Trajectory content (`task`, `steps`, `final`) and
labels (`labels`) are physically separate:

  * Step fields are copied from a WHITELIST, so injection bookkeeping
    (injection_applied, fm_error_type, injected_input_messages,
    clean_response_before_corruption, injection_process, ...) can never reach
    `steps`; it is collected into `labels.injection` instead.
  * `input_messages` is the clean (pre-injection) input. For the legacy
    wrappers that do not guarantee this, `provenance.input_messages_clean` is
    false (original_input_messages is used when the record has it).
  * `reasoning` (the provider's separate reasoning text) is OMITTED by
    default: on a prompt-injected step a reasoning model's thinking usually
    discusses the injected instruction, i.e. it leaks the label. With
    `--reasoning keep` it is exported for non-injected steps and moved to
    `labels.injection[].reasoning` for injected ones (so its absence on a
    step is itself a weak label signal; drop the field when training an
    attribution model on inject runs).
  * Token counts reported by the API are LABEL-side (`labels.llm_meta[step_id]`):
    on a response-corrupted step they describe the clean call whose output was
    replaced, so output length / API token count identifies corrupted steps
    (MedHyperTrace measured 10.06 vs 7.10 chars per token on the mock data,
    issue #1 round 26). Steps instead carry `output_tokens_est`, recounted from
    the stored `output` with one fixed tokenizer for every step
    (`provenance.output_tokenizer`). `finish_reason` stays on the step.

Branching runs (scripts/branch_pilot.py; issue #1 2026-11-03): a branch or control record has the
same framework / model / dataset / id / run_index as its recorded parent normal run, so it needs its
own identity. The exporter takes it from the record's embedded `branch` block (runs from 2026-11-03 on)
or from `--branch_sidecar` (keyed by input file basename + record id; the 2026-10-26 pilot:
data_runs/branch_pilot_2026-10-26/branch_sidecar.jsonl). Such a record gets run_mode "branch",
run_id "<pair_id>|<arm>|rep<k>" and `labels.branch` (never model input). A branch_pilot output file
without identity is refused (fail closed). Duplicate run_ids now stop the export by default
(`--allow_duplicate_run_ids` to override); every problem is also written to <out>.problems.json.

Pairing: `labels.paired_normal_run_ids` lists the normal runs of the same
(framework, question_id, model) found among ALL input files, so pass the clean
and inject outputs together.
"""
import argparse
import importlib.util
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import branch_identity  # noqa: E402

try:   # fixed tokenizer for output_tokens_est (the same for every step / backbone)
    import tiktoken
    _ENC = tiktoken.get_encoding("o200k_base")
    TOKENIZER = "tiktoken:o200k_base"
except Exception:      # offline fallback: words + punctuation
    _ENC = None
    TOKENIZER = "regex:words+punct"


def count_tokens(text):
    text = text or ""
    if _ENC is not None:
        return len(_ENC.encode(text, disallowed_special=()))
    return len(re.findall(r"\w+|[^\w\s]", text))

SCHEMA = "mas-traj/1"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REGISTRY = os.path.join(HERE, "..", "configs", "framework_registry.yaml")

# Whether a RECORD came from the structured contract (clean inputs, sources,
# step ids) is read from the record itself: since 2026-10-20 every framework
# runs on StructuredFMWrapper, but older result files of the same frameworks
# were produced by the legacy wrappers and are exported best-effort + flagged.
def _is_structured(log):
    hist = [h for h in log.get("conversation_history") or [] if not h.get("is_input")]
    return bool(log.get("input_messages_are_clean")) and bool(hist) and all("step_id" in h for h in hist)


def load_registry(path):
    reg = (yaml.safe_load(open(path, encoding="utf-8")) or {}).get("frameworks", {})
    alias = {}
    for name, meta in reg.items():
        alias[name] = name
        for a in meta.get("aliases") or []:
            alias[a] = name
    return reg, alias


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s or "agent").lower()).strip("_")


def _norm_phase(phase):
    """mdagents results written before 2026-10-21 put the expert's specialty
    (and the revision round) into the phase ("expert_answer/Cardiologist",
    "expert_revise_r1/..."), which split one slot into many; the specialty is
    already the step's agent_label and the round its `round`."""
    if isinstance(phase, str) and "/" in phase and phase.split("/")[0].startswith("expert_"):
        base = phase.split("/")[0]
        return "expert_revise" if base.startswith("expert_revise") else base
    return phase


def _inject_signature(targets, history=None):
    key = [{k: t.get(k) for k in ("injected_role", "injected_role_index", "injected_phase",
                                  "injected_round", "fm_error_type", "injection_strategy")}
           for t in targets or []]
    # Injection variants that change the injected text but not the target
    # (prompt wrapper style, rewrite pool) are part of the id too, so e.g. the
    # "direct" and "simulation" reruns of one question do not collide. The
    # default ("direct", no pool) adds nothing, which keeps earlier ids stable.
    extra = set()
    for h in history or []:
        ip = h.get("injection_process") or {}
        if ip.get("prompt_wrapper_style") not in (None, "direct"):
            extra.add(f"wrapper={ip['prompt_wrapper_style']}")
        if ip.get("template_pool"):
            extra.add(f"pool={ip['template_pool']}")
        if h.get("pi_length_match"):          # PI fix versions (2026-10-21)
            stated = any("words long" in str(m.get("content", "")) for m in (h.get("injected_input_messages") or []))
            extra.add("lenmatch+stated" if stated else "lenmatch")
        if h.get("sham"):
            extra.add(f"sham={h.get('sham')}")
            if str(ip.get("sham_variant") or "").startswith("style_v2"):
                extra.add("sham_v2")         # reworded sham_style vs the old single wording
        if ip.get("note_version"):            # format-matched note (fmt_v1, MHT r43)
            extra.add(f"note={ip['note_version']}")
        if ((h.get("pi_length_match") or {}).get("format") or {}).get("match_format"):
            extra.add("fmtsel")              # tries also selected on markdown match
        if ((h.get("pi_length_match") or {}).get("format") or {}).get("match_opener"):
            extra.add("opener")              # role-intro opener in the signature (v10 r10)
    if extra:
        key.append(sorted(extra))
    return hashlib.md5(json.dumps(key, sort_keys=True).encode()).hexdigest()[:8]


def _gold(gt):
    if isinstance(gt, dict):
        if gt.get("acceptable_answers"):
            return gt.get("correct_answer"), list(gt["acceptable_answers"])
        return gt.get("correct_answer"), None
    return gt, None


def _final_answer(rec, log, steps_by_id):
    for v in (rec.get("pred_answer"), log.get("final_level")):
        if v not in (None, ""):
            return v
    fs = log.get("final_step_id")
    st = (steps_by_id.get(fs) or {}).get("structured") or {}
    for k in ("answer", "esi_level"):
        if st.get(k) not in (None, ""):
            return st[k]
    return (rec.get("verification") or {}).get("regex_extracted")


def convert(rec, reg, alias, reasoning_mode, branch=None):
    log = rec.get("injection_log") or {}
    fw_raw = rec.get("framework") or log.get("framework") or "unknown"
    fw = alias.get(fw_raw, fw_raw)
    meta = reg.get(fw, {})
    dataset = rec.get("dataset") or "unknown"
    qid = rec.get("question_id") or f"{dataset}/{rec.get('id')}"
    run_index = int(rec.get("run_index") or 0)
    run_mode = "normal" if rec.get("run_mode") == "clean" else "inject"
    targets = log.get("multi_injection_info") or []
    mode_tag = run_mode if run_mode == "normal" else f"inject-{_inject_signature(targets, log.get('conversation_history'))}"
    # the backbone is part of the id: the same question / run index is run on
    # several backbones (a collision found on the first real probe, 2026-10-20)
    model_name = (rec.get("model") or {}).get("name") or "unknown-model"
    run_id = f"{fw}|{model_name}|{dataset}|{rec.get('id')}|{mode_tag}|r{run_index}"
    if branch is not None:
        # branch / control arm of a branching run: own identity, never counted as a normal run
        run_mode = "branch"
        run_id = branch_identity.branch_run_id(branch)
    structured_fw = _is_structured(log)

    obs = log.get("task_observations") or []
    obs_ids = {o["id"] for o in obs}

    steps, injections, order = [], [], 0
    llm_meta_labels = {}
    for h in log.get("conversation_history") or []:
        if h.get("is_input"):            # legacy "User" prompt entries are not calls
            continue
        sid = h.get("step_id") or f"s{order}"
        is_tool = bool(h.get("is_tool"))
        lm = h.get("llm_meta") or {}
        injected = bool(h.get("injection_applied"))
        role = h.get("role") or h.get("agent_name")
        clean_in = h.get("input_messages")
        if not structured_fw and h.get("original_input_messages"):
            clean_in = h["original_input_messages"]
        how = h.get("source_how") or {}
        sources = None
        if "sources" in h:
            sources = [{"step_id": s, "how": how.get(s, "verbatim")} for s in h.get("sources") or []]
            sources += [{"step_id": f"task:obs:{o}", "how": "verbatim"}
                        for o in h.get("observations") or [] if o in obs_ids]
        step = {
            "step_id": sid, "order": order, "kind": "tool" if is_tool else "llm",
            "agent_id": h.get("agent_id") or f"{_slug(role)}_{h.get('role_index', 0)}",
            "agent_role": role, "agent_label": h.get("agent_label"),
            "phase": _norm_phase(h.get("phase")), "round": h.get("round"),
            "event_ids": list(h.get("event_ids") or []),
            "input_messages": None if is_tool else clean_in,
            "sources": sources,
            "output": h.get("content") if h.get("content") is not None else h.get("response"),
            "structured": h.get("structured"),
            "tool_calls": h.get("tool_calls") or [],
            "finish_reason": lm.get("finish_reason"),
        }
        step["output_tokens_est"] = count_tokens(step["output"]) if not is_tool else None
        if lm:
            llm_meta_labels[sid] = {k: lm.get(k) for k in
                                    ("model", "served_model", "max_tokens", "prompt_tokens",
                                     "completion_tokens", "reasoning_tokens")}
        if is_tool and h.get("stub"):
            step["tool_stub"] = True
        if reasoning_mode == "keep":
            step["reasoning"] = None if injected else lm.get("reasoning")
        steps.append(step)
        if injected:
            inj = {
                "step_id": sid, "agent_id": step["agent_id"],
                "strategy": h.get("injection_strategy"), "fm_error_type": h.get("fm_error_type"),
                "target_index": h.get("target_index"), "applied": True,
                "injected_input_messages": h.get("injected_input_messages"),
                "clean_output": h.get("clean_response_before_corruption"),
                "injection_process": h.get("injection_process"),
            }
            # the strategy that actually produced this step: an RC step with no
            # answer to change is redone as PI (rc_fallback "pi") and counts as PI
            inj["planned_strategy"] = ("response_corruption" if h.get("rc_fallback_to_pi")
                                       else h.get("injection_strategy"))
            inj["effective_strategy"] = h.get("injection_strategy")
            if h.get("sham"):
                # placebo: same note as a prompt injection but no error asked for
                inj["planned_strategy"] = inj["effective_strategy"] = (
                    "sham_style" if h.get("sham") == "style" else "sham")
                ip = h.get("injection_process") or {}
                # wording variant; runs before the v2 wordings have none recorded
                inj["sham_variant"] = ip.get("sham_variant") or (
                    "style_v1" if h.get("sham") == "style" else "plain_v1")
            if h.get("pi_length_match"):
                inj["pi_length_match"] = h.get("pi_length_match")
            if (h.get("injection_process") or {}).get("note_version"):
                inj["note_version"] = h["injection_process"]["note_version"]
            if h.get("rc_fallback_to_pi"):
                inj["rc_fallback_to_pi"] = True
                inj["discarded_clean_output"] = h.get("discarded_clean_response")
            if reasoning_mode == "keep":
                inj["reasoning"] = lm.get("reasoning")
            injections.append(inj)
        order += 1

    by_id = {s["step_id"]: s for s in steps}
    gold, acceptable = _gold(rec.get("ground_truth"))
    is_valid = rec.get("is_valid_error") if run_mode == "inject" else rec.get("is_valid_normal")
    task = {"dataset": dataset, "query": rec.get("query"),
            "images": list(rec.get("images") or []),
            "observations": [dict(o, id=f"obs:{o['id']}") for o in obs]}
    out = {
        "schema_version": SCHEMA,
        "run_id": run_id, "question_id": qid, "run_mode": run_mode,
        "run_index": run_index, "seed": None,
        "framework": fw, "framework_family": meta.get("family", fw),
        "framework_description": meta.get("description"),
        "model": rec.get("model") or {"name": None},
        "task": task,
        "steps": steps,
        "final": {"answer": _final_answer(rec, log, by_id), "response": rec.get("response"),
                  "source_step_ids": list(log.get("final_source_step_ids") or [])
                  or ([log["final_step_id"]] if log.get("final_step_id") else [])},
        "labels": {
            "gold": gold, "acceptable_answers": acceptable,
            "is_correct": rec.get("is_correct"), "is_valid": is_valid,
            "status": rec.get("status"),
            "verification_path": (rec.get("verification") or {}).get("decision_path"),
            "execution_successful": log.get("execution_successful"),
            "injection": injections,
            "injection_targets": [dict(t) for t in targets],
            # API-reported token usage per step: NOT a model input (side channel
            # on response-corrupted steps); see the module docstring.
            "llm_meta": llm_meta_labels,
            "paired_normal_run_ids": [],
        },
        "provenance": {
            "source_record_id": rec.get("id"), "wrapper_contract": "structured" if structured_fw else "legacy",
            "input_messages_clean": bool(log.get("input_messages_are_clean")) or not injections,
            "sources_recorded": all(s["sources"] is not None for s in steps if s["kind"] == "llm"),
            "history_alignment_ok": log.get("history_alignment_ok"),
            "reasoning_exported": reasoning_mode == "keep",
            "output_tokenizer": TOKENIZER,
        },
    }
    if branch is not None:
        # experiment metadata: label side only, never rendered into model input or graph features
        out["labels"]["branch"] = branch
    return out


# ---------------------------------------------------------------------- outcome
STEP_ANSWER_KEYS = ("answer", "esi_level", "final_answer")


def _step_answer(step):
    st = step.get("structured") or {}
    for k in STEP_ANSWER_KEYS:
        if st.get(k) is not None:
            return st[k]
    return None


def injection_outcome(r, correct_by_id):
    """labels.outcome of an injected run (MedHyperTrace r28, MAFA's two layers:
    the injected step is the defect layer, the final result the responsibility
    layer).

      not_fired      the target never ran (e.g. a sampled target the run did not reach)
      flipped        paired normal runs are mostly correct, this run is wrong
      repaired       the injected step's answer is wrong, the run is still correct
      benign         the injected step's answer is not wrong, the run is correct
      baseline_wrong this run is wrong, but so are most paired normal runs (or
                     there are none): the failure cannot be credited to the injection
      unresolved     the run is correct and the injected step states no parsable answer

    Also: labels.injected_step_wrong (True / False / None) and
    labels.paired_normal_accuracy.
    """
    lab = r["labels"]
    fired = [t for t in lab.get("injection_targets") or [] if t.get("fired", True)]
    inj = lab.get("injection") or []
    paired = [correct_by_id.get(x) for x in lab.get("paired_normal_run_ids") or []]
    paired = [bool(x) for x in paired if x is not None]
    acc = sum(paired) / len(paired) if paired else None
    out = {"paired_normal_accuracy": acc, "injected_step_wrong": None}
    if not fired or not inj:
        out["outcome"] = "not_fired"
        return out
    if all(str(i.get("effective_strategy")).startswith("sham") for i in inj):
        out["outcome"] = "sham"      # placebo run: not a fault by construction
        return out
    gold = lab.get("gold")
    by_id = {s["step_id"]: s for s in r["steps"]}
    wrong = None
    for i in inj:
        a = _step_answer(by_id.get(i["step_id"], {}))
        if a is not None and gold is not None:
            acc_set = {str(x).strip().lower() for x in (lab.get("acceptable_answers") or [gold])}
            w = str(a).strip().lower() not in acc_set
            wrong = w if wrong is None else (wrong or w)
    out["injected_step_wrong"] = wrong
    correct = lab.get("is_correct")
    if not correct:
        out["outcome"] = "flipped" if (acc is not None and acc >= 0.5) else "baseline_wrong"
    elif wrong is True:
        out["outcome"] = "repaired"
    elif wrong is False:
        out["outcome"] = "benign"
    else:
        out["outcome"] = "unresolved"
    return out


# ---------------------------------------------------------------------- checks
INJECTION_MARKERS = ("[UPDATED INSTRUCTION", "SUPERSEDES ALL EARLIER INSTRUCTIONS")
LABEL_KEYS = {"prompt_tokens", "completion_tokens", "reasoning_tokens",
              "injection_applied", "fm_error_type", "injection_strategy", "prompt_modified",
              "injected_input_messages", "clean_response_before_corruption",
              "response_corrupted", "injection_process", "injection_description",
              "target_index", "current_role", "current_role_index",
              "discarded_clean_response", "discarded_llm_meta", "rc_fallback_to_pi",
              "pi_length_match", "length_ref_llm_meta", "sham"}


# kind "environment" (schema note docs/mas_traj_schema_notes.md, v10 round 15): text no agent wrote
# (prompt templates, tool / web page dumps, scaffold messages). Never an attribution candidate; may be
# truncated or compressed; may be cited in `sources`. llm steps are never rewritten or summarised.
KINDS = {"llm", "tool", "environment"}
ENV_TYPES = {"template", "tool_output", "web_page", "scaffold_prompt", "user_simulator"}
PHASE_CANONICAL = {"plan", "route", "analyze", "answer", "discuss", "synthesize", "vote", "review", "revise",
                   "decide", "act", "tool", "environment", "other"}   # v1, configs/phase_canonical_v1.yaml (adopted r62)


def check(rec):
    """Schema invariants + leak checks; returns a list of problems."""
    probs = []
    ids = {s["step_id"]: s["order"] for s in rec["steps"]}
    b = rec["labels"].get("branch")
    if rec["run_mode"] == "branch" or b is not None:
        if rec["run_mode"] != "branch" or b is None:
            probs.append("run_mode branch and labels.branch must come together")
        else:
            probs += branch_identity.block_problems(b)
            if rec["run_id"] != branch_identity.branch_run_id(b):
                probs.append("branch run_id is not <pair_id>|<arm>|rep<k>")
            if set(b.get("regenerated_step_ids") or []) | set(b.get("replayed_step_ids") or []) != \
                    {s["step_id"] for s in rec["steps"] if s["kind"] == "llm"}:
                probs.append("branch regenerated + replayed != llm steps")
            if any("branch" in s for s in rec["steps"]):
                probs.append("branch metadata inside steps")
    obs = {o["id"] for o in rec["task"]["observations"]}
    for s in rec["steps"]:
        kind = s.get("kind", "llm")
        if kind not in KINDS:
            probs.append(f"{s['step_id']}: bad kind {kind}")
        if kind == "environment":
            if s.get("env_type") not in ENV_TYPES:
                probs.append(f"{s['step_id']}: environment step needs env_type in {sorted(ENV_TYPES)}")
            if s.get("tool_calls"):
                probs.append(f"{s['step_id']}: environment step with tool_calls")
        elif "env_type" in s and s["env_type"] is not None:
            probs.append(f"{s['step_id']}: env_type on a {kind} step")
        if s.get("phase_canonical") is not None and s["phase_canonical"] not in PHASE_CANONICAL:
            probs.append(f"{s['step_id']}: bad phase_canonical {s['phase_canonical']}")
        leaked = LABEL_KEYS & set(s)
        if leaked:
            probs.append(f"{s['step_id']}: label keys in step {sorted(leaked)}")
        blob = json.dumps(s.get("input_messages"), ensure_ascii=False)
        if any(m in blob for m in INJECTION_MARKERS):
            probs.append(f"{s['step_id']}: injection marker in input_messages")
        for src in s["sources"] or []:
            sid = src["step_id"]
            if sid.startswith("task:"):
                if sid[len("task:"):] not in obs:
                    probs.append(f"{s['step_id']}: unknown observation {sid}")
            elif sid not in ids:
                probs.append(f"{s['step_id']}: unknown source {sid}")
            elif ids[sid] >= s["order"]:
                probs.append(f"{s['step_id']}: source {sid} is not earlier")
            if src["how"] not in ("verbatim", "excerpt", "structured_field", "summary", "control"):
                probs.append(f"{s['step_id']}: bad how {src['how']}")
    for inj in rec["labels"]["injection"]:
        if inj["step_id"] not in ids:
            probs.append(f"injection on unknown step {inj['step_id']}")
    for fs in rec["final"]["source_step_ids"]:
        if fs not in ids:
            probs.append(f"final source {fs} unknown")
    return probs


# ---- MedAgentAudit (MAA) exclusion (MedHyperTrace round 57) -------------------------------
# MAA is MHT's zero-shot evaluation set; none of its questions may enter training data.
# The list is maintained by MHT (MedHyperTrace-v2/docs/interfaces/maa_exclusion_v1.json, a
# copy in docs/requests/). norm_stem and the probe rule are copied verbatim from
# MedHyperTrace-v2/data_tools/maa_exclusion.py so both sides decide overlap the same way.
_MAA_OPT = re.compile(r"\n\s*Options:|\nAnswer Choices|\n\s*\(?A[\).:]\s")


def maa_norm_stem(q):
    q = _MAA_OPT.split(q or "")[0]
    return re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()


def load_maa_exclusion(path):
    doc = json.load(open(path, encoding="utf-8"))
    by_stem = defaultdict(list)
    for e in doc["entries"]:
        by_stem[e["norm_stem"]].append(e)
    long = [e for e in doc["entries"] if len(e["norm_stem"]) >= 200]
    return {"version": doc.get("version"), "by_stem": by_stem, "long": long,
            "blob": "\n".join(e["norm_stem"] for e in long)}


def maa_overlap(rec, ex):
    """(exact question ids, probe-candidate question ids) for one exported record."""
    task = rec.get("task") or {}
    s = maa_norm_stem(task.get("query") or "")
    ims = set(task.get("images") or [])
    exact = sorted({e["question_id"] for e in ex["by_stem"].get(s, [])
                    if not e["images"] or ims & set(e["images"])})
    probe = []
    if len(s) >= 200:
        w = s[100:160]
        if w in ex["blob"]:
            probe = [e["question_id"] for e in ex["long"] if w in e["norm_stem"]]
        else:
            probe = [e["question_id"] for e in ex["long"] if e["norm_stem"][100:160] in s]
    return exact, sorted(set(probe) - set(exact))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--reasoning", choices=("omit", "keep"), default="omit")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--strict", action="store_true", help="exit 1 if any record fails the checks")
    ap.add_argument("--branch_sidecar", action="append", default=[],
                    help="branch identity sidecar(s) for branch_pilot outputs without an embedded `branch` block")
    ap.add_argument("--allow_duplicate_run_ids", action="store_true",
                    help="write the export even if run_ids collide (default: stop, nothing written)")
    ap.add_argument("--maa_exclusion", default=None,
                    help="MAA exclusion list (docs/requests/maa_exclusion_v1.json): exact overlaps go to "
                         "labels.maa_overlap, probe candidates to labels.maa_probe (manual review)")
    ap.add_argument("--phase_canonical", default=os.path.join(HERE, "phase_canonical.py"),
                    help="writes step['phase_canonical'] (default on, table configs/phase_canonical_v1.yaml); 'none' to skip")
    a = ap.parse_args()

    reg, alias = load_registry(a.registry)
    sidecar = {}
    for sp in a.branch_sidecar:
        sidecar.update(branch_identity.load_sidecar(sp))
    records, n_skipped, unstamped = [], 0, []
    for path in a.inputs:
        with branch_identity.open_any(path) as f:
            for line in f:
                if not line.strip():
                    continue
                raw = json.loads(line)
                branch = raw.get("branch") or sidecar.get((os.path.basename(path), raw.get("id")))
                if branch is None and branch_identity.is_branch_output(path):
                    unstamped.append(f"{path}:{raw.get('id')}")
                    continue
                if not raw.get("injection_log") or raw.get("status") in ("error", "llm_api_failure"):
                    # a sample main.py could not run (status "error"), or an API call
                    # failed mid-run ("llm_api_failure"): no complete trajectory
                    n_skipped += 1
                    print(f"-- skipped {path}:{raw.get('id')} (status={raw.get('status')}, no trajectory)",
                          file=sys.stderr)
                    continue
                records.append(convert(raw, reg, alias, a.reasoning, branch))
    if unstamped:
        # fail closed: a branch / control record without its identity would collide with its parent run
        print(f"!! {len(unstamped)} branch_pilot records have no branch identity (embedded `branch` or "
              f"--branch_sidecar), e.g. {unstamped[:3]}; nothing written", file=sys.stderr)
        sys.exit(2)

    normals = defaultdict(list)
    for r in records:
        if r["run_mode"] == "normal":
            normals[(r["framework"], r["question_id"], r["model"].get("name"))].append(r["run_id"])
    correct_by_id = {r["run_id"]: r["labels"].get("is_correct") for r in records}
    for r in records:
        if r["run_mode"] == "inject":
            r["labels"]["paired_normal_run_ids"] = sorted(
                normals.get((r["framework"], r["question_id"], r["model"].get("name")), []))
            r["labels"].update(injection_outcome(r, correct_by_id))

    if a.maa_exclusion:
        ex = load_maa_exclusion(a.maa_exclusion)
        n_ex = n_pr = 0
        qs_ex = set()
        for r in records:
            exact, probe = maa_overlap(r, ex)
            r["labels"]["maa_overlap"] = exact          # [] = checked, no overlap
            if probe:
                r["labels"]["maa_probe"] = probe
            r["provenance"]["maa_exclusion_version"] = ex["version"]
            n_ex += bool(exact); n_pr += bool(probe)
            if exact:
                qs_ex.add(r["question_id"])
        print(f"MAA exclusion ({ex['version']}): {n_ex} runs on {len(qs_ex)} overlapping questions "
              f"{sorted(qs_ex)}; {n_pr} runs with probe candidates", file=sys.stderr)

    if a.phase_canonical and a.phase_canonical != "none":
        spec = importlib.util.spec_from_file_location("phase_canonical", a.phase_canonical)
        pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc)
        table = pc.load()
        for r in records:
            pc.annotate(table, r)
            r["provenance"]["phase_canonical_table"] = table["version"]

    seen, n_bad, dups, problems = set(), 0, defaultdict(int), {}
    for r in records:
        if r["run_id"] in seen:
            dups[r["run_id"]] += 1
            print(f"!! duplicate run_id {r['run_id']}", file=sys.stderr); n_bad += 1
        seen.add(r["run_id"])
        probs = check(r)
        if probs:
            n_bad += 1
            problems.setdefault(r["run_id"], []).extend(probs)
            print(f"!! {r['run_id']}: " + "; ".join(probs[:5]), file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out + ".problems.json", "w", encoding="utf-8") as f:
        json.dump({"n_records": len(records), "n_with_problems": n_bad,
                   "duplicate_run_ids": {k: v + 1 for k, v in dups.items()},
                   "check_problems": problems, "skipped_without_trajectory": n_skipped},
                  f, ensure_ascii=False, indent=1)
    if dups and not a.allow_duplicate_run_ids:
        print(f"!! {len(dups)} duplicate run_ids (see {a.out}.problems.json); nothing written. "
              f"Pass --allow_duplicate_run_ids to override.", file=sys.stderr)
        sys.exit(2)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_fw = defaultdict(lambda: [0, 0, 0])
    for r in records:
        by_fw[r["framework"]][{"normal": 0, "inject": 1}.get(r["run_mode"], 2)] += 1
    print(f"exported {len(records)} runs -> {a.out}  (records with problems: {n_bad}; "
          f"skipped without trajectory: {n_skipped})")
    for fw, (n, i, b) in sorted(by_fw.items()):
        print(f"  {fw:22s} normal={n:4d} inject={i:4d}" + (f" branch={b:4d}" if b else ""))
    if a.strict and n_bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
