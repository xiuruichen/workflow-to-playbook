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
from dataclasses import dataclass, replace

from .decisions import NONE, Decision, add_ratio_pairs, ratio_pairs
from .rulelist import RuleList, fit_rulelist  # noqa: F401  (a rule list is accepted wherever a tree is)

MAX_DEPTH = 3
MIN_LEAF = 2
# Context features (changed_x, delta_x) are derived from neighbouring decisions and there are
# many of them, so they can fit noise. They must beat a plain on-screen number by this margin.
DERIVED_PENALTY = 0.05
# Opt-in (fit(lookahead=True)): choose each split by how well its children fit after one more split (see
# _with_lookahead). On compound rules it recovers more from few visits; on noisy labels it memorises more.
LOOKAHEAD = False
LOOKAHEAD_MARGIN = 0.05  # training accuracy the lookahead tree must add to be preferred


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


def _penalty(f: str) -> float:
    return DERIVED_PENALTY if f.startswith(("changed_", "delta_")) or "/" in f else 0.0


def _best_split(rows: list[Decision], min_leaf: int) -> tuple[float, str, float, int] | None:
    """The best single split of `rows` that gets more training decisions right than no split:
    (score, feature, threshold, decisions right). Counts are accumulated while sweeping the sorted values."""
    labels = [d.outcome for d in rows]
    base, n = _gini(labels), len(rows)
    total = Counter(labels)
    top = total.most_common(1)[0][1]
    best: tuple[float, str, float, int] | None = None
    for f in sorted({k for d in rows for k in d.features}):
        vals = sorted((d.features.get(f, float("-inf")), d.outcome) for d in rows)
        lo: Counter = Counter()
        for i in range(n - 1):
            lo[vals[i][1]] += 1
            if vals[i][0] == vals[i + 1][0] or i + 1 < min_leaf or n - i - 1 < min_leaf or vals[i][0] == float("-inf") and vals[i + 1][0] == float("-inf"):
                continue
            hi = total - lo
            right = max(lo.values()) + max(hi.values())
            if right <= top:
                continue  # the split must get more training decisions right, not just look purer
            g_lo = 1.0 - sum((c / (i + 1)) ** 2 for c in lo.values())
            g_hi = 1.0 - sum((c / (n - i - 1)) ** 2 for c in hi.values())
            score = base - ((i + 1) * g_lo + (n - i - 1) * g_hi) / n - _penalty(f)
            thr = (vals[i][0] + vals[i + 1][0]) / 2 if vals[i][0] != float("-inf") else vals[i + 1][0] - 1.0
            if score > 1e-9 and (best is None or score > best[0] + 1e-12):
                best = (score, f, thr, right)
    return best


def _with_lookahead(rows: list[Decision], min_leaf: int) -> tuple[float, str, float] | None:
    """Pick the split whose children, each split once more, fit best. A rule made of two regimes
    ("under 5,000: decide by vendor; otherwise by days overdue") has a first split that looks poor on
    its own and is only recognisable by what it makes possible; greedy choice misses it."""
    labels = [d.outcome for d in rows]
    n, top = len(rows), Counter(labels).most_common(1)[0][1]
    base = _gini(labels)
    best: tuple[float, str, float] | None = None
    for f in sorted({k for d in rows for k in d.features}):
        values = sorted({d.features.get(f, float("-inf")) for d in rows})
        for a, b in zip(values, values[1:]):
            thr = (a + b) / 2 if a != float("-inf") else b - 1.0
            lo = [d for d in rows if d.features.get(f, float("-inf")) <= thr]
            hi = [d for d in rows if d.features.get(f, float("-inf")) > thr]
            if len(lo) < min_leaf or len(hi) < min_leaf:
                continue
            right, impurity = 0, 0.0
            for child in (lo, hi):
                lab = [d.outcome for d in child]
                keep = Counter(lab).most_common(1)[0][1]
                nxt = _best_split(child, min_leaf) if len(child) >= 2 * min_leaf and len(set(lab)) > 1 else None
                right += nxt[3] if nxt else keep
                impurity += len(child) * (_gini(lab) - (nxt[0] if nxt else 0.0))
            if right <= top:
                continue
            score = base - impurity / n - _penalty(f)
            if score > 1e-9 and (best is None or score > best[0] + 1e-12):
                best = (score, f, thr)
    return best


def _build(rows: list[Decision], depth: int, max_depth: int, min_leaf: int, lookahead: bool) -> Node:
    labels = [d.outcome for d in rows]
    label, count = Counter(labels).most_common(1)[0]
    node = Node(label, len(rows), count)
    if depth >= max_depth or len(set(labels)) == 1 or len(rows) < 2 * min_leaf:
        return node
    if lookahead and depth + 1 < max_depth:
        found = _with_lookahead(rows, min_leaf)
    else:
        one = _best_split(rows, min_leaf)
        found = (one[0], one[1], one[2]) if one else None
    if found is None:
        return node
    _, f, thr = found
    lo_rows = [d for d in rows if d.features.get(f, float("-inf")) <= thr]
    hi_rows = [d for d in rows if d.features.get(f, float("-inf")) > thr]
    node.feature, node.threshold = f, thr
    node.low = _build(lo_rows, depth + 1, max_depth, min_leaf, lookahead)
    node.high = _build(hi_rows, depth + 1, max_depth, min_leaf, lookahead)
    return node


def fit(decisions: list[Decision], max_depth: int = MAX_DEPTH, min_leaf: int = MIN_LEAF, lookahead: bool | None = None) -> Node:
    """The greedy tree, unless a tree built with lookahead fits the training decisions clearly better.

    The margin matters: searching more widely always fits training data at least as well, and on a
    readout that merely drifts with time (loss) or on noisy labels that is memorising, not finding a rule.
    """
    if not decisions:
        raise ValueError("no decisions to fit")
    greedy = _build(decisions, 0, max_depth, min_leaf, False)
    if not (LOOKAHEAD if lookahead is None else lookahead) or accuracy(greedy, decisions) >= 1.0:
        return greedy
    deep = _build(decisions, 0, max_depth, min_leaf, True)
    return deep if accuracy(deep, decisions) - accuracy(greedy, decisions) >= LOOKAHEAD_MARGIN else greedy


def leaves(tree: Node, conds: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Node]]:
    """(conditions, leaf) for every leaf, e.g. (('spikes > 1.5', 'changed_batch_size <= 0.5'), leaf). For a rule list: its rules in order."""
    if isinstance(tree, RuleList):
        return tree.leaves()
    if tree.leaf:
        return [(conds, tree)]
    return (leaves(tree.low, (*conds, f"{tree.feature} <= {tree.threshold:g}"))
            + leaves(tree.high, (*conds, f"{tree.feature} > {tree.threshold:g}")))


def predict(tree: Node, d: Decision) -> str:
    if isinstance(tree, RuleList):
        return tree.predict(d)
    node = tree
    while not node.leaf:
        node = node.low if d.features.get(node.feature, float("-inf")) <= node.threshold else node.high
    return node.label


def accuracy(tree: Node, decisions: list[Decision]) -> float:
    return sum(predict(tree, d) == d.outcome for d in decisions) / len(decisions) if decisions else 0.0


def features_used(tree: Node) -> set[str]:
    if isinstance(tree, RuleList):
        return tree.features_used()
    return set() if tree.leaf else {tree.feature} | features_used(tree.low) | features_used(tree.high)


def path_features(tree: Node, d: Decision) -> set[str]:
    """The features tested on the way from the root to the leaf that decides `d` (for a rule list: those of the rule that fires)."""
    if isinstance(tree, RuleList):
        return tree.path_features(d)
    out: set[str] = set()
    node = tree
    while not node.leaf:
        out.add(node.feature)
        node = node.low if d.features.get(node.feature, float("-inf")) <= node.threshold else node.high
    return out


def rules(tree: Node, prefix: str = "") -> list[str]:
    """One readable line per leaf, e.g. 'spikes > 1.5 and changed_batch_size <= 0.5 -> stop (7/7)'."""
    if isinstance(tree, RuleList):
        return tree.lines()
    if tree.leaf:
        return [f"{prefix or 'always'} -> {tree.label} ({tree.correct}/{tree.n})"]
    glue = f"{prefix} and " if prefix else ""
    return (rules(tree.low, f"{glue}{tree.feature} <= {tree.threshold:g}")
            + rules(tree.high, f"{glue}{tree.feature} > {tree.threshold:g}"))


def disagreements(decisions: list[Decision], max_depth: int = MAX_DEPTH, min_leaf: int = MIN_LEAF,
                  lookahead: bool | None = None) -> list[tuple[Decision, str]]:
    """Decisions whose outcome the rule fitted on all the *other* decisions would not predict.

    Leave-one-out, so a decision can't be explained by itself. Returns (decision, predicted outcome).
    """
    out = []
    for i, d in enumerate(decisions):
        rest = decisions[:i] + decisions[i + 1:]
        if len({r.outcome for r in rest}) < 1 or not rest:
            continue
        guess = predict(fit(rest, max_depth, min_leaf, lookahead), d)
        if guess != d.outcome:
            out.append((d, guess))
    return out


WITHOUT = ("context", "none")


def strip_context(decisions: list[Decision]) -> list[Decision]:
    """Copies whose features are the on-screen readouts only (no changed_x / delta_x from neighbouring decisions)."""
    return [replace(d, features={k: v for k, v in d.features.items() if not k.startswith(("changed_", "delta_"))}) for d in decisions]


def holdout(decisions: list[Decision], train_fraction: float = 0.7, without: str | None = None, **kw) -> dict:
    """Chronological split with an optional ablation (protocol H2/H3).

    without="context": fit and test on on-screen readouts only. without="none": fit only on decisions where
    the person acted (the non-actions are dropped from training; the test set is unchanged).
    """
    if without not in (None, *WITHOUT):
        raise ValueError(f"without must be one of {WITHOUT}")
    if without == "context":
        decisions = strip_context(decisions)
    cut = max(1, int(len(decisions) * train_fraction))
    train, test = decisions[:cut], decisions[cut:]
    if without == "none":
        train = [d for d in train if d.outcome != NONE] or train
    tree = fit(train, **kw)
    return {"train": len(train), "test": len(test), "train_accuracy": accuracy(tree, train),
            "test_accuracy": accuracy(tree, test), "rule": rules(tree), "tree": tree}


def holdout_accuracy(decisions: list[Decision], train_fraction: float = 0.7, **kw) -> tuple[float, float]:
    """(train, test) accuracy for a chronological split: fit on the earliest decisions, test on the rest."""
    cut = max(1, int(len(decisions) * train_fraction))
    train, test = decisions[:cut], decisions[cut:]
    tree = fit(train, **kw)
    return accuracy(tree, train), accuracy(tree, test)


# --------------------------------------------------------------------------- automatic selection (amendment 9)

AUTO_MARGIN = 0.04  # cross-validated accuracy a variant must add over the plain tree to be preferred
AUTO_FOLDS = 5
# From simplest to most elaborate; ties and near-ties go to the earlier one.
AUTO_MENU = (("plain", "tree"), ("plain", "lookahead"), ("plain", "rulelist"), ("ratios", "tree"), ("ratios", "lookahead"), ("ratios", "rulelist"))


def _copies(decisions: list[Decision]) -> list[Decision]:
    return [replace(d, features=dict(d.features)) for d in decisions]


def _fit_kind(decisions: list[Decision], kind: str):
    if kind == "rulelist":
        return fit_rulelist(decisions)
    return fit(decisions, lookahead=kind == "lookahead")


def _cv_accuracy(decisions: list[Decision], ratios: bool, kind: str, folds: int = AUTO_FOLDS) -> float:
    """Blocked (contiguous) k-fold accuracy, so that a rule that drifts is not flattered by shuffling."""
    n = len(decisions)
    if n < 2 * folds:
        return 0.0
    right = total = 0
    for k in range(folds):
        lo, hi = k * n // folds, (k + 1) * n // folds
        train, test = _copies(decisions[:lo] + decisions[hi:]), _copies(decisions[lo:hi])
        if ratios:
            pairs = ratio_pairs(train)
            add_ratio_pairs(train, pairs)
            add_ratio_pairs(test, pairs)
        model = _fit_kind(train, kind)
        right += sum(predict(model, d) == d.outcome for d in test)
        total += len(test)
    return right / total if total else 0.0


@dataclass
class Auto:
    """The result of `fit_auto`: the model, what it was chosen from, and the means to apply it to new decisions."""
    model: object
    ratios: bool
    kind: str
    pairs: list
    cv: dict

    def prepare(self, decisions: list[Decision]) -> list[Decision]:
        out = _copies(decisions)
        return add_ratio_pairs(out, self.pairs) if self.ratios else out

    def predict(self, d: Decision) -> str:
        return predict(self.model, self.prepare([d])[0])

    def accuracy(self, decisions: list[Decision]) -> float:
        return accuracy(self.model, self.prepare(decisions))

    def rules(self) -> list[str]:
        return rules(self.model)

    @property
    def choice(self) -> str:
        return f"{'with ratio features' if self.ratios else 'plain features'}, {self.kind}"


def fit_auto(decisions: list[Decision], margin: float = AUTO_MARGIN, menu=AUTO_MENU) -> Auto:
    """Fit the plain tree unless a more elaborate variant (ratio features, a lookahead tree, a rule list) predicts clearly
    better under blocked cross-validation on the same decisions (by `margin`). Nothing is tuned on the data to be predicted,
    and with fewer than ten decisions only the plain tree is fitted."""
    cv = {(r, k): _cv_accuracy(decisions, r == "ratios", k) for r, k in menu}
    base = cv[menu[0]]
    best = max(menu, key=lambda m: (cv[m], -menu.index(m)))
    chosen = best if cv[best] >= base + margin else menu[0]
    ratios, kind = chosen[0] == "ratios", chosen[1]
    train = _copies(decisions)
    pairs = ratio_pairs(train) if ratios else []
    if ratios:
        add_ratio_pairs(train, pairs)
    return Auto(_fit_kind(train, kind), ratios, kind, pairs, {f"{r}/{k}": round(v, 3) for (r, k), v in cv.items()})
