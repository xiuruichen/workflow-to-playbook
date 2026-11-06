"""Fit a short, readable rule to pooled decisions, then list where behaviour disagrees with it.

Tacit expertise often looks like a rule the person has never stated ("one spike is fine, two
close together means the run is diverging, unless the batch size was just changed"). Given
the screen state at each decision and what the person did (including doing nothing), we
recover a small decision tree over the numeric features. This is a simple stand-in for
inverse reinforcement learning (Ng and Russell, 2000, see docs/references.bib): recover what
the person is optimising from what they chose. A tree is used because the expert has to be
able to read, dispute and correct it.

The cases the rule gets wrong, or fits only by luck, are where the expert is asked to explain
(elicit.py). Pure Python, no training time worth measuring.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .decisions import Decision

MAX_DEPTH = 3
MIN_LEAF = 2
# Context features (changed_x, delta_x) are derived from neighbouring decisions and there are
# many of them, so they can fit noise. They must beat a plain on-screen number by this margin.
DERIVED_PENALTY = 0.05


@dataclass
class Node:
    label: str  # majority outcome at this node
    n: int
    correct: int  # training decisions at this node whose outcome equals `label`
    feature: str | None = None
    threshold: float | None = None
    low: "Node | None" = None  # feature <= threshold
    high: "Node | None" = None

    @property
    def leaf(self) -> bool:
        return self.feature is None


def _gini(labels: list[str]) -> float:
    n = len(labels)
    return 1.0 - sum((c / n) ** 2 for c in Counter(labels).values()) if n else 0.0


def _build(rows: list[Decision], depth: int, max_depth: int, min_leaf: int) -> Node:
    labels = [d.outcome for d in rows]
    label, count = Counter(labels).most_common(1)[0]
    node = Node(label, len(rows), count)
    if depth >= max_depth or len(set(labels)) == 1 or len(rows) < 2 * min_leaf:
        return node
    best: tuple[float, str, float] | None = None
    base = _gini(labels)
    for f in sorted({k for d in rows for k in d.features}):
        vals = sorted({d.features[f] for d in rows if f in d.features})
        for a, b in zip(vals, vals[1:]):
            thr = (a + b) / 2
            lo = [d.outcome for d in rows if d.features.get(f, float("-inf")) <= thr]
            hi = [d.outcome for d in rows if d.features.get(f, float("-inf")) > thr]
            if len(lo) < min_leaf or len(hi) < min_leaf:
                continue
            # A split must get more training decisions right, not just look purer: otherwise it only
            # memorises a stray case (and a readout that drifts with time, like loss, can do that).
            right = Counter(lo).most_common(1)[0][1] + Counter(hi).most_common(1)[0][1]
            if right <= count:
                continue
            gain = base - (len(lo) * _gini(lo) + len(hi) * _gini(hi)) / len(rows)
            score = gain - (DERIVED_PENALTY if f.startswith(("changed_", "delta_")) else 0.0)
            if gain > 1e-9 and score > 0 and (best is None or score > best[0] + 1e-12):
                best = (score, f, thr)
    if best is None:
        return node
    _, f, thr = best
    lo_rows = [d for d in rows if d.features.get(f, float("-inf")) <= thr]
    hi_rows = [d for d in rows if d.features.get(f, float("-inf")) > thr]
    node.feature, node.threshold = f, thr
    node.low = _build(lo_rows, depth + 1, max_depth, min_leaf)
    node.high = _build(hi_rows, depth + 1, max_depth, min_leaf)
    return node


def fit(decisions: list[Decision], max_depth: int = MAX_DEPTH, min_leaf: int = MIN_LEAF) -> Node:
    if not decisions:
        raise ValueError("no decisions to fit")
    return _build(decisions, 0, max_depth, min_leaf)


def leaves(tree: Node, conds: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Node]]:
    """(conditions, leaf) for every leaf, e.g. (('spikes > 1.5', 'changed_batch_size <= 0.5'), leaf)."""
    if tree.leaf:
        return [(conds, tree)]
    return (leaves(tree.low, (*conds, f"{tree.feature} <= {tree.threshold:g}"))
            + leaves(tree.high, (*conds, f"{tree.feature} > {tree.threshold:g}")))


def predict(tree: Node, d: Decision) -> str:
    node = tree
    while not node.leaf:
        node = node.low if d.features.get(node.feature, float("-inf")) <= node.threshold else node.high
    return node.label


def accuracy(tree: Node, decisions: list[Decision]) -> float:
    return sum(predict(tree, d) == d.outcome for d in decisions) / len(decisions) if decisions else 0.0


def features_used(tree: Node) -> set[str]:
    return set() if tree.leaf else {tree.feature} | features_used(tree.low) | features_used(tree.high)


def rules(tree: Node, prefix: str = "") -> list[str]:
    """One readable line per leaf, e.g. 'spikes > 1.5 and changed_batch_size <= 0.5 -> stop (7/7)'."""
    if tree.leaf:
        return [f"{prefix or 'always'} -> {tree.label} ({tree.correct}/{tree.n})"]
    glue = f"{prefix} and " if prefix else ""
    return (rules(tree.low, f"{glue}{tree.feature} <= {tree.threshold:g}")
            + rules(tree.high, f"{glue}{tree.feature} > {tree.threshold:g}"))


def disagreements(decisions: list[Decision], max_depth: int = MAX_DEPTH, min_leaf: int = MIN_LEAF) -> list[tuple[Decision, str]]:
    """Decisions whose outcome the rule fitted on all the *other* decisions would not predict.

    Leave-one-out, so a decision can't be explained by itself. Returns (decision, predicted outcome).
    """
    out = []
    for i, d in enumerate(decisions):
        rest = decisions[:i] + decisions[i + 1:]
        if len({r.outcome for r in rest}) < 1 or not rest:
            continue
        guess = predict(fit(rest, max_depth, min_leaf), d)
        if guess != d.outcome:
            out.append((d, guess))
    return out


def holdout_accuracy(decisions: list[Decision], train_fraction: float = 0.7, **kw) -> tuple[float, float]:
    """(train, test) accuracy for a chronological split: fit on the earliest decisions, test on the rest."""
    cut = max(1, int(len(decisions) * train_fraction))
    train, test = decisions[:cut], decisions[cut:]
    tree = fit(train, **kw)
    return accuracy(tree, train), accuracy(tree, test)
