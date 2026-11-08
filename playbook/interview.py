"""An interview driven by a language model, for the choices a fitted rule cannot explain.

`elicit.py` asks a fixed question and needs the person to type a condition and tick the cases it held for. Here a
(local) model writes a short question for each misfit, turns the free-text answer into a named condition, and
decides when to stop. It adapts two papers, from their abstracts only (docs/related-work.md): Brennig (2025), where a
conversational agent uses targeted queries to draw out tacit knowledge that is then incorporated into the event log,
and Zuin et al. (2025), where an agent questions people iteratively and criticises its own progress.

What is deliberately NOT left to the model, because it can be checked in code:
* a question must be short and may not contain a digit (so it cannot state a threshold); otherwise a plain template is used;
* the model is never given the fitted rule, only what was on screen and what happened;
* a condition must be at most five words, and vague answers must yield none;
* which other cases a condition held for is read from the person's reply by code, and only offered cases count;
* the model's self-rating of an answer is recorded next to the measured effect and never overrides it.

`chat(messages, response_format) -> str` is the same callable `replay.model_decider` takes, so any backend, or a
fake in tests, works. `ask(text, ctx) -> str` is the person (or a simulated one); `ctx` carries the decision key for
simulations and is ignored by people.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from . import elicit, induce
from .decisions import Decision, slug
from .interview_prompts import (CLASSIFY_SYSTEM, CRITIQUE_SYSTEM, DEFAULT_STRATEGY, FALLBACK_QUESTION, FOLLOW_UP, GROUP_QUESTION,
                                INTERPRET_SYSTEM, PHRASE_VARIANTS, QUESTION_SYSTEM, STRATEGIES)

Chat = Callable[[list[dict], dict], str]
Ask = Callable[[str, dict], str]

MAX_QUESTION_WORDS = 30
MAX_CONDITION_WORDS = 5  # the first version
MAX_PHRASE_WORDS = 8  # gated extraction: a quoted phrase


def _schema(name: str, props: dict, required: list[str]) -> dict:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": {"type": "object", "properties": props, "required": required}}}


QUESTION_FORMAT = _schema("question", {"question": {"type": "string"}}, ["question"])
INTERPRET_FORMAT = _schema("interpretation", {"condition": {"type": ["string", "null"]},
                                              "kind": {"type": "string", "enum": ["on_screen", "off_screen", "none"]}}, ["condition", "kind"])
CLASSIFY_FORMAT = _schema("category", {"category": {"type": "string", "enum": ["ITEM", "SELF", "NONE"]}}, ["category"])
PHRASE_FORMAT = _schema("phrase", {"phrase": {"type": "string"}}, ["phrase"])
CRITIQUE_FORMAT = _schema("critique", {"rating": {"type": "number"}}, ["rating"])


def _call(chat: Chat, system: str, user: str, fmt: dict) -> dict | None:
    """One model call; the reply as a dict, or None if the call or the JSON failed."""
    try:
        out = json.loads(chat([{"role": "system", "content": system}, {"role": "user", "content": user}], fmt))
    except Exception:  # a failed call must never stop an interview
        return None
    return out if isinstance(out, dict) else None


def describe(q: elicit.Question) -> str:
    """What the model is told about a misfit: what was on screen and what happened. Never the fitted rule."""
    d = q.decision
    seen = ", ".join([f"{k.replace('_', ' ')} {v:g}" for k, v in d.readouts.items()] + [f"{k.replace('_', ' ')} {v}" for k, v in d.cats.items()])
    lines = [f"On screen: {seen}.", f"The person chose: {d.outcome}.", f"In similar situations they chose: {q.expected}."]
    diffs = [f"{f.replace('_', ' ')} was {a:g} here and typically {b:g} there" for f, a, b in q.differences if not f.startswith(("delta_", "changed_"))]
    if diffs:
        lines.append("Compared with those: " + "; ".join(diffs) + ".")
    return "\n".join(lines)


def _valid_question(text: str) -> bool:
    words = text.split()
    return 3 <= len(words) <= MAX_QUESTION_WORDS and text.rstrip().endswith("?") and not re.search(r"\d", text)


def fallback_question(q: elicit.Question) -> str:
    return FALLBACK_QUESTION.format(did=q.decision.outcome, expected=q.expected)


def make_question(q: elicit.Question, chat: Chat | None, strategy: str = DEFAULT_STRATEGY) -> tuple[str, bool]:
    """(question, written_by_model). The model's question is used only if it is short, a question and has no digit."""
    if strategy == "template":  # the fixed question of elicit.py, as a baseline for comparing question wording
        return q.text(), False
    if chat is None:
        return fallback_question(q), False
    out = _call(chat, QUESTION_SYSTEM + " " + STRATEGIES[strategy]["instruction"], describe(q), QUESTION_FORMAT)
    text = str(out.get("question", "")).strip() if out else ""
    return (text, True) if _valid_question(text) else (fallback_question(q), False)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def grounded(phrase: str, answer: str) -> bool:
    """The phrase really comes from the answer: its words appear there in order, or at least 75% of them (by their first
    five letters, so 'restarted' matches 'restart') do. A model cannot invent a condition the person did not say."""
    pw, aw = _words(phrase), _words(answer)
    if not pw:
        return False
    if " ".join(pw) in " ".join(aw):
        return True
    stems = {w[:5] for w in aw}
    return sum(w[:5] in stems for w in pw) / len(pw) >= 0.75


def interpret(answer: str, known: list[str], chat: Chat | None, method: str = "gated") -> dict:
    """The condition the person gave, as {"condition": short phrase or None, "kind": ...}. `method` is "gated" (a
    three-way ITEM / SELF / NONE classification, then a phrase of at most eight words that must come from the answer,
    chosen by a majority of three wordings) or "v0" (one free extraction, the first version)."""
    return interpret_v0(answer, known, chat) if method == "v0" else interpret_gated(answer, known, chat)


def interpret_gated(answer: str, known: list[str], chat: Chat | None) -> dict:
    none = {"condition": None, "kind": "none"}
    if chat is None or len(answer.strip()) < 3:
        return none
    verdict = (_call(chat, CLASSIFY_SYSTEM, f"Answer: {answer}", CLASSIFY_FORMAT) or {}).get("category")
    if verdict != "ITEM":  # a reason about the item itself; the person's own day and shrugs go no further
        return none
    phrases = []
    for p in PHRASE_VARIANTS:
        out = _call(chat, p, f"KNOWN conditions: {known or 'none yet'}\nAnswer: {answer}", PHRASE_FORMAT)
        ph = str((out or {}).get("phrase") or "").strip().strip(".").lower()
        if ph and len(ph.split()) <= MAX_PHRASE_WORDS and (ph in known or grounded(ph, answer)):
            phrases.append(ph)
    if not phrases:
        return none
    return {"condition": Counter(phrases).most_common(1)[0][0], "kind": "stated"}  # ties go to the earliest prompt's phrase


def interpret_v0(answer: str, known: list[str], chat: Chat | None) -> dict:
    """The first version: one free extraction. Kept as the baseline for the amendment-8 comparison."""
    none = {"condition": None, "kind": "none"}
    if chat is None or len(answer.strip()) < 3:
        return none
    out = _call(chat, INTERPRET_SYSTEM, f"KNOWN conditions: {known or 'none yet'}\nAnswer: {answer}", INTERPRET_FORMAT)
    if not out:
        return none
    cond = str(out.get("condition") or "").strip().strip(".").lower()
    kind = out.get("kind") if out.get("kind") in ("on_screen", "off_screen") else "none"
    if not cond or kind == "none" or len(cond.split()) > MAX_CONDITION_WORDS:
        return none
    return {"condition": cond, "kind": kind}


def parse_held_for(reply: str, n: int) -> list[int]:
    """The case numbers (1..n) named in a reply: 'Cases 2, 5', 'all of them', 'none'. Read by code, not by the model."""
    low = reply.lower()
    if re.search(r"\bnone\b|\bno\b|\bnot any\b", low) and not re.search(r"\d", low):
        return []
    if re.search(r"\ball\b|\bevery\b", low) and not re.search(r"\d", low):
        return list(range(1, n + 1))
    return sorted({int(x) for x in re.findall(r"\d+", reply) if 1 <= int(x) <= n})


def critique(question: str, answer: str, chat: Chat | None) -> float | None:
    """The model's own 0-1 rating of how specifically the answer explains the choice (Zuin et al.); recorded, never trusted."""
    if chat is None:
        return None
    out = _call(chat, CRITIQUE_SYSTEM, f"Question: {question}\nAnswer: {answer}", CRITIQUE_FORMAT)
    try:
        return min(1.0, max(0.0, float(out["rating"]))) if out else None
    except (KeyError, TypeError, ValueError):
        return None


def apply_union(decisions: list[Decision], answers: list[elicit.Answer]) -> list[Decision]:
    """Add each named condition as a 0/1 feature. Answers naming the same condition are one claim tagged piece by
    piece, so their tagged cases are united (`elicit.apply_answers` lets the last answer overwrite the others)."""
    tagged: dict[str, set[str]] = {}
    for a in answers:
        if a.fact:
            tagged.setdefault(slug(a.fact), set()).update({a.key, *a.also})
    for name, keys in tagged.items():
        for d in decisions:
            d.features[name] = 1.0 if elicit.key(d) in keys else 0.0
    return decisions


def unexplained(decisions: list[Decision], answers: list[elicit.Answer]) -> int:
    """How many decisions the rule still cannot explain (leave-one-out) once the answers are applied, on copies."""
    copy = [Decision(**{**d.__dict__, "features": dict(d.features)}) for d in decisions]
    apply_union(copy, answers)
    return len(induce.disagreements(copy))


@dataclass
class Turn:
    key: str
    question: str
    by_model: bool
    answer: str
    condition: str | None
    kind: str
    held_for: list[str]
    rating: float | None
    unexplained_before: int
    unexplained_after: int
    follow_up: str | None = None

    @property
    def delta(self) -> int:
        """Decisions newly explained by this answer (positive is good)."""
        return self.unexplained_before - self.unexplained_after


@dataclass
class Interview:
    answers: list[elicit.Answer] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    stopped: str = ""


def evaluate_answer(turn: Turn, rubric: dict | None = None) -> dict:
    """Mechanical measures of one answer, which need no judgment, plus an optional person's rubric scores
    (e.g. {"specificity": 0-2, "actionability": 0-2, "evidence": 0-2}) kept beside them. Which rubric dimensions matter
    is a design question for whoever writes the questions (docs/interview-guide.md)."""
    out = {"named_condition": turn.condition is not None, "tagged_other_cases": len(turn.held_for),
           "measured_delta": turn.delta, "self_rating": turn.rating, "by_model": turn.by_model}
    if rubric:
        out["rubric"] = rubric
    return out


def effect(decisions: list[Decision], answers: list[elicit.Answer]) -> dict:
    """What the answers changed, as `elicit.effect` reports it, but with answers naming one condition united."""
    def snapshot(ds):
        tree = induce.fit(ds)
        return {"rule": induce.rules(tree), "accuracy": induce.accuracy(tree, ds), "unexplained": len(induce.disagreements(ds))}

    before = snapshot(decisions)
    apply_union(decisions, answers)
    return {"before": before, "after": snapshot(decisions), "facts": sorted({slug(a.fact) for a in answers if a.fact})}


def local_chat(stack, settings) -> Chat:
    """The local model as a `chat` callable, started for as long as `stack` (a contextlib.ExitStack) is open.
    Calls are cached like every other model call, so repeating an interview on the same answers is free."""
    from .analyzer import VisionClient
    from .llama_runtime import serving

    vc = VisionClient(settings)
    if vc.backend.server is not None:
        stack.enter_context(serving(settings, vc.backend.server, status=print))
    return vc.chat


def load_rubric(path) -> dict[str, dict]:
    """Human scores per answer, one JSON object per line: {"key": "visit013@402", "specificity": 2, "actionability": 1, ...}.
    `key` is the decision key (`Turn.key`); every other field is a score the rubric's author defines."""
    from pathlib import Path

    out: dict[str, dict] = {}
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row.pop("key")] = row
    return out


def _leaf_for(tree: induce.Node, d: Decision) -> induce.Node:
    node = tree
    while not node.leaf:
        node = node.low if d.features.get(node.feature, float("-inf")) <= node.threshold else node.high
    return node


def _leaf_path(tree: induce.Node, d: Decision) -> tuple:
    node, path = tree, []
    while not node.leaf:
        low = d.features.get(node.feature, float("-inf")) <= node.threshold
        path.append((node.feature, low))
        node = node.low if low else node.high
    return tuple(path)


def rank_misfits(decisions: list[Decision], questions: list[elicit.Question], order: str = "time") -> list[elicit.Question]:
    """The misfits in the order to ask about them. "time" is the order they happened (the first version). The others are
    guesses at which misfits share a cause, tried in amendment 8: "surprise" puts first the ones the rule was surest
    about (the purity of the leaf, weighted by its size); "burst" those with misfits right next to them in time; "cluster"
    those whose (what was done, what the rule expected, where in the tree) matches the most other misfits."""
    if order not in ("time", "surprise", "burst", "cluster"):
        raise ValueError("order must be time, surprise, burst or cluster")
    if order == "time" or len(questions) < 2:
        return list(questions)
    index = {elicit.key(d): i for i, d in enumerate(decisions)}
    misfit_at = {index[elicit.key(q.decision)] for q in questions}
    full = induce.fit(decisions)
    sig = Counter((q.decision.outcome, q.expected, _leaf_path(full, q.decision)) for q in questions)
    keyed = []
    for pos, q in enumerate(questions):
        d = q.decision
        leaf = _leaf_for(induce.fit([x for x in decisions if x is not d]), d)  # the rule that was wrong about it
        purity = (leaf.correct / leaf.n if leaf.n else 0.0) * leaf.n / (leaf.n + 3)
        i = index[elicit.key(d)]
        near = sum((i + k) in misfit_at for k in (-1, 1))
        score = {"surprise": (-purity,), "burst": (-near, -purity), "cluster": (-sig[(d.outcome, q.expected, _leaf_path(full, d))], -purity)}[order]
        keyed.append((score, pos, q))
    return [q for _, _, q in sorted(keyed, key=lambda t: (t[0], t[1]))]


def group_turn(decisions: list[Decision], questions: list[elicit.Question], ask: Ask, chat: Chat | None, extraction: str,
               size: int = 8, say: Callable[[str], None] = lambda s: None) -> tuple[Turn, elicit.Answer] | None:
    """One question about the largest group of misfits that share what was done and what the rule expected. The person says
    what they have in common and which of them it applies to; the numbers are read by code, and if they name none the
    condition is taken to apply to the whole group. Returns None if there is no group of at least three."""
    groups: dict[tuple, list[elicit.Question]] = {}
    for q in questions:
        groups.setdefault((q.decision.outcome, q.expected), []).append(q)
    biggest = max(groups.values(), key=len, default=[])
    if len(biggest) < 3:
        return None
    members = biggest[:size]
    listing = "\n".join(f"{i}. {m.decision.session} at {m.decision.t1:.0f}s: on screen "
                        + ", ".join([f"{k} {v:g}" for k, v in m.decision.readouts.items()] + [f"{k} {v}" for k, v in m.decision.cats.items()])
                        for i, m in enumerate(members, 1))
    text = GROUP_QUESTION.format(n=len(members), did=members[0].decision.outcome, expected=members[0].expected, cases=listing)
    say(text)
    keys = [elicit.key(m.decision) for m in members]
    answer = ask(text, {"key": "group", "group_keys": keys, "followup": False})
    interp = interpret(answer, [], chat, extraction)
    named = parse_held_for(answer, len(members))
    held = [keys[i - 1] for i in named] if named else (keys if interp["condition"] else [])
    anchor = next((m.decision for m in members if elicit.key(m.decision) in set(held)), members[0].decision)  # an Answer always tags its own decision
    ans = elicit.Answer(anchor.session, anchor.t1, answer, interp["condition"], [k for k in held if k != elicit.key(anchor)])
    before = len(questions)
    after = unexplained(decisions, [ans])
    turn = Turn("group", text, False, answer, interp["condition"], interp["kind"], held, critique(text, answer, chat), before, after, None)
    return turn, ans


def run_interview(decisions: list[Decision], ask: Ask, chat: Chat | None, strategy: str = DEFAULT_STRATEGY,
                  max_questions: int = 8, patience: int = 4, follow_up: bool = True, say: Callable[[str], None] = lambda s: None,
                  extraction: str = "gated", order: str = "time", group_first: bool = False,
                  on_turn: Callable[[Turn, elicit.Answer], None] | None = None) -> Interview:
    """Question the person about the decisions the rule cannot explain; stop when nothing is left, the budget is spent,
    or `patience` answers in a row changed nothing. `decisions` should be the ones the rule was fitted on."""
    result = Interview()
    questions = elicit.build_questions(decisions)
    before = len(questions)
    quiet = 0
    if group_first:  # one question about the biggest group of similar misfits, then the usual one-by-one questions
        got = group_turn(decisions, questions, ask, chat, extraction, say=say)
        if got:
            turn, ans = got
            result.turns.append(turn)
            result.answers.append(ans)
            if on_turn:
                on_turn(turn, ans)
            quiet = 0 if turn.delta > 0 else 1
    for q in rank_misfits(decisions, questions, order):
        if len(result.turns) >= max_questions:
            result.stopped = "question budget spent"
            break
        key = elicit.key(q.decision)
        if any(key in {a.key, *a.also} for a in result.answers if a.fact):
            continue  # an earlier answer already claims this decision
        text, by_model = make_question(q, chat, strategy)
        say(text)
        answer = ask(text, {"key": key, "followup": False})
        known = sorted({a.fact for a in result.answers if a.fact})
        interp = interpret(answer, known, chat, extraction)
        cands = elicit.tag_candidates(q, questions)
        others = [c for c in cands if elicit.key(c) != key]
        held: list[str] = []
        asked_follow = None
        if interp["condition"] and follow_up and others:
            listing = "\n".join(f"{i}. {c.session} at {c.t1:.0f}s: you chose {c.outcome}; on screen "
                                + ", ".join([f"{k} {v:g}" for k, v in c.readouts.items()] + [f"{k} {v}" for k, v in c.cats.items()])
                                for i, c in enumerate(others, 1))
            asked_follow = FOLLOW_UP.format(fact=interp["condition"], cases=listing)
            say(asked_follow)
            reply = ask(asked_follow, {"key": key, "followup": True, "candidate_keys": [elicit.key(c) for c in others]})
            held = [elicit.key(others[i - 1]) for i in parse_held_for(reply, len(others))]
        ans = elicit.Answer(q.decision.session, q.decision.t1, answer, interp["condition"], held)
        trial = [*result.answers, ans]
        after = unexplained(decisions, trial)
        prev = unexplained(decisions, result.answers) if result.answers else before
        rating = critique(text, answer, chat)
        result.turns.append(Turn(key, text, by_model, answer, interp["condition"], interp["kind"], held, rating, prev, after, asked_follow))
        result.answers = trial
        if on_turn:
            on_turn(result.turns[-1], ans)  # e.g. save as we go, so an interrupted interview keeps what it has
        quiet = 0 if after < prev else quiet + 1
        if after == 0:
            result.stopped = "nothing left to explain"
            break
        if quiet >= patience:
            result.stopped = f"{patience} answers in a row changed nothing"
            break
    else:
        result.stopped = result.stopped or ("nothing left to explain" if before == 0 else "no more questions")
    return result
