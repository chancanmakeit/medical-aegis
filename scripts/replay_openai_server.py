#!/usr/bin/env python3
"""Replay server: answers /v1/chat/completions from RECORDED runs (branching / counterfactual replay,
v10 round 15). No network, no API cost.

A request whose messages hash (sha1 of [(role, content)], the key of check_replay_cache_keys.py) equals the
recorded `input_messages` of a step of the selected runs gets that step's recorded reply. Every other
request is a MISS: it is answered by the offline mock (mock_openai_server.reply_for) so the framework can
finish, and the miss is logged with a diagnosis -- the recorded step with the longest common message
prefix, the first differing message and the first differing character.

With --overrides the reply of chosen steps is replaced (a simulated branch at step t, no API): every
later request that does not embed the new reply is still served from the record, so the misses count
exactly the downstream calls a real branch would have to pay for.

  python scripts/replay_openai_server.py --port 18090 --run_index 0 \
      --results /home/claude/anchor_runs/mdagents__normal.jsonl --log /tmp/replay_calls.jsonl

Identical keys inside the selected runs are served first-in-first-out.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mock_openai_server import reply_for  # noqa: E402

LOCK = threading.Lock()


def _text_of(content):
    # multimodal requests carry [{"type": "text"}, {"type": "image_url"}, ...]; recorded input_messages keep
    # the text only (the images are task observations), so key on the text parts
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content


def norm_msgs(msgs):
    return [(m.get("role"), _text_of(m.get("content"))) for m in msgs]


_FILE_SHA = {}


def _file_sha1(path):
    if path not in _FILE_SHA:
        with open(path, "rb") as f:
            _FILE_SHA[path] = hashlib.sha1(f.read()).hexdigest()
    return _FILE_SHA[path]


def request_images(msgs):
    """sha1 of every attached image of a live request (data URLs: of the decoded bytes, else of the URL)."""
    out = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    url = (p.get("image_url") or {}).get("url", "")
                    if url.startswith("data:") and "," in url:
                        out.append(hashlib.sha1(base64.b64decode(url.split(",", 1)[1])).hexdigest())
                    else:
                        out.append(hashlib.sha1(url.encode()).hexdigest())
                elif isinstance(p, dict) and p.get("type") == "input_audio":
                    # MAM: the same prompt text for every recording, so the audio must be part of the key
                    data = (p.get("input_audio") or {}).get("data", "")
                    if data.startswith("data:") and "," in data:
                        data = data.split(",", 1)[1]
                    try:
                        out.append(hashlib.sha1(base64.b64decode(data)).hexdigest())
                    except ValueError:
                        out.append(hashlib.sha1(data.encode()).hexdigest())
    return out


def step_images(rec, step):
    """sha1 of the images a recorded step saw (its `observations` -> task_observations paths)."""
    obs = {o["id"]: o.get("path") for o in (rec.get("injection_log") or {}).get("task_observations") or []}
    # images and audio (MAM) are both task observations; relative paths are relative to the repo root
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [_file_sha1(obs[o] if os.path.isabs(obs[o]) else os.path.join(root, obs[o]))
            for o in step.get("observations") or [] if obs.get(o)]


def key(msgs, images=None, sample=None):
    """Request key. Text parts only (recorded inputs keep the text; images are task observations), plus the
    image hashes when there are any: questions with the same text and different images (Kvasir-VQA-x1:
    "Is there any abnormality observed in this image?") must not share replies (fixed 2026-11-03)."""
    payload = norm_msgs(msgs)
    if images is None:
        images = request_images(msgs)
    if images:
        payload = [payload, sorted(images)]
    if sample is not None:          # --sample_keys: the request's X-Aegis-Sample header / the record id
        payload = [payload, "sample", str(sample)]
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def step_key(rec, step, sample_keys=False):
    return key(step["input_messages"], step_images(rec, step), rec.get("id") if sample_keys else None)


class Cache:
    def __init__(self, files, run_index, ids=None, overrides=None, sample_keys=False):
        self.sample_keys = sample_keys
        self.q = defaultdict(deque)           # key -> deque of (reply, meta)
        self.steps = []                       # (qid, step_id, agent, phase, msgs) for miss diagnosis
        self.n_steps = 0
        for f in files:
            for line in open(f, encoding="utf-8"):
                r = json.loads(line)
                if int(r.get("run_index", 0)) != run_index or (ids and r["id"] not in ids):
                    continue
                for s in r["injection_log"]["conversation_history"]:
                    msgs = s.get("input_messages")
                    if not isinstance(msgs, list):
                        continue
                    reply = s.get("response") if s.get("response") is not None else s.get("content")
                    meta = {"qid": r["id"], "step_id": s.get("step_id"), "agent": s.get("agent_name"), "phase": s.get("phase")}
                    if overrides and (r["id"], s.get("step_id")) in overrides:   # branch point: serve a different reply
                        reply = overrides[(r["id"], s.get("step_id"))]
                        meta["override"] = True
                    self.q[step_key(r, s, sample_keys)].append((reply, meta))
                    self.steps.append((meta, norm_msgs(msgs)))
                    self.n_steps += 1

    def take(self, msgs, sample=None):
        k = key(msgs, sample=sample if self.sample_keys else None)
        with LOCK:
            d = self.q.get(k)
            if d:
                return d.popleft()
        return None

    def diagnose(self, msgs):
        req = norm_msgs(msgs)
        best = None
        for meta, rec in self.steps:
            n = 0
            for a, b in zip(req, rec):
                if a != b:
                    break
                n += 1
            # tie-break on how far the first differing message agrees
            cpos = 0
            if n < min(len(req), len(rec)):
                a, b = str(req[n][1]), str(rec[n][1])
                while cpos < min(len(a), len(b)) and a[cpos] == b[cpos]:
                    cpos += 1
            score = (n, cpos)
            if best is None or score > best[0]:
                best = (score, meta, rec)
        if best is None:
            return {"nearest": None}
        (n, cpos), meta, rec = best
        out = {"nearest": meta, "req_msgs": len(req), "rec_msgs": len(rec), "common_prefix_msgs": n}
        if n < min(len(req), len(rec)):
            a, b = str(req[n][1]), str(rec[n][1])
            out.update(first_diff_msg=n, role=req[n][0], diff_char=cpos,
                       req_snip=a[max(0, cpos - 60):cpos + 120], rec_snip=b[max(0, cpos - 60):cpos + 120],
                       req_len=len(a), rec_len=len(b))
        elif len(req) != len(rec):
            out.update(first_diff_msg=n, note="one is a prefix of the other")
        else:
            out.update(note="identical messages but recorded reply already consumed (more identical calls than recorded)")
        return out


def make_handler(cache, log_path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            msgs = body.get("messages", [])
            sample = self.headers.get("X-Aegis-Sample")
            k = key(msgs, sample=sample if cache.sample_keys else None)
            got = cache.take(msgs, sample)
            if got is not None:
                text, meta = got
                rec = {"hit": True, "key": k, **meta}
            else:
                text = reply_for(msgs) or "OK."
                rec = {"hit": False, "key": k, "diag": cache.diagnose(msgs)}
            if sample is not None:
                rec["sample"] = sample
            rec["t"] = time.time()
            with LOCK, open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            resp = {"id": "replay", "object": "chat.completion", "created": int(time.time()), "model": body.get("model", "replay"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            data = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18090)
    ap.add_argument("--results", nargs="+", required=True)
    ap.add_argument("--run_index", type=int, default=0)
    ap.add_argument("--ids", default=None, help="comma-separated question ids to load (default all)")
    ap.add_argument("--log", required=True)
    ap.add_argument("--sample_keys", action="store_true",
                    help="key requests by the X-Aegis-Sample header too (main.py run with AEGIS_SAMPLE_HEADER=1)")
    ap.add_argument("--overrides", default=None,
                    help="JSONL of {qid, step_id, text}: serve `text` instead of the recorded reply at that step "
                         "(simulated branch; later requests that embed it then miss)")
    a = ap.parse_args()
    ov = None
    if a.overrides:
        ov = {(o["qid"], o["step_id"]): o["text"] for o in map(json.loads, open(a.overrides)) }
    cache = Cache(a.results, a.run_index, set(a.ids.split(",")) if a.ids else None, ov, a.sample_keys)
    print(f"replay cache: {cache.n_steps} recorded steps, {len(cache.q)} distinct keys", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(cache, a.log)).serve_forever()


if __name__ == "__main__":
    main()
