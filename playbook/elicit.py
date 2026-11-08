"""Ask the person about the decisions a fitted rule cannot explain.

A rule fitted to pooled decisions (induce.py) is a hypothesis. Where the person's choice
disagrees with it, either the rule is wrong or the person used something the screen did not
show. Each such decision becomes a question: what you did, what the rule expected, and how
this screen differs from the most similar ones where you did what the rule expected. The
person answers in their own words and may name a *fact* ("warmup phase", "ran out of budget")
and say which other decisions it also held for. A named fact becomes a new feature (1 for the
decisions it was tagged on, 0 for the rest), and the rule is fitted again. The answer is kept
with its provenance, so a stated rule can be traced to the case that prompted it.

This is the externalization step of Nonaka and Takeuchi (1995): tacit knowledge becomes
explicit by being articulated against concrete cases. Eliciting tacit knowledge with
targeted questions, and adding the answers to the event record, follows the direction of
Brennig (2025) and Zuin et al. (2025), who use LLM interviewers; the questions here are
generated deterministically so they cost nothing and can be audited. See docs/references.bib.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import induce
from .decisions import Decision, slug

N_SIMILAR = 3


def key(d: Decision) -> str:
    return f"{d.session}@{d.t1:g}"


@dataclass
class Question:
    decision: Decision
    expected: str  # what the fitted rule predicted
    similar: list[Decision]  # nearest decisions where the person did what the rule expected
    differences: list[tuple[str, float, float]]  # (feature, this value, median over `similar`)

    def text(self) -> str:
        lines = [f"In {self.decision.session} (at {self.decision.t1:.0f}s) you did: {self.decision.outcome}.",
                 f"The rule fitted to your other decisions expected: {self.expected}.",
                 f"On screen: {self.decision.features}"]
        if self.differences:
            lines.append(f"Compared with the {len(self.similar)} most similar decisions where you did '{self.expected}':")
            lines += [f"  {f}: {a:g} here, typically {b:g} there" for f, a, b in self.differences]
        else:
            lines.append("Nothing on screen differs from the similar decisions where you did "
                         f"'{self.expected}'. What did you know that the screen does not show?")
        lines.append("Why did you do this one differently?")
        return "\n".join(lines)


@dataclass
class Answer:
    session: str
    t1: float
    reason: str  # the person's words, verbatim
    fact: str | None = None  # a named condition, becomes a 0/1 feature
    also: list[str] = field(default_factory=list)  # keys (session@t1) of other decisions the fact held for
    asked_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def key(self) -> str:
        return f"{self.session}@{self.t1:g}"


def _distance(a: Decision, b: Decision, scale: dict[str, float]) -> float:
    shared = [f for f in a.features if f in b.features]
    if not shared:
        return float("inf")
    return sum(abs(a.features[f] - b.features[f]) / scale[f] for f in shared) / len(shared)


def build_questions(decisions: list[Decision], max_depth: int = induce.MAX_DEPTH) -> list[Question]:
    """One question per decision the rule (fitted on the others) would not predict."""
    names = {f for d in decisions for f in d.features}
    scale = {f: (statistics.pstdev([d.features[f] for d in decisions if f in d.features]) or 1.0) for f in names}
    out = []
    for d, guess in induce.disagreements(decisions, max_depth):
        pool_ = [o for o in decisions if o is not d and o.outcome == guess]
        near = sorted(pool_, key=lambda o: _distance(d, o, scale))[:N_SIMILAR]
        diffs = []
        for f in sorted(x for x in d.features if not x.startswith("delta_")):  # deltas are noise to a person
            vals = [o.features[f] for o in near if f in o.features]
            if vals and abs(d.features[f] - statistics.median(vals)) > 0.5 * scale[f]:
                diffs.append((f, d.features[f], statistics.median(vals)))
        out.append(Question(d, guess, near, diffs))
    return out


def tag_candidates(q: Question, questions: list[Question]) -> list[Decision]:
    """Decisions the person is offered when asked which others a fact also held for: this one,
    the similar ones shown, and the other decisions the rule could not explain."""
    seen, out = set(), []
    for d in [q.decision, *q.similar, *(o.decision for o in questions)]:
        if key(d) not in seen:
            seen.add(key(d))
            out.append(d)
    return out


def apply_answers(decisions: list[Decision], answers: list[Answer]) -> list[Decision]:
    """Add each answer's fact as a feature: 1.0 on the decisions it was tagged on, 0.0 elsewhere."""
    for a in answers:
        if not a.fact:
            continue
        name, tagged = slug(a.fact), {a.key, *a.also}
        for d in decisions:
            d.features[name] = 1.0 if key(d) in tagged else 0.0
    return decisions


def vet(decisions: list[Decision], answers: list[Answer]) -> tuple[list[Answer], list[Answer]]:
    """(kept, dropped): keep an answer only if the fact it names makes the rule explain more of the decisions.

    A named condition is a claim that it explains the decisions it was tagged on. Answers are tried one at a
    time, in order, on copies; one is kept if the refitted rule gets more of the decisions right, or leaves fewer
    of them unexplained under leave-one-out, and is otherwise dropped (the person's words stay on record, the
    condition just does not become a feature). Answers with no named condition are neither kept nor dropped here.
    """
    kept: list[Answer] = []
    dropped: list[Answer] = []

    def score(extra: list[Answer]) -> tuple[float, int]:
        copy = [Decision(**{**d.__dict__, "features": dict(d.features)}) for d in decisions]
        apply_answers(copy, extra)
        return induce.accuracy(induce.fit(copy), copy), len(induce.disagreements(copy))

    groups: dict[str, list[Answer]] = {}
    for a in answers:  # answers naming the same condition are one claim, tagged piece by piece
        if a.fact:
            groups.setdefault(slug(a.fact), []).append(a)
    best = score(kept)
    for group in groups.values():
        trial = score([*kept, *group])
        if trial[0] > best[0] + 1e-9 or trial[1] < best[1]:
            kept.extend(group)
            best = trial
        else:
            dropped.extend(group)
    return kept, dropped


def save_answers(answers: list[Answer], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(a), ensure_ascii=False) + "\n" for a in answers), encoding="utf-8")


def load_answers(path: Path) -> list[Answer]:
    if not path.is_file():
        return []
    return [Answer(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def effect(decisions: list[Decision], answers: list[Answer]) -> dict:
    """What the answers changed: the rule and how many decisions it explains, before and after.

    Both are measured on the decisions the person was asked about plus all others, using the
    rule fitted on everything (training accuracy), and by leave-one-out disagreements.
    """
    before_tree = induce.fit(decisions)
    before = {"rule": induce.rules(before_tree), "accuracy": induce.accuracy(before_tree, decisions),
              "unexplained": len(induce.disagreements(decisions))}
    apply_answers(decisions, answers)
    after_tree = induce.fit(decisions)
    after = {"rule": induce.rules(after_tree), "accuracy": induce.accuracy(after_tree, decisions),
             "unexplained": len(induce.disagreements(decisions))}
    return {"before": before, "after": after, "facts": sorted({slug(a.fact) for a in answers if a.fact})}
