"""A rule list: "if A and B then X; otherwise if C then Y; otherwise Z", learned by sequential covering.

A decision tree must split the whole space at each step. A person's rule is often a *regime* plus *exceptions*
("above 5,000: escalate if it is late and new, otherwise leave; below: approve if the vendor is known"), which a list of
short conjunctions says directly and may need fewer examples to find. Same readable output as the tree (sentences, with
support), same use in the skill (rules are exported in order and the first that matches applies).

Learning: take the label that is not the default, grow one rule by adding the condition that makes the covered examples
purest (a threshold on one feature), stop at a precision bar or three conditions, remove what it covers, repeat; the
default is whatever label is most common among what is left. Pure Python.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .decisions import Decision

DERIVED_PENALTY = 0.05  # as in induce.py: changed_x, delta_x and ratios must beat a plain readout by this much


@dataclass
class Leaf:
    label: str
    n: int
    correct: int


@dataclass
class Rule:
    conds: tuple[tuple[str, str, float], ...]  # (feature, "<=" or ">", threshold)
    label: str
    n: int
    correct: int

    def matches(self, d: Decision) -> bool:
        return all((d.features.get(f, float("-inf")) <= t) if op == "<=" else (d.features.get(f, float("-inf")) > t) for f, op, t in self.conds)

    def texts(self) -> tuple[str, ...]:
        return tuple(f"{f} {op} {t:g}" for f, op, t in self.conds)


@dataclass
class RuleList:
    rules: list[Rule] = field(default_factory=list)
    default: str = ""
    default_n: int = 0
    default_correct: int = 0

    def predict(self, d: Decision) -> str:
        return next((r.label for r in self.rules if r.matches(d)), self.default)

    def leaves(self) -> list[tuple[tuple[str, ...], Leaf]]:
        """Rules in order, then the default as 'always'; the first rule that matches applies (as the skill's reader does)."""
        out = [(r.texts(), Leaf(r.label, r.n, r.correct)) for r in self.rules]
        return out + [((), Leaf(self.default, self.default_n, self.default_correct))]

    def lines(self) -> list[str]:
        out = [f"{' and '.join(r.texts())} -> {r.label} ({r.correct}/{r.n})" for r in self.rules]
        return out + [f"otherwise -> {self.default} ({self.default_correct}/{self.default_n})"]

    def features_used(self) -> set[str]:
        return {f for r in self.rules for f, _, _ in r.conds}

    def path_features(self, d: Decision) -> set[str]:
        r = next((r for r in self.rules if r.matches(d)), None)
        return {f for f, _, _ in r.conds} if r else set()


def _penalty(f: str) -> float:
    return DERIVED_PENALTY if f.startswith(("changed_", "delta_")) or "/" in f else 0.0


def _grow(rows: list[Decision], target: str, features: list[str], thresholds: dict[str, list[float]], min_cover: int,
          min_precision: float, max_conds: int) -> Rule | None:
    """One rule for `target`: add the threshold condition that makes the covered rows purest, until precise enough."""
    covered, conds = rows, []
    best_prec = sum(r.outcome == target for r in rows) / len(rows)
    for _ in range(max_conds):
        pick = None
        for f in features:
            for t in thresholds[f]:
                for op in ("<=", ">"):
                    sub = [r for r in covered if ((r.features.get(f, float("-inf")) <= t) if op == "<=" else (r.features.get(f, float("-inf")) > t))]
                    if len(sub) < min_cover or len(sub) == len(covered):
                        continue
                    pos = sum(r.outcome == target for r in sub)
                    if pos < min_cover:
                        continue
                    score = (pos + 0.5) / (len(sub) + 1) - _penalty(f)  # smoothed precision
                    key = (score, pos, -len(conds))
                    if pick is None or key > pick[0]:
                        pick = (key, f, op, t, sub, pos / len(sub))
        if pick is None or pick[5] <= best_prec - 1e-9 and conds:
            break
        _, f, op, t, covered, best_prec = pick
        conds.append((f, op, t))
        if best_prec >= min_precision:
            break
    if not conds:
        return None
    pos = sum(r.outcome == target for r in covered)
    return Rule(tuple(conds), target, len(covered), pos) if pos / len(covered) >= min_precision and pos >= min_cover else None


def fit_rulelist(decisions: list[Decision], max_rules: int = 6, min_precision: float = 0.9, min_cover: int = 2, max_conds: int = 3) -> RuleList:
    if not decisions:
        raise ValueError("no decisions to fit")
    features = sorted({k for d in decisions for k in d.features})
    thresholds = {}
    for f in features:
        vals = sorted({d.features.get(f, float("-inf")) for d in decisions})
        thresholds[f] = [(a + b) / 2 if a != float("-inf") else b - 1.0 for a, b in zip(vals, vals[1:])]
    remaining, rules = list(decisions), []
    default = Counter(d.outcome for d in decisions).most_common(1)[0][0]
    for _ in range(max_rules):
        default = Counter(d.outcome for d in remaining).most_common(1)[0][0]
        rest = [d for d in remaining if d.outcome != default]
        if len(rest) < min_cover:
            break
        candidates = [r for label in sorted({d.outcome for d in rest})
                      if (r := _grow(remaining, label, features, thresholds, min_cover, min_precision, max_conds))]
        if not candidates:
            break
        rule = max(candidates, key=lambda r: (r.correct, r.correct / r.n, -len(r.conds)))
        rules.append(rule)
        remaining = [d for d in remaining if not rule.matches(d)]
        if not remaining:
            break
    default = Counter(d.outcome for d in remaining).most_common(1)[0][0] if remaining else default
    return RuleList(rules, default, len(remaining), sum(d.outcome == default for d in remaining))
