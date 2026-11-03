#!/usr/bin/env python3
"""Run identity for branching runs (branch / control arms): stamping, sidecar backfill, validation.

Why (issue #1, GPT 6596651619 / Muse 6596804700, agreed by MHT round 82): the branch and control outputs
of scripts/branch_pilot.py carry the same framework / model / dataset / id / run_mode / run_index as each
other AND as their recorded parent normal run, so the generic exporter gave them one run_id. Each record
now gets a `branch` block (embedded by branch_pilot.py at run time; a sidecar for the 2026-10-26 pilot):

  experiment_id, protocol_id
  parent_run_id        exporter run_id of the recorded normal run that was branched (same run_index)
  candidate_step_id    = t_step_id, the stable key of step t in the parent run
  candidate_index      {"t": int, "base": 0, "sequence": "llm_steps"}; llm_steps = entries of
                       injection_log.conversation_history whose input_messages is a list (environment
                       events are not counted). Position only; join on candidate_step_id.
  pair_id              parent_run_id | candidate_step_id | protocol_id. A GROUP: one branch rep 0, one
                       control rep 0, and any further control repetitions.
  arm, repetition      "branch" | "control", 0-based
  regenerated_step_ids steps generated upstream in this run (branch: t and D(t); control: D(t));
                       validated against the call log: every upstream output equals exactly one step
  replayed_step_ids    every other llm step, served from the parent record
  evidence             per regenerated step: call-log tag, temperature, sha1 of the step text
  selection            candidate rule; for control repetitions >= 1 why this point was re-run
  pass                 index of the candidate within its run under the selection rule (first / middle / last)

None of this is model input: the exporter puts it under labels.branch, and renderers must not read it.

  python scripts/branch_identity.py backfill   # writes data_runs/branch_pilot_2026-10-26/branch_sidecar.jsonl
  python scripts/branch_identity.py validate --sidecar <file>
"""
import argparse
import glob
import gzip
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PILOT_DIR = os.path.join(REPO, "data_runs/branch_pilot_2026-10-26")
PILOT_CANDS = os.path.join(REPO, "docs/requests/samples/round16_2026-10-26")
PILOT_EXPERIMENT = "branch-pilot-2026-10-26"
PROTOCOL_ID = "branch-resample-t-at-0.7_descendants-at-0_replay-rest_v1"
CANDIDATE_RULE = ("wrong-letter answer steps of runs that end wrong; first / middle / last per run "
                  "(pass 0 / 1 / 2); MAA-overlap questions excluded")
REP_RULE = ("control repetition 1: every point that flipped at repetition 0, plus a random share of the "
            "undetermined points (rep1_plan.txt)")
FILE_RE = re.compile(r"(?P<fw>[a-z_]+?)_p(?P<pass>\d+)_(?P<arm>branch|control)_rep(?P<rep>\d+)_out\.jsonl(\.gz)?$")
UPSTREAM_TAGS = ("t_resample", "forced_dependent", "miss", "t_kept_missing")


def sha1(text):
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()


def open_any(path):
    return gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")


def llm_steps(r):
    return [s for s in r["injection_log"]["conversation_history"] if isinstance(s.get("input_messages"), list)]


def normal_run_id(rec, fw=None):
    """Exporter run_id of the recorded normal run a branch record descends from (same run_index:
    branch_pilot.py replays run k as main.py run k).
    Must stay identical to scripts/export_schema_v1.convert() for run_mode normal."""
    fw = fw or rec.get("framework")
    model = (rec.get("model") or {}).get("name") or "unknown-model"
    return f"{fw}|{model}|{rec.get('dataset') or 'unknown'}|{rec.get('id')}|normal|r{int(rec.get('run_index') or 0)}"


def branch_run_id(b):
    return f"{b['pair_id']}|{b['arm']}|rep{b['repetition']}"


def regenerated_from_calls(rec, calls):
    """Map every upstream call of this question to the step whose text it produced.
    Returns (regenerated step ids in order, evidence, problems)."""
    by_text = defaultdict(list)
    for s in llm_steps(rec):
        by_text[(s.get("content") or "").strip()].append(s["step_id"])
    regen, ev, probs = [], {}, []
    for c in calls:
        if not c.get("upstream"):
            continue
        ids = [i for i in by_text.get((c.get("output") or "").strip(), []) if i not in ev]
        if not ids:
            probs.append(f"upstream call {c.get('key', '')[:10]} ({c.get('tag')}) matches no step")
            continue
        sid = ids[0]
        regen.append(sid)
        ev[sid] = {"tag": c.get("tag"), "temperature": c.get("temperature"), "text_sha1": sha1(c.get("output"))}
    return regen, ev, probs


def make_block(rec, cand, arm, rep, regen, evidence, experiment_id, rep_reason=None, fw=None):
    parent = normal_run_id(rec, fw)
    h = llm_steps(rec)
    order = [s["step_id"] for s in h]
    regen_sorted = [s for s in order if s in set(regen)]
    b = {
        "experiment_id": experiment_id,
        "protocol_id": PROTOCOL_ID,
        "parent_run_id": parent,
        "candidate_step_id": cand["t_step_id"],
        "candidate_index": {"t": cand["t"], "base": 0, "sequence": "llm_steps"},
        "pass": cand["pass"],
        "pair_id": f"{parent}|{cand['t_step_id']}|{PROTOCOL_ID}",
        "arm": arm,
        "repetition": rep,
        "descendant_step_ids": list(cand.get("force_step_ids") or []),
        "regenerated_step_ids": regen_sorted,
        "replayed_step_ids": [s for s in order if s not in set(regen)],
        "evidence": evidence,
        "selection": {"candidate_rule": cand.get("rule") or CANDIDATE_RULE,
                      **{k: cand[k] for k in ("position", "peers_right", "letter_status", "run_end") if k in cand}},
    }
    if rep > 0:
        b["selection"]["repetition_rule"] = REP_RULE
        b["selection"]["repetition_reason"] = rep_reason
    return b


def block_problems(b, rec=None):
    """Invariants of one branch block (and of the record it describes, if given)."""
    p = []
    for k in ("experiment_id", "protocol_id", "parent_run_id", "candidate_step_id", "pair_id", "arm", "repetition"):
        if b.get(k) in (None, ""):
            p.append(f"branch.{k} missing")
    if b.get("arm") not in ("branch", "control"):
        p.append(f"branch.arm {b.get('arm')!r}")
    if not isinstance(b.get("repetition"), int) or b["repetition"] < 0:
        p.append("branch.repetition must be an int >= 0")
    if b.get("pair_id") != f"{b.get('parent_run_id')}|{b.get('candidate_step_id')}|{b.get('protocol_id')}":
        p.append("branch.pair_id is not parent|candidate|protocol")
    regen, rep = set(b.get("regenerated_step_ids") or []), set(b.get("replayed_step_ids") or [])
    if regen & rep:
        p.append("a step is both regenerated and replayed")
    exp = set(b.get("descendant_step_ids") or []) | ({b.get("candidate_step_id")} if b.get("arm") == "branch" else set())
    if regen != exp:
        p.append(f"regenerated {sorted(regen)} != expected {sorted(exp)}")
    if b.get("arm") == "control" and b.get("candidate_step_id") not in rep:
        p.append("control arm must replay step t")
    if set(b.get("evidence") or {}) != regen:
        p.append("evidence does not cover exactly the regenerated steps")
    if b.get("repetition", 0) > 0 and b.get("arm") == "control" and not (b.get("selection") or {}).get("repetition_reason"):
        p.append("control repetition >= 1 without a recorded selection reason")
    if rec is not None:
        h = llm_steps(rec)
        ids = [s["step_id"] for s in h]
        if regen | rep != set(ids):
            p.append("regenerated + replayed do not cover the record's llm steps")
        ci = b.get("candidate_index") or {}
        if not (0 <= ci.get("t", -1) < len(h)) or h[ci["t"]]["step_id"] != b.get("candidate_step_id"):
            p.append("candidate_index.t does not point at candidate_step_id")
        text = {s["step_id"]: s.get("content") for s in h}
        for sid, e in (b.get("evidence") or {}).items():
            if sid in text and e.get("text_sha1") != sha1(text[sid]):
                p.append(f"evidence sha1 mismatch on {sid}")
    return p


def stamp_file(out_path, cands, arm, rep, calls_path, experiment_id, rep_reasons=None, fw=None):
    """Embed `branch` into every record of a fresh branch_pilot output file (called by branch_pilot.py)."""
    calls = defaultdict(list)
    for l in open(calls_path, encoding="utf-8"):
        c = json.loads(l)
        calls[c.get("qid")].append(c)
    by_q = {c["qid"]: c for c in cands}
    rows, probs = [], []
    for l in open(out_path, encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        regen, ev, pr = regenerated_from_calls(r, calls[r["id"]])
        b = make_block(r, by_q[r["id"]], arm, rep, regen, ev, experiment_id,
                       (rep_reasons or {}).get(r["id"]), fw)
        pr += block_problems(b, r)
        probs += [f"{r['id']}: {x}" for x in pr]
        r["branch"] = b
        rows.append(r)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return probs


def load_sidecar(path):
    """{(source file basename, record id): branch block}"""
    out = {}
    for l in open(path, encoding="utf-8"):
        x = json.loads(l)
        key = (x["source_file"], x["record_id"])
        if key in out:
            raise ValueError(f"sidecar {path}: duplicate key {key}")
        out[key] = x["branch"]
    return out


def is_branch_output(path):
    return bool(FILE_RE.search(os.path.basename(path)))


# ------------------------------------------------------------------ backfill of the 2026-10-26 pilot
def cmd_backfill(a):
    cands = {}
    for fw in ("llm_debate", "mdagents"):
        for l in open(os.path.join(a.cands_dir, f"{fw}_candidates.jsonl")):
            x = json.loads(l)
            cands[(fw, x["pass"], x["qid"])] = x
    files = sorted(glob.glob(os.path.join(a.runs_dir, "*_out.jsonl.gz")))
    finals = {}
    for f in files:
        m = FILE_RE.search(os.path.basename(f))
        if m["rep"] == "0":
            for l in open_any(f):
                r = json.loads(l)
                finals[(m["fw"], int(m["pass"]), m["arm"], r["id"])] = r.get("response")
    import importlib
    sys.path.insert(0, HERE)
    letter = importlib.import_module("branch_pilot").letter
    rows, probs = [], []
    for f in files:
        m = FILE_RE.search(os.path.basename(f))
        fw, p, arm, rep = m["fw"], int(m["pass"]), m["arm"], int(m["rep"])
        calls = defaultdict(list)
        for l in open(os.path.join(a.calls_dir, f"{fw}_p{p}_{arm}_rep{rep}_calls.jsonl"), encoding="utf-8"):
            c = json.loads(l)
            calls[c.get("qid")].append(c)
        for l in open_any(f):
            r = json.loads(l)
            reason = None
            if rep > 0:
                flipped = letter(finals[(fw, p, "branch", r["id"])]) != letter(finals[(fw, p, "control", r["id"])])
                reason = "flipped_at_rep0" if flipped else "random_undetermined"
            regen, ev, pr = regenerated_from_calls(r, calls[r["id"]])
            b = make_block(r, cands[(fw, p, r["id"])], arm, rep, regen, ev, PILOT_EXPERIMENT, reason, fw)
            pr += block_problems(b, r)
            probs += [f"{os.path.basename(f)}:{r['id']}: {x}" for x in pr]
            rows.append({"source_file": os.path.basename(f), "record_id": r["id"], "branch": b})
    with open(a.out, "w", encoding="utf-8") as fo:
        for x in rows:
            fo.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"backfill: {len(files)} files, {len(rows)} records -> {a.out}; problems {len(probs)}")
    for x in probs[:20]:
        print("  !!", x)
    sys.exit(1 if probs else 0)


def validate(blocks, parents=None):
    """Cross-record checks over a set of branch blocks. Returns (problems, summary)."""
    probs = []
    rid = Counter(branch_run_id(b) for b in blocks)
    probs += [f"duplicate branch run_id {k} x{n}" for k, n in rid.items() if n > 1]
    groups = defaultdict(list)
    for b in blocks:
        groups[b["pair_id"]].append(b)
        probs += block_problems(b)
    n_full = 0
    for pid, g in groups.items():
        arms = Counter((b["arm"], b["repetition"]) for b in g)
        if arms[("branch", 0)] != 1 or arms[("control", 0)] != 1:
            probs.append(f"{pid}: needs exactly one branch rep0 and one control rep0, has {dict(arms)}")
        else:
            n_full += 1
        if len({b["candidate_index"]["t"] for b in g}) != 1:
            probs.append(f"{pid}: arms disagree on candidate index")
        if any(b["arm"] == "branch" and b["repetition"] > 0 for b in g):
            probs.append(f"{pid}: branch repetitions are not part of protocol v1")
    if parents is not None:
        miss = sorted({b["parent_run_id"] for b in blocks} - set(parents))
        probs += [f"parent run missing: {x}" for x in miss]
    summary = {"records": len(blocks), "unique_run_ids": len(rid), "pairs": len(groups), "complete_rep0_pairs": n_full,
               "extra_control_reps": sum(1 for b in blocks if b["arm"] == "control" and b["repetition"] > 0),
               "rep_reasons": dict(Counter((b.get("selection") or {}).get("repetition_reason") for b in blocks
                                           if b["repetition"] > 0))}
    return probs, summary


def cmd_validate(a):
    sc = load_sidecar(a.sidecar)
    probs, summary = validate(list(sc.values()))
    print(json.dumps(summary, indent=1))
    for x in probs[:20]:
        print("  !!", x)
    sys.exit(1 if probs else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--runs_dir", default=PILOT_DIR)
    b.add_argument("--cands_dir", default=PILOT_CANDS)
    b.add_argument("--calls_dir", default="/home/claude/branch_pilot/runs",
                   help="full call logs with output texts (HF workspace snapshot; the repo copy has no texts)")
    b.add_argument("--out", default=os.path.join(PILOT_DIR, "branch_sidecar.jsonl"))
    v = sub.add_parser("validate")
    v.add_argument("--sidecar", default=os.path.join(PILOT_DIR, "branch_sidecar.jsonl"))
    a = ap.parse_args()
    {"backfill": cmd_backfill, "validate": cmd_validate}[a.cmd](a)


if __name__ == "__main__":
    main()
