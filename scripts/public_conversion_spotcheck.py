#!/usr/bin/env python3
"""Spot-check of MHT's public-dataset -> mas-traj/1 conversions (issue #1, owed since MHT r57/r60).

For N sampled records per dataset (fixed seed) we go back to the RAW dataset row and check:
  A  check() from export_schema_v1 (our validator) passes
  B  verbatim fidelity: each step output (whitespace-normalised) occurs in the raw trajectory text
  C  coverage: share of raw trajectory characters that end up in some step output / task.query
  D  label alignment: labelled step ids exist; the agent of the labelled step vs the labelled agent
  E  leakage: label text (reasons, summaries, evidence) appearing verbatim in steps or query
  F  hygiene: empty outputs, very long outputs, repeated consecutive outputs, phase=unknown, sources=None

Raw layouts are the ones MHT's converters read (README of data_tools/public_to_mas_traj).
No network, no API.

  python scripts/public_conversion_spotcheck.py --data /home/claude/public_mas/mas_traj \
      --raw /home/claude/public_mas/raw --n 20 --seed 0 --out docs/requests/samples/public_spotcheck_2026-10-26
"""
import argparse
import ast
import gzip
import importlib.util
import json
import os
import random
import re
import zipfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATASETS = ["who_and_when", "traceelephant", "mast_data", "aria", "aftraj", "mascope", "agentrx_tau"]


def load_check():
    spec = importlib.util.spec_from_file_location("es1", os.path.join(HERE, "export_schema_v1.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.check


def ws(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def alnum(s):
    s = str(s).encode().decode("unicode_escape", errors="ignore") if "\\u" in str(s) else str(s)
    return re.sub(r"[^0-9a-z]", "", s.lower())


def maybe_parse(s):
    if not isinstance(s, str) or len(s) < 2 or s[0] not in "[{":
        return None
    for f in (json.loads, ast.literal_eval):
        try:
            return f(s)
        except Exception:
            pass
    # numpy reprs inside python reprs: array([...], dtype=object)
    try:
        return ast.literal_eval(re.sub(r"array\((\[.*?\])(?:, dtype=\w+)?\)", r"\1", s, flags=re.S))
    except Exception:
        return None


def strings(o, out, keep_orig=False):
    """Flatten every string leaf, descending into JSON / python-repr strings (keep_orig: also keep the
    undecoded string, for verbatim matching of steps that store a JSON blob as their output)."""
    if hasattr(o, "tolist"):
        o = o.tolist()
    if isinstance(o, dict):
        for v in o.values():
            strings(v, out, keep_orig)
    elif isinstance(o, (list, tuple)):
        for v in o:
            strings(v, out, keep_orig)
    elif isinstance(o, str):
        p = maybe_parse(o)
        if p is not None and not isinstance(p, str):
            if keep_orig:
                out.append(o)
                out.append(json.dumps(p, ensure_ascii=False))
            strings(p, out, keep_orig)
        else:
            out.append(o)
    elif o is not None and not isinstance(o, (bool, int, float)):
        out.append(str(o))
    return out


# ------------------------------------------------------------------ raw loaders: id -> trajectory object
def raw_index(ds, raw):
    import pandas as pd
    idx = {}
    if ds == "who_and_when":
        for sub in ("Hand-Crafted", "Algorithm-Generated"):
            df = pd.read_parquet(f"{raw}/Kevin355__Who_and_When/{sub}/train/0000.parquet")
            for _, r in df.iterrows():
                idx[f"{sub}/{r['question_ID']}"] = [dict(m) for m in r["history"]]
    elif ds == "traceelephant":
        z = zipfile.ZipFile(f"{raw}/TraceElephant__TraceElephant/data.zip")
        for n in z.namelist():
            if n.endswith("/step_records.json"):
                idx[n[: -len("/step_records.json")]] = json.loads(z.read(n))
    elif ds == "mast_data":
        df = pd.read_parquet(f"{raw}/mcemri__MAST-Data/default/train/0000.parquet")
        for _, r in df.iterrows():
            t = r["trace"]
            idx[f"{t['key']}/{t['index']}"] = t["trajectory"]
    elif ds == "aria":
        for sp in ("train", "validation", "test"):
            df = pd.read_parquet(f"{raw}/Edlison__ARIA/data/{sp}.parquet", columns=["id", "task", "trajectory"])
            for _, r in df.iterrows():
                idx[r["id"]] = {"task": r["task"], "trajectory": r["trajectory"]}
    elif ds == "aftraj":
        for f in ("aftraj_safe", "aftraj_unsafe"):
            df = pd.read_parquet(f"{raw}/ZBox008003__AFTraj/{f}.parquet")
            for _, r in df.iterrows():
                idx[r["conv_id"]] = {"task": r["task"], "turns": r["turns"]}
    elif ds == "mascope":
        for f in ("LG-Ctrl", "Inject-Mix"):
            for line in open(f"{raw}/mascope__mascope-bench/{f}.jsonl", encoding="utf-8"):
                r = json.loads(line)
                idx[r["trace_id"]] = {"task": r.get("task_description"), "trajectory": r["trajectory"]}
    elif ds == "agentrx_tau":
        for line in open(f"{raw}/microsoft__AgentRx/tau_retail_dataset.jsonl", encoding="utf-8"):
            r = json.loads(line)
            idx[r["trajectory_id"]] = {"instruction": r.get("instruction"), "steps": r["steps"]}
    return idx


def read_records(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def norm_agent(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


JUDGMENT_KEYS = {"mistake_reason", "failure_summary", "step_reason", "category_reason", "root_cause_reason",
                 "reason_for_root_cause", "rationale", "explanation", "summary", "note", "feedback"}


def label_texts(ext, path=""):
    """(key path, text) for long label strings."""
    out = []
    if isinstance(ext, dict):
        for k, v in ext.items():
            out += label_texts(v, f"{path}.{k}" if path else k)
    elif isinstance(ext, list):
        for i, v in enumerate(ext):
            out += label_texts(v, f"{path}[{i}]")
    elif isinstance(ext, str) and len(ext) >= 40:
        out.append((path, ext))
    return out


def labelled_steps(ds, ext):
    """[(step_id, labelled_agent or None)] from labels.external."""
    out = []
    if ds in ("who_and_when", "traceelephant"):
        if ext.get("mistake_step_id") is not None or ext.get("mistake_step") not in (None, ""):
            out.append((ext.get("mistake_step_id"), ext.get("mistake_agent")))
        for f in ((ext.get("agentrx") or {}).get("failures") or []):
            out.append((f.get("step_id"), f.get("failed_agent")))
    elif ds == "aria":
        for s in ext.get("first_bad_step_ids") or []:
            out.append((s, None))
    elif ds == "agentrx_tau":
        for f in ext.get("failures") or []:
            out.append((f.get("step_id"), f.get("failed_agent")))
    return out


def spot(ds, data, raw, n, seed, check):
    recs = list(read_records(os.path.join(data, f"{ds}.jsonl.gz")))
    rng = random.Random(f"{seed}|{ds}")
    sample = rng.sample(recs, min(n, len(recs)))
    idx = raw_index(ds, raw)
    R = {"dataset": ds, "n_records": len(recs), "n_sampled": len(sample)}
    c = Counter()
    examples = defaultdict(list)
    cov = []
    for r in sample:
        rid = r["provenance"].get("source_record_id")
        probs = check(r)
        c["check_fail"] += bool(probs)
        if probs:
            examples["check"].append((r["run_id"], probs[:3]))
        rawobj = idx.get(rid)
        if rawobj is None:
            c["raw_missing"] += 1
            examples["raw_missing"].append(rid)
            continue
        raw_strs = strings(rawobj, [])
        blob = ws("\n".join(strings(rawobj, [], keep_orig=True)))
        blob_l = blob.lower()
        blob_a = alnum(blob)
        outs = [ws(s.get("output") or "") for s in r["steps"]]
        # B verbatim
        for s, o in zip(r["steps"], outs):
            c["steps"] += 1
            if not o:
                c["empty_output"] += 1
                c[f"empty_output:{s['kind']}:{'with_tool_calls' if s.get('tool_calls') else 'no_tool_calls'}"] += 1
                continue
            if o in blob:
                c["verbatim"] += 1
            elif o.lower() in blob_l:
                c["verbatim_casefold"] += 1
            elif alnum(o) and alnum(o) in blob_a:
                c["verbatim_alnum"] += 1      # same characters, different serialisation (JSON re-dump, escapes)
            else:
                # partial: longest 80-char window present?
                wins = [o[i:i + 80] for i in range(0, max(1, len(o) - 80), 80)]
                hit = sum(w in blob for w in wins)
                key = "partial" if hit else "absent"
                c[key] += 1
                if len(examples[key]) < 6:
                    examples[key].append({"run_id": r["run_id"], "step": s["step_id"], "kind": s["kind"],
                                          "agent": s["agent_id"], "win_hit": f"{hit}/{len(wins)}", "output": o[:200]})
        # C coverage of raw trajectory text (strings >= 40 chars)
        extra = strings(r["task"].get("observations") or [], [])   # e.g. AgentRx obs:policy (missed in round 15)
        for s_ in r["steps"]:
            for m in s_.get("input_messages") or []:
                extra += strings(m, [])
            extra += strings(s_.get("tool_calls") or [], [])
            extra += strings(s_.get("structured") or {}, [])
        have = ws(" ".join(outs + [ws(r["task"].get("query") or "")] + [ws(x) for x in extra]))
        # serialisation-tolerant: compare alphanumeric-only text in 100-char windows
        have_a = alnum(have)
        long_raw = [x for x in raw_strs if len(alnum(x)) >= 40]
        tot = got = 0
        miss = []
        for x in long_raw:
            xa = alnum(x)
            wins = [xa[i:i + 100] for i in range(0, len(xa), 100)]
            hit = sum(len(w) for w in wins if w in have_a)
            tot += len(xa)
            got += hit
            if hit < 0.5 * len(xa):
                miss.append(ws(x))
        cov.append(got / (tot or 1))
        miss.sort(key=len, reverse=True)
        if miss and len(examples["uncovered"]) < 10:
            examples["uncovered"].append({"run_id": r["run_id"], "cov": round(got / (tot or 1), 3), "n_missing": len(miss),
                                          "largest": [m[:160] for m in miss[:2]], "largest_len": [len(m) for m in miss[:2]]})
        # D labels
        sid2 = {s["step_id"]: s for s in r["steps"]}
        for sid, agent in labelled_steps(ds, r["labels"].get("external") or {}):
            c["label_steps"] += 1
            if sid is None:
                c["label_step_unmapped"] += 1
                if len(examples["label_unmapped"]) < 6:
                    examples["label_unmapped"].append(r["run_id"])
                continue
            if sid not in sid2:
                c["label_step_missing"] += 1
                continue
            if agent:
                st = sid2[sid]
                a, w = norm_agent(agent), norm_agent(f"{st['agent_id']} {st['agent_role']}")
                if a and (a in w or w in a):
                    c["label_agent_match"] += 1
                else:
                    c["label_agent_mismatch"] += 1
                    if len(examples["label_agent_mismatch"]) < 8:
                        examples["label_agent_mismatch"].append({"run_id": r["run_id"], "step": sid, "labelled_agent": agent,
                                                                 "step_agent": st["agent_id"], "step_role": st["agent_role"]})
        # E leakage
        visible = ws(" ".join(outs + [r["task"].get("query") or ""]))
        for path, t in label_texts(r["labels"].get("external") or {}):
            leaf = path.split(".")[-1].split("[")[0]
            t = ws(t)
            if len(t) >= 40 and t in visible:
                kind = "judgment" if leaf in JUDGMENT_KEYS else "other"
                c[f"label_text_in_visible_{kind}"] += 1
                if len(examples["leak"]) < 6:
                    examples["leak"].append({"run_id": r["run_id"], "field": path, "text": t[:160]})
        # F hygiene
        for i, s in enumerate(r["steps"]):
            c["phase_unknown"] += s.get("phase") in (None, "unknown")
            c["sources_none"] += s.get("sources") is None
            c["very_long_output"] += len(s.get("output") or "") > 50000
            if i and outs[i] and outs[i] == outs[i - 1]:
                c["repeat_consecutive"] += 1
            c[f"kind:{s['kind']}"] += 1
            for src in s.get("sources") or []:
                c[f"how:{src.get('how')}"] += 1
                c[f"inferred:{src.get('inferred')}"] += 1
    R["counts"] = dict(c)
    R["coverage_mean"] = round(sum(cov) / len(cov), 3) if cov else None
    R["coverage_min"] = round(min(cov), 3) if cov else None
    R["examples"] = dict(examples)
    return R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--datasets", nargs="*", default=DATASETS)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    check = load_check()
    allr = {}
    for ds in a.datasets:
        R = spot(ds, a.data, a.raw, a.n, a.seed, check)
        allr[ds] = R
        c = R["counts"]
        st = c.get("steps", 0) or 1
        print(f"== {ds}: sampled {R['n_sampled']}/{R['n_records']}  check_fail={c.get('check_fail', 0)} raw_missing={c.get('raw_missing', 0)}")
        print(f"   steps={c.get('steps', 0)} verbatim={c.get('verbatim', 0) / st:.3f} casefold={c.get('verbatim_casefold', 0) / st:.3f} "
              f"alnum={c.get('verbatim_alnum', 0) / st:.3f} partial={c.get('partial', 0) / st:.3f} absent={c.get('absent', 0) / st:.3f} empty={c.get('empty_output', 0) / st:.3f}")
        print(f"   raw coverage mean={R['coverage_mean']} min={R['coverage_min']}")
        print(f"   labels: steps={c.get('label_steps', 0)} unmapped={c.get('label_step_unmapped', 0)} missing={c.get('label_step_missing', 0)} "
              f"agent_match={c.get('label_agent_match', 0)} agent_mismatch={c.get('label_agent_mismatch', 0)}")
        print(f"   leakage: judgment={c.get('label_text_in_visible_judgment', 0)} other={c.get('label_text_in_visible_other', 0)}")
        print(f"   hygiene: phase_unknown={c.get('phase_unknown', 0) / st:.3f} sources_none={c.get('sources_none', 0) / st:.3f} "
              f"very_long={c.get('very_long_output', 0)} repeat_consecutive={c.get('repeat_consecutive', 0)}")
        print("   empty by kind:", {k: v for k, v in c.items() if k.startswith("empty_output:")})
        print("   kinds/how:", {k: v for k, v in c.items() if k.startswith(("kind:", "how:", "inferred:"))})
    json.dump(allr, open(os.path.join(a.out, "spotcheck.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
