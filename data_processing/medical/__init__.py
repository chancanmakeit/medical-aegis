# Medical dataset converters for AEGIS.
# Each converter turns a raw HuggingFace medical dataset into the AEGIS input
# format expected by main.py: a JSON list of samples, each:
#   {
#     "id": <str>,
#     "query": <str>,          # full prompt incl. options for MCQ
#     "answer": <str|num>,     # primary gold answer (legacy key main.py reads)
#     "ground_truth": {        # rich gold used by medical_verifier
#         "correct_answer": ...,
#         ... dataset-specific fields ...
#     }
#   }
