"""Mock replies for MAC (methods/mac_groupchat/mac_groupchat_main.py) -- offline
tests only.

reply(user, system, messages) -> str | None recognises the MAC prompts (the
AutoGen speaker-selection prompt, Doctor / Supervisor / Consultant turns) by
their system messages and returns plausible replies. Everything is stateless
and varies deterministically with a digest of the question and the transcript
length, so across a few questions the runs exercise: valid selections,
retries ("multiple names" / "no name"), exhausted retries (round-robin
fallback), repeat speakers, early Supervisor TERMINATE and runs that reach
n_round.
"""
import hashlib
import json
import re

_INIT = "Here is a multiple-choice question for analysis"


def _h(*parts) -> int:
    return int(hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)


def _c(m) -> str:
    c = m.get("content")
    return c if isinstance(c, str) else ""


def _case(messages):
    for m in messages:
        if _INIT in _c(m):
            return _c(m)
    return ""


def _options(case):
    return dict(re.findall(r"(?m)^\s*([A-J])\.\s+(.*\S)\s*$", case))


def _transcript(messages):
    """Group messages after the system prompt (initial message included)."""
    out, started = [], False
    for m in messages:
        if _INIT in _c(m):
            started = True
        if started and m.get("role") in ("user", "assistant") and not _c(m).startswith(
                ("You provided more than one name", "You didn't choose a speaker")):
            out.append(m)
    return out


def _intended(names, tr, qh):
    """Who the mock selector wants next."""
    n = len(tr)
    docs = [x for x in names if x != "Supervisor"]
    if n == 1:
        return docs[0]
    last = tr[-1].get("name")
    if _h(qh, n, "repeat") % 6 == 0 and last:
        return last
    if last == "Supervisor":
        return docs[(n + qh) % len(docs)]
    if (n - 1) % 3 == 0:
        return "Supervisor"
    return docs[(n - 1) % len(docs)]


def _select(user, system, messages):
    lst = re.search(r"select the next role from \[([^\]]*)\] to play", system)
    names = re.findall(r"'([^']+)'", lst.group(1))
    tr = [m for m in messages if m.get("role") == "user" and m.get("name")]
    case = _case(messages)
    qh = _h(case)
    n = len(tr)
    want = _intended(names, tr, qh)
    is_retry = user.startswith(("You provided more than one name", "You didn't choose a speaker"))
    r = _h(qh, n, "sel") % 8
    if is_retry:
        if r == 0:      # still no single name -> attempts exhausted -> next_agent fallback
            return "Let the team decide."
        return want
    if r in (0, 1) and n > 1:
        others = [x for x in names if x != want]
        return f"{want} should answer {others[0]}'s point, then {others[-1]} can follow."
    if r == 2 and n > 1:
        return "The next role should be the most relevant expert."
    return want


def _doctor(system, messages):
    m = re.search(r"You are (.+?)\. This is a hypothetical scenario", system)
    me = m.group(1) if m else "Doctor"
    case = _case(messages)
    opts = _options(case)
    letters = sorted(opts) or list("ABCD")
    qh = _h(case)
    base = letters[qh % len(letters)]
    own_turns = sum(1 for x in _transcript(messages) if x.get("role") == "assistant")
    sup_ans = None
    for x in _transcript(messages):
        if x.get("name") == "Supervisor":
            mm = re.search(r'"Most Likely Answer"\s*:\s*"([A-J])', _c(x))
            if mm:
                sup_ans = mm.group(1)
    idx = _h(me) % 3
    if own_turns == 0:
        ans = letters[(qh + 1) % len(letters)] if (qh + idx) % 3 == 0 else base
    else:
        ans = sup_ans or base
    alt = letters[(letters.index(ans) + 2) % len(letters)]
    n = len(_transcript(messages))
    last = _transcript(messages)[-1]
    reacting = f" I have read {last.get('name')}'s remarks and" if last.get("name") else ""
    return (f"As {me}, here is my analysis at message {n} of the discussion.{reacting} the key "
            f"findings in the stem point toward option {ans} ({opts.get(ans, 'n/a')[:60]}). "
            f"Option {alt} remains a possible alternative but fits the presentation less well "
            f"(digest {_h(case, me, n) % 10000}).\n\nAnswer: {ans}")


def _supervisor(system, messages):
    case = _case(messages)
    opts = _options(case)
    letters = sorted(opts) or list("ABCD")
    qh = _h(case)
    tr = _transcript(messages)
    latest = {}
    for x in tr:
        if x.get("role") == "user" and x.get("name") and x.get("name") != "Supervisor":
            mm = re.search(r"Answer:\s*([A-J])", _c(x))
            if mm:
                latest[x["name"]] = mm.group(1)
    votes = list(latest.values())
    maj = max(set(votes), key=votes.count) if votes else letters[qh % len(letters)]
    agree = len(votes) >= 2 and len(set(votes)) == 1
    terminate = agree and qh % 2 == 0
    others = [l for l in letters if l != maj][:2]
    summary = {"Most Likely Answer": maj,
               "Other Possible Answers": ", ".join(others),
               "Areas of Disagreement": "None" if agree else
               f"{len(set(votes))} different options among {len(votes)} doctors"}
    body = (f"Supervisor review after {len(tr)} messages: the doctors' current answers are "
            f"{latest or 'not yet available'}. I challenge the team to rule out option "
            f"{others[0]} explicitly before we settle (digest {_h(case, len(tr)) % 10000}).\n\n"
            f"```json\n{json.dumps(summary, indent=4)}\n```")
    return body + ("\n\nTERMINATE" if terminate else "")


def _consultant(user):
    k = int((re.search(r"select the top (\d+)", user) or [None, 4])[1])
    pool = ["Orthopedic surgeon", "Radiologist", "Rheumatologist", "Infectious disease specialist",
            "Pathologist", "Neurologist"]
    return "```json\n" + json.dumps({"top_k_specialists": pool[:k]}) + "\n```"


def reply(user, system, messages):
    if "You are in a role play game. The following roles are available:" in system:
        if "Read the above conversation. Then select the next role from" in user \
                or user.startswith(("You provided more than one name", "You didn't choose a speaker")) \
                or _INIT in user:
            return _select(user, system, messages)
        return None
    if "You are a Senior Medical Consultant." in system and "top_k_specialists" in user:
        return _consultant(user)
    if "You are the Medical Supervisor in a hypothetical scenario." in system and _case(messages):
        return _supervisor(system, messages)
    if "This is a hypothetical scenario involving no actual patients." in system and _case(messages):
        return _doctor(system, messages)
    return None
