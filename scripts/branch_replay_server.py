#!/usr/bin/env python3
"""Branch / control replay server for the branching pilot (v10 round 16; design: issue rounds 43, 61).

For each question of the pilot a spec line says which recorded step t is the branch point, which arm this
pass runs, and which recorded steps depend on t (D(t), estimated offline by scripts/branch_pilot.py deps):

  {"qid": ..., "arm": "branch"|"control", "t_step_id": "s3", "force_step_ids": ["s4", "s6"]}

Request routing (key = sha1 of [(role, content)], as replay_openai_server.py):
  * request == recorded input of step t:   branch  -> upstream at --t_temperature (the original 0.7:
                                                       natural resampling of step t, mode (a))
                                           control -> the recorded reply (step t kept)
  * request == recorded input of a step in D(t)  -> upstream at --down_temperature (0), both arms
  * any other recorded request                   -> recorded reply (prefix, and downstream steps that do
                                                    not read step t: identical in both arms)
  * anything else (a miss)                       -> upstream at --down_temperature
Every upstream call is logged with tag, temperature, usage, model and system_fingerprint.
--upstream mock answers upstream calls offline (mock_openai_server.reply_for) for smoke tests.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mock_openai_server import reply_for  # noqa: E402
from replay_openai_server import Cache, key, step_key  # noqa: E402

LOCK = threading.Lock()
ARRIVALS = {}


def load_spec(path, results, run_index):
    spec = {json.loads(l)["qid"]: json.loads(l) for l in open(path) if l.strip()}
    t_keys, force_keys = {}, {}
    for f in results:
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if int(r.get("run_index", 0)) != run_index or r["id"] not in spec:
                continue
            sp = spec[r["id"]]
            force = set(sp.get("force_step_ids") or [])
            seen = {}
            for s in r["injection_log"]["conversation_history"]:
                if not isinstance(s.get("input_messages"), list):
                    continue
                k = step_key(r, s)
                occ = seen.get(k, 0)
                seen[k] = occ + 1
                if s.get("step_id") == sp["t_step_id"]:
                    # identical requests (e.g. llm_debate round-1 agents share one prompt) are told apart by
                    # arrival order, which replays preserve (replay_hit_analysis: 1,200/1,200 identical runs)
                    t_keys[k] = (r["id"], sp["arm"], occ)
                elif s.get("step_id") in force:
                    force_keys[step_key(r, s)] = r["id"]
    return spec, t_keys, force_keys


def make_handler(a, cache, t_keys, force_keys):
    api_key = os.environ.get(a.api_key_env, "")

    def upstream(body, temperature):
        b = dict(body)
        b["temperature"] = temperature
        if a.upstream == "mock":
            text = reply_for(b.get("messages", [])) or "OK."
            return {"id": "mock", "object": "chat.completion", "created": int(time.time()), "model": "mock",
                    "system_fingerprint": None,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        req = urllib.request.Request(a.upstream.rstrip("/") + "/chat/completions", data=json.dumps(b).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    return json.loads(resp.read())
            except Exception as e:   # noqa: BLE001 -- retried, then surfaced to the framework as an error
                last = e
                time.sleep(2 * (attempt + 1))
        raise last

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            msgs = body.get("messages", [])
            k = key(msgs)
            rec = {"key": k, "t": time.time(), "req_temperature": body.get("temperature")}
            out = None
            is_t = False
            if k in t_keys:
                with LOCK:
                    n_seen = ARRIVALS.get(k, 0)
                    ARRIVALS[k] = n_seen + 1
                is_t = n_seen == t_keys[k][2]
                if not is_t:
                    got = cache.take(msgs)
                    if got is not None:
                        out = got[0]
                        rec.update(tag="recorded_same_input", qid=t_keys[k][0], occurrence=n_seen)
                    else:
                        rec.update(tag="miss", qid=t_keys[k][0], temperature=a.down_temperature)
            if out is not None or rec.get("tag") == "miss":
                pass
            elif is_t and t_keys[k][1] == "branch":
                cache.take(msgs)       # drop step t's recorded reply so later identical requests stay aligned
                rec.update(tag="t_resample", qid=t_keys[k][0], temperature=a.t_temperature)
            elif is_t:
                got = cache.take(msgs)
                rec.update(tag="t_kept", qid=t_keys[k][0])
                if got is None:      # should not happen: the recorded reply of step t was consumed already
                    rec.update(tag="t_kept_missing", temperature=a.down_temperature)
                else:
                    out = got[0]
            elif k in force_keys:
                rec.update(tag="forced_dependent", qid=force_keys[k], temperature=a.down_temperature)
            else:
                got = cache.take(msgs)
                if got is not None:
                    out = got[0]
                    rec.update(tag="recorded", qid=got[1]["qid"], step_id=got[1]["step_id"])
                else:
                    nm = (cache.diagnose(msgs).get("nearest") or {})
                    rec.update(tag="miss", qid=nm.get("qid"), nearest_step=nm.get("step_id"), temperature=a.down_temperature)
            try:
                if out is not None:
                    resp = {"id": "replay", "object": "chat.completion", "created": int(time.time()),
                            "model": body.get("model", "replay"),
                            "choices": [{"index": 0, "message": {"role": "assistant", "content": out}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
                else:
                    resp = upstream(body, rec["temperature"])
                    rec.update(upstream=True, usage=resp.get("usage"), model=resp.get("model"),
                               system_fingerprint=resp.get("system_fingerprint"),
                               finish_reason=(resp.get("choices") or [{}])[0].get("finish_reason"),
                               output=(resp.get("choices") or [{}])[0].get("message", {}).get("content"))
                data = json.dumps(resp).encode()
                code = 200
            except Exception as e:   # noqa: BLE001
                rec.update(error=repr(e)[:300])
                data = json.dumps({"error": {"message": repr(e)[:300]}}).encode()
                code = 502
            with LOCK, open(a.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--results", nargs="+", required=True)
    ap.add_argument("--run_index", type=int, default=0)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--upstream", default="mock", help="'mock' or an OpenAI-compatible base URL (…/v1)")
    ap.add_argument("--api_key_env", default="AIHUBMIX_API_KEY")
    ap.add_argument("--t_temperature", type=float, default=0.7)
    ap.add_argument("--down_temperature", type=float, default=0.0)
    a = ap.parse_args()
    spec, t_keys, force_keys = load_spec(a.spec, a.results, a.run_index)
    cache = Cache(a.results, a.run_index, set(spec))
    print(f"branch server: {len(spec)} questions, {len(t_keys)} branch points, {len(force_keys)} forced dependent steps, "
          f"upstream={a.upstream if a.upstream == 'mock' else 'real'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(a, cache, t_keys, force_keys)).serve_forever()


if __name__ == "__main__":
    main()
