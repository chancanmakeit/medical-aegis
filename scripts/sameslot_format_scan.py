#!/usr/bin/env python3
# Same-slot format features, injected vs normal (MHT r43 follow-up).
# Usage: python3 scripts/sameslot_format_scan.py <gate_export.jsonl>
import json,collections,re,sys
F={"md(###|**)":lambda t:"###" in t or "**" in t,
   "bracketed [..]":lambda t:bool(re.match(r"\s*\[",t)),
   "list line":lambda t:bool(re.search(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+\S",t)),
   "colon-label":lambda t:bool(re.search(r"(?m)^[A-Z][A-Za-z ]{2,30}:",t)),
   "blank lines>=3":lambda t:t.count("\n\n")>=3,
   "ends with .":lambda t:t.rstrip().endswith("."),
   # markdown dialect (fmt_v1 overshoot, v10 round 5): bullet marker, bold labels, first person
   "star bullet":lambda t:bool(re.search(r"(?m)^[ \t]*\*[ \t]+\S",t)),
   "dash bullet":lambda t:bool(re.search(r"(?m)^[ \t]*-[ \t]+\S",t)),
   "bold label":lambda t:bool(re.search(r"\*\*[^*\n]{2,40}:\*\*|\*\*[^*\n]{2,40}\*\*:",t)),
   "first person":lambda t:bool(re.search(r"\bI (have|believe|think|would)\b",t))}
runs=[json.loads(l) for l in open(sys.argv[1])]
def sk(r):
    occ=collections.Counter();o={}
    for s in r["steps"]:
        b=(s["agent_id"],s["phase"],s["round"]);o[s["step_id"]]=b+(occ[b],);occ[b]+=1
    return o
norm=collections.defaultdict(list)
for r in runs:
    if r["run_mode"]=="normal":
        k=sk(r)
        for s in r["steps"]: norm[(r["framework"],r["question_id"])+k[s["step_id"]]].append(s["output"] or "")
agg=collections.defaultdict(lambda: collections.defaultdict(lambda:[0,0.0])); n=collections.Counter()
for r in runs:
    if r["run_mode"]!="inject":continue
    k=sk(r);by={s["step_id"]:s for s in r["steps"]}
    for i in r["labels"].get("injection") or []:
        st=(i.get("effective_strategy") or "")+("@"+i["note_version"] if i.get("note_version") else "")
        s=by[i["step_id"]];key=(r["framework"],r["question_id"])+k[s["step_id"]]
        if key not in norm or st.startswith("response"):continue
        n[(r["framework"],st)]+=1
        for f,fn in F.items():
            a=agg[(r["framework"],st)][f]; a[0]+=fn(s["output"] or ""); a[1]+=sum(map(fn,norm[key]))/len(norm[key])
print(f"{'fw':14s}{'strategy':18s}"+"".join(f"{f:>18s}" for f in F))
for k in sorted(agg):
    print(f"{k[0]:14s}{k[1]:18s}"+"".join(f"{agg[k][f][0]/n[k]:8.2f}/{agg[k][f][1]/n[k]:<9.2f}" for f in F))
