"""Does the exported skill make a decider choose like the person did?

The skill's judgment section is only worth having if following it reproduces the person's
decisions on situations it has not seen. This replays held-out decisions (the latest 30%,
never used to fit the rules) through several deciders and scores agreement with what the
person actually did, counting "ask a human" separately:

  majority         always the person's most common outcome in the training decisions
  rules            a mechanical reading of the exported rules (no model): checks that the
                   export is complete enough to act on, and gives the upper bound for it
  skill            a language model given the procedure only (optional; needs a model)
  skill+judgment   the same model given the procedure and the judgment section

Wrong actions (taking an action the person did not take) are counted apart from wrong
inactions, because stopping a healthy run costs more than waiting. Facts the person named
that are not on screen are supplied as if a human had been asked; that favours both model
arms equally. Reported numbers are agreement with one person's recorded behaviour on a small
set, not correctness.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Callable

from .decisions import NONE, Decision, slug
from .elicit import apply_answers
from .skill import build_judgment

ASK = "ask a human"
Decider = Callable[[Decision], str]
_COND = re.compile(r"^(?P<f>\S+) (?P<op><=|>) (?P<v>-?[\d.e+-]+)$")


def split(decisions: list[Decision], train_fraction: float = 0.7) -> tuple[list[Decision], list[Decision]]:
    cut = max(1, int(len(decisions) * train_fraction))
    return decisions[:cut], decisions[cut:]


def majority_decider(train: list[Decision]) -> Decider:
    label = Counter(d.outcome for d in train).most_common(1)[0][0]
    return lambda d: label


def evaluate_rules(judgment: dict, features: dict[str, float], readouts: dict[str, float]) -> dict:
    """Apply the exported rules to one situation, in order: the first that matches wins. The one place this logic lives:
    the mechanical reader below, `python -m playbook judge` and the agent arm of the H5 tests all call it.

    Returns {"outcome": a label, or "ask a human", "rule": the rule that fired (or None), "reason": why}. It asks a human
    when a value is outside the range seen (the rules were never fitted there) or no rule matches."""
    for n, (lo, hi) in judgment["basis"]["observed_ranges"].items():
        if n in readouts and not (lo <= readouts[n] <= hi):
            return {"outcome": ASK, "rule": None, "reason": f"{n} = {readouts[n]:g} is outside the range seen ({lo:g} to {hi:g})"}
    for rule in judgment["rules"]:
        ok = True
        for cond in rule["when"]:
            if cond == "always":
                continue
            m = _COND.match(cond)
            value = features.get(m["f"], float("-inf")) if m else None
            if m is None or not ((value <= float(m["v"])) if m["op"] == "<=" else (value > float(m["v"]))):
                ok = False
                break
        if ok:
            return {"outcome": rule["then"], "rule": " and ".join(rule["when"]), "reason": f"matches: {' and '.join(rule['when'])} (seen {rule['support']})"}
    return {"outcome": ASK, "rule": None, "reason": "no rule matches"}


def situation_features(judgment: dict, readouts: dict[str, float], cats: dict[str, str] | None = None, previous: dict[str, float] | None = None) -> dict[str, float]:
    """The features the rules talk about, from what is on screen now (and, for changed_x / delta_x, at the previous check):
    readouts, `label=word` as 0/1, `a/b` as the quotient. Only the features the rules mention are computed beyond the readouts."""
    feats = dict(readouts)
    for n, v in readouts.items():
        if previous and n in previous:
            feats[f"changed_{n}"], feats[f"delta_{n}"] = float(v != previous[n]), v - previous[n]
    wanted = {m["f"] for rule in judgment["rules"] for c in rule["when"] if (m := _COND.match(c))}
    for f in wanted:
        if "=" in f:
            label, word = f.split("=", 1)
            feats[f] = float((cats or {}).get(label) == word)
        elif "/" in f:
            a, b = f.split("/", 1)
            if a in readouts and readouts.get(b, 0) > 0:
                feats[f] = readouts[a] / readouts[b]
    return feats


def judge(judgment: dict, readouts: dict[str, float], cats: dict[str, str] | None = None, previous: dict[str, float] | None = None) -> dict:
    """What the exported rules say about a situation. `judgment` is the "judgment" part of a skill.json."""
    return evaluate_rules(judgment, situation_features(judgment, readouts, cats, previous), readouts)


def rules_decider(judgment: dict) -> Decider:
    """Follow the exported rules literally. Asks a human when a value is outside the observed range
    or no rule matches (the same boundary the skill text gives to an agent)."""
    return lambda d: evaluate_rules(judgment, d.features, d.readouts)["outcome"]


def _screen(d: Decision, facts: list[str], context: list[str] = ()) -> str:
    seen = ", ".join([f"{k.replace('_', ' ')} = {v:g}" for k, v in d.readouts.items()]
                     + [f"{k.replace('_', ' ')} = {v}" for k, v in d.cats.items()])
    known = [f"{f.replace('_', ' ')}: {'yes' if d.features.get(f) else 'no'}" for f in facts]
    # What the rules call changed_x is not on this screen: it compares with the previous check.
    prior = [f"{c.removeprefix('changed_').replace('_', ' ')} changed since the previous check: "
             f"{'yes' if d.features.get(c) else 'no'}" for c in context if c.startswith("changed_")]
    seen += "".join(f", {c} = {d.features[c]:.4g}" for c in context if "/" in c and c in d.features)  # a rule on a quotient: do the division for the model
    return (f"The screen shows: {seen}." + (f" From earlier checks: {'; '.join(prior)}." if prior else "")
            + (f" A human confirms - {'; '.join(known)}." if known else ""))


STRICT = ("Apply the rules in the 'Judgment calls' section literally and in order, using only what the screen shows. "
          "Do not reason beyond them. If no rule applies, or a value is outside the observed range, choose the ask-a-human option.")


def model_decider(chat: Callable[[list[dict], dict], str], skill_md: str, options: list[str], facts: list[str] = (),
                  context: list[str] = (), strict: bool = False) -> Decider:
    """A language model that reads the skill and picks one of `options` (or asks a human).

    `strict` is the second prompt variant declared for the H5 runs: the same prompt plus an instruction to follow the rules literally."""
    choices = [*options, ASK]
    fmt = {"type": "json_schema", "json_schema": {"name": "choice", "schema": {
        "type": "object", "properties": {"choice": {"type": "string", "enum": choices}}, "required": ["choice"]}}}

    def decide(d: Decision) -> str:
        messages = [
            {"role": "system", "content": "You act for a person using the skill below. Choose what they would do now."
                                         + (f" {STRICT}" if strict else "") + "\n\n" + skill_md},
            {"role": "user", "content": f"{_screen(d, list(facts), list(context))}\nOptions: {', '.join(choices)}. "
                                        f"('{NONE}' means take no action.) Reply as JSON: {{\"choice\": ...}}"},
        ]
        try:
            pick = json.loads(chat(messages, fmt)).get("choice", ASK)
        except (ValueError, AttributeError):
            return ASK
        return pick if pick in choices else ASK

    return decide


def score(decider: Decider, test: list[Decision]) -> dict:
    picks = [(decider(d), d.outcome) for d in test]
    answered = [(p, t) for p, t in picks if p != ASK]
    return {
        "n": len(test),
        "agreement": round(sum(p == t for p, t in picks) / len(test), 3) if test else 0.0,
        "ask_human": sum(p == ASK for p, _ in picks),
        "agreement_when_answered": round(sum(p == t for p, t in answered) / len(answered), 3) if answered else None,
        "wrong_actions": sum(p != NONE and p != t for p, t in answered),  # acted when the person did not (or did something else)
        "missed_actions": sum(p == NONE and t != NONE for p, t in answered),
    }


def run(decisions: list[Decision], answers=None, chat=None, procedure_md: str = "", train_fraction: float = 0.7,
        lookahead: bool | None = None, strict: bool = False) -> dict:
    """Fit on the earliest decisions, replay the rest. `chat(messages, response_format) -> str` enables the model arms."""
    apply_answers(decisions, answers or [])  # facts a human would confirm, for the held-out decisions too
    train, test = split(decisions, train_fraction)
    if not test:
        raise ValueError("no held-out decisions: need more decisions")
    judgment = build_judgment(train, answers, lookahead=lookahead)
    if judgment is None:
        raise ValueError("need at least 6 training decisions")
    options = sorted({d.outcome for d in train if d.outcome != NONE} | {NONE})
    facts = [slug(s["fact"]) for s in judgment["stated_by_person"] if s["fact"]]
    context = sorted({c.split()[0] for r in judgment["rules"] for c in r["when"] if c.startswith(("changed_", "delta_")) or "/" in c.split()[0]})
    arms: dict[str, Decider] = {"majority": majority_decider(train), "rules": rules_decider(judgment)}
    if chat is not None:
        with_judgment = procedure_md + "\n\n" + _judgment_text(judgment)
        arms["skill"] = model_decider(chat, procedure_md or "Check the run and decide whether to act.", options)
        arms["skill+judgment"] = model_decider(chat, with_judgment, options, facts, context, strict=strict)
    return {"train": len(train), "test": len(test), "options": options,
            "arms": {name: score(decide, test) for name, decide in arms.items()}}


def _judgment_text(judgment: dict) -> str:
    from .skill import _judgment_md

    return "\n".join(_judgment_md(judgment))
