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
