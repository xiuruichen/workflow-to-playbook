"""Second planted-rule domain: an accounts-payable clerk reviewing the top overdue invoice each day.

Written to test whether the method is more than the dashboard trick, so the rule differs on
purpose: three outcomes (Escalate, Approve, leave alone), a numeric threshold on one value plus
a second on another, a *word* on screen (the vendor is Known or New) and a different cross-session
exception. **This rule was fixed before any result on this domain was looked at.**

Each visit is one review of the invoice at the top of the queue. With probability 0.3 it is the
same invoice as at the previous review (a day older, same amount); otherwise a new one. The hidden
rule, never labelled on screen:

    amount >= 5,000: escalate if it is at least 30 days overdue AND it is a different invoice
        from the last review (the same one was already dealt with); otherwise leave it alone.
    amount <  5,000: approve if the vendor is Known; leave it alone if the vendor is New.

"The amount changed since the last review" is never shown; only the sequence of visits reveals it,
as with the batch size on the dashboard. All data is fictional.

Base rates were set on development seeds 100-102 (not the confirmatory seeds 1-5) so that every branch of the rule
occurs often enough to be learnable from 40 visits: half the invoices are 5,000 or more, 60% of those are at least
30 days overdue, and about 70% of visits are a new invoice, so about 20% of visits escalate. The first version, with
rarer escalations (4 of 40), was not learnable from 28 training visits; that is a sample-size limit, not a finding.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .scenarios import Scenario, Script, box, canvas, text, titlebar

AMOUNT_LIMIT = 5000
OVERDUE_LIMIT = 30
ESCALATE_BTN = (880, 600)
APPROVE_BTN = (1060, 600)
AMOUNTS = (450, 1200, 2300, 3400, 5200, 6100, 7400, 9800)
TITLE = "Overdue invoices - Review queue - Excel"


@dataclass
class Visit:
    amount: int
    days_overdue: int
    vendor: str  # "Known" or "New"
    amount_changed: bool  # ground truth: a different invoice from the previous review

    @property
    def outcome(self) -> str:
        if self.amount >= AMOUNT_LIMIT:
            return "Escalate" if self.days_overdue >= OVERDUE_LIMIT and self.amount_changed else "none"
        return "Approve" if self.vendor == "Known" else "none"


def make_visits(n: int, seed: int = 0) -> list[Visit]:
    """A reproducible run of daily reviews; now and then the same invoice comes up again, a day older."""
    rng = random.Random(seed)
    visits: list[Visit] = []
    for i in range(n):
        if visits and rng.random() < 0.3:
            prev = visits[-1]
            visits.append(Visit(prev.amount, prev.days_overdue + 1, prev.vendor, False))
        else:
            amount = rng.choice(AMOUNTS) + rng.randrange(0, 90)
            changed = i > 0 and amount != visits[-1].amount
            visits.append(Visit(amount, rng.randrange(10, 60), rng.choice(["Known", "New"]), changed))
    return visits


def triage_screen(v: Visit, done: str | None = None, separators: bool = False) -> np.ndarray:
    img = canvas((250, 250, 252))
    titlebar(img, TITLE)
    text(img, "AP / overdue / top of queue", 40, 80, 0.9, thick=2)
    rows = [("Amount", f"{v.amount:,}" if separators else str(v.amount)), ("Days overdue", str(v.days_overdue)), ("Vendor", v.vendor)]
    for i, (label, value) in enumerate(rows):
        y = 150 + i * 60
        box(img, 40, y - 32, 400, y + 18, fill=(255, 255, 255))
        text(img, f"{label}: {value}", 56, y, 0.9, thick=2)
    box(img, 440, 120, 1000, 520, fill=(255, 255, 255))  # a grid-shaped panel (not read by the pipeline)
    for r in range(8):
        box(img, 440, 120 + r * 50, 1000, 170 + r * 50, border=(220, 220, 220))
    for x, label, color in ((ESCALATE_BTN[0], "Escalate", (60, 60, 200)), (APPROVE_BTN[0], "Approve", (60, 150, 60))):
        box(img, x - 85, 575, x + 85, 625, fill=color, border=None)
        text(img, label, x - 70, 608, 0.8, (255, 255, 255), 2)
    if done:
        text(img, f"{done} recorded", 40, 360, 1.0, (40, 40, 180), 2)
    return img


def visit_scenario(v: Visit, name: str, dwell_s: float = 12.0, separators: bool = False) -> Scenario:
    def build() -> Script:
        s = Script(triage_screen(v, separators=separators), "excel.exe", TITLE)
        s.wait(1.0)
        s.click(200, 80, hold=0.5)  # open the queue (an ordinary click, so the visit starts with an event)
        s.wait(dwell_s)  # reads the invoice
        if v.outcome == "Escalate":
            s.click(*ESCALATE_BTN, then=triage_screen(v, "Escalate", separators), hold=1.5)
        elif v.outcome == "Approve":
            s.click(*APPROVE_BTN, then=triage_screen(v, "Approve", separators), hold=1.5)
        else:
            s.wait(2.0)
        return s

    return Scenario(name, "Review the top overdue invoice and decide what to do", build, expected_steps=[])


def planted_label(v: Visit) -> str:
    return v.outcome


def rule_recovery(decisions, visits: list[Visit]) -> float:
    """Fraction of decisions whose recorded outcome matches the planted rule (a check on the capture itself)."""
    def norm(o: str) -> str:
        return "none" if o == "none" else o.lower().replace(" ", "")

    ok = sum(norm(d.outcome) == v.outcome.lower() for d, v in zip(decisions, visits))
    return ok / len(visits) if visits else 0.0


def build_sessions(settings: Settings, root: Path, visits: list[Visit], separators: bool = False) -> list[Path]:
    from .scenarios import simulate

    return [simulate(visit_scenario(v, f"visit{i:03d}", separators=separators), settings, root / f"visit{i:03d}") for i, v in enumerate(visits)]


def _drifted_outcome(v: Visit) -> str:
    if v.amount >= AMOUNT_LIMIT:
        return "Escalate" if v.days_overdue >= OVERDUE_LIMIT + 15 and v.amount_changed else "none"
    return "Approve" if v.vendor == "Known" else "none"


def domain():
    from .study import Domain

    return Domain(
        "triage", make_visits,
        lambda v: {"amount": float(v.amount), "days_overdue": float(v.days_overdue)},
        lambda v, drifted: _drifted_outcome(v) if drifted else v.outcome,
        ("Escalate", "Approve"),
        "the overdue limit rises from 30 to 45 days",
        cats=lambda v: {"vendor": v.vendor.lower()},
        depends_on_history=lambda v: v.amount >= AMOUNT_LIMIT and v.days_overdue >= OVERDUE_LIMIT,
    )


def evaluate(n: int = 40, seed: int = 0, settings: Settings | None = None, root: Path | None = None) -> dict:
    """Capture n visits, fit a rule on the earliest 70%, and score it on the rest (as dashboard.evaluate)."""
    import tempfile
    from collections import Counter

    from . import induce
    from .config import get_settings
    from .decisions import pool

    settings = settings or get_settings()
    root = root or Path(tempfile.mkdtemp(prefix="triage_eval_"))
    visits = make_visits(n, seed)
    decisions = pool(build_sessions(settings, root, visits))
    cut = max(1, int(len(decisions) * 0.7))
    tree = induce.fit(decisions[:cut])
    majority = Counter(d.outcome for d in decisions[:cut]).most_common(1)[0][0]
    test = decisions[cut:]
    return {
        "domain": "triage", "visits": n, "seed": seed, "train": cut, "test": len(test),
        "capture_matches_planted_rule": rule_recovery(decisions, visits),
        "test_accuracy_with_context": induce.accuracy(tree, test),
        "test_accuracy_without_context": induce.holdout(decisions, without="context")["test_accuracy"],
        "test_accuracy_majority_baseline": sum(d.outcome == majority for d in test) / len(test) if test else 0.0,
        "rule": induce.rules(tree),
        "disagreements": len(induce.disagreements(decisions)),
        "sessions": str(root),
    }
