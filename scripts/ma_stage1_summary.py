"""Summarise MAFA Stage-1 pre-annotation on the medical-aegis batch ma_v1 (320 traces).

Usage: python3 scripts/ma_stage1_summary.py <mafa_dir> [--merge-out DIR]

Arms are read from <mafa_dir>/work_ma/<tax>_<model>[,_c,_f,_r0-2]/stage1.jsonl.  Gemini (slow: ~10 min
per trace under load) was split into three processes: the original dir (clean traces in data order),
*_c (the tail of the clean traces) and *_f (the faulty half); they are merged here (on a duplicate
trace an ok record wins).  The a6api quota ran out at ~01:44; after the top-up the remaining
traces were split into three disjoint lists (*_r0, *_r1, *_r2).  With --merge-out the merged stage1.jsonl per arm
is written to DIR/<tax>_<model>/stage1.jsonl.

v3 step ids are 0-based mas-traj ids (s4); MAFA step ids are 1-based and zero-padded (s05) over the
same step order, so v3 sK <-> MAFA s{K+1:02d} (checked by hand on AgentVerse: v3 s0..s4 =
role_assigner, solver, critic_0, critic_1, evaluator = MAFA s01..s05).  The last column counts
mapped v3 steps that have no MAFA step slot (0 means every mapped step exists).

The v3 comparison is for the organisers only: v3 labels must never be shown to the doctors.
"""
import json, os, sys, collections

mafa = sys.argv[1]
merge_out = sys.argv[sys.argv.index('--merge-out') + 1] if '--merge-out' in sys.argv else None
W = os.path.join(mafa, 'work_ma')
sel = {}
for l in open(os.path.join(W, 'ma_v1_selection.jsonl')):
    r = json.loads(l); sel[r['trace_id']] = r

ARMS = [(t, m) for t in ('mast', 'maa') for m in ('gemini-4-hydrogen', 'gpt-6.1-terra')]


def load(tax, model):
    out = {}
    for suf in ('', '_c', '_f', '_r0', '_r1', '_r2'):
        p = os.path.join(W, f'{tax}_{model}{suf}', 'stage1.jsonl')
        if os.path.exists(p):
            for l in open(p):
                r = json.loads(l)
                old = out.get(r['trace_id'])
                if old is None or r['status'] == 'ok' or old['status'] != 'ok':
                    out[r['trace_id']] = r   # an ok record is never replaced by a failed one
    return out


def steps_flagged(r):
    a = r['annotation']
    s = {f.get('step_id') for f in a.get('findings') or [] if f.get('step_id')}
    return s


data, nfail = {}, {}
for tax, m in ARMS:
    d = load(tax, m)
    nfail[(tax, m)] = sum(r['status'] != 'ok' for r in d.values())
    data[(tax, m)] = {t: r for t, r in d.items() if r['status'] == 'ok'}
    if merge_out:
        os.makedirs(os.path.join(merge_out, f'{tax}_{m}'), exist_ok=True)
        with open(os.path.join(merge_out, f'{tax}_{m}', 'stage1.jsonl'), 'w') as f:
            for tid in sel:
                if tid in d:
                    f.write(json.dumps(d[tid], ensure_ascii=False) + '\n')

print('# MAFA Stage-1 on ma_v1: summary\n')
print('| arm | traces ok | still failed | schema | flagged (>=1 finding) wrong / right | findings per trace wrong / right | novel modes |')
print('|---|---|---|---|---|---|---|')
for (tax, m), d in data.items():
    rs = list(d.values())
    ok = nfail[(tax, m)]
    sch = collections.Counter(r.get('schema_style') for r in rs)
    fw = [r for r in rs if not sel[r['trace_id']]['is_correct']]
    fr = [r for r in rs if sel[r['trace_id']]['is_correct']]
    fl = lambda xs: f"{sum(bool(r['annotation']['findings']) for r in xs)}/{len(xs)}"
    mf = lambda xs: f"{sum(len(r['annotation']['findings']) for r in xs)/max(1,len(xs)):.2f}"
    nov = sum(len(r['annotation'].get('novel_modes') or []) for r in rs)
    print(f'| {tax} {m} | {len(rs)} | {ok} | {dict(sch)} | {fl(fw)} / {fl(fr)} | {mf(fw)} / {mf(fr)} | {nov} |')

print('\n## Flag rate by group (wrong / right)\n')
groups = sorted({s['group'] for s in sel.values()})
print('| group | ' + ' | '.join(f'{t} {m}' for t, m in ARMS) + ' |')
print('|---|' + '---|' * len(ARMS))
for g in groups:
    row = []
    for k in ARMS:
        d = data[k]
        cell = []
        for corr in (False, True):
            xs = [r for t, r in d.items() if sel[t]['group'] == g and sel[t]['is_correct'] == corr]
            cell.append(f"{sum(bool(r['annotation']['findings']) for r in xs)}/{len(xs)}")
        row.append(' / '.join(cell))
    print(f'| {g} | ' + ' | '.join(row) + ' |')

print('\n## Agreement between the two models (same taxonomy, trace flagged or not)\n')
for tax in ('mast', 'maa'):
    a, b = data[(tax, 'gemini-4-hydrogen')], data[(tax, 'gpt-6.1-terra')]
    both = set(a) & set(b)
    c = collections.Counter((bool(a[t]['annotation']['findings']), bool(b[t]['annotation']['findings'])) for t in both)
    print(f'- {tax}: n={len(both)}; both flag {c[(True,True)]}, gemini only {c[(True,False)]}, gpt only {c[(False,True)]}, neither {c[(False,False)]}')

print('\n## Organiser-only: does the LLM point at the v3 counterfactual-positive step? (wrong runs with >=1 v3 positive)\n')
print('| arm | runs | any finding on a v3-positive step | earliest_fault_step = a v3-positive step | mapped step missing |')
print('|---|---|---|---|---|')
for (tax, m), d in data.items():
    n = hit = ef = mism = 0
    for t, r in d.items():
        s = sel[t]
        if s['is_correct'] or not s['v3_positive_steps']:
            continue
        n += 1
        pos = {f"s{int(x[1:]) + 1:02d}" for x in s['v3_positive_steps']}
        fl = steps_flagged(r)
        hit += bool(fl & pos)
        ef += r['annotation'].get('earliest_fault_step_id') in pos
        slots = {sl['step_id']: sl.get('agent_uid') for sl in r['annotation']['plan']['slots'] if sl.get('kind') == 'step'}
        mism += sum(1 for p in pos if p not in slots)
    print(f'| {tax} {m} | {n} | {hit} | {ef} | {mism} |')
