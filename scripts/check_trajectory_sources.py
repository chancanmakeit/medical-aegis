#!/usr/bin/env python3
"""Check that each step's recorded `sources` really appear in its input_messages,
and flag earlier outputs that appear in the input but are not listed.
Usage: python scripts/check_trajectory_sources.py <results.jsonl>
Heuristic (prefix match); classifier-style steps contribute only names."""
import json, sys
def txt(msgs): return "\n".join(m["content"] if isinstance(m["content"], str) else str(m["content"]) for m in (msgs or []))
bad = 0; checked = 0; missing = 0
for rec in map(json.loads, open(sys.argv[1])):
    h = rec["injection_log"]["conversation_history"]
    by_id = {s["step_id"]: s for s in h}
    for s in h:
        inp = txt(s["input_messages"])
        for src in s["sources"]:
            out = by_id[src]["content"]
            # classifier outputs contribute only domain names
            if by_id[src]["agent_name"].endswith("Classifier"):
                names = out.split(":")[-1].strip().split(" | ")
                ok = any(n in inp for n in names)
            else:
                body = out.split("Total Analysis:")[-1].strip()
                ok = body[:40] in inp
            checked += 1
            if not ok:
                bad += 1; print("SOURCE NOT FOUND", rec["id"], s["step_id"], s["agent_name"], "<-", src)
        # converse: any earlier non-classifier step whose output appears but is not listed
        for p in h:
            if p["step_id"] == s["step_id"]: break
            if p["agent_name"].endswith("Classifier") or p["step_id"] in s["sources"]: continue
            body = p["content"].split("Total Analysis:")[-1].strip()
            if len(body) > 25 and body[:40] in inp:
                # identical text produced by a listed source is not a miss
                if any(by_id[x]["content"] == p["content"] for x in s["sources"]): continue
                missing += 1; print("UNLISTED READ", rec["id"], s["step_id"], s["agent_name"], "reads", p["step_id"], p["agent_name"])
print(f"checked={checked} not_found={bad} unlisted={missing}")
