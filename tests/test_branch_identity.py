"""Branch / control run identity (issue #1, 2026-11-03).

Runs the exporter on all 16 branch-pilot output files of 2026-10-26 (264 records) plus their parent normal
runs, with and without the identity sidecar. No API calls; needs only files in the repo.

  python3 -m pytest -q tests/test_branch_identity.py
"""
import glob
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import branch_identity as bi  # noqa: E402

PILOT = os.path.join(REPO, "data_runs/branch_pilot_2026-10-26")
SIDECAR = os.path.join(PILOT, "branch_sidecar.jsonl")
NORMALS = [os.path.join(REPO, f"data_runs/anchor_llama_2026-10-21/{fw}__normal.jsonl.gz") for fw in ("llm_debate", "mdagents")]
BRANCH_FILES = sorted(glob.glob(os.path.join(PILOT, "*_out.jsonl.gz")))


def export(tmp_path, inputs, *extra):
    out = str(tmp_path / "export.jsonl")
    p = subprocess.run([sys.executable, os.path.join(REPO, "scripts/export_schema_v1.py"), *inputs, "--out", out,
                        "--phase_canonical", "none", *extra], capture_output=True, text=True, cwd=REPO)
    rows = [json.loads(l) for l in open(out)] if p.returncode == 0 else None
    return p, rows, out


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    p, rows, _ = export(tmp_path_factory.mktemp("exp"), NORMALS + BRANCH_FILES, "--branch_sidecar", SIDECAR, "--strict")
    assert p.returncode == 0, p.stderr[-2000:]
    return rows


def test_inventory():
    assert len(BRANCH_FILES) == 16


def test_unstamped_branch_files_fail_closed(tmp_path):
    p, rows, out = export(tmp_path, BRANCH_FILES)
    assert p.returncode != 0 and rows is None
    assert "no branch identity" in p.stderr
    assert not os.path.exists(out)


def test_duplicate_run_ids_stop_the_export(tmp_path):
    # the same normal file twice -> 300 colliding run_ids
    p, rows, out = export(tmp_path, NORMALS[:1] + NORMALS[:1])
    assert p.returncode == 2 and not os.path.exists(out)
    rep = json.load(open(out + ".problems.json"))
    assert len(rep["duplicate_run_ids"]) == 300


def test_unique_ids_and_groups(exported):
    br = [r for r in exported if r["run_mode"] == "branch"]
    assert len(br) == 264
    assert len({r["run_id"] for r in exported}) == len(exported)
    probs, summary = bi.validate([r["labels"]["branch"] for r in br],
                                 parents={r["run_id"] for r in exported if r["run_mode"] == "normal"})
    assert probs == []
    assert summary["pairs"] == 118 and summary["complete_rep0_pairs"] == 118
    assert summary["extra_control_reps"] == 28
    assert summary["rep_reasons"] == {"flipped_at_rep0": 12, "random_undetermined": 16}


def test_pairs_reach_each_other_and_their_parent(exported):
    by_id = {r["run_id"]: r for r in exported}
    groups = {}
    for r in exported:
        if r["run_mode"] == "branch":
            groups.setdefault(r["labels"]["branch"]["pair_id"], []).append(r)
    for pid, g in groups.items():
        parent = by_id[g[0]["labels"]["branch"]["parent_run_id"]]
        assert parent["run_mode"] == "normal" and parent["run_index"] == 0
        t = g[0]["labels"]["branch"]["candidate_step_id"]
        steps = [s["step_id"] for s in parent["steps"] if s["kind"] == "llm"]
        for r in g:
            b = r["labels"]["branch"]
            assert b["candidate_step_id"] == t
            assert [s["step_id"] for s in r["steps"] if s["kind"] == "llm"] == steps
            # the prefix before t is replayed in both arms: same text as the parent
            pos = steps.index(t)
            for s, ps in zip(r["steps"][:pos], parent["steps"][:pos]):
                assert s["output"] == ps["output"]
            if b["arm"] == "control":
                assert r["steps"][pos]["output"] == parent["steps"][pos]["output"]


def test_branch_metadata_stays_label_side(exported):
    assert sum(r["run_mode"] == "normal" for r in exported) == 600
    for r in exported:
        assert all("branch" not in s for s in r["steps"])
        if r["run_mode"] != "branch":
            assert "branch" not in r["labels"]
