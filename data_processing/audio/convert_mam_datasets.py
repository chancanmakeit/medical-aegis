#!/usr/bin/env python3
"""Build MAM audio datasets (Heartbeat A/B, Sound-Dr) as AEGIS dataset JSON.

Sources (HF, user's collection):
  UUUooUUU/Heartbeat : PASCAL CHSC2011 zips (Atraining_*.zip, Btraining_*.zip)
  UUUooUUU/Sound-Dr  : data.csv + cough/*.wav

Datasets produced
  heartbeat_b : digital-stethoscope set B, classes normal / murmur / extrasystole
                (the noisy* sub-folders are excluded), up to --per_class each
  heartbeat_a : iStethoscope set A, classes normal / murmur / extra heart sound /
                artifact, up to --per_class each (extrahls has only 19)
  sounddr     : cough recordings, task = respiratory symptoms yes / no, using the
                label definition of the official baseline
                (SoundDr_BaselineSystem.py: label_symptom =
                 symptoms_status_choice != "['No']"); the CSV's own `label`
                column is undocumented and NOT used.

Leakage guard: source file names encode the label (Sound-Dr "bad_cough_...",
Heartbeat folder names), so audio is written as <dataset>_<nnnn>.wav and the
original name is stored only under `provenance` (label-side, never shown to a
model). Audio is resampled to 16 kHz mono 16-bit WAV (Heartbeat B is 4 kHz).

Output sample:
  {"id", "query", "answer", "ground_truth": {"correct_answer", "classes", "aliases"},
   "audio": {"path": "<audio_dir>/<id>.wav", "duration_s", "sample_rate": 16000},
   "provenance": {"source": ..., "source_file": ...}}

Usage:
  python data_processing/audio/convert_mam_datasets.py --dataset heartbeat_b \
      --heartbeat_dir <unzipped dir> --audio_dir datasets/audio --out datasets/data/heartbeat_b.json
  python data_processing/audio/convert_mam_datasets.py --dataset sounddr \
      --sounddr_csv <data.csv> --sounddr_dir <dir with cough/*.wav> ...
"""
import argparse
import glob
import json
import os
import random
import wave

import numpy as np
from scipy.signal import resample_poly

TARGET_SR = 16000

HEARTBEAT = {
    "heartbeat_b": {
        "classes": {"normal": "Training B Normal", "murmur": "Btraining_murmur",
                    "extrasystole": "Btraining_extrastole"},
        "aliases": {"extrasystole": ["extrastole", "extra systole", "premature beat"]},
        "question": ("This is a heart sound recording captured with a digital stethoscope. "
                     "Which category does it belong to? Options: normal, murmur, extrasystole. "
                     "Answer with one of these labels."),
    },
    "heartbeat_a": {
        "classes": {"normal": "Atraining_normal", "murmur": "Atraining_murmur",
                    "extra heart sound": "Atraining_extrahls", "artifact": "Atraining_artifact"},
        "aliases": {"extra heart sound": ["extrahls", "extra heart sounds", "gallop"]},
        "question": ("This is a heart sound recording captured with a smartphone stethoscope app. "
                     "Which category does it belong to? Options: normal, murmur, extra heart sound, artifact. "
                     "Answer with one of these labels."),
    },
}
SOUNDDR_QUESTION = ("This is a recording of a person coughing. Does this person currently have "
                    "respiratory symptoms? Options: yes, no. Answer with one of these labels.")


def _read_wav(path):
    with wave.open(path) as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if sw == 1:
        x = (x - 128.0) / 128.0
    else:
        x = x / float(np.iinfo(dtype).max)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def _write_wav16k(x, sr, out_path):
    if sr != TARGET_SR:
        g = np.gcd(sr, TARGET_SR)
        x = resample_poly(x, TARGET_SR // g, sr // g)
    x = np.clip(x, -1.0, 1.0)
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(TARGET_SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return len(x) / TARGET_SR


def build_heartbeat(name, root, audio_dir, per_class, seed):
    spec = HEARTBEAT[name]
    rng = random.Random(seed)
    picked = []
    for label, folder in spec["classes"].items():
        files = sorted(f for f in glob.glob(os.path.join(root, folder, "*.wav")))  # top level only: no noisy*
        rng.shuffle(files)
        picked += [(label, f) for f in files[:per_class]]
    rng.shuffle(picked)
    return _emit(name, picked, spec["question"], list(spec["classes"]), spec["aliases"], audio_dir, "Heartbeat (PASCAL CHSC2011)")


def build_sounddr(csv_path, sdr_dir, audio_dir, per_class, seed):
    import pandas as pd
    df = pd.read_csv(csv_path)
    df["label_symptom"] = (df["symptoms_status_choice"].map(str) != "['No']").astype(int)
    rng = random.Random(seed)
    picked = []
    for val, label in ((1, "yes"), (0, "no")):
        rows = df[df["label_symptom"] == val]["file_cough"].tolist()
        rng.shuffle(rows)
        picked += [(label, os.path.join(sdr_dir, r + ".wav")) for r in rows[:per_class]]
    rng.shuffle(picked)
    return _emit("sounddr", picked, SOUNDDR_QUESTION, ["yes", "no"], {"yes": [], "no": []}, audio_dir, "Sound-Dr")


def _emit(name, picked, question, classes, aliases, audio_dir, source):
    os.makedirs(os.path.join(audio_dir, name), exist_ok=True)
    out = []
    for i, (label, src) in enumerate(picked):
        sid = f"{name}_{i:04d}"
        dst = os.path.join(audio_dir, name, f"{sid}.wav")
        x, sr = _read_wav(src)
        dur = _write_wav16k(x, sr, dst)
        out.append({
            "id": sid,
            "query": question,
            "answer": label,
            "ground_truth": {"correct_answer": label, "classes": classes, "aliases": aliases},
            "audio": {"path": dst, "duration_s": round(dur, 2), "sample_rate": TARGET_SR},
            "provenance": {"source": source, "source_file": os.path.relpath(src)},
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=["heartbeat_a", "heartbeat_b", "sounddr"])
    ap.add_argument("--heartbeat_dir", help="folder containing the unzipped Heartbeat class folders")
    ap.add_argument("--sounddr_csv"); ap.add_argument("--sounddr_dir")
    ap.add_argument("--audio_dir", default="datasets/audio")
    ap.add_argument("--out", help="output JSON (required unless --list_only)")
    ap.add_argument("--per_class", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--list_only", action="store_true", help="sounddr: print the cough files to download and exit")
    a = ap.parse_args()
    if a.dataset == "sounddr" and a.list_only:
        import pandas as pd
        df = pd.read_csv(a.sounddr_csv)
        df["label_symptom"] = (df["symptoms_status_choice"].map(str) != "['No']").astype(int)
        rng = random.Random(a.seed)
        for val in (1, 0):
            rows = df[df["label_symptom"] == val]["file_cough"].tolist(); rng.shuffle(rows)
            for r in rows[: a.per_class]:
                print(r + ".wav")
        return
    if a.dataset.startswith("heartbeat"):
        data = build_heartbeat(a.dataset, a.heartbeat_dir, a.audio_dir, a.per_class, a.seed)
    else:
        data = build_sounddr(a.sounddr_csv, a.sounddr_dir, a.audio_dir, a.per_class, a.seed)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(data, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(f"wrote {len(data)} samples to {a.out}; labels {dict(Counter(d['answer'] for d in data))}; "
          f"duration {min(d['audio']['duration_s'] for d in data)}-{max(d['audio']['duration_s'] for d in data)}s")


if __name__ == "__main__":
    main()
