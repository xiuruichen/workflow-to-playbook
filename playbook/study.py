"""Fast, model-free experiments on planted-rule domains (docs/evaluation-protocol.md).

The capture path (drawn frames or a real window, then OCR) takes seconds per visit. Most protocol
questions (does cross-session context help, how many visits does a rule need, what do noisy labels
do) only concern what happens *after* capture, so this module builds the decision log directly
from the visit sequence and runs `induce` / `elicit` on it in milliseconds. A test
(`test_fast_harness_matches_the_capture_path`) checks the direct log against what the real pipeline
reads from rendered screens, so the shortcut stays honest.

Knobs, all off by default: `label_noise` (the person acts against their own rule this often),
`misread` (a digit of a readout is misread this often, as OCR sometimes does), `distractors`
(extra readouts unrelated to the rule), `drift_at` (the rule changes from this visit on),
`hidden_fact` (a fact that is never on screen changes what the person does; the thing `elicit`
is for).
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from . import elicit, induce
from .decisions import NONE, Decision, add_context

HIDDEN_FACT = "warmup"
HIDDEN_PERIOD = (3, 4)  # visits i with i % 9 in this range happen "during warmup": the person waits


@dataclass
class Domain:
    name: str
    make_visits: Callable[[int, int], list]
    readouts: Callable[[object], dict[str, float]]  # what is on screen, as the pipeline would read it
    outcome: Callable[[object, bool], str]  # (visit, rule_has_drifted) -> label of what the planted rule does
    actions: tuple[str, ...]  # every label other than NONE the rule can produce
    drift_note: str = ""
    cats: Callable[[object], dict[str, str]] | None = None  # words on screen, e.g. {"vendor": "known"}
    # Ground truth for E6: does the planted outcome of this visit depend on a fact only earlier visits show?
    depends_on_history: Callable[[object], bool] | None = None


def _dashboard() -> Domain:
    from . import dashboard

    def outcome(v, drifted: bool) -> str:
        limit = dashboard.SPIKE_LIMIT + (1 if drifted else 0)
        return "Stop run" if v.spikes >= limit and not v.batch_changed else NONE

    return Domain("dashboard", dashboard.make_visits,
                  lambda v: {"spikes": float(v.spikes), "batch_size": float(v.batch_size), "loss": float(v.loss)},
                  outcome, ("Stop run",), "the spike limit rises from 2 to 3",
                  depends_on_history=lambda v: v.spikes >= dashboard.SPIKE_LIMIT)


def domains() -> dict[str, Domain]:
    out = {"dashboard": _dashboard()}
    try:
        from . import triage

        out["triage"] = triage.domain()
    except ImportError:  # the second domain is optional until it exists
        pass
    return out


def _misread(value: float, rng: random.Random) -> float:
    text = f"{value:g}"
    digits = [i for i, c in enumerate(text) if c.isdigit()]
    if not digits:
        return value
    i = rng.choice(digits)
    new = rng.choice([c for c in "0123456789" if c != text[i]])
    try:
        return float(text[:i] + new + text[i + 1:])
    except ValueError:
        return value


@dataclass
class Built:
    decisions: list[Decision]
    clean: dict[str, str]  # decision key -> what the planted rule says (before any noise)
    hidden: set[str]  # keys of decisions made during the off-screen warmup
    flipped: set[str]  # keys of decisions where the person acted against their rule


def build(domain: Domain, n: int, seed: int, *, label_noise: float = 0.0, misread: float = 0.0, distractors: int = 0,
          drift_at: int | None = None, hidden_fact: bool = False) -> Built:
    visits = domain.make_visits(n, seed)
    rng = random.Random(f"study-{domain.name}-{seed}")
    rows, clean, hidden, flipped = [], {}, set(), set()
    for i, v in enumerate(visits):
        drifted = drift_at is not None and i >= drift_at
        planted = domain.outcome(v, drifted)
        warm = hidden_fact and i % 9 in HIDDEN_PERIOD
        if warm:
            planted = NONE  # the person waits while the run is warming up
        shown = planted
        if rng.random() < label_noise:
            shown = rng.choice([a for a in (NONE, *domain.actions) if a != planted])
        reads = dict(domain.readouts(v))
        for name in list(reads):
            if rng.random() < misread:
                reads[name] = _misread(reads[name], rng)
        for k in range(distractors):
            reads[f"aux{k + 1}"] = round(rng.uniform(0, 10), 1)
        d = Decision(f"visit{i:03d}", i * 30.0, i * 30.0 + 12.0, "study", reads, shown,
                     cats=dict(domain.cats(v)) if domain.cats else {})
        rows.append(d)
        key = elicit.key(d)
        clean[key] = planted
        if warm:
            hidden.add(key)
        if shown != planted:
            flipped.add(key)
    return Built(add_context(rows), clean, hidden, flipped)


def majority_accuracy(train: list[Decision], test: list[Decision]) -> float:
    if not train or not test:
        return 0.0
    label = Counter(d.outcome for d in train).most_common(1)[0][0]
    return sum(d.outcome == label for d in test) / len(test)


def simulated_expert(questions: list[elicit.Question], hidden: set[str], rng: random.Random,
                     accuracy: float = 1.0, wrong_fact: bool = False) -> list[elicit.Answer]:
    """A scripted person who answers each question about a decision made during warmup by naming
    the warmup fact and tagging the warmup decisions among those shown. With probability
    1 - accuracy the answer is wrong: no usable fact, or (wrong_fact) a fact tagged on the wrong decisions."""
    answers = []
    for q in questions:
        if elicit.key(q.decision) not in hidden:
            continue
        cands = elicit.tag_candidates(q, questions)
        if rng.random() < accuracy:
            tagged = [elicit.key(c) for c in cands if elicit.key(c) in hidden]
            answers.append(elicit.Answer(q.decision.session, q.decision.t1, "the run was still warming up", HIDDEN_FACT,
                                         [k for k in tagged if k != elicit.key(q.decision)]))
        elif wrong_fact:
            wrong = [elicit.key(c) for c in rng.sample(cands, k=min(2, len(cands)))]
            answers.append(elicit.Answer(q.decision.session, q.decision.t1, "it just felt wrong", HIDDEN_FACT,
                                         [k for k in wrong if k != elicit.key(q.decision)]))
        else:
            answers.append(elicit.Answer(q.decision.session, q.decision.t1, "I don't remember why", None, []))
    return answers


def elicitation(built: Built, seed: int, accuracy: float = 1.0, wrong_fact: bool = False, train_fraction: float = 0.7) -> dict:
    """H4: ask about the training decisions the rule can't explain, apply the answers, compare held-out agreement.

    As in replay.py, the fact's value for held-out decisions is supplied as if a human had been asked.
    """
    cut = max(1, int(len(built.decisions) * train_fraction))
    train = [Decision(**{**d.__dict__, "features": dict(d.features)}) for d in built.decisions[:cut]]
    test = [Decision(**{**d.__dict__, "features": dict(d.features)}) for d in built.decisions[cut:]]
    before = induce.accuracy(induce.fit(train), test)
    questions = elicit.build_questions(train)
    answers = simulated_expert(questions, built.hidden, random.Random(f"expert-{seed}"), accuracy, wrong_fact)
    elicit.apply_answers(train, answers)
    facts = {a.fact for a in answers if a.fact}
    for d in test:
        for fact in facts:
            d.features[fact] = 1.0 if elicit.key(d) in built.hidden else 0.0
    after = induce.accuracy(induce.fit(train), test)
    return {"questions": len(questions), "answers": len(answers), "test_before": before, "test_after": after,
            "unexplained_before": len(questions), "unexplained_after": len(induce.disagreements(train))}


def run(domain: Domain, n: int, seed: int, **knobs) -> dict:
    """One experiment: the ablations, the baseline, rule recovery against the planted rule, and what the
    disagreements point at."""
    built = build(domain, n, seed, **knobs)
    ds = built.decisions
    full = induce.holdout(ds)
    cut = max(1, int(len(ds) * 0.7))
    tree_all = induce.fit(ds)
    # Rule recovery: agreement of a rule fitted on everything with what the planted rule says (no noise).
    recovery = sum(induce.predict(tree_all, d) == built.clean[elicit.key(d)] for d in ds) / len(ds)
    odd = induce.disagreements(ds)
    flagged = {elicit.key(d) for d, _ in odd}
    return {
        "domain": domain.name, "n": n, "seed": seed, **knobs,
        "test_agreement": full["test_accuracy"],
        "without_context": induce.holdout(ds, without="context")["test_accuracy"],
        "without_none": induce.holdout(ds, without="none")["test_accuracy"],
        "majority": majority_accuracy(ds[:cut], ds[cut:]),
        "recovery": recovery,
        "rule": full["rule"],
        "unexplained": len(odd),
        "unexplained_that_were_noise": len(flagged & built.flipped),
        "noisy_decisions": len(built.flipped),
    }


def summarize(rows: list[dict], keys: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """Mean, min and max of each numeric key over the rows (one row per seed)."""
    return {k: {"mean": round(statistics.fmean(r[k] for r in rows), 3), "min": round(min(r[k] for r in rows), 3),
                "max": round(max(r[k] for r in rows), 3)} for k in keys}
