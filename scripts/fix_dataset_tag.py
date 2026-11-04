"""Fix the dataset tag of archived runs (v11 r11, MHT #1 round 84): the multimodal mdagents runs were recorded
with dataset "medxpertqa-text" and the MAM runs with "medxpertqa_text" (gemini_run.sh passed
--test_dataset_name medxpertqa_text). The tag is part of run_id / question_id / pair_id / annotation_id, so it
is rewritten consistently in every string of every record: an exact value OLD, "|OLD|" inside ids and an
"OLD/" question_id prefix. Text of steps is not touched (strings equal to OLD or containing "|OLD|" / starting
with "OLD/" only). Works on .jsonl and .jsonl.gz in place.
  fix_dataset_tag.py --old medxpertqa-text --new pathvqa FILE [FILE ...]"""
import argparse, gzip, json, os


def fix(o, old, new):
    if isinstance(o, dict):
        return {k: fix(v, old, new) for k, v in o.items()}
    if isinstance(o, list):
        return [fix(v, old, new) for v in o]
    if isinstance(o, str):
        if o == old:
            return new
        if f"|{old}|" in o:
            o = o.replace(f"|{old}|", f"|{new}|")
        if o.startswith(f"{old}/"):
            o = new + o[len(old):]
        return o
    return o


ap = argparse.ArgumentParser()
ap.add_argument("--old", required=True); ap.add_argument("--new", required=True)
ap.add_argument("files", nargs="+")
a = ap.parse_args()
for p in a.files:
    op = gzip.open if p.endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    rows = [fix(r, a.old, a.new) for r in rows]
    tmp = p + ".tmp"
    with (gzip.open(tmp, "wt", encoding="utf-8") if p.endswith(".gz") else open(tmp, "w", encoding="utf-8")) as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)
    print(f"{p}: {len(rows)} records, {a.old} -> {a.new}")
