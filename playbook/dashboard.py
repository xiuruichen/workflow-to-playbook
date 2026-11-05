"""Synthetic benchmark with a planted, unstated rule: when does an ML engineer kill a training run?

Each simulated session is one visit to a training dashboard. The person looks at the readouts
for a while and then either clicks "Stop run" or does nothing. The hidden rule:

    stop the run if there were >= 2 gradient-norm spikes recently, unless the batch size was
    just changed (then wait); otherwise leave it alone.

The batch size is never labelled "changed" on screen. Only the sequence of sessions shows it,
which is what makes the rule cross-session. Ground truth is known, so `rule_recovery` can
score how well a fitted rule matches the planted one on held-out visits. All data is fictional.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .scenarios import H, W, Scenario, Script, box, canvas, text, titlebar

STOP_BTN = (1000, 600)  # centre of the "Stop run" button
SPIKE_LIMIT = 2


@dataclass
class Visit:
    spikes: int
    batch_size: int
    batch_changed: bool  # ground truth: differs from the previous visit
    loss: float

    @property
    def stop(self) -> bool:
        return self.spikes >= SPIKE_LIMIT and not self.batch_changed


def make_visits(n: int, seed: int = 0) -> list[Visit]:
    """A reproducible two-week sequence of visits; the batch size is raised now and then."""
    rng = random.Random(seed)
    visits, batch, loss = [], 256, 3.0
    for i in range(n):
        changed = i > 0 and rng.random() < 0.3  # the first visit has nothing to compare with
        if changed:
            batch *= 2
        loss = max(0.5, loss - rng.random() * 0.1)
        spikes = rng.choices([0, 1, 2, 3], weights=[2, 2, 3, 2])[0]
        visits.append(Visit(spikes, batch, changed, round(loss, 2)))
    return visits


def dashboard_screen(v: Visit, stopped: bool = False) -> np.ndarray:
    img = canvas((245, 247, 250))
    titlebar(img, "Run 7 - Training dashboard - Chrome")
    text(img, "pretrain-sweep / run-7", 40, 80, 0.9, thick=2)
    for i, (label, value) in enumerate([("Spikes", str(v.spikes)), ("Batch size", str(v.batch_size)), ("Loss", f"{v.loss:.2f}")]):
        y = 150 + i * 60
        box(img, 40, y - 32, 360, y + 18, fill=(255, 255, 255))
        text(img, f"{label}: {value}", 56, y, 0.9, thick=2)
    box(img, 420, 120, 960, 520, fill=(255, 255, 255))  # a chart-shaped panel (not read by the pipeline)
    pts = np.array([[430 + i * 8, 500 - int(300 * np.exp(-i / 25.0)) - (40 if i in (30, 33) and v.spikes else 0)]
                    for i in range(65)], np.int32)
    import cv2

    cv2.polylines(img, [pts], False, (200, 110, 30), 2)
    box(img, 900, 575, 1100, 625, fill=(60, 60, 200), border=None)
    text(img, "Stop run", 925, 608, 0.8, (255, 255, 255), 2)
    if stopped:
        text(img, "Run stopped", 40, 360, 1.0, (40, 40, 180), 2)
    return img


def visit_scenario(v: Visit, name: str, dwell_s: float = 12.0) -> Scenario:
    def build() -> Script:
        s = Script(dashboard_screen(v), "chrome.exe", "Run 7 - Training dashboard - Chrome")
        s.wait(1.0)
        s.click(200, 80, hold=0.5)  # open the run page (an ordinary click, so the visit starts with an event)
        s.wait(dwell_s)  # looks at the curves
        if v.stop:
            s.click(*STOP_BTN, then=dashboard_screen(v, stopped=True), hold=1.5)
        else:
            s.wait(2.0)  # leaves the run alone
        return s

    return Scenario(name, "Check a training run and decide whether to stop it", build, expected_steps=[])


def planted_label(v: Visit) -> str:
    return "stop" if v.stop else "none"


def rule_recovery(decisions, visits: list[Visit]) -> float:
    """Fraction of decisions whose recorded outcome matches the planted rule (a check on the capture itself)."""
    ok = sum((d.outcome != "none") == v.stop for d, v in zip(decisions, visits))
    return ok / len(visits) if visits else 0.0


def build_sessions(settings: Settings, root: Path, visits: list[Visit]) -> list[Path]:
    """Render one session per visit under `root` (names sort in time order)."""
    from .scenarios import simulate

    return [simulate(visit_scenario(v, f"visit{i:03d}"), settings, root / f"visit{i:03d}") for i, v in enumerate(visits)]


def evaluate(n: int = 40, seed: int = 0, settings: Settings | None = None, root: Path | None = None) -> dict:
    """Build n visits, capture them, fit a rule on the earliest 70%, and score it on the rest.

    Reports the capture check, held-out accuracy with and without cross-session context, and
    the majority-outcome baseline.
    """
    import tempfile
    from collections import Counter

    from . import induce
    from .config import get_settings
    from .decisions import pool

    settings = settings or get_settings()
    root = root or Path(tempfile.mkdtemp(prefix="dashboard_eval_"))
    visits = make_visits(n, seed)
    sessions = build_sessions(settings, root, visits)
    decisions = pool(sessions)
    cut = max(1, int(len(decisions) * 0.7))
    plain = [type(d)(**{**d.__dict__, "features": dict(d.readouts)}) for d in decisions]  # no cross-session context
    tree = induce.fit(decisions[:cut])
    majority = Counter(d.outcome for d in decisions[:cut]).most_common(1)[0][0]
    test = decisions[cut:]
    return {
        "visits": n, "seed": seed, "train": cut, "test": len(test),
        "capture_matches_planted_rule": rule_recovery(decisions, visits),
        "test_accuracy_with_context": induce.accuracy(tree, test),
        "test_accuracy_without_context": induce.accuracy(induce.fit(plain[:cut]), plain[cut:]),
        "test_accuracy_majority_baseline": sum(d.outcome == majority for d in test) / len(test) if test else 0.0,
        "rule": induce.rules(tree),
        "disagreements": len(induce.disagreements(decisions)),
        "sessions": str(root),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(evaluate(), indent=2))
