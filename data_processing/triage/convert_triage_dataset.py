"""
Convert the TriageAgent ESI triage test sets into the medical-aegis dataset
format, with the RAG evidence precomputed per case.

Source: the user's reproduction repo chancanmakeit/TriageAgent (TriageAgent,
Lu et al., EMNLP 2024 Findings). Its `data/Test-{1,2,3}` files are messy TSVs
(vignettes contain newlines/tabs; the label separator is sometimes a space);
records are recovered exactly as its `src/data_loader.py` does. Labels are ESI
1-5, a few are "4 or 5" (either is correct).

Retrieval reproduces its `src/rag.py` (per-page pdftotext text -> 600-char
chunks with 120 overlap -> TF-IDF, min_df 2, cosine, top-3, query = vignette).
It is deterministic, so precomputing it here gives the same hits the upstream
pipeline retrieves at run time, and runs need neither the PDF nor pdftotext.

Usage (from the medical-aegis root):
  python3 data_processing/triage/convert_triage_dataset.py \
      --triage_repo /home/claude/triageagent --out datasets/data/triage_esi.json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile

import numpy as np

# ------------------------------------------------------------------ data
LABEL_RE = re.compile(r"[ \t]([1-5](?: or [1-5])?)[ \t]*\r?$", re.M)


def parse_file(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    records, prev_end = [], 0
    for i, m in enumerate(LABEL_RE.finditer(text)):
        body = text[prev_end:m.start()].strip()
        prev_end = m.end()
        if not body or len(body) < 30:      # header line / degenerate fragment
            continue
        records.append({"vignette": " ".join(body.split()), "label_raw": m.group(1).strip(),
                        "upstream_id": f"{os.path.basename(path)}#{i}"})
    return records


# ------------------------------------------------------------------ RAG (port of src/rag.py)
CHUNK_CHARS, CHUNK_OVERLAP, MIN_DF, MAX_FEATURES = 600, 120, 2, 20000
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset("""a an the and or of to in on for with is are was were be been
being by at as from that this these those it its into out over under again
further then once here there when where which who whom whose why how all any
both each few more most other some such no nor not only own same so than too
very can will just don should now he she they them his her their we you your
i me my us our him her had has have do does did doing would could ought am
are was were be been being s t d ll m re ve y ain aren couldn didn doesn
hadn hasn haven isn ma mightn mustn needn shan shouldn wasn weren won wouldn
""".split())


def tokenize(text):
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2 and t not in _STOP]


def handbook_pages(pdf_path):
    if not shutil.which("pdftotext"):
        raise SystemExit("pdftotext not found (poppler-utils); upstream prefers it, and the "
                         "pypdf fallback yields different chunks")
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        subprocess.run(["pdftotext", "-layout", pdf_path, tmp_path], check=True, timeout=120)
        raw = open(tmp_path, encoding="utf-8", errors="replace").read()
    finally:
        os.unlink(tmp_path)
    pages = []
    for i, page_text in enumerate(raw.split("\f")):
        t = re.sub(r"[ \t]+", " ", page_text)
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        t = re.sub(r"-\n(?=[a-z0-9])", "-", t)
        t = re.sub(r"\s+", " ", t)
        if len(t) > 100:
            pages.append({"page": i + 1, "text": t})
    return pages


def chunk_pages(pages):
    chunks = []
    for p in pages:
        text, start = p["text"], 0
        while start < len(text):
            end = min(start + CHUNK_CHARS, len(text))
            if end < len(text):
                cut = text.rfind(". ", start, end)
                if cut > start + 200:
                    end = cut + 1
            piece = text[start:end].strip()
            if len(piece) > 150:
                chunks.append({"page": p["page"], "text": piece})
            if end >= len(text):
                break
            start = end - CHUNK_OVERLAP
    return chunks


def build_index(chunks):
    docs = [tokenize(c["text"]) for c in chunks]
    df = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    vocab = [t for t, c in sorted(df.items(), key=lambda kv: -kv[1]) if c >= MIN_DF][:MAX_FEATURES]
    idx = {t: i for i, t in enumerate(vocab)}
    n = len(docs)
    idf = np.array([np.log((n + 1) / (df[t] + 1)) + 1.0 for t in vocab], dtype=np.float32)
    mat = np.zeros((n, len(vocab)), dtype=np.float32)
    for di, toks in enumerate(docs):
        counts = {}
        for t in toks:
            j = idx.get(t)
            if j is not None:
                counts[j] = counts.get(j, 0) + 1
        for j, c in counts.items():
            mat[di, j] = (1 + np.log(c)) * idf[j]
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    return {"idx": idx, "idf": idf, "matrix": mat, "chunks": chunks}


def retrieve(query, index, k=3):
    q = np.zeros(len(index["idx"]), dtype=np.float32)
    for t in tokenize(query):
        j = index["idx"].get(t)
        if j is not None:
            q[j] += index["idf"][j]
    q /= np.linalg.norm(q) + 1e-9
    scores = index["matrix"] @ q
    return [{"page": index["chunks"][i]["page"], "text": index["chunks"][i]["text"],
             "score": float(scores[i])} for i in np.argsort(-scores)[:k]]


# ------------------------------------------------------------------ main
QUERY_TEMPLATE = ("Assign the Emergency Severity Index (ESI) triage level (1-5) for the "
                  "following emergency department case.\n\nClinical record:\n{vignette}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triage_repo", required=True, help="clone of chancanmakeit/TriageAgent")
    ap.add_argument("--splits", nargs="+", default=["Test-1", "Test-2", "Test-3"])
    ap.add_argument("--top_k", type=int, default=3)
    ap.add_argument("--out", default="datasets/data/triage_esi.json")
    args = ap.parse_args()

    pdf = os.path.join(args.triage_repo, "references", "esi_handbook.pdf")
    index = build_index(chunk_pages(handbook_pages(pdf)))
    out = []
    for split in args.splits:
        recs = parse_file(os.path.join(args.triage_repo, "data", split))
        print(f"{split}: {len(recs)} records")
        for n, r in enumerate(recs):
            acceptable = re.findall(r"[1-5]", r["label_raw"])
            out.append({
                "id": f"triage_{split.lower().replace('-', '')}_{n:03d}",
                "query": QUERY_TEMPLATE.format(vignette=r["vignette"]),
                "answer": r["label_raw"],
                "ground_truth": {
                    "correct_answer": acceptable[0] if len(acceptable) == 1 else r["label_raw"],
                    "acceptable_answers": acceptable,
                    "classes": ["1", "2", "3", "4", "5"],
                },
                "triage": {
                    "vignette": r["vignette"],
                    "retrieval": {"tool": "tfidf_esi_handbook", "top_k": args.top_k,
                                  "query": "vignette",
                                  "hits": retrieve(r["vignette"], index, args.top_k)},
                },
                "provenance": {"source": "TriageAgent (Lu et al., EMNLP 2024 Findings) / ESI Handbook v4",
                               "split": split, "upstream_id": r["upstream_id"]},
            })
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    multi = sum(len(x["ground_truth"]["acceptable_answers"]) > 1 for x in out)
    print(f"wrote {len(out)} cases ({multi} with more than one acceptable level) -> {args.out}")


if __name__ == "__main__":
    main()
