#!/usr/bin/env python3
"""Minimal OpenAI-compatible /v1/chat/completions mock for OFFLINE pipeline tests.

No network, no API cost. Replies are chosen by keyword rules on the last user
message (see RULES), so a framework's control flow can be exercised end to end.
Every request is appended to --log (JSONL) so tests can inspect exactly what
each agent received.

Usage:
  python scripts/mock_openai_server.py --port 18080 --log /tmp/mock_calls.jsonl &
  # then point model_url at http://127.0.0.1:18080/v1 with any api_key.

Built-in rules target MedAgents (medagents_mc); extend RULES for other frameworks.
"""
import argparse
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()


def _text(content):
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def reply_for(messages):
    user = _text(messages[-1].get("content")) if messages else ""
    system = " ".join(_text(m.get("content")) for m in messages if m.get("role") == "system")
    # --- MedAgents ---------------------------------------------------------
    if "classify the question into five different subfields" in user:
        return "Medical Field: Cardiology | Neurology | Pharmacology | Pathology | Radiology"
    if "categorize the options into two distinct subfields" in user:
        return "Medical Field: Medical Coding | Clinical Terminology"
    if "Please respond only with: [YES or NO]" in user:
        # Neurology disagrees until the report has been revised once.
        if "Neurology" in system and "REVISED" not in user:
            return "NO"
        return "YES"
    if "propose revisions to this report" in user:
        return "Revisions: emphasise the laterality in the code description."
    if "output the revised analysis" in user:
        return "Total Analysis: REVISED analysis: the code denotes the right femur, so option D."
    if "derive a refined and synthesized report" in user:
        return ("Key Knowledge: ICD-10-CM S72.24 is a nondisplaced subtrochanteric fracture.\n"
                "Total Analysis: The experts agree option D matches the code.")
    if "using the following format: '''Option: [Selected Option's Letter]'''" in user:
        return "Option: D"
    if "interpret the condition being depicted" in user:
        return "The scenario concerns a femur fracture code. The laterality is right. Option D fits best."
    if "scrutinize each option individually" in user:
        return "Options A-C mismatch displacement or laterality. Option D is plausible."
    # --- ClinicalAgent ------------------------------------------------------
    for tag, val in (("safety_score", "0.3"), ("efficacy_score", "0.4"), ("enrollment_score", "0.2")):
        if f"<{tag}>0.X</{tag}>" in user:
            return f"Lane analysis for {tag.split('_')[0]}. <{tag}>{val}</{tag}>"
    if "<final_result>0.X</final_result> tags (0-1" in user:
        return "p = 0.30*0.3 + 0.40*0.4 + 0.30*0.2 = 0.31\n<final_result>0.31</final_result>"
    # --- ConSensus (consensus + baselines) ---------------------------------
    # REASON texts carry the agent name + a digest of the request so every
    # step's output is unique (keeps scripts/check_trajectory_sources.py from
    # flagging false "unlisted" reads). CONFIDENCE is added when the prompt
    # asks for one (ReConcile).
    agent = (re.search(r"You are (\S+) agent", system) or re.search(r"You are (an? \w+ \w+)", system))
    agent = agent.group(1) if agent else "agent"
    digest = hashlib.md5(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:8]
    wants_conf = "confidence" in user.lower() or any("confidence" in _text(m.get("content")).lower()
                                                     for m in messages if m.get("role") == "user")
    def _js(reason, ans):
        d = {"REASON": f"{reason} [{agent} {digest}]"}
        if wants_conf:
            d["CONFIDENCE"] = "0.85"
        d["ANSWER"] = ans
        return json.dumps(d, indent=2)
    if "Failed to parse the JSON from the previous response" in user:
        return _js("Retry: spindle-like activity and low EMG.", "N2")
    if "You have received sensor features from" in user:
        # EMG agent breaks the JSON format on its first turn -> exercises retry.
        if "EMG" in system and len(messages) <= 2:
            return "I think it is N2 because the EMG is low."
        return _js("Features resemble the N2 example.", "N3" if "EEG-Pz-Oz" in system else "N2")
    m = re.search(r"You are on the side that the correct answer is (\S+) which", user)
    if m:
        return '{"REASON": "Majority is consistent; dissenting agents are noisy.", "ANSWER": "%s"}' % m.group(1)
    if "analyze the reasonings and answers and provide a final reasoned answer" in user:
        return '{"REASON": "Most modalities indicate N2.", "ANSWER": "N2"}'
    if "determine the responses from the fusion agents" in user:
        return '{"REASON": "Both fusion agents agree on N2.", "ANSWER": "N2"}'
    # --- generic JSON template filler (any "strict JSON format" request) ----
    # Fills every "FIELD": "<...>" placeholder in the requested template;
    # ANSWER-like fields get the first class of "<Answer among [...]>" (or a
    # literal value already present in the template). Lets new sensing
    # baselines run under the mock without per-framework rules.
    tmpl = re.search(r"strict JSON format:\s*(\{.*?\n\})", user, re.DOTALL)
    if tmpl:
        fields = re.findall(r'"([A-Z_]+)"\s*:\s*"([^"]*)"', tmpl.group(1))
        out = {}
        for k, v in fields:
            if not (v.startswith("<") and v.endswith(">")):
                out[k] = v                      # literal (e.g. a fixed majority answer)
                continue
            cls = re.search(r"among \[([^\]]*)\]", v)
            if cls:
                first = [c.strip().strip("'\"") for c in cls.group(1).split(",")][0]
                out[k] = first
            elif any(w in v.lower() for w in ("confidence", "score")):
                out[k] = "0.8"
            elif any(w in v.lower() for w in ("yes", "no", "agree")):
                out[k] = "yes"
            else:
                out[k] = f"mock {k.lower()} text [{agent} {digest}]."
        if out:
            return json.dumps(out)
    # --- generic (LLM judge, describers, ...) ------------------------------
    if re.search(r"\bCORRECT\b|\bINCORRECT\b", user):
        return "CORRECT"
    return "OK."


class Handler(BaseHTTPRequestHandler):
    log_path = None

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages", [])
        content = reply_for(msgs)
        if self.log_path:
            with LOCK, open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"messages": msgs, "reply": content,
                                    "max_tokens": body.get("max_tokens"),
                                    "temperature": body.get("temperature")},
                                   ensure_ascii=False) + "\n")
        resp = {
            "id": "mock", "object": "chat.completion", "created": 0,
            "model": body.get("model", "mock"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": sum(len(_text(m.get("content")).split()) for m in msgs),
                      "completion_tokens": len(content.split()), "total_tokens": 0},
        }
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    Handler.log_path = a.log
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
