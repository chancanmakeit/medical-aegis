#!/usr/bin/env python3
"""Build multimodal MCQ datasets (mm_v1) from four public Hugging Face datasets.

Datasets (test split only):
  medxpertqa_mm  TsinghuaC3I/MedXpertQA, config MM (5-option MCQ, images in images.zip)
  pathvqa        flaviagiammarino/path-vqa (closed yes/no only)
  slake          BoKelvin/SLAKE (English, answer_type CLOSED; yes/no + parseable
                 "A or B" questions; images in imgs.zip)
  kvasir_vqa_x1  SimulaMet/Kvasir-VQA-x1 (complexity-1 rows whose single atomic
                 QA answer is yes/no and whose rephrased question passes a
                 polarity/semantic keyword check; images in the repo's images/)

Output records follow datasets/data/medxpertqa_text.json (id, query, answer,
ground_truth) plus image_paths (absolute, under /home/claude/mm_data/<ds>/images/)
and source metadata.  Per dataset: exact-duplicate removal on (normalised query,
image content hashes); eval/corpus split by a seeded (seed 0) shuffle of image
groups (connected components of questions sharing any image), eval = 200
questions (or half if < 400 kept), greedy fill, remaining groups -> corpus.

Writes datasets/data/mm_v1/<ds>_eval.json, <ds>_corpus.json, manifest.json.
Raw downloads go to /home/claude/mm_data/raw/<ds>/ (pinned to the commit sha
resolved at run time).  The HF token is read from /home/claude/.hf_token.

Usage: python3 -I scripts/build_mm_datasets.py [--only ds1,ds2]
"""
import argparse
import collections
import glob
import hashlib
import io
import json
import os
import random
import re
import sys
import zipfile

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download, snapshot_download
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "datasets", "data", "mm_v1")
MM_ROOT = "/home/claude/mm_data"
RAW = os.path.join(MM_ROOT, "raw")
TOKEN_FILE = "/home/claude/.hf_token"
SEED = 0
EVAL_N = 200
INSTRUCTION = "Answer with the single best option letter and a brief justification."
LETTERS = "ABCDEFGHIJ"

SOURCES = {
    "medxpertqa_mm": "TsinghuaC3I/MedXpertQA",
    "pathvqa": "flaviagiammarino/path-vqa",
    "slake": "BoKelvin/SLAKE",
    "kvasir_vqa_x1": "SimulaMet/Kvasir-VQA-x1",
}


def token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


# ----------------------------------------------------------------- helpers
def build_query(question, options):
    opts = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(options))
    return f"{question.strip()}\n\nOptions:\n{opts}\n\n{INSTRUCTION}"


def make_record(ds, orig_id, question, options, correct_idx, images, extra):
    letter = LETTERS[correct_idx]
    rec = {
        "id": f"{ds}_{orig_id}",
        "query": build_query(question, options),
        "answer": letter,
        "ground_truth": {"correct_answer": letter, "answer_text": options[correct_idx]},
        "image_paths": [p for p, _ in images],
        "image_sha1": [h for _, h in images],
        "source_dataset": SOURCES[ds],
        "source_split": "test",
        "orig_id": orig_id,
        "options": {LETTERS[i]: o for i, o in enumerate(options)},
    }
    rec.update(extra)
    return rec


class ImageStore:
    """Writes images to MM_ROOT/<ds>/images, verifies them with PIL, dedups by sha1."""

    def __init__(self, ds):
        self.dir = os.path.join(MM_ROOT, ds, "images")
        os.makedirs(self.dir, exist_ok=True)
        self.cache = {}
        self.converted = 0

    def put(self, name, data):
        """Store bytes under `name`; returns (abs_path, sha1 of the stored file)."""
        if name in self.cache:
            return self.cache[name]
        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode == "CMYK":  # many VLM APIs mis-render CMYK JPEGs
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=95)
            data = buf.getvalue()
            name = os.path.splitext(name)[0] + ".jpg"
            self.converted += 1
        path = os.path.join(self.dir, name)
        if not (os.path.exists(path) and open(path, "rb").read() == data):
            with open(path, "wb") as f:
                f.write(data)
        with Image.open(path) as chk:
            chk.verify()
        with Image.open(path) as chk:
            chk.load()
        res = (path, hashlib.sha1(data).hexdigest())
        self.cache[name] = res
        return res


def yes_no(ans):
    a = str(ans).strip().lower()
    return a if a in ("yes", "no") else None


YN_OPTIONS = ["yes", "no"]  # fixed order: A = yes, B = no


# ----------------------------------------------------------------- loaders
def load_medxpertqa(rev, tok, stats):
    d = os.path.join(RAW, "medxpertqa")
    repo = SOURCES["medxpertqa_mm"]
    for f in ["README.md", "MM/test.jsonl", "images.zip"]:
        hf_hub_download(repo, f, repo_type="dataset", revision=rev, token=tok, local_dir=d)
    rows = [json.loads(l) for l in open(os.path.join(d, "MM", "test.jsonl"))]
    stats["raw"] = len(rows)
    store = ImageStore("medxpertqa_mm")
    zf = zipfile.ZipFile(os.path.join(d, "images.zip"))
    members = {os.path.basename(n): n for n in zf.namelist() if n.startswith("images/") and not n.endswith("/")}
    recs, drop = [], collections.Counter()
    for r in rows:
        q = r["question"]
        m = re.search(r"\n\s*Answer Choices:\s*\(A\)", q)
        if not m:
            drop["no_answer_choices_block"] += 1
            continue
        stem, choices = q[: m.start()], q[m.start():]
        letters = sorted(r["options"])
        if letters != list("ABCDE") or r["label"] not in letters:
            drop["bad_options_or_label"] += 1
            continue
        # sanity: the inline choices list carries the same option texts
        inline = re.findall(r"\(([A-E])\)\s*(.*?)(?=\s*\([A-E]\)\s|\s*$)", choices.strip(), flags=re.S)
        if [k for k, _ in inline] != letters or any(v.strip() != r["options"][k].strip() for k, v in inline):
            stats.setdefault("inline_choice_text_mismatch_ids", []).append(r["id"])
        # source defect: a distractor's text carries the generator's rationale
        # ("...a plausible but incorrect distractor option...", MM-46, MM-839).
        # Multi-line markdown-table options (start with '|' or '**|') are legitimate.
        if any("\n" in v and not v.lstrip(" *").startswith("|") for v in r["options"].values()):
            drop["option_text_leaks_distractor_rationale"] += 1
            stats.setdefault("dropped_ids", []).append(r["id"])
            continue
        if any(f not in members for f in r["images"]):
            drop["image_missing_in_zip"] += 1
            continue
        imgs = [store.put(f, zf.read(members[f])) for f in r["images"]]
        options = [r["options"][k] for k in letters]
        recs.append(make_record(
            "medxpertqa_mm", r["id"], stem, options, letters.index(r["label"]), imgs,
            {"question_type": r["question_type"], "answer_type": "mcq5",
             "medical_task": r["medical_task"], "body_system": r["body_system"],
             "n_images": len(imgs),
             # options are just letter labels drawn in the image (e.g. "A. D")
             "options_are_image_labels": all(re.fullmatch(r"[A-Z]\d?", o.strip()) is not None
                                             for o in options),
             "options_markdown_table": any(o.lstrip(" *").startswith("|") for o in options)}))
    stats["dropped"] = dict(drop)
    stats["images_cmyk_converted"] = store.converted
    return recs


def load_pathvqa(rev, tok, stats):
    d = os.path.join(RAW, "pathvqa")
    repo = SOURCES["pathvqa"]
    files = [f for f in HfApi(token=tok).list_repo_files(repo, repo_type="dataset", revision=rev)
             if f.startswith("data/test-") and f.endswith(".parquet")]
    for f in ["README.md"] + files:
        hf_hub_download(repo, f, repo_type="dataset", revision=rev, token=tok, local_dir=d)
    df = pd.concat([pd.read_parquet(os.path.join(d, f)) for f in sorted(files)], ignore_index=True)
    stats["raw"] = len(df)
    store = ImageStore("pathvqa")
    recs, drop = [], collections.Counter()
    for i, r in df.iterrows():
        yn = yes_no(r["answer"])
        if yn is None:
            drop["open_ended_answer"] += 1
            continue
        data = r["image"]["bytes"]
        h = hashlib.sha1(data).hexdigest()
        ext = (Image.open(io.BytesIO(data)).format or "jpeg").lower().replace("jpeg", "jpg")
        img = store.put(f"pathvqa_{h[:16]}.{ext}", data)
        recs.append(make_record(
            "pathvqa", int(i), r["question"], YN_OPTIONS, YN_OPTIONS.index(yn), [img],
            {"question_type": "closed_yes_no", "answer_type": "yes_no",
             "orig_answer": r["answer"], "orig_image_name": r["image"].get("path"),
             "modality": "pathology"}))
    stats["dropped"] = dict(drop)
    stats["images_cmyk_converted"] = store.converted
    return recs


def parse_alternatives(question):
    """Return the list of alternatives named in an 'X or Y' question, or None."""
    q = question.strip().rstrip("?").strip()
    if " or " not in q:
        return None
    if "," in q:
        tail = q.split(",", 1)[1]
        alts = [a.strip() for a in re.split(r"\s*,\s*(?:or\s+)?|\s+or\s+", tail) if a.strip()]
    else:
        m = re.search(r"(\S+)\s+or\s+(\S+)$", q)
        if not m:
            return None
        alts = [m.group(1), m.group(2)]
    if len(alts) < 2 or len({a.lower() for a in alts}) != len(alts):
        return None
    if any(a.lower() not in question.lower() for a in alts):
        return None
    return alts


def load_slake(rev, tok, stats):
    d = os.path.join(RAW, "slake")
    repo = SOURCES["slake"]
    for f in ["README.md", "test.json", "imgs.zip"]:
        hf_hub_download(repo, f, repo_type="dataset", revision=rev, token=tok, local_dir=d)
    rows = json.load(open(os.path.join(d, "test.json")))
    stats["raw"] = len(rows)
    store = ImageStore("slake")
    zf = zipfile.ZipFile(os.path.join(d, "imgs.zip"))
    names = set(zf.namelist())
    recs, drop = [], collections.Counter()
    for r in rows:
        if r["q_lang"] != "en":
            drop["not_english"] += 1
            continue
        if r["answer_type"] != "CLOSED":
            drop["open_answer_type"] += 1
            continue
        yn = yes_no(r["answer"])
        if yn is not None:
            options, idx, qtype = YN_OPTIONS, YN_OPTIONS.index(yn), "closed_yes_no"
        else:
            alts = parse_alternatives(r["question"])
            if alts is None:
                drop["closed_non_yn_alternatives_unparseable"] += 1
                continue
            hit = [i for i, a in enumerate(alts) if a.lower() == r["answer"].strip().lower()]
            if len(hit) != 1:
                drop["closed_non_yn_answer_not_among_alternatives"] += 1
                stats.setdefault("answer_not_among_alternatives_examples", []).append(
                    {"qid": r["qid"], "question": r["question"], "answer": r["answer"], "alternatives": alts})
                continue
            options, idx, qtype = alts, hit[0], "closed_choice"
        member = "imgs/" + r["img_name"]
        if member not in names:
            drop["image_missing_in_zip"] += 1
            continue
        img = store.put(r["img_name"].replace("/", "_"), zf.read(member))
        recs.append(make_record(
            "slake", r["qid"], r["question"], options, idx, [img],
            {"question_type": qtype, "answer_type": "yes_no" if qtype == "closed_yes_no" else f"choice{len(options)}",
             "orig_answer": r["answer"], "modality": r["modality"], "organ": r["location"],
             "content_type": r["content_type"], "base_type": r["base_type"],
             "img_id": r["img_id"], "img_name": r["img_name"]}))
    stats["dropped"] = dict(drop)
    stats["images_cmyk_converted"] = store.converted
    return recs


# rephrased-question checks for Kvasir-VQA-x1 (atomic answer is the gold label;
# the x1 rephrase must keep the atomic question's meaning and polarity)
KVASIR_REQUIRE = {
    "box_artifact_presence": r"green or black",
    "text_presence": r"\btext",
    "finding_presence": r"abnormal|finding",
    "polyp_removal_status": r"\ball\b|complete",
}
KVASIR_FORBID = r"remain|residual"
AUX = r"^(is|are|was|were|has|have|had|does|do|did|can|could)\b"


def load_kvasir(rev, tok, stats):
    d = os.path.join(RAW, "kvasir_vqa_x1")
    repo = SOURCES["kvasir_vqa_x1"]
    for f in ["README.md", "data/test-00000-of-00001.parquet"]:
        hf_hub_download(repo, f, repo_type="dataset", revision=rev, token=tok, local_dir=d)
    df = pd.read_parquet(os.path.join(d, "data", "test-00000-of-00001.parquet"))
    stats["raw"] = len(df)
    stats["raw_by_complexity"] = {int(k): int(v) for k, v in df.complexity.value_counts().sort_index().items()}
    keep, drop = [], collections.Counter()
    for i, r in df.iterrows():
        atoms = json.loads(r["original"])
        if r["complexity"] != 1 or len(atoms) != 1:
            drop["multi_atom_complexity_2_3"] += 1
            continue
        yn = yes_no(atoms[0]["a"])
        if yn is None:
            drop["atomic_answer_not_yes_no"] += 1
            continue
        cls = list(r["question_class"])[0]
        q = r["question"].strip()
        if not re.match(AUX, q, flags=re.I):
            drop["rephrase_not_yes_no_form"] += 1
            continue
        if re.search(KVASIR_FORBID, q, flags=re.I):
            drop["rephrase_polarity_inverted"] += 1
            continue
        if cls not in KVASIR_REQUIRE or not re.search(KVASIR_REQUIRE[cls], q, flags=re.I):
            drop["rephrase_semantic_check_failed"] += 1
            continue
        keep.append((int(i), r, atoms[0], yn, cls))
    need = sorted({r["img_id"] for _, r, _, _, _ in keep})
    snapshot_download(repo, repo_type="dataset", revision=rev, token=tok, local_dir=d,
                      allow_patterns=[f"images/{x}.jpg" for x in need], max_workers=8)
    store = ImageStore("kvasir_vqa_x1")
    recs = []
    for i, r, atom, yn, cls in keep:
        src = os.path.join(d, "images", f"{r['img_id']}.jpg")
        if not os.path.exists(src):
            drop["image_missing"] += 1
            continue
        img = store.put(f"{r['img_id']}.jpg", open(src, "rb").read())
        recs.append(make_record(
            "kvasir_vqa_x1", i, r["question"], YN_OPTIONS, YN_OPTIONS.index(yn), [img],
            {"question_type": "closed_yes_no", "answer_type": "yes_no", "question_class": cls,
             "complexity": int(r["complexity"]), "img_id": r["img_id"],
             "atomic_question": atom["q"], "atomic_answer": atom["a"],
             "x1_answer": r["answer"], "modality": "GI endoscopy"}))
    stats["dropped"] = dict(drop)
    stats["images_cmyk_converted"] = store.converted
    return recs


LOADERS = {"medxpertqa_mm": load_medxpertqa, "pathvqa": load_pathvqa,
           "slake": load_slake, "kvasir_vqa_x1": load_kvasir}


# ----------------------------------------------------------------- dedup + split
def norm_text(s):
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(" ?.!")


def dedup(recs, stats):
    by_key = collections.OrderedDict()
    for r in recs:
        by_key.setdefault((norm_text(r["query"]), tuple(sorted(r["image_sha1"]))), []).append(r)
    out, n_dup, n_conf = [], 0, 0
    for group in by_key.values():
        if len({g["answer"] for g in group}) > 1:
            n_conf += len(group)
            stats.setdefault("conflicting_duplicate_ids", []).extend(g["id"] for g in group)
            continue
        out.append(group[0])
        n_dup += len(group) - 1
    stats["exact_duplicates_removed"] = n_dup
    stats["conflicting_duplicates_dropped"] = n_conf
    return out


def image_groups(recs):
    """Connected components of records that share any image (by content hash)."""
    parent = list(range(len(recs)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first = {}
    for i, r in enumerate(recs):
        for h in r["image_sha1"]:
            if h in first:
                parent[find(i)] = find(first[h])
            else:
                first[h] = i
    groups = collections.OrderedDict()
    for i in range(len(recs)):
        groups.setdefault(find(i), []).append(recs[i])
    # stable group key: smallest image hash in the component
    return {min(h for r in g for h in r["image_sha1"]): g for g in groups.values()}


def split(recs, stats):
    groups = image_groups(recs)
    keys = sorted(groups)
    random.Random(SEED).shuffle(keys)
    target = EVAL_N if len(recs) >= 2 * EVAL_N else len(recs) // 2
    ev, co, n_ev_groups = [], [], 0
    for k in keys:
        g = groups[k]
        for r in g:
            r["image_group"] = k[:16]
        if len(ev) + len(g) <= target and len(ev) < target:
            ev.extend(g)
            n_ev_groups += 1
        else:
            co.extend(g)
    stats.update({"n_image_groups": len(keys), "eval_target": target,
                  "eval_groups": n_ev_groups, "corpus_groups": len(keys) - n_ev_groups})
    return ev, co


def balance(recs):
    c = collections.Counter(r["ground_truth"]["answer_text"] if r.get("answer_type") == "yes_no" else r["answer"]
                            for r in recs)
    return dict(sorted(c.items()))


LICENSE_NOTES = {
    "medxpertqa_mm": "MIT (dataset card). Images originate from third-party medical sources per the paper.",
    "pathvqa": "MIT (dataset card); card notes image/caption copyrights belong to the textbook publishers and PEIR.",
    "slake": "CC-BY-4.0 (dataset card).",
    "kvasir_vqa_x1": "CC-BY-NC-4.0 (dataset card): academic / non-commercial use only.",
}
FILTERS = {
    "medxpertqa_mm": "config MM, test split; 5-option MCQ, options as given ('Answer Choices:' block stripped "
                     "from the stem and re-rendered as 'Options:'); all images attached; dropped: items whose "
                     "option text contains a non-table line break (leaked distractor-generation rationale). "
                     "Flags: options_are_image_labels (option texts are letters drawn in the image), "
                     "options_markdown_table",
    "pathvqa": "test split; answer in {yes, no} only; options fixed A. yes / B. no",
    "slake": "test.json; q_lang == en; answer_type == CLOSED; yes/no -> A. yes / B. no; other closed answers kept only "
             "if the question names >= 2 alternatives ('..., X or Y' / '..., X, Y or Z' after the first comma, or "
             "single-word 'X or Y' at the end) and the answer equals exactly one of them (options in question order)",
    "kvasir_vqa_x1": "test split; complexity == 1 (single atomic QA); atomic answer in {yes, no} (gold label); "
                     "x1 rephrased question used as the stem only if it starts with an auxiliary verb, contains no "
                     "'remain|residual' (polarity inversion vs atomic 'Have all polyps been removed?'), and matches a "
                     "per-class keyword (box artifact: 'green or black'; text: 'text'; finding: 'abnormal|finding'; "
                     "polyp removal: 'all|complete'); options A. yes / B. no",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    todo = [x for x in SOURCES if not args.only or x in args.only.split(",")]
    tok = token()
    api = HfApi(token=tok)
    os.makedirs(OUT_DIR, exist_ok=True)
    man_path = os.path.join(OUT_DIR, "manifest.json")
    manifest = json.load(open(man_path)) if os.path.exists(man_path) else {}
    manifest.update({
        "version": "mm_v1",
        "format": "list of MCQ records like datasets/data/medxpertqa_text.json + image_paths (absolute)",
        "image_root": MM_ROOT,
        "split_rule": (f"per dataset: exact dedup on (normalised query incl. options, sorted image sha1s); "
                       f"image groups = connected components of questions sharing any image (content sha1); "
                       f"group keys sorted then random.Random({SEED}).shuffle; walk groups in that order, a group "
                       f"goes to eval if it fits within the target (eval = {EVAL_N}, or half the kept items if "
                       f"< {2 * EVAL_N}), otherwise to corpus; files keep this seeded order (within a group: "
                       f"source order). No image is shared between eval and corpus."),
        "seed": SEED,
        "script": "scripts/build_mm_datasets.py",
    })
    manifest.setdefault("datasets", {})
    for ds in todo:
        repo = SOURCES[ds]
        info = api.dataset_info(repo)
        card = info.card_data.to_dict() if info.card_data else {}
        stats = {}
        print(f"[{ds}] {repo}@{info.sha}", flush=True)
        recs = LOADERS[ds](info.sha, tok, stats)
        n_conv = len(recs)
        recs = dedup(recs, stats)
        ev, co = split(recs, stats)
        for r in ev + co:
            missing = [p for p in r["image_paths"] if not os.path.isfile(p)]
            assert not missing, (r["id"], missing)
            assert r["answer"] in r["options"]
        with open(os.path.join(OUT_DIR, f"{ds}_eval.json"), "w") as f:
            json.dump(ev, f, ensure_ascii=False, indent=1)
        with open(os.path.join(OUT_DIR, f"{ds}_corpus.json"), "w") as f:
            json.dump(co, f, ensure_ascii=False, indent=1)
        used = {p for r in ev + co for p in r["image_paths"]}
        n_img = len(used)
        img_dir = os.path.join(MM_ROOT, ds, "images")
        for p in glob.glob(os.path.join(img_dir, "*")):  # orphans (e.g. dropped / CMYK originals)
            if p not in used:
                os.remove(p)
        manifest["datasets"][ds] = {
            "source_dataset": repo, "source_split": "test", "source_revision": info.sha,
            "license": card.get("license"), "license_note": LICENSE_NOTES[ds],
            "gated": info.gated, "private": info.private,
            "filters": FILTERS[ds],
            "n_raw": stats.pop("raw"), "n_converted": n_conv, "n_kept": len(recs),
            "n_eval": len(ev), "n_corpus": len(co), "n_images": n_img,
            "answer_balance": {"all": balance(recs), "eval": balance(ev), "corpus": balance(co)},
            "files": {"eval": f"datasets/data/mm_v1/{ds}_eval.json",
                      "corpus": f"datasets/data/mm_v1/{ds}_corpus.json"},
            "image_dir": os.path.join(MM_ROOT, ds, "images"),
            **stats,
        }
        print(f"[{ds}] raw={manifest['datasets'][ds]['n_raw']} kept={len(recs)} eval={len(ev)} "
              f"corpus={len(co)} images={n_img} balance={balance(recs)}", flush=True)
        with open(man_path, "w") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.exit(main())
