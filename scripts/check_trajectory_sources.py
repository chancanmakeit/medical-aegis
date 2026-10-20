#!/usr/bin/env python3
"""Check that each step's recorded `sources` really appear in its input_messages,
and flag earlier outputs that appear in the input but are not listed.

Usage: python scripts/check_trajectory_sources.py <results.jsonl>

Heuristic matching per source output (any one is enough):
  - classifier-style steps ("...Classifier"): one of the domain names it produced;
  - JSON outputs ({"REASON": ...}): the REASON text (frameworks re-serialise
    parsed JSON before passing it on, so the raw prefix need not survive);
  - otherwise: the first 40 chars after an optional "Total Analysis:" header;
  - source_how "structured_field": its ANSWER value; without an ANSWER (e.g. a
    vote that only enters as a count) it is counted as derived_unverifiable;
  - source_how "excerpt": any non-trivial line of the source output (XML-style
    tags stripped), or the value after a leading "Label:" on such a line;
  - tool steps (is_tool): checked against their tool_calls arguments.
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
    checked = bad = missing = derived = 0
    for rec in map(json.loads, open(path)):
        log = rec.get("injection_log")
        if not log:
            continue
        h = log["conversation_history"]
        by_id = {s["step_id"]: s for s in h}
        for s in h:
            # tool steps have no chat input: check against their call arguments
            inp = json.dumps(s.get("tool_calls"), ensure_ascii=False) if s.get("is_tool") else txt(s["input_messages"])
            how = s.get("source_how", {})
            for src in s.get("sources", []):
                checked += 1
                pr = probes(by_id[src])
                if how.get(src) == "structured_field":
                    # only a derived field enters the prompt: an ANSWER (count line)
                    # if the source has one; otherwise (e.g. vote counts) unverifiable
                    m = re.findall(r'"ANSWER"\s*:\s*"([^"]*)"', by_id[src].get("content") or "")
                    if not m:
                        derived += 1
                        continue
                    pr = m[-1:]
                elif how.get(src) == "excerpt":
                    # a parsed part of the output: any non-trivial line of it
                    # (XML-style tags stripped: e.g. ClinicalAgent passes the text
                    # inside <subproblem>...</subproblem> on, not the tags)
                    lines = [re.sub(r"<[^>]+>", "", ln).strip()
                             for ln in (by_id[src].get("content") or "").splitlines()]
                    # (and the value after a leading "Label:", e.g. AgentVerse passes
                    # on only the text after the evaluator's "Response:")
                    lines += [ln.split(":", 1)[1].strip() for ln in lines if ":" in ln[:40]]
                    pr = [ln for ln in lines if len(ln) >= 12]
                if not any(p in inp for p in pr):
                    bad += 1
                    print("SOURCE NOT FOUND", rec["id"], s["step_id"], s["agent_name"], "<-", src)
            if s.get("is_tool"):
                continue
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
    print(f"checked={checked} not_found={bad} unlisted={missing} derived_unverifiable={derived}")


if __name__ == "__main__":
    main(sys.argv[1])
