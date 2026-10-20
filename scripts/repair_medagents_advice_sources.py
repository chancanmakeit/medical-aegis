#!/usr/bin/env python3
"""Repair Reviser read sets in medagents_mc results written before the fix of
2026-10-20 (methods/medagents_mc/medagents_mc_main.py, advice_by_domain).

MedAgents keys revision advice by domain name. When a question expert and an
option expert share a domain and both vote NO, the later advice replaces the
earlier one in the Reviser prompt. Old results still listed both Advisor steps
as Reviser sources. This script keeps, per domain, only the last Advisor step
of that vote round -- the same rule the fixed code applies at run time.

Usage: python scripts/repair_medagents_advice_sources.py in.jsonl out.jsonl
"""
import json
import re
import sys

DOMAIN_RE = re.compile(r"specialized in (.+?), please make full use", re.S)


def advisor_domain(step):
    text = "\n".join(m.get("content", "") for m in step.get("input_messages") or []
                     if isinstance(m.get("content"), str))
    m = DOMAIN_RE.search(text)
    return m.group(1).strip() if m else None


def repair(rec):
    n = 0
    log = rec.get("injection_log") or {}
    for key in ("conversation_history", "raw_history"):
        h = log.get(key) or []
        by_id = {s.get("step_id"): s for s in h}
        for s in h:
            if s.get("agent_name") != "Reviser" and s.get("role") != "Reviser":
                continue
            last = {}
            for src in s.get("sources", []):
                p = by_id.get(src, {})
                if (p.get("agent_name") or p.get("role")) == "Advisor":
                    last[advisor_domain(p) or src] = src
            keep = set(last.values())
            drop = [x for x in s.get("sources", [])
                    if (by_id.get(x, {}).get("agent_name") or by_id.get(x, {}).get("role")) == "Advisor"
                    and x not in keep]
            if drop:
                s["sources"] = [x for x in s["sources"] if x not in drop]
                for x in drop:
                    (s.get("source_how") or {}).pop(x, None)
                n += len(drop) if key == "conversation_history" else 0
    return n


if __name__ == "__main__":
    total = 0
    with open(sys.argv[1]) as fi, open(sys.argv[2], "w") as fo:
        for line in fi:
            rec = json.loads(line)
            total += repair(rec)
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"dropped {total} overwritten advice sources")
