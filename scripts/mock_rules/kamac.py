"""Mock replies for KAMAC (methods/kamac/kamac_main.py) -- offline tests only.

reply(user, system, messages) -> str | None recognises the KAMAC prompts by
their fixed wording and returns plausible replies. Choices vary
deterministically with a digest of the question (and of the agent's whole
conversation where noted), so across a few questions the runs exercise both
branches: talk / no talk, gap / no gap, recruit / skip.
"""
import hashlib
import json
import re


def _h(*parts) -> int:
    return int(hashlib.md5("|".join(parts).encode()).hexdigest()[:8], 16)


def _question(messages) -> str:
    for m in messages:
        c = m.get("content") if isinstance(m.get("content"), str) else ""
        mm = re.search(r"Question: (.{0,200})", c)
        if mm:
            return mm.group(1)
    return ""


def _n_prior(messages, marker) -> int:
    return sum(1 for m in messages[:-1] if m.get("role") == "user" and marker in (m.get("content") or ""))


_SPECS = [("Cardiologist", "Specializes in disorders of the heart and vessels."),
          ("Orthopedic Surgeon", "Treats bone and joint conditions surgically."),
          ("Radiologist", "Interprets medical imaging studies.")]


def reply(user, system, messages):
    dig = hashlib.md5(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:8]
    q = _question(messages)
    qh = _h(q)
    if "which kind(s) of expert would you recruit" in user:
        n = int(re.search(r"You may recruit (\d+) expert", user).group(1))
        return "\n".join(f"{i+1}. {_SPECS[(qh + i) % 3][0]} - {_SPECS[(qh + i) % 3][1]} - Hierarchy: Independent"
                         for i in range(n))
    if "Give your answer in this format:" in user:
        letter = "CD"[_h(q, system) % 2]
        return (f"From my specialty's perspective the findings point to one option [{dig}]. "
                f"The other options do not fit the presentation as well.\nAnswer: {letter}")
    if "say whether you want to talk to any other expert (yes/no)" in user:
        turn = _n_prior(messages, "say whether you want to talk to any other expert")
        if turn == 0 and qh % 3 != 2:
            return f"Yes, I would like to discuss the case with a colleague [{dig}]."
        if (turn == 1 and _h(q, system) % 2 == 0) or (turn >= 2 and qh % 2 == 1):
            return f"Yes, one more exchange would help [{dig}]."
        return f"No, I am confident in my current assessment [{dig}]."
    if "Give the number of the expert you want to talk to" in user:
        nums = re.findall(r"^Agent (\d+): (.*?) - ", user, re.M)
        others = [k for k, role in nums if role.lower() not in system.lower()]
        return ",".join(others[:2]) if others else "1"
    if "leave your opinion for the expert you chose" in user:
        who = re.search(r"\(Agent \d+\. (.*?)\)", user)
        return (f"Dear {who.group(1) if who else 'colleague'}, I think the answer is D because the "
                f"key finding is best explained by it [{dig}].")
    if ("calls for help from another specialist" in user
            or "decide whether any additional type of specialist is needed" in user):
        first = (_n_prior(messages, "calls for help from another specialist")
                 + _n_prior(messages, "decide whether any additional type of specialist")) == 0
        if first and qh % 2 == 0:
            return f"Answer: yes\nReason: a Hematologist should review the coagulation findings [{dig}]."
        return f"Answer: no\nReason: the current team covers the case [{dig}]."
    if "Extract only the **unique, useful and specific** recommendations" in user:
        return f"Hematologist: to interpret the coagulation findings [{dig}]."
    if "Identified knowledge gap:" in user:
        if _n_prior(messages, "Identified knowledge gap:") == 0 and qh % 4 != 2:
            return ("1. Hematologist - Specializes in blood and coagulation disorders. - Hierarchy: Independent")
        return "<skip recruitment>"
    if "give your final answer to the question" in user:
        return f"After hearing my colleagues, I keep my reasoning on the key finding [{dig}].\nAnswer: D"
    if "decide the final answer to the question by majority vote" in user:
        return f"Answer: D) majority of the experts [{dig}]"
    return None
