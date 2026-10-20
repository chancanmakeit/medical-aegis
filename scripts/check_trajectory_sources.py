#!/usr/bin/env python3
"""Check that each step's recorded `sources` really appear in its input_messages,
and flag earlier outputs that appear in the input but are not listed.

Usage: python scripts/check_trajectory_sources.py <results.jsonl>

Heuristic matching per source output (any one is enough):
  - classifier-style steps ("...Classifier"): one of the domain names it produced;
  - JSON outputs ({"REASON": ...}): the REASON text (frameworks re-serialise
    parsed JSON before passing it on, so the raw prefix need not survive);
  - otherwise: the first 40 chars after an optional "Total Analysis:" header.
Short outputs (< 25 chars, e.g. "YES") are skipped by the unlisted-read check.
"""
import json
import re
import sys


def txt(msgs):
    return "\n".join(m["content"] if isinstance(m.get("content"), str) else str(m.get("content"))
                     for m in (msgs or []))


def probes(step):
    out = step.get("content") or ""
    if step.get("agent_name", "").endswith("Classifier"):
        return [n for n in out.split(":")[-1].strip().split(" | ") if n]
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and obj.get("REASON"):
                return [json.dumps(str(obj["REASON"]))[1:-1][:60]]
        except Exception:
            pass
    body = out.split("Total Analysis:")[-1].strip()
    return [body[:40]] if body else []


def main(path):
    checked = bad = missing = 0
    for rec in map(json.loads, open(path)):
        log = rec.get("injection_log")
        if not log:
            continue
        h = log["conversation_history"]
        by_id = {s["step_id"]: s for s in h}
        for s in h:
            inp = txt(s["input_messages"])
            for src in s.get("sources", []):
                checked += 1
                if not any(p in inp for p in probes(by_id[src])):
                    bad += 1
                    print("SOURCE NOT FOUND", rec["id"], s["step_id"], s["agent_name"], "<-", src)
            for p in h:
                if p["step_id"] == s["step_id"]:
                    break
                if p["step_id"] in s.get("sources", []) or p.get("agent_name", "").endswith("Classifier"):
                    continue
                pr = [x for x in probes(p) if len(x) >= 25]
                if pr and any(x in inp for x in pr):
                    if any(by_id[x]["content"] == p["content"] for x in s.get("sources", [])):
                        continue  # identical text produced by a listed source
                    missing += 1
                    print("UNLISTED READ", rec["id"], s["step_id"], s["agent_name"], "reads", p["step_id"], p["agent_name"])
    print(f"checked={checked} not_found={bad} unlisted={missing}")


if __name__ == "__main__":
    main(sys.argv[1])
