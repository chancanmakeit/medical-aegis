#!/usr/bin/env python3
"""Branching pilot driver (v10 round 16; design issue round 43 + MHT round 61).

1 branch + 1 control per candidate point. Step t: natural resampling at the original temperature (0.7,
mode (a)); every step that reads step t: temperature 0, in both arms; everything else replayed from the
record. Flip = branch and control end with a different final answer. No flip = "undetermined" (never a
negative). Controls are re-run (rep 1) on all flipped points and on a random share of the rest, to measure
how deterministic temperature 0 is (the chance-flip baseline).

  python scripts/branch_pilot.py select  --fw llm_debate --n 20 --out <dir>
  python scripts/branch_pilot.py select_strat --fw llm_debate --out <dir>                 # plan A (v11)
  python scripts/branch_pilot.py deps    --fw llm_debate --dir <dir>                      # offline, mock
  python scripts/branch_pilot.py run     --fw llm_debate --dir <dir> --arm branch  --pass 0 --upstream mock|real
  python scripts/branch_pilot.py run     --fw llm_debate --dir <dir> --arm control --pass 0 --rep 1 --only <qids>
  python scripts/branch_pilot.py analyze --dir <dir> [--fw ...]

Candidates (rule recall): llm steps whose stated answer letter is wrong, in a run that ends wrong;
up to 3 per run (the first, middle and last such step), pass p = the p-th candidate of each run.
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RECORDED = "/home/claude/anchor_runs/{fw}__normal.jsonl"
# backbone profiles (--backbone); "anchor" = the llama-4-maverick name on aihubmix (served as gemma-4-31B-it-turbo)
BACKBONES = {
    "anchor": {"recorded": "/home/claude/anchor_runs/{fw}__normal.jsonl", "model": "llama-4-maverick",
               "yaml_dir": "experiments/fm_injection/anchor", "upstream": "https://aihubmix.com/v1",
               "key_env": "AIHUBMIX_API_KEY", "price": (0.27e-6, 0.85e-6),
               "dataset": os.path.join(REPO, "datasets/data/anchor_medxpertqa100.json")},
    # gemini batch (v11 r6): xiaojingai endpoint; cost reported at the Google list price (an upper bound)
    "gemini": {"recorded": "/home/claude/gemini_runs/{fw}__normal_eval.jsonl", "model": "gemini-2.5-flash-lite",
               "yaml_dir": "experiments/fm_injection/gemini", "upstream": "https://open.xiaojingai.com/v1",
               "key_env": "XIAOJINGAI_GEMINI_API_KEY", "price": (0.10e-6, 0.40e-6),
               "dataset": os.path.join(REPO, "datasets/data/pools_v1/eval.json")},
}
MODEL, YAML_DIR, UPSTREAM, KEY_ENV = "llama-4-maverick", "experiments/fm_injection/anchor", "https://aihubmix.com/v1", "AIHUBMIX_API_KEY"
DATASET = os.path.join(REPO, "datasets/data/anchor_medxpertqa100.json")
MAA_IDS = {"medxpertqa_text_1499", "medxpertqa_text_1939"}     # MAA overlap (labels.maa_overlap)
LETTER = re.compile(r"(?:Correct Option|Final answer|Final Answer|Answer|answer is)\s*[:\-]?\s*\**\s*\(?([A-J])\b\)?")
P_IN, P_OUT = 0.27e-6, 0.85e-6
NO_ANSWER_PHASES = ("recruitment", "expert_gathering", "select_speaker")   # steps that do not state an answer


def letter(text):
    m = LETTER.findall(text or "")
    return m[-1] if m else None


ESI = re.compile(r"ESI\s*level\s*[:=]?\s*\**\s*([1-5])\b", re.I)


def _classes(r):
    g = r.get("ground_truth")
    if isinstance(g, str):
        try:
            import ast
            g = ast.literal_eval(g)
        except (ValueError, SyntaxError):
            g = {}
    return (g or {}).get("classes") or [], (g or {}).get("aliases") or {}


def final_answer(r, text=None):
    """Final answer of a run (or of one step's text) as a comparable string: the option letter for MCQ,
    the ESI level for triage, the class name for MAM-style classification ("NONE" handled by callers)."""
    text = r.get("response") if text is None else text
    classes, aliases = _classes(r)
    if classes and all(c in "12345" for c in classes):
        m = ESI.findall(text or "")
        return m[-1] if m else None
    if classes and not all(len(c) == 1 for c in classes):
        low = (text or "").lower()
        best, pos = None, -1
        for c in classes:
            for name in [c] + list(aliases.get(c) or []):
                i = low.rfind(name.lower())
                if i > pos:
                    best, pos = c, i
        return best
    return letter(text)


def gold(r):
    g = r.get("ground_truth")
    if isinstance(g, str):
        m = re.search(r"'correct_answer': '([A-J])'", g)
        return m.group(1) if m else r.get("answer")
    if isinstance(g, dict):
        return g.get("correct_answer")
    return r.get("answer")


def recorded(fw, run_index=0):
    out = {}
    for line in open(RECORDED.format(fw=fw), encoding="utf-8"):
        r = json.loads(line)
        if int(r["run_index"]) == run_index:
            out[r["id"]] = r
    return out


def recorded_all(fw):
    """{(qid, run_index): record} over all K recorded normal runs."""
    out = {}
    for line in open(RECORDED.format(fw=fw), encoding="utf-8"):
        r = json.loads(line)
        out[(r["id"], int(r["run_index"]))] = r
    return out


def rec_of(allrec, c):
    return allrec[(c["qid"], int(c.get("run_index", 0)))]


def llm_steps(r):
    return [s for s in r["injection_log"]["conversation_history"] if isinstance(s.get("input_messages"), list)]


def cmd_select(a):
    os.makedirs(a.out, exist_ok=True)
    rec = recorded(a.fw)
    order = [d["id"] for d in json.load(open(DATASET))]
    rows = []
    for qid in order:
        r = rec.get(qid)
        if r is None or qid in MAA_IDS or r.get("is_correct") is not False:
            continue
        g = gold(r)
        h = llm_steps(r)
        wrong = [i for i, s in enumerate(h) if not str(s.get("phase", "")).startswith(NO_ANSWER_PHASES)
                 and letter(s.get("content")) not in (None, g)]
        if not wrong:
            continue
        picks = sorted({wrong[0], wrong[len(wrong) // 2], wrong[-1]})
        for p, i in enumerate(picks):
            rows.append({"fw": a.fw, "qid": qid, "pass": p, "t": i, "n_steps": len(h), "t_step_id": h[i]["step_id"],
                         "agent": h[i].get("agent_name"), "phase": h[i].get("phase"), "round": h[i].get("round"),
                         "t_letter": letter(h[i].get("content")), "gold": g,
                         "recorded_final": letter(r.get("response")), "n_wrong_steps": len(wrong)})
        if len({x["qid"] for x in rows}) >= a.n:
            break
    with open(os.path.join(a.out, f"{a.fw}_candidates.jsonl"), "w") as f:
        for x in rows:
            f.write(json.dumps(x) + "\n")
    print(f"{a.fw}: {len({x['qid'] for x in rows})} runs, {len(rows)} candidate points, passes {Counter(x['pass'] for x in rows)}")


# Plan A (v11, issue #1 rounds 46-48): llm_debate round-1 agents only, all K recorded runs, stratified by
# speaker position x peer support (round-1 peers that state the gold letter, 0 or >= 1), so position and
# peer support are not confounded. Main points: wrong letter in runs that end wrong. Control candidates
# (MHT r64 cont.): right letter in runs that end wrong, and right letter in runs that end right (right ->
# wrong direction). Letter-less steps are not candidates. Aggregator / D(t)-empty points are excluded.
PLAN_A = [  # (run_end, letter_status, n per position with peers_right == 0, n per position with >= 1)
    ("end_wrong", "wrong", 15, 15),
    ("end_wrong", "right", 7, 8),
    ("end_right", "right", 5, 10),
]
PLAN_A_RULE = ("plan A v1: llm_debate round-1 agent steps, all K=3 recorded runs, MAA overlap excluded; per "
               "speaker position: wrong-letter in wrong-ending runs 15 + 15, right-letter in wrong-ending runs "
               "7 + 8, right-letter in right-ending runs 5 + 10 (peers right 0 / >= 1); seed 0")


def cmd_select_strat(a):
    """Stratified candidates (plan A). One batch ('pass') = one run_index, distinct questions."""
    os.makedirs(a.out, exist_ok=True)
    assert a.fw == "llm_debate", "plan A is defined for llm_debate round 1"
    rng = random.Random(0)
    pools = defaultdict(list)
    for (qid, ri), r in sorted(recorded_all(a.fw).items()):
        if qid in MAA_IDS or r.get("is_correct") is None:
            continue
        g, h = gold(r), llm_steps(r)
        r1 = [i for i, s in enumerate(h) if s.get("round") == 1]
        if len(r1) != 3:
            continue
        L = [letter(h[i].get("content")) for i in r1]
        end = "end_right" if r["is_correct"] else "end_wrong"
        for p, i in enumerate(r1):
            if L[p] is None:
                continue
            status = "right" if L[p] == g else "wrong"
            peers = sum(L[j] == g for j in range(3) if j != p)
            pools[(end, status, p, min(peers, 1))].append(
                {"fw": a.fw, "qid": qid, "run_index": ri, "t": i, "n_steps": len(h), "t_step_id": h[i]["step_id"],
                 "agent": h[i].get("agent_name"), "phase": h[i].get("phase"), "round": 1, "position": p,
                 "t_letter": L[p], "gold": g, "recorded_final": letter(r.get("response")), "run_end": end,
                 "letter_status": status, "peers_right": peers, "rule": PLAN_A_RULE})
    rows = []
    for end, status, n0, n1 in PLAN_A:
        for p in range(3):
            for peer, n in ((0, n0), (1, n1)):
                pool = pools[(end, status, p, peer)]
                if len(pool) < n:
                    sys.exit(f"pool {(end, status, p, peer)} has {len(pool)} < {n}")
                rows += rng.sample(pool, n)
    # batches: one run_index each, a question at most once per batch
    batches = []
    for c in sorted(rows, key=lambda c: (c["run_index"], c["qid"], c["position"])):
        for b in batches:
            if b["ri"] == c["run_index"] and c["qid"] not in b["q"]:
                break
        else:
            b = {"ri": c["run_index"], "q": set(), "n": 0, "id": len(batches)}
            batches.append(b)
        b["q"].add(c["qid"]); b["n"] += 1
        c["pass"] = b["id"]
    with open(os.path.join(a.out, f"{a.fw}_candidates.jsonl"), "w") as f:
        for c in sorted(rows, key=lambda c: (c["pass"], c["qid"])):
            f.write(json.dumps(c) + "\n")
    print(f"{a.fw}: {len(rows)} candidate points in {len(batches)} batches "
          f"{[(b['id'], b['ri'], b['n']) for b in batches]}; strata "
          f"{dict(Counter((c['run_end'], c['letter_status'], c['position'], min(c['peers_right'], 1)) for c in rows))}")


ALL_STEPS_RULE = ("eval set v1: every LLM step of each wrong-ending normal run (all K recorded runs), aggregator / "
                  "last step included (its D(t) is empty: single-step resampling baseline); batch = step index t")


def cmd_select_all(a):
    """Every LLM step of every wrong-ending recorded run (MHT r83: within-trajectory ranking needs >= 4 points per run).
    One batch ('pass') = one (run_index, t) so that a question appears once per batch."""
    os.makedirs(a.out, exist_ok=True)
    rows = []
    for (qid, ri), r in sorted(recorded_all(a.fw).items()):
        if qid in MAA_IDS or r.get("is_correct") is not False or r.get("status") != "success":
            continue
        if a.limit and len({(x["qid"], x["run_index"]) for x in rows}) >= a.limit:
            break
        g, h = gold(r), llm_steps(r)
        for i, s in enumerate(h):
            L = final_answer(r, s.get("content"))
            rows.append({"fw": a.fw, "qid": qid, "run_index": ri, "t": i, "n_steps": len(h), "t_step_id": s["step_id"],
                         "agent": s.get("agent_name"), "phase": s.get("phase"), "round": s.get("round"),
                         "t_letter": L, "gold": g, "recorded_final": final_answer(r), "run_end": "end_wrong",
                         "letter_status": "none" if L is None else ("right" if L == g else "wrong"), "rule": ALL_STEPS_RULE})
    # one batch = one (run_index, t) and distinct question TEXTS: the replay server keys requests by their
    # text (+ attached images), so two questions with the same text in one batch (Kvasir-VQA-x1: "Is there
    # any abnormality observed in this image?") would swap their text-only replies (e.g. the recruiter's)
    text = {qid: rec_q.get("query") for (qid, _), rec_q in recorded_all(a.fw).items()}
    seen = Counter()
    for c in sorted(rows, key=lambda c: (c["run_index"], c["t"], c["qid"])):
        # with --sample_keys the replay key carries the sample id (one wrapper/MAS per sample in main.py), so equal
        # texts may share a batch (MAM: every recording has the same prompt; text batching gave 1 question/batch)
        k = (c["run_index"], c["t"], c["qid"] if SAMPLE_KEYS else text.get(c["qid"]))
        c["_sub"] = seen[k]
        seen[k] += 1
    keys = sorted({(c["run_index"], c["t"], c["_sub"]) for c in rows})
    bid = {k: i for i, k in enumerate(keys)}
    for c in rows:
        c["pass"] = bid[(c["run_index"], c["t"], c.pop("_sub"))]
    with open(os.path.join(a.out, f"{a.fw}_candidates.jsonl"), "w") as f:
        for c in sorted(rows, key=lambda c: (c["pass"], c["qid"])):
            f.write(json.dumps(c) + "\n")
    print(f"{a.fw}: {len({(c['qid'], c['run_index']) for c in rows})} parent runs, {len(rows)} candidate points, "
          f"{len(keys)} batches")


def subset_dataset(qids, path):
    d = [x for x in json.load(open(DATASET)) if x["id"] in qids]
    json.dump(d, open(path, "w"), ensure_ascii=False)
    return len(d)


def write_cfg(fw, port, wd, tag):
    import yaml
    api = os.path.join(wd, f"_api_{tag}.json")
    json.dump({MODEL: {"model_list": [{"model_name": MODEL, "model_url": f"http://127.0.0.1:{port}/v1",
                                                   "api_key": "via-branch-server"}], "max_workers_per_model": 2}}, open(api, "w"))
    c = yaml.safe_load(open(os.path.join(REPO, f"{YAML_DIR}/{fw}_normal.yaml")))
    c["llm_config"].update(model_name=MODEL, model_url=f"http://127.0.0.1:{port}/v1", api_key="via-branch-server")
    cfg = os.path.join(wd, f"_cfg_{tag}.yaml")
    open(cfg, "w").write(yaml.safe_dump(c, sort_keys=False, allow_unicode=True))
    return api, cfg


MAX_WORKERS = 16
SAMPLE_KEYS = False


def run_main(fw, api, cfg, ds, out, log, run_index=0):
    if os.path.exists(out):      # main.py resumes from an existing output file
        os.remove(out)
    env = {k: v for k, v in os.environ.items() if k not in ("AIHUBMIX_API_KEY", "OPENAI_API_KEY", KEY_ENV)}
    if SAMPLE_KEYS:
        env["AEGIS_SAMPLE_HEADER"] = "1"
    cmd = [sys.executable, "main.py", "--method_name", fw, "--experiment_config", cfg, "--model_api_config", api,
           "--model_name", MODEL, "--dataset_file", ds, "--test_dataset_name", "medxpertqa_text",
           "--output_path", out, "--model_temperature", "0.7", "--model_max_tokens", "4096", "--max_workers", str(MAX_WORKERS),
           "--num_runs", "1", "--run_index_start", str(run_index), "--no_inject"]
    with open(log, "w") as lf:
        return subprocess.run(cmd, cwd=REPO, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode


def start_server(args, log_path, srv_log, env=None):
    p = subprocess.Popen([sys.executable] + args, cwd=REPO, stdout=open(srv_log, "w"), stderr=subprocess.STDOUT, env=env)
    time.sleep(3)
    return p


def cmd_deps(a):
    """D(t) = every later step that reads step t directly or transitively, from the RECORDED read sets
    (`sources` in conversation_history, instrumented at run time). Exact for parsed reads too (e.g. experts
    reading the recruiter's specialty list), which a text perturbation would miss. Both arms regenerate
    exactly D(t) at temperature 0."""
    path = os.path.join(a.dir, f"{a.fw}_candidates.jsonl")
    cands = [json.loads(l) for l in open(path)]
    rec = recorded_all(a.fw)
    for c in cands:
        h = llm_steps(rec_of(rec, c))
        dep = {c["t_step_id"]}
        for s in h[c["t"] + 1:]:
            src = s.get("sources") or []
            src = [x if isinstance(x, str) else x.get("step_id") for x in src]
            if dep & set(src):
                dep.add(s["step_id"])
        c["force_step_ids"] = [s["step_id"] for s in h[c["t"] + 1:] if s["step_id"] in dep]
        c["n_downstream"] = len(h) - c["t"] - 1
    with open(path, "w") as f:
        for c in cands:
            f.write(json.dumps(c) + "\n")
    by = defaultdict(list)
    for c in cands:
        by[(c["pass"], c["phase"].split("/")[0])].append(len(c["force_step_ids"]) / max(1, c["n_downstream"]) if c["n_downstream"] else 0)
    print(a.fw, {k: f"n={len(v)} mean share of downstream in D(t)={sum(v) / len(v):.2f}" for k, v in sorted(by.items())})


def cmd_deps_mock(a):
    """D(t): recorded steps after t that are no longer served from the record once t's reply changes
    (offline: replay_openai_server.py --overrides, misses answered by the mock)."""
    cands = [json.loads(l) for l in open(os.path.join(a.dir, f"{a.fw}_candidates.jsonl"))]
    rec = recorded(a.fw)
    wd = os.path.join(a.dir, "deps"); os.makedirs(wd, exist_ok=True)
    for p in sorted({c["pass"] for c in cands}):
        cp = [c for c in cands if c["pass"] == p]
        ov = os.path.join(wd, f"{a.fw}_p{p}_ov.jsonl")
        with open(ov, "w") as f:
            for c in cp:
                s = next(x for x in llm_steps(rec[c["qid"]]) if x["step_id"] == c["t_step_id"])
                txt = s.get("response") or s.get("content") or ""
                # change BOTH the text and the stated letter: some readers of step t see only the parsed
                # answer (e.g. an aggregator fed the experts' letters), others the full text
                ms = list(LETTER.finditer(txt))
                if ms:
                    m0 = ms[-1]
                    alt = "A" if m0.group(1) != "A" else "B"
                    txt = txt[:m0.start(1)] + alt + txt[m0.end(1):]
                f.write(json.dumps({"qid": c["qid"], "step_id": c["t_step_id"],
                                    "text": txt + "\n\n(Note: on reflection I am less certain about this.)"}) + "\n")
        port = a.port + p
        calls = os.path.join(wd, f"{a.fw}_p{p}_calls.jsonl")
        if os.path.exists(calls):
            os.remove(calls)
        srv = start_server(["scripts/replay_openai_server.py", "--port", str(port), "--run_index", "0", "--results",
                            RECORDED.format(fw=a.fw), "--ids", ",".join(c["qid"] for c in cp), "--log", calls, "--overrides", ov],
                           calls, os.path.join(wd, f"{a.fw}_p{p}_server.log"))
        try:
            ds = os.path.join(wd, f"{a.fw}_p{p}_ds.json"); subset_dataset({c["qid"] for c in cp}, ds)
            api, cfg = write_cfg(a.fw, port, wd, f"{a.fw}_p{p}_deps")
            rc = run_main(a.fw, api, cfg, ds, os.path.join(wd, f"{a.fw}_p{p}_out.jsonl"), os.path.join(wd, f"{a.fw}_p{p}_main.log"))
        finally:
            srv.terminate()
        hit = defaultdict(set)
        for l in open(calls):
            x = json.loads(l)
            if x["hit"]:
                hit[x["qid"]].add(x["step_id"])
        for c in cp:
            h = llm_steps(rec[c["qid"]])
            c["force_step_ids"] = [s["step_id"] for s in h[c["t"] + 1:] if s["step_id"] not in hit[c["qid"]]]
            c["n_downstream"] = len(h) - c["t"] - 1
        print(f"{a.fw} pass {p}: main.py exit {rc}; mean |D(t)| {sum(len(c['force_step_ids']) for c in cp) / max(len(cp), 1):.2f}")
    with open(os.path.join(a.dir, f"{a.fw}_candidates.jsonl"), "w") as f:
        for c in cands:
            f.write(json.dumps(c) + "\n")


def cmd_run(a):
    cands = [json.loads(l) for l in open(os.path.join(a.dir, f"{a.fw}_candidates.jsonl"))]
    cp = [c for c in cands if c["pass"] == a.pass_ and (not a.only or c["qid"] in set(a.only.split(",")))]
    if a.limit:
        cp = cp[:a.limit]
    tag = f"{a.fw}_p{a.pass_}_{a.arm}_rep{a.rep}"
    ris = {int(c.get("run_index", 0)) for c in cp}
    if len(ris) != 1 or len({c["qid"] for c in cp}) != len(cp):
        sys.exit(f"{tag}: a batch needs one run_index and distinct questions (got run_index {ris})")
    ri = ris.pop()
    wd = os.path.join(a.dir, "runs"); os.makedirs(wd, exist_ok=True)
    done_out = os.path.join(wd, f"{tag}_out.jsonl")
    if a.skip_done and os.path.exists(done_out):
        # resumable batches: skip when every expected question is in the output and already stamped
        try:
            got = {r["id"] for r in map(json.loads, open(done_out)) if r.get("branch")}
        except ValueError:
            got = set()
        if {c["qid"] for c in cp} <= got:
            print(f"{tag}: already complete ({len(got)} records), skipped")
            return
    spec = os.path.join(wd, f"{tag}_spec.jsonl")
    with open(spec, "w") as f:
        for c in cp:
            f.write(json.dumps({"qid": c["qid"], "arm": a.arm, "t_step_id": c["t_step_id"],
                                "force_step_ids": c.get("force_step_ids", [])}) + "\n")
    calls = os.path.join(wd, f"{tag}_calls.jsonl")
    if os.path.exists(calls):
        os.remove(calls)
    env = dict(os.environ)
    upstream = "mock"
    if a.upstream == "real":
        for line in open("/home/claude/.mht_api.env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k.replace("export ", "")] = v.strip().strip('"').strip("'")
        upstream = UPSTREAM
    srv = start_server(["scripts/branch_replay_server.py", "--port", str(a.port), "--results", RECORDED.format(fw=a.fw),
                        "--api_key_env", KEY_ENV] + (["--sample_keys"] if a.sample_keys else []) + [
                        "--run_index", str(ri), "--spec", spec, "--log", calls, "--upstream", upstream], calls, os.path.join(wd, f"{tag}_server.log"), env)
    try:
        ds = os.path.join(wd, f"{tag}_ds.json"); subset_dataset({c["qid"] for c in cp}, ds)
        api, cfg = write_cfg(a.fw, a.port, wd, tag)
        rc = run_main(a.fw, api, cfg, ds, os.path.join(wd, f"{tag}_out.jsonl"), os.path.join(wd, f"{tag}_main.log"), ri)
    finally:
        srv.terminate()
    # run identity at the source (issue #1, 2026-11-03): embed a `branch` block in every output record
    import branch_identity
    from replay_openai_server import step_key as replay_key
    out = os.path.join(wd, f"{tag}_out.jsonl")
    reasons = None
    if a.protocol == "v3":
        branch_identity.PROTOCOL_ID = branch_identity.PROTOCOL_ID_V3
        if a.rep > 0:
            reasons = {c["qid"]: ("stage1" if a.rep == 1 else "stage2_disagreement") for c in cp}
    elif a.rep > 0:
        fin = {}
        for arm in ("branch", "control"):
            p0 = os.path.join(wd, f"{a.fw}_p{a.pass_}_{arm}_rep0_out.jsonl")
            for l in open(p0) if os.path.exists(p0) else []:
                r = json.loads(l)
                fin[(arm, r["id"])] = letter(r.get("response"))
        reasons = {c["qid"]: ("flipped_at_rep0" if fin.get(("branch", c["qid"])) != fin.get(("control", c["qid"]))
                              else "random_undetermined") if ("branch", c["qid"]) in fin else "rep0_missing"
                   for c in cp}
    if os.path.exists(out):
        allrec = recorded_all(a.fw)
        for c in cp:      # parent structure, for frameworks whose step sequence can change after t
            ph = llm_steps(rec_of(allrec, c))
            c["parent_step_ids"] = [s["step_id"] for s in ph]
            n_pre = c["t"] + (0 if a.arm == "branch" else 1)
            c["parent_prefix_sha1"] = [branch_identity.sha1(s.get("content")) for s in ph[:n_pre]]
            c["parent_keys"] = [(s["step_id"], replay_key(rec_of(allrec, c), s, a.sample_keys)) for s in ph]
        bad = branch_identity.stamp_file(out, cp, a.arm, a.rep, calls, a.experiment_id or os.path.basename(
            os.path.abspath(a.dir)), reasons, a.fw)
        print(f"{tag}: branch identity stamped; problems {len(bad)}" + (f" e.g. {bad[:3]}" if bad else ""))
    L = [json.loads(l) for l in open(calls)]
    up = [x for x in L if x.get("upstream")]
    cost = sum((x.get("usage") or {}).get("prompt_tokens", 0) * P_IN + (x.get("usage") or {}).get("completion_tokens", 0) * P_OUT for x in up)
    print(f"{tag}: main.py exit {rc}; requests {len(L)} tags {dict(Counter(x['tag'] for x in L))}; "
          f"upstream calls {len(up)}; errors {sum('error' in x for x in L)}; cost ${cost:.4f}")


def auroc_pairs(a_texts, b_texts, groups):
    """Grouped-CV AUROC of a char n-gram logistic regression telling a_texts (label 0) from b_texts (1)."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold
    X = a_texts + b_texts
    y = np.array([0] * len(a_texts) + [1] * len(b_texts))
    g = np.array(groups + groups)
    scores = np.zeros(len(X))
    for tr, te in GroupKFold(n_splits=min(5, len(set(groups)))).split(X, y, g):
        v = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True)
        m = LogisticRegression(max_iter=2000, C=1.0).fit(v.fit_transform([X[i] for i in tr]), y[tr])
        scores[te] = m.predict_proba(v.transform([X[i] for i in te]))[:, 1]
    auc = roc_auc_score(y, scores)
    rng = np.random.default_rng(0)
    qs = sorted(set(groups))
    boots = []
    by_q = {q: np.flatnonzero(g == q) for q in qs}
    for _ in range(1000):
        # cluster bootstrap with replacement: a question drawn k times contributes its rows k times
        # (fixed 2026-11-03; it used to be set(rng.choice(...)), which dropped the multiplicity).
        # CI over fixed out-of-fold scores: it does not include refitting variance.
        idx = np.concatenate([by_q[q] for q in rng.choice(qs, len(qs), replace=True)])
        if len(set(y[idx])) == 2:
            boots.append(roc_auc_score(y[idx], scores[idx]))
    return auc, np.percentile(boots, 2.5), np.percentile(boots, 97.5)


def cmd_analyze(a):
    wd = os.path.join(a.dir, "runs")
    fws = a.fw.split(",") if a.fw else sorted({f.split("_candidates")[0] for f in os.listdir(a.dir) if f.endswith("_candidates.jsonl")})
    tot_cost = 0.0
    for fw in fws:
        cands = {(c["qid"], c["pass"]): c for c in map(json.loads, open(os.path.join(a.dir, f"{fw}_candidates.jsonl")))}
        rec = recorded_all(fw)
        outs = defaultdict(dict)    # (qid, pass) -> {(arm, rep): record}
        calls = []
        for fn in os.listdir(wd):
            m = re.match(rf"{fw}_p(\d+)_(branch|control)_rep(\d+)_out\.jsonl$", fn)
            if m:
                for l in open(os.path.join(wd, fn)):
                    r = json.loads(l)
                    outs[(r["id"], int(m.group(1)))][(m.group(2), int(m.group(3)))] = r
            m = re.match(rf"{fw}_p(\d+)_(branch|control)_rep(\d+)_calls\.jsonl$", fn)
            if m:
                calls += [dict(json.loads(l), _arm=m.group(2), _pass=int(m.group(1))) for l in open(os.path.join(wd, fn))]
        up = [x for x in calls if x.get("upstream")]
        cost = sum((x.get("usage") or {}).get("prompt_tokens", 0) * P_IN + (x.get("usage") or {}).get("completion_tokens", 0) * P_OUT for x in up)
        tot_cost += cost
        res = Counter(); pos = defaultdict(Counter); orig_t, new_t, grp = [], [], []
        examples = []
        for k, o in sorted(outs.items()):
            c = cands.get(k)
            if c is None or ("branch", 0) not in o or ("control", 0) not in o:
                continue
            b, ctl = letter(o[("branch", 0)].get("response")), letter(o[("control", 0)].get("response"))
            flip = b != ctl
            wrong_to_right = (ctl != c["gold"]) and (b == c["gold"])
            ctl_reps = [letter(v.get("response")) for (arm, rep), v in o.items() if arm == "control"]
            stable = len(set(ctl_reps)) == 1
            res["points"] += 1
            res["flip"] += flip
            res["flip_wrong_to_right"] += wrong_to_right
            res["control_rerun"] += len(ctl_reps) > 1
            res["control_rerun_disagree"] += len(ctl_reps) > 1 and not stable
            if flip and len(ctl_reps) > 1:
                res["flip_confirmed"] += stable
            res["control_differs_from_recorded"] += ctl != c["recorded_final"]
            bucket = min(4, int(5 * c["t"] / max(1, c["n_steps"])))
            pos[f"{bucket * 20}-{bucket * 20 + 20}%"]["points"] += 1
            pos[f"{bucket * 20}-{bucket * 20 + 20}%"]["flip"] += flip
            pos[c["phase"]]["points"] += 1
            pos[c["phase"]]["flip"] += flip
            # step t: recorded text vs its natural resample (same slot)
            bs = next((s for s in o[("branch", 0)]["injection_log"]["conversation_history"] if s.get("step_id") == c["t_step_id"]), None)
            os_ = next(s for s in llm_steps(rec_of(rec, c)) if s["step_id"] == c["t_step_id"])
            if bs is not None and bs.get("content") and bs.get("content") != os_.get("content"):
                orig_t.append(os_["content"]); new_t.append(bs["content"]); grp.append(c["qid"])
            if flip and len(examples) < 3:
                examples.append({"qid": c["qid"], "t_step": c["t_step_id"], "phase": c["phase"], "t_letter": c["t_letter"],
                                 "t_resample_letter": letter(bs.get("content")) if bs else None,
                                 "control_final": ctl, "branch_final": b, "gold": c["gold"]})
        n = max(res["points"], 1)
        print(f"== {fw}: points {res['points']}  flip {res['flip']} ({res['flip'] / n:.2f})  undetermined {res['points'] - res['flip']}  "
              f"wrong->right {res['flip_wrong_to_right']}  | controls re-run {res['control_rerun']}, disagree {res['control_rerun_disagree']}  "
              f"| flips confirmed by a 2nd control {res['flip_confirmed']}  | control final != recorded final {res['control_differs_from_recorded']}")
        print("   position / phase:", {k: f"{v['flip']}/{v['points']}" for k, v in sorted(pos.items())})
        fps = Counter(x.get("system_fingerprint") for x in up)
        print(f"   upstream calls {len(up)} by tag {dict(Counter(x['tag'] for x in up))}; models {dict(Counter(x.get('model') for x in up))}; "
              f"system_fingerprint {dict(fps)}; errors {sum('error' in x for x in calls)}; cost ${cost:.4f}")
        if len(orig_t) >= 10:
            auc, lo, hi = auroc_pairs(orig_t, new_t, grp)
            print(f"   same-slot AUROC recorded step t vs its resample (char 2-5, grouped CV): {auc:.3f} [{lo:.3f}, {hi:.3f}] n={len(orig_t)} pairs")
        for e in examples:
            print("   flip example:", e)
    print(f"TOTAL upstream cost ${tot_cost:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "select_strat", "select_all", "deps", "deps_mock", "run", "analyze"])
    ap.add_argument("--fw")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out")
    ap.add_argument("--dir")
    ap.add_argument("--arm", choices=["branch", "control"])
    ap.add_argument("--pass", dest="pass_", type=int, default=0)
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--upstream", choices=["mock", "real"], default="mock")
    ap.add_argument("--port", type=int, default=18200)
    ap.add_argument("--experiment_id", default=None, help="branch identity experiment id (default: basename of --dir)")
    ap.add_argument("--backbone", choices=sorted(BACKBONES), default="anchor")
    ap.add_argument("--protocol", choices=["v2", "v3"], default="v2")
    ap.add_argument("--recorded", default=None, help="recorded normal runs (overrides the backbone profile; {fw} allowed)")
    ap.add_argument("--dataset", default=None, help="dataset JSON of the recorded runs (overrides the backbone profile)")
    ap.add_argument("--max_workers", type=int, default=16)
    ap.add_argument("--skip_done", action="store_true", help="skip a batch whose output is complete and stamped")
    ap.add_argument("--sample_keys", action="store_true",
                    help="replay keys include the sample id (frameworks / datasets whose samples send identical text)")
    a = ap.parse_args()
    global RECORDED, MODEL, YAML_DIR, UPSTREAM, KEY_ENV, P_IN, P_OUT, DATASET, MAX_WORKERS, SAMPLE_KEYS
    MAX_WORKERS = a.max_workers
    SAMPLE_KEYS = a.sample_keys
    bb = BACKBONES[a.backbone]
    DATASET = a.dataset or bb["dataset"]
    if a.recorded:
        bb = dict(bb, recorded=a.recorded)
    RECORDED, MODEL, YAML_DIR, UPSTREAM, KEY_ENV = bb["recorded"], bb["model"], bb["yaml_dir"], bb["upstream"], bb["key_env"]
    P_IN, P_OUT = bb["price"]
    {"select": cmd_select, "select_strat": cmd_select_strat, "select_all": cmd_select_all, "deps": cmd_deps, "deps_mock": cmd_deps_mock, "run": cmd_run, "analyze": cmd_analyze}[a.cmd](a)


if __name__ == "__main__":
    main()
