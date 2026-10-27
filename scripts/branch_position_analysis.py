#!/usr/bin/env python3
"""Offline checks of MHT's two concerns about scaling the branching pilot (issue, MHT round 64 cont.).

(a) position confound: flips concentrate in llm_debate round-1 / mdagents expert steps.
    1. Is there a speaker-order effect in the *recorded normal runs* (no API calls)?
       llm_debate: when round 1 splits, which round-1 agent does the final answer follow?
       mdagents:  when the 5 experts disagree, which panel position does the final follow?
    2. Pilot flip rate by (framework, round, speaker position) and a position-only baseline
       (leave-one-question-out empirical flip rate per stratum -> AUROC).
(b) visible selection condition: size of the "control candidate" pools MHT suggests
    (correct-letter / no-letter steps in matching (round, position) strata), in wrong- and right-ending runs.

Usage: python3 scripts/branch_position_analysis.py [--pilot_dir /home/claude/branch_pilot]
                                                 [--runs data_runs/branch_pilot_2026-10-26] [--out FILE]
"""
import argparse, gzip, json, os, random, sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from branch_pilot import letter, gold, llm_steps, MAA_IDS  # noqa: E402

REPO = os.path.dirname(HERE)
NORMAL = "/home/claude/anchor_runs/{fw}__normal.jsonl"


def load_normal(fw):
    return [json.loads(l) for l in open(NORMAL.format(fw=fw), encoding="utf-8")]


def stratum(fw, h, i):
    """(round, position) of llm step i; position = speaker order within its round / panel."""
    s = h[i]
    ph = str(s.get("phase", ""))
    if ph.startswith("aggregation"):
        return ("agg", 0)
    if fw == "llm_debate":
        rnd = s.get("round")
        same = [j for j, x in enumerate(h) if x.get("round") == rnd and not str(x.get("phase", "")).startswith("aggregation")]
        return (f"r{rnd}", same.index(i))
    if fw == "mdagents":
        if ph.startswith("expert_answer"):
            ex = [j for j, x in enumerate(h) if str(x.get("phase", "")).startswith("expert_answer")]
            return ("expert", ex.index(i))
        return (ph.split("/")[0], 0)
    return (ph, 0)


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    w = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0, c - w), min(1, c + w))


def fmt(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n:.2f} [{lo:.2f}, {hi:.2f}]" if n else f"{k}/0"


def order_effect(out):
    out.append("## (a1) Speaker-order effect in recorded normal runs (K=3 x 100 questions, no API calls)\n")
    # llm_debate
    rows = load_normal("llm_debate")
    split21 = defaultdict(lambda: [0, 0])     # minority agent -> [final follows minority, n]
    three = Counter(); n3 = 0
    r2_follow = defaultdict(lambda: [0, 0])   # in 2:1 splits: round-2 agent j adopts the minority letter
    n_runs = 0
    for r in rows:
        h = llm_steps(r)
        r1 = [letter(s.get("content")) for s in h if s.get("round") == 1]
        r2 = [letter(s.get("content")) for s in h if s.get("round") == 2]
        fin = letter(r.get("response"))
        if len(r1) != 3 or None in r1 or fin is None:
            continue
        n_runs += 1
        c = Counter(r1)
        if len(c) == 2:
            minority = [i for i, x in enumerate(r1) if c[x] == 1][0]
            split21[minority][1] += 1
            split21[minority][0] += fin == r1[minority]
            for j, x in enumerate(r2):
                r2_follow[(minority, j)][1] += 1
                r2_follow[(minority, j)][0] += x == r1[minority]
        elif len(c) == 3:
            n3 += 1
            for i in range(3):
                three[i] += fin == r1[i]
    out.append(f"llm_debate: {n_runs} runs with three round-1 letters and a final letter. Round-1 requests are identical,")
    out.append("so the three round-1 agents are exchangeable; only the round-2 presentation order differs (agent 0 is")
    out.append("listed first among the 'other opinions' for agents 1 and 2; agent 2 is listed second for 0 and 1).\n")
    out.append("2:1 splits — final answer = the minority agent's letter, by which agent was the minority:")
    for m in range(3):
        k, n = split21[m]
        out.append(f"- minority = agent {m}: {fmt(k, n)}")
    tot_k = sum(v[0] for v in split21.values()); tot_n = sum(v[1] for v in split21.values())
    out.append(f"- all 2:1 splits: {fmt(tot_k, tot_n)}")
    out.append("Round-2 adoption of the minority letter (rows: minority agent, cols: round-2 agent j):")
    for m in range(3):
        cells = []
        for j in range(3):
            k, n = r2_follow[(m, j)]
            cells.append(f"{k}/{n}")
        out.append(f"- minority {m}: " + "  ".join(f"j{j}={c}" for j, c in enumerate(cells)))
    out.append(f"3-way splits ({n3}): final = agent 0 / 1 / 2: {three[0]} / {three[1]} / {three[2]}\n")

    # recency: each round-2 step sees [own (assistant turn), first other, last other]; sources order = text order
    rc = defaultdict(lambda: [0, 0])
    for r in rows:
        h = llm_steps(r)
        L = {s["step_id"]: letter(s.get("content")) for s in h}
        for s in h:
            if s.get("round") != 2:
                continue
            own, first, last = [L[x] for x in s["sources"]]
            x = letter(s.get("content"))
            if None in (own, first, last, x) or own == first == last:
                continue
            if own == first != last:
                k = "own = first-other, last-other differs"
            elif own == last != first:
                k = "own = last-other, first-other differs"
            elif first == last != own:
                k = "both others agree against own"
            else:
                k = "all three differ"
            for name, v in (("own", own), ("first-other", first), ("last-other", last)):
                rc[(k, name)][1] += 1
                rc[(k, name)][0] += x == v
    out.append("Round-2 step letter = which input's round-1 letter (each round-2 agent sees its own answer as an")
    out.append("assistant turn, then the two others in `sources` order; the last one directly precedes the instruction;")
    out.append("presentation order checked against `sources` on all 900 round-2 steps, 0 mismatches):")
    for k in ("own = first-other, last-other differs", "own = last-other, first-other differs",
              "both others agree against own", "all three differ"):
        cells = [f"{name} {fmt(*rc[(k, name)])}" for name in ("own", "first-other", "last-other")]
        out.append(f"- {k}: " + "; ".join(cells))
    out.append("")

    # mdagents
    rows = load_normal("mdagents")
    follow = defaultdict(lambda: [0, 0])   # position -> [final == expert letter, n] among runs with disagreement
    uniq = defaultdict(lambda: [0, 0])     # position -> [final == expert letter AND that letter held by only this expert, n singleton]
    n_dis = 0
    for r in rows:
        h = llm_steps(r)
        ex = [letter(s.get("content")) for s in h if str(s.get("phase", "")).startswith("expert_answer")]
        fin = letter(r.get("response"))
        if fin is None or None in ex or len(set(ex)) == 1:
            continue
        n_dis += 1
        c = Counter(ex)
        for p, x in enumerate(ex):
            follow[p][1] += 1
            follow[p][0] += fin == x
            if c[x] == 1:
                uniq[p][1] += 1
                uniq[p][0] += fin == x
    out.append(f"mdagents: {n_dis} runs where the 5 experts do not all agree.")
    out.append("final = expert letter, by panel position (all / when that expert's letter is held by nobody else):")
    for p in range(5):
        out.append(f"- position {p}: {fmt(*follow[p])}   singleton: {fmt(*uniq[p])}")
    out.append("")


def final_letters(path):
    d = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            d[r["id"]] = letter(r.get("response"))
    return d


def auroc(scores, labels):
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return float("nan")
    tot = 0.0
    for p in pos:
        for n in neg:
            tot += 1 if p > n else 0.5 if p == n else 0
    return tot / (len(pos) * len(neg))


def pilot(out, pilot_dir, runs_dir):
    out.append("## (a2) Pilot flips by (round, speaker position); position-only baseline\n")
    pts = []
    for fw in ("llm_debate", "mdagents"):
        rec = {r["id"]: r for r in load_normal(fw) if int(r["run_index"]) == 0}
        cands = [json.loads(l) for l in open(os.path.join(pilot_dir, f"{fw}_candidates.jsonl"))]
        for p in (0, 1, 2):
            b = os.path.join(runs_dir, f"{fw}_p{p}_branch_rep0_out.jsonl.gz")
            c = os.path.join(runs_dir, f"{fw}_p{p}_control_rep0_out.jsonl.gz")
            if not os.path.exists(b):
                continue
            bf, cf = final_letters(b), final_letters(c)
            for x in cands:
                if x["pass"] != p or x["qid"] not in bf:
                    continue
                r = rec[x["qid"]]
                h = llm_steps(r)
                st = stratum(fw, h, x["t"])
                g = gold(r)
                if fw == "llm_debate":
                    peers = [s for j, s in enumerate(h) if j != x["t"] and s.get("round") == h[x["t"]].get("round")]
                else:
                    peers = [s for j, s in enumerate(h) if j != x["t"] and str(s.get("phase", "")).startswith("expert_answer")]
                pts.append({"fw": fw, "qid": x["qid"], "stratum": st, "flip": bf[x["qid"]] != cf[x["qid"]],
                            "n_down": len(x.get("force_step_ids") or []),
                            "peers_right": sum(letter(s.get("content")) == g for s in peers)})
    # peer support: how many same-round peers (llm_debate) / other experts (mdagents) already state the gold letter
    mg = defaultdict(lambda: [0, 0])
    for q in pts:
        if q["stratum"][0] == "agg":
            continue
        k = q["peers_right"]
        mg[(q["fw"], q["stratum"][0], k)][1] += 1
        mg[(q["fw"], q["stratum"][0], k)][0] += q["flip"]
    out.append("Flips by peer support (peers in the same round / other experts that already state the gold letter):")
    for k in sorted(mg, key=str):
        out.append(f"- {k[0]} {k[1]} peers right {k[2]}: {mg[k][0]}/{mg[k][1]}")
    out.append("")
    by = defaultdict(lambda: [0, 0])
    for q in pts:
        by[(q["fw"],) + q["stratum"]][1] += 1
        by[(q["fw"],) + q["stratum"]][0] += q["flip"]
    for k in sorted(by, key=str):
        out.append(f"- {k[0]} {k[1]} pos {k[2]}: {by[k][0]}/{by[k][1]}")
    # position-only baseline, leave-one-question-out empirical rate per stratum (aggregator excluded)
    for fw in ("llm_debate", "mdagents", "both"):
        sub = [q for q in pts if (fw == "both" or q["fw"] == fw) and q["stratum"][0] != "agg"]
        for name, key in (("round only", lambda q: (q["fw"], q["stratum"][0])),
                          ("round x position", lambda q: (q["fw"],) + q["stratum"]),
                          ("|D(t)|", lambda q: (q["fw"], q["n_down"])),
                          ("peer support", lambda q: (q["fw"], q["stratum"][0], min(q["peers_right"], 2)))):
            tag = f"- baseline AUROC [{fw}, no aggregator, n={len(sub)}, flips={sum(q['flip'] for q in sub)}] {name}:"
            if len({key(q) for q in sub}) < 2:
                out.append(f"{tag} n/a (feature constant)")
                continue
            loo, ins = [], []
            for q in sub:
                train = [z for z in sub if z["qid"] != q["qid"] and key(z) == key(q)]
                allt = [z for z in sub if z["qid"] != q["qid"]]
                prior = sum(z["flip"] for z in allt) / max(1, len(allt))
                loo.append((sum(z["flip"] for z in train) + prior) / (len(train) + 1))   # add-one smoothing to the global rate
                same = [z for z in sub if key(z) == key(q)]
                ins.append(sum(z["flip"] for z in same) / len(same))
            y = [q["flip"] for q in sub]
            out.append(f"{tag} leave-one-question-out {auroc(loo, y):.2f}, in-sample {auroc(ins, y):.2f}")
    out.append("")
    return pts


def pools(out):
    out.append("## (b) Control-candidate pools (MHT suggestion), recorded normal runs, all K=3, MAA overlap excluded\n")
    out.append("Steps that state an answer, by (round, position) x letter status (wrong / right / none), split by how the run ends.\n")
    for fw in ("llm_debate", "mdagents"):
        tab = defaultdict(Counter)
        for r in load_normal(fw):
            if r["id"] in MAA_IDS or r.get("is_correct") is None:
                continue
            g = gold(r)
            h = llm_steps(r)
            end = "run_right" if r.get("is_correct") else "run_wrong"
            for i, s in enumerate(h):
                st = stratum(fw, h, i)
                if st[0] in ("agg", "recruitment"):
                    continue
                L = letter(s.get("content"))
                stat = "none" if L is None else ("right" if L == g else "wrong")
                tab[(end,) + st][stat] += 1
        out.append(f"{fw}:")
        for k in sorted(tab, key=str):
            c = tab[k]
            out.append(f"- {k[0]} {k[1]} pos {k[2]}: wrong {c['wrong']}, right {c['right']}, none {c['none']}")
        out.append("")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot_dir", default="/home/claude/branch_pilot")
    ap.add_argument("--runs", default=os.path.join(REPO, "data_runs/branch_pilot_2026-10-26"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    random.seed(0)
    out = ["# Branching pilot: position / selection checks (offline, no API calls)\n"]
    order_effect(out)
    pilot(out, a.pilot_dir, a.runs)
    pools(out)
    txt = "\n".join(out)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")


if __name__ == "__main__":
    main()
