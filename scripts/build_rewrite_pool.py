#!/usr/bin/env python3
"""Build a rewrite pool for the factory's response-corruption templates.

Why: with direct_prepend, every corrupted step of one FM type ends with the same
fixed sentence (e.g. "Wait — after re-reading, the answer is actually A."). A
classifier can then locate injected steps by spotting the template instead of
the reasoning error (MedHyperTrace measured 0.90 step-localisation accuracy for
a template detector on old ClinicalAgent data). The pool holds many paraphrases
per template; the factory draws one per corruption (seeded, recorded in
labels as template_variant).

One LLM call per template asks for N paraphrases. Each paraphrase must pass
checks before it enters the pool:
  * the same placeholders, in the same order, and {orig} kept at the start
    (or end) if the original has it there;
  * no hard-coded answers: no option letters A-J, digits, or tags that are not
    in the original;
  * the same parsed outcome as the original (MCQ: methods.answer_parsing
    .mcq_answer on a filled-in example gives the slot letter, or None for the
    hedging templates);
  * length of the fixed text within 0.4x-3x of the original's;
  * English, no newline changes beyond the original's paragraph breaks.

Pools can be built per backbone (key = model name), so the wording sounds like
the model whose steps it is spliced into; the factory falls back to "default".

Usage:
  python scripts/build_rewrite_pool.py --model mercury-2.5-preview \
      --base_url https://aihubmix.com/v1 --api_key_env AIHUBMIX_API_KEY \
      --tables DIRECT_MCQ --n 30 --out malicious_factory/rewrite_pool.json
  (adds/replaces pools[<model>][<TABLE>|<FM>] in --out; --dry_run prints the
   prompts and token estimate without calling the API)
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from malicious_factory.fm_malicious_system import FMMaliciousFactory as F  # noqa: E402
from methods.answer_parsing import mcq_answer  # noqa: E402

TABLES = {
    "DIRECT_MCQ": (F._DIRECT_RESPONSE_TEMPLATES_MCQ, False),
    "DIRECT_NUMERIC": (F._DIRECT_RESPONSE_TEMPLATES_NUMERIC, False),
    "DIRECT_ERROR_CORRECTION": (F._DIRECT_RESPONSE_TEMPLATES_ERROR_CORRECTION, False),
    "DIRECT_OPEN": (F._DIRECT_RESPONSE_TEMPLATES_OPEN, False),
    "PROBABILITY": (F._PROBABILITY_CORRUPTION, True),
    "CLASSIFICATION_FIELD": (F._CLASSIFICATION_FIELD_CORRUPTION, True),
    "CLASSIFICATION": (F._CLASSIFICATION_CORRUPTION, True),
}
CONTEXT = {
    "DIRECT_MCQ": "a medical agent's reply to a multiple-choice question; {orig} is the agent's original reply, {wrong_answer} is an option letter",
    "DIRECT_NUMERIC": "a medical agent's reply to a calculation question; {orig} is the original reply, {wrong_answer} is a number",
    "DIRECT_ERROR_CORRECTION": "a medical agent's verdict on which sentence of a clinical note has an error; {orig} is the original reply, {wrong_answer} is a verdict",
    "DIRECT_OPEN": "a medical agent's free-text answer; {orig} is the original reply",
    "PROBABILITY": "a clinical-trial agent's probability estimate; {orig} is the original reply, {tags} are its probability tags",
    "CLASSIFICATION_FIELD": "a note a triage clinician appends to a labelled answer such as 'ESI level: 3'; {wrong_answer} is the label value",
    "CLASSIFICATION": "the reasoning text of an agent that classifies sensor or audio data; {orig_reason} is its original reasoning, {wrong_answer} is a class name",
}
PH = re.compile(r"\{(\w+)\}")
SAMPLE_ORIG = ("Considering the presentation and the mechanism, option C best fits "
               "the findings.\n\nThe answer is C.")


def fixed_text(t):
    return PH.sub("", t)


def prompt_for(table, fm, tpl, n):
    return (
        "We are building a research dataset that simulates mistakes made by agents in a "
        "medical multi-agent system, so that a model can learn to locate the faulty step. "
        f"Below is a sentence template used to write one such mistake into {CONTEXT[table]}.\n\n"
        f"Error type: {fm}\nTemplate:\n<<<\n{tpl}\n>>>\n\n"
        f"Write {n} different rewrites of this template. Requirements:\n"
        "- Same meaning and the same kind of mistake; vary wording, sentence structure and "
        "register (terse, conversational, clinical, hedged, matter-of-fact).\n"
        "- Keep every placeholder in curly braces exactly as written, each exactly as often "
        "and in the same order as in the template. Do not add new placeholders.\n"
        "- If the template starts or ends with {orig} (or {orig_reason}), so must every rewrite. "
        "Keep blank lines (\\n\\n) around {orig} as in the template.\n"
        "- Never write a concrete answer (no option letters, numbers, or labels); the "
        "placeholders supply them.\n"
        "- Do not mention simulations, templates, or that this is an error.\n"
        + MCQ_RULE.get((table, _mcq_kind(tpl)), "")
        + f"Return only a JSON array of {n} strings."
    )


def _mcq_kind(tpl):
    if "{wrong_answer}" not in tpl:
        return "keep"
    out = mcq_answer(tpl.format(orig=SAMPLE_ORIG, wrong_answer="E"))
    return "commit" if out == "E" else ("hedge" if out is None else "keep")


# Downstream parsers (methods/answer_parsing.mcq_answer and the frameworks'
# own extractors) must still read the corrupted answer, so the sentence that
# states it keeps an explicit answer phrase; the rest of the wording varies.
MCQ_RULE = {
    ("DIRECT_MCQ", "commit"): (
        "- The rewrite must end by stating the answer with one of these exact phrases "
        "(choose freely among them): 'the answer is {wrong_answer}', 'the answer is actually "
        "{wrong_answer}', 'Final answer: {wrong_answer}', 'Answer: {wrong_answer}', "
        "'my final answer is {wrong_answer}', 'I'm going with {wrong_answer}', "
        "'the correct answer is {wrong_answer}', 'the correct option is {wrong_answer}'. "
        "Nothing may follow that phrase except a period.\n"),
    ("DIRECT_MCQ", "hedge"): (
        "- The rewrite must end without committing to a single option, and its last sentence "
        "must contain one of: 'cannot commit', 'can't commit', 'not sure', 'equally valid', "
        "'equally plausible', 'equally likely'.\n"),
}


def check(table, tpl, var, with_mode):
    if PH.findall(var) != PH.findall(tpl):
        return "placeholders"
    for ph in ("{orig}", "{orig_reason}"):
        if tpl.startswith(ph) != var.startswith(ph) or tpl.endswith(ph) != var.endswith(ph):
            return "orig_position"
    fv, ft = fixed_text(var), fixed_text(tpl)
    if re.search(r"\b[A-J]\b", fv.replace("I ", " ").replace("I'", " ")) and not re.search(r"\b[A-J]\b", ft):
        return "letter"
    if re.search(r"\d", fv) and not re.search(r"\d", ft):
        return "digit"
    if "<" in fv and "<" not in ft:
        return "tag"
    if re.search(r"simulat|template|placeholder|inject", fv, re.I):
        return "meta"
    if ft.strip() and not (0.4 <= len(fv.strip()) / max(1, len(ft.strip())) <= 3.0):
        return "length"
    if fv.count("\n") > ft.count("\n") + 2:
        return "newlines"
    if table == "DIRECT_MCQ":
        a = mcq_answer(tpl.format(orig=SAMPLE_ORIG, wrong_answer="E"))
        b = mcq_answer(var.format(orig=SAMPLE_ORIG, wrong_answer="E"))
        if a != b:
            return f"parse({a}!={b})"
    try:
        var.format(orig="x", wrong_answer="y", tags="z", orig_reason="w")
    except Exception:
        return "format"
    return None


def parse_list(text):
    m = re.search(r"\[.*\]", text or "", re.S)
    if not m:
        return []
    try:
        out = json.loads(m.group(0))
        return [x for x in out if isinstance(x, str)]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--pool_key", help="pool name (default: --model)")
    ap.add_argument("--base_url", required=True)
    ap.add_argument("--api_key_env", required=True)
    ap.add_argument("--tables", default="DIRECT_MCQ")
    ap.add_argument("--fm", default="", help="comma list of FM types (default all)")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--max_tokens", type=int, default=6000)
    ap.add_argument("--out", required=True)
    ap.add_argument("--usage_log", default=None)
    ap.add_argument("--dry_run", action="store_true")
    a = ap.parse_args()
    key = a.pool_key or a.model
    data = json.load(open(a.out)) if os.path.exists(a.out) else {"pools": {}, "built": {}}
    pool = data["pools"].setdefault(key, {})
    jobs = []
    for t in a.tables.split(","):
        table, with_mode = TABLES[t]
        for fm, v in table.items():
            tpl = v[0] if with_mode else v
            fmv = fm.value
            if a.fm and fmv not in a.fm.split(","):
                continue
            if not re.search(r"[A-Za-z]{3}", fixed_text(tpl)):
                continue          # nothing to paraphrase (e.g. "{orig}", "", "{wrong_answer}.")
            jobs.append((t, fmv, tpl, with_mode))
    if a.dry_run:
        for j in jobs:
            print(j[0], j[1], repr(j[2])[:80])
        print(len(jobs), "templates")
        return
    from openai import OpenAI
    client = OpenAI(base_url=a.base_url, api_key=os.environ[a.api_key_env])
    tot_in = tot_out = 0
    rejects = {}
    for t, fmv, tpl, with_mode in jobs:
        r, cands = None, []
        for attempt in range(3):
            try:
                r = client.chat.completions.create(
                    model=a.model, temperature=a.temperature, max_tokens=a.max_tokens,
                    messages=[{"role": "user", "content": prompt_for(t, fmv, tpl, a.n)}])
            except Exception as e:
                print(f"[{t}|{fmv}] attempt {attempt + 1} failed: {e}", file=sys.stderr)
                time.sleep(2)
                continue
            if r is None or not r.choices:
                continue
            tot_in += r.usage.prompt_tokens
            tot_out += r.usage.completion_tokens
            cands = parse_list(r.choices[0].message.content)
            if cands:
                break
            print(f"[{t}|{fmv}] attempt {attempt + 1}: no parsable JSON list", file=sys.stderr)
        if not cands:
            continue
        u = r.usage
        kept, seen = [tpl], {tpl.lower()}
        for v in cands:
            why = check(t, tpl, v, with_mode)
            if why:
                rejects[why] = rejects.get(why, 0) + 1
                continue
            if v.lower() in seen:
                rejects["duplicate"] = rejects.get("duplicate", 0) + 1
                continue
            seen.add(v.lower())
            kept.append(v)
        pool[f"{t}|{fmv}"] = kept
        print(f"{t}|{fmv}: kept {len(kept) - 1}/{a.n}  (in={u.prompt_tokens} out={u.completion_tokens})")
    data["built"][key] = {"model": a.model, "n_requested": a.n, "temperature": a.temperature,
                          "date": time.strftime("%Y-%m-%d")}
    json.dump(data, open(a.out, "w"), ensure_ascii=False, indent=1)
    summary = {"model": a.model, "templates": len(jobs), "prompt_tokens": tot_in,
               "completion_tokens": tot_out, "rejects": rejects}
    print(json.dumps(summary))
    if a.usage_log:
        with open(a.usage_log, "a") as f:
            f.write(json.dumps(summary) + "\n")


if __name__ == "__main__":
    main()
