"""Shared parsing of what an agent's reply COMMITS to, for `structured`
step fields (MedHyperTrace spec v1.1: the first divergent step is defined on
this semantic layer).

`mcq_answer` returns the option letter of the LAST explicit answer statement
in the reply, or None when the reply ends by declining to commit (a hedge
after the last statement). It recognises the phrasings models use and the
ones the injection factory's MCQ corruption templates append ("Final answer:
X", "the answer is (actually) X", "Answer: X", "Option: X", a reply that is
just "X."), so a corrupted reply is parsed as the answer it now states.
"""
import re
from typing import Optional

_LETTER = r"\(?([A-J])\)?(?![A-Za-z])"
_COMMIT = re.compile(
    r"(?:final\s+answer\s*(?:is|[:：])|(?<![a-z])answer\s+is(?:\s+actually)?|(?<![a-z])answer\s*[:：]"
    r"|\boption\s*[:：]|\bgoing\s+with|\bcorrect\s+(?:answer|option)\s+is)\s*\**\s*" + _LETTER,
    re.IGNORECASE)
_HEDGE = re.compile(r"cannot commit|can't commit|not sure|equally (?:valid|plausible|likely)", re.IGNORECASE)


def mcq_answer(text: str) -> Optional[str]:
    t = (text or "").strip()
    m = re.fullmatch(r"\(?([A-J])\)?\.?", t)
    if m:
        return m.group(1).upper()
    hits = list(_COMMIT.finditer(t))
    if not hits:
        return None
    last = hits[-1]
    if _HEDGE.search(t[last.end():]):
        return None
    return last.group(1).upper()


def _plain(t: str) -> str:
    return re.sub(r"[*_`]", "", t or "").lower()


def concluding_paragraph(text: str) -> str:
    """The last paragraph of a reply (the last two when the last is short)."""
    paras = [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    if not paras:
        return ""
    concl = paras[-1]
    if len(concl) < 80 and len(paras) > 1:
        concl = paras[-2] + "\n\n" + concl
    return concl


def mcq_leaning(text: str, options: dict) -> Optional[str]:
    """The option a reply favours: its committed letter (mcq_answer), else the
    option whose text its concluding paragraph names last (analyses and
    reports often name the option by content, e.g. "*Streptococcus
    pneumoniae* is the most likely organism"). None when neither is found.
    Used for `structured.answer` of analysis steps and by the factory's
    in-place corruption, so both agree on what a step's answer is."""
    a = mcq_answer(text)
    if a is not None or not options:
        return a
    low = _plain(concluding_paragraph(text))
    best, pos = None, -1
    for k, v in options.items():
        nv = _plain(str(v))
        if len(nv) >= 4:
            i = low.rfind(nv)
            if i > pos:
                best, pos = k, i
    return best
