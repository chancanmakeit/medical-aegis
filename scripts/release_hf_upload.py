import os, sys
from huggingface_hub import HfApi
tok = open("/home/claude/.hf_write_token").read().strip()
api = HfApi(token=tok)
REPO = "UUUooUUU/medical-mas-trajectories"
api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
MA = "/home/claude/medical-aegis"
jobs = [
    ("/home/claude/release", "", None),
    (f"{MA}/data_runs/eval_v3_2026-11-04", "medical_aegis/eval_v3_branch", None),
    (f"{MA}/data_runs/corpus_v1_2026-11-04", "medical_aegis/corpus_v1", None),
    (f"{MA}/data_runs/anchor_llama_2026-10-21", "medical_aegis/anchor_llama", None),
    (f"{MA}/data_runs/gemini_trial_2026-11-03", "medical_aegis/pilot_and_trials/gemini_trial_2026-11-03", None),
    (f"{MA}/data_runs/branch_pilot_2026-10-26", "medical_aegis/pilot_and_trials/branch_pilot_2026-10-26", None),
    (f"{MA}/data_runs/branch_planA_2026-11-03", "medical_aegis/pilot_and_trials/branch_planA_2026-11-03", None),
    (f"{MA}/docs/requests/samples/pilot_2026-10-20", "medical_aegis/pilot_and_trials/pilot_2026-10-20", None),
    (f"{MA}/docs/requests/samples/eval_v3_2026-11-04", "medical_aegis/eval_v3_branch/report", None),
    (f"{MA}/datasets/audio", "medical_aegis/audio", None),
]
only = sys.argv[1:] or None
for i, (src, dst, pat) in enumerate(jobs):
    if only and str(i) not in only:
        continue
    r = api.upload_folder(folder_path=src, path_in_repo=dst or ".", repo_id=REPO, repo_type="dataset",
                          commit_message=f"add {dst or 'root docs + annotation_ready'}", allow_patterns=pat)
    print(i, dst, "ok", flush=True)
print("done")
