"""Rendered-token statistics of mas-traj exports (v11 r13, for MHT's per-arm token budget).
Rendering assumed: task query + every step output + ~12 tokens of agent/phase header per step + 20 (o200k).
  corpus_token_stats.py FILE.mastraj.jsonl.gz [...]"""
import gzip, json, statistics as st, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_schema_v1 import count_tokens
print("| file | runs | rendered tokens / run: mean (median, p90) | total | steps / run | share of LLM steps reading a strict subset of history |")
print("|---|---|---|---|---|---|")
for p in sys.argv[1:]:
    rend, nst, sel, tot = [], [], 0, 0
    for l in gzip.open(p, "rt"):
        r = json.loads(l)
        rend.append(count_tokens(r["task"]["query"]) + sum(s.get("output_tokens_est") or 0 for s in r["steps"]) + 12 * len(r["steps"]) + 20)
        nst.append(len(r["steps"]))
        prev = []
        for s in r["steps"]:
            if s["kind"] == "llm" and prev:
                src = {x["step_id"] for x in (s["sources"] or []) if not x["step_id"].startswith("task:")}
                tot += 1; sel += bool(src) and src != set(prev)
            prev.append(s["step_id"])
    rs = sorted(rend)
    print(f"| {os.path.basename(p)} | {len(rend)} | {st.mean(rend):.0f} ({st.median(rend):.0f}, {rs[int(.9*len(rs))]}) | {sum(rend)/1e6:.2f}M | {st.mean(nst):.1f} | {sel/max(1,tot):.2f} |")
