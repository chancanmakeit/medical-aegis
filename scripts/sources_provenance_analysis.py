"""Sources provenance analysis for MHT r41 (anchor export).

1. `how` distribution per framework.
2. Per (framework, phase): how predictable the read set is from the phase alone.
   pattern = sorted tuple of (phase, round-offset, agent_id) of the sources;
   mode share = share of the most common pattern.
   'choice' steps (MHT r41-suppl criterion): candidates = earlier LLM steps in the same
   phase(s) as the true sources; the step reads a strict subset of them.
3. Does injection change sources? Inject run vs normal run (run 0) of the same question,
   steps keyed by (agent_id, phase, round, k-th occurrence), sources mapped to keys.
"""
import json
import sys
from collections import Counter, defaultdict

path = sys.argv[1]
how = defaultdict(Counter)
pat = defaultdict(Counter)
choice = Counter()
nsteps = Counter()
normal_keyed = {}
inj_runs = []


def keyed(r):
    occ = Counter()
    sid2key = {}
    out = {}
    for s in r["steps"]:
        if s.get("kind") != "llm":
            continue
        k0 = (s.get("agent_id"), s.get("phase"), s.get("round"))
        occ[k0] += 1
        key = k0 + (occ[k0],)
        sid2key[s["step_id"]] = key
        out[key] = s
    res = {}
    for key, s in out.items():
        res[key] = tuple(sorted(str(sid2key.get(x["step_id"], x["step_id"])) for x in s.get("sources") or []))
    return res


for l in open(path):
    r = json.loads(l)
    fw = r["framework"]
    if r["run_mode"] == "normal":
        steps = [s for s in r["steps"] if s.get("kind") == "llm"]
        by = {s["step_id"]: s for s in steps}
        for i, s in enumerate(steps):
            src = s.get("sources") or []
            for x in src:
                how[fw][x["how"]] += 1
            ph = s.get("phase")
            nsteps[(fw, ph)] += 1
            rd = s.get("round") or 0
            p = tuple(sorted((by[x["step_id"]].get("phase"), (rd - (by[x["step_id"]].get("round") or 0)),
                              by[x["step_id"]].get("agent_id")) for x in src if x["step_id"] in by))
            pat[(fw, ph)][p] += 1
            src_ids = {x["step_id"] for x in src if x["step_id"] in by}
            if src_ids:
                phases = {by[x].get("phase") for x in src_ids}
                cands = {t["step_id"] for t in steps[:i] if t.get("phase") in phases}
                if len(cands) > len(src_ids):
                    choice[(fw, ph)] += 1
        if r["run_index"] == 0:
            normal_keyed[(fw, r["question_id"])] = keyed(r)
    else:
        inj = (r["labels"].get("injection") or [{}])[0]
        inj_runs.append((fw, r["question_id"], inj.get("effective_strategy"), keyed(r)))

print("== how values (normal runs) ==")
for fw, c in sorted(how.items()):
    print(fw, dict(c))
print("\n== read-set predictability per (framework, phase), normal runs ==")
print(f"{'framework':14s} {'phase':22s} {'steps':>6s} {'patterns':>8s} {'mode_share':>10s} {'choice_steps':>12s}")
for k in sorted(nsteps):
    c = pat[k]
    print(f"{k[0]:14s} {str(k[1]):22s} {nsteps[k]:6d} {len(c):8d} {c.most_common(1)[0][1] / nsteps[k]:10.2f} {choice[k]:12d}")
print("\n== injection vs paired normal (run 0), steps present in both ==")
agg = defaultdict(lambda: [0, 0])
for fw, q, st, kd in inj_runs:
    nk = normal_keyed.get((fw, q))
    if not nk:
        continue
    for key, src in kd.items():
        if key in nk:
            agg[(fw, st)][0] += 1
            agg[(fw, st)][1] += src == nk[key]
for k, (n, same) in sorted(agg.items(), key=str):
    print(f"{k[0]:14s} {str(k[1]):22s} common_steps={n:6d} same_sources={same / n:.3f}")

# ---- refinement: determinism given the slot (agent_id, phase, round) and normal-vs-normal baseline
slotpat = defaultdict(Counter)
nk_all = defaultdict(dict)
for l in open(path):
    r = json.loads(l)
    if r["run_mode"] != "normal":
        continue
    kd = keyed(r)
    nk_all[(r["framework"], r["question_id"])][r["run_index"]] = kd
    for key, src in kd.items():
        # src as slot keys without occurrence counters of the same run -> already relative
        slotpat[(r["framework"], key[1], key[2], key[0])][src] += 1
det = defaultdict(lambda: [0, 0])
for (fw, ph, rd, ag), c in slotpat.items():
    det[(fw, ph)][0] += sum(c.values())
    det[(fw, ph)][1] += c.most_common(1)[0][1]
print("\n== share of steps whose read set equals the most common one for their slot (agent, phase, round) ==")
for k, (n, m) in sorted(det.items(), key=str):
    print(f"{k[0]:14s} {str(k[1]):22s} steps={n:5d} slot_determined={m / n:.2f}")
print("\n== normal run 0 vs normal run 1 (same question), baseline for the comparison above ==")
b = defaultdict(lambda: [0, 0])
for (fw, q), runs in nk_all.items():
    if 0 in runs and 1 in runs:
        for key, src in runs[1].items():
            if key in runs[0]:
                b[fw][0] += 1
                b[fw][1] += src == runs[0][key]
for fw, (n, same) in sorted(b.items()):
    print(f"{fw:14s} common_steps={n:6d} same_sources={same / n:.3f}")
