#!/usr/bin/env python3
# Usage: python3 scripts/sameslot_markdown.py <gate_export.jsonl.gz>  (MHT round 43 check)
# Same-slot markdown ratio: injected step vs normal steps at the same (q, fw, agent, phase, round, k-th occurrence)
import gzip,json,sys,re,collections
MD=re.compile(r"###|\*\*")
def key_steps(r):
    occ=collections.Counter(); out={}
    for s in r["steps"]:
        if s.get("kind")!="llm": continue
        b=(s["agent_id"],s["phase"],s["round"]); k=occ[b]; occ[b]+=1
        out[s["step_id"]]=(r["question_id"],r["framework"])+b+(k,)
    return out
normal=collections.defaultdict(list); inj=[]
for l in gzip.open(sys.argv[1],"rt"):
    r=json.loads(l); ks=key_steps(r); byid={s["step_id"]:s for s in r["steps"]}
    if r["run_mode"]=="normal":
        for sid,k in ks.items(): normal[k].append(bool(MD.search(byid[sid]["output"] or "")))
    else:
        for i in r["labels"].get("injection") or []:
            if not i.get("applied") or i["step_id"] not in ks: continue
            st=i.get("effective_strategy") or i.get("strategy")
            if i.get("sham_variant"): st={"plain_v1":"sham","style_v1":"sham_style"}.get(i["sham_variant"],i["sham_variant"])
            inj.append((r["framework"],st,ks[i["step_id"]],bool(MD.search(byid[i["step_id"]]["output"] or ""))))
agg=collections.defaultdict(lambda:[0,0,0.0])
for fw,st,k,m in inj:
    if k not in normal: continue
    a=agg[(fw,st)]; a[0]+=1; a[1]+=m; a[2]+=sum(normal[k])/len(normal[k])
for (fw,st),(n,mi,mn) in sorted(agg.items()):
    print(f"{fw:15s} {st:22s} n={n:4d}  inj_md={mi/n:.2f}  sameslot_normal_md={mn/n:.2f}")
