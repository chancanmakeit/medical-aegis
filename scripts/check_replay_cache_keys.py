#!/usr/bin/env python3
"""Can a run be replayed from its own record? (v10 round 11, branching / counterfactual replay)

Checks that every non-injected step's recorded `input_messages` (raw main.py output,
injection_log.conversation_history) equals, message for message, a request the LLM server
actually received -- i.e. a replay server keyed on a hash of the request messages would
return the recorded reply for every prefix step. Needs a mock-server call log
(scripts/mock_openai_server.py --log) and the result files of the same runs.

Usage: python3 scripts/check_replay_cache_keys.py <mock_calls.jsonl> <results.jsonl>...
"""
import hashlib
import json
import sys


def key(msgs):
    return hashlib.sha1(json.dumps([(m.get("role"), m.get("content")) for m in msgs],
                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    logged = {key(json.loads(l)["messages"]) for l in open(sys.argv[1]) if l.strip()}
    tot = hit = 0
    for f in sys.argv[2:]:
        for l in open(f):
            r = json.loads(l)
            for s in r["injection_log"]["conversation_history"]:
                if str(s.get("injection_applied")) == "True" or not isinstance(s.get("input_messages"), list):
                    continue
                tot += 1
                hit += key(s["input_messages"]) in logged
    print(f"recorded inputs matching a logged request exactly: {hit}/{tot}")


if __name__ == "__main__":
    main()
