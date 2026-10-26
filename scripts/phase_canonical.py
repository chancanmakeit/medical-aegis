#!/usr/bin/env python3
"""phase_canonical lookup (DRAFT v0, configs/phase_canonical_v0.yaml; v10 round 15).

  from phase_canonical import load, canonical
  table = load()
  canonical(table, framework, phase, kind="llm", round_=None, n_peer_sources=0) -> str

CLI: coverage report over mas-traj/1 files (.jsonl or .jsonl.gz), optionally writing an annotated copy
(adds step["phase_canonical"]; nothing else changes):

  python scripts/phase_canonical.py report <file>... [--annotate_out <file.jsonl>]
"""
import argparse
import gzip
import json
import os
import sys
from collections import Counter, defaultdict

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "configs", "phase_canonical_v0.yaml")


def load(path=DEFAULT):
    t = yaml.safe_load(open(path, encoding="utf-8"))
    vocab = set(t["vocab"])
    for fw, m in (t.get("frameworks") or {}).items():
        for ph, c in m.items():
            assert c in vocab, f"{fw}.{ph}: {c} not in vocab"
    for ph, c in (t.get("defaults") or {}).items():
        assert c in vocab, f"defaults.{ph}: {c} not in vocab"
    return t


def canonical(t, framework, phase, kind="llm", round_=None, n_peer_sources=None):
    """n_peer_sources: number of sources written by OTHER agents (None = unknown, keep the table value)."""
    if kind == "environment":
        return "environment"
    fwm = (t.get("frameworks") or {}).get(framework) or {}
    ph = phase or ""
    c = fwm.get(ph) or fwm.get(ph.split("/")[0]) or (t.get("defaults") or {}).get(ph)
    if c is None and ph.endswith("_expert_turn"):
        c = "discuss"
    if c is None:
        c = "tool" if kind == "tool" else "other"
    if c in ("answer", "discuss") and n_peer_sources is not None:
        c = "discuss" if n_peer_sources else "answer"     # peer rule: seeing other agents' answers = discuss
    return c


def read(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def annotate(t, rec):
    """Two passes: table value first; then the peer rule counts only sources that are other agents'
    answer/discuss steps (reading a recruiter or a router is not reading a peer's answer)."""
    base = {s["step_id"]: canonical(t, rec["framework"], s.get("phase"), s.get("kind", "llm")) for s in rec["steps"]}
    agent_of = {s["step_id"]: s.get("agent_id") for s in rec["steps"]}
    for s in rec["steps"]:
        peers = None if s.get("sources") is None else sum(
            1 for src in s["sources"]
            if base.get(src["step_id"]) in ("answer", "discuss") and agent_of.get(src["step_id"]) not in (None, s.get("agent_id")))
        s["phase_canonical"] = canonical(t, rec["framework"], s.get("phase"), s.get("kind", "llm"), s.get("round"), peers)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["report"])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--table", default=DEFAULT)
    ap.add_argument("--annotate_out", default=None)
    a = ap.parse_args()
    t = load(a.table)
    per_fw = defaultdict(Counter)
    other = defaultdict(Counter)
    out = open(a.annotate_out, "w", encoding="utf-8") if a.annotate_out else None
    for f in a.files:
        for rec in read(f):
            annotate(t, rec)
            for s in rec["steps"]:
                per_fw[rec["framework"]][s["phase_canonical"]] += 1
                if s["phase_canonical"] == "other":
                    other[rec["framework"]][s.get("phase")] += 1
            if out:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tot = Counter()
    for fw, c in sorted(per_fw.items()):
        n = sum(c.values())
        tot.update(c)
        print(f"{fw:26s} steps={n:6d} other={c['other'] / n:.3f}  " + " ".join(f"{k}={v}" for k, v in c.most_common()))
        if other[fw]:
            print(f"{'':26s} unmapped phases: {dict(other[fw].most_common(6))}")
    n = sum(tot.values())
    print(f"ALL steps={n} other={tot['other'] / max(n, 1):.4f} " + " ".join(f"{k}={v}" for k, v in tot.most_common()))


if __name__ == "__main__":
    sys.exit(main())
