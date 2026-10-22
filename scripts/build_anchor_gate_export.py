#!/usr/bin/env python3
"""Select the current anchor injection versions from a full anchor export.

  python3 scripts/build_anchor_gate_export.py anchor_all.jsonl gate_export.jsonl [--new_sham_style_only]

Keeps all normal runs and RC runs; keeps PI runs only if they are the
length-matched version (`pi_length_match` set: older PI versions in
`*__inject.jsonl` run 1 are superseded by `*__inject_pi4.jsonl`). With
--new_sham_style_only, sham_style runs with sham_variant "style_v1" (the old
single wording that leaked "firmly"/"colleague") are dropped.
"""
import argparse
import json

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--new_sham_style_only", action="store_true")
a = ap.parse_args()
n_in = n_out = 0
with open(a.dst, "w") as f:
    for line in open(a.src):
        n_in += 1
        r = json.loads(line)
        if r["run_mode"] == "inject":
            inj = (r["labels"].get("injection") or [{}])[0]
            st = inj.get("effective_strategy")
            if st == "prompt_injection" and not inj.get("pi_length_match"):
                continue
            if a.new_sham_style_only and st == "sham_style" and \
                    inj.get("sham_variant") in (None, "style_v1"):
                continue
        f.write(line)
        n_out += 1
print(f"{n_out}/{n_in} runs -> {a.dst}")
