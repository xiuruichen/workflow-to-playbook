"""Third planted-rule domain: an on-call engineer checking a service after deploys.

Written to test a failure the first two domains cannot show: a rule on a *ratio* of two readouts.
People reason in rates ("1% of requests are failing"), but the screen shows counts, and a tree that
splits on one readout at a time cannot express "errors divided by requests". **This rule was fixed
before any result on this domain was looked at.**

Each visit is one check of the service. The hidden rule, never labelled on screen:

    error rate = Errors / Requests
    error rate >= 5%                                   -> Page on-call (whatever else is going on)
    error rate >= 1% and Latency >= 400 ms, and the Version is the same as at the last check
                                                       -> Roll back
    anything else (including the same symptoms right after a new Version: give the deploy time)
                                                       -> leave it alone

"The version changed since the last check" is never labelled; only the sequence of visits shows it.
All data is fictional.

Base rates were set on development seeds 100-119 (not the confirmatory seeds). The first version drew requests from
5,000-20,000, where the raw error count is a good proxy for the rate and a one-readout tree does well; requests now
span 2,000-200,000 so that only the quotient carries the rule.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Settings
from .scenarios import Scenario, Script, box, canvas, text, titlebar

PAGE_RATE = 0.05
ROLLBACK_RATE = 0.01
LATENCY_LIMIT = 400
ROLLBACK_BTN = (880, 600)
PAGE_BTN = (1060, 600)
RATES = (0.001, 0.004, 0.008, 0.013, 0.02, 0.03, 0.06, 0.09)
TITLE = "Service health - Checks - Chrome"


@dataclass
class Visit:
    requests: int
    errors: int
    latency: int
    version: int
    version_changed: bool  # ground truth: a new build since the last check

    @property
    def rate(self) -> float:
        return self.errors / self.requests

    @property
    def outcome(self) -> str:
        if self.rate >= PAGE_RATE:
            return "Page on-call"
        if self.rate >= ROLLBACK_RATE and self.latency >= LATENCY_LIMIT and not self.version_changed:
            return "Roll back"
        return "none"


def make_visits(n: int, seed: int = 0) -> list[Visit]:
    rng = random.Random(seed)
    out: list[Visit] = []
    version = 40
    for i in range(n):
        changed = i > 0 and rng.random() < 0.25
        version += 1 if changed else 0
        requests = rng.choice([2000, 5000, 12000, 30000, 80000, 200000]) + rng.randrange(0, 900)
        errors = round(requests * rng.choice(RATES) * rng.uniform(0.9, 1.1))
        out.append(Visit(requests, errors, rng.choice([120, 180, 260, 340, 450, 520, 610, 700]), version, changed))
    return out


def service_screen(v: Visit, done: str | None = None) -> np.ndarray:
    img = canvas((248, 250, 250))
    titlebar(img, TITLE)
    text(img, "payments-api / production", 40, 80, 0.9, thick=2)
    rows = [("Requests", str(v.requests)), ("Errors", str(v.errors)), ("Latency", str(v.latency)), ("Version", str(v.version))]
    for i, (label, value) in enumerate(rows):
        y = 140 + i * 56
        box(img, 40, y - 30, 380, y + 16, fill=(255, 255, 255))
        text(img, f"{label}: {value}", 56, y, 0.85, thick=2)
    box(img, 440, 120, 1000, 520, fill=(255, 255, 255))  # a chart-shaped panel (not read by the pipeline)
    for x, label, color in ((ROLLBACK_BTN[0], "Roll back", (60, 60, 200)), (PAGE_BTN[0], "Page on-call", (40, 120, 200))):
        box(img, x - 95, 575, x + 95, 625, fill=color, border=None)
        text(img, label, x - 85, 608, 0.7, (255, 255, 255), 2)
    if done:
        text(img, f"{done} done", 40, 400, 1.0, (40, 40, 180), 2)
    return img


def visit_scenario(v: Visit, name: str, dwell_s: float = 12.0) -> Scenario:
    def build() -> Script:
        s = Script(service_screen(v), "chrome.exe", TITLE)
        s.wait(1.0)
        s.click(200, 80, hold=0.5)
        s.wait(dwell_s)
        if v.outcome == "Roll back":
            s.click(*ROLLBACK_BTN, then=service_screen(v, "Roll back"), hold=1.5)
        elif v.outcome == "Page on-call":
            s.click(*PAGE_BTN, then=service_screen(v, "Page on-call"), hold=1.5)
        else:
            s.wait(2.0)
        return s

    return Scenario(name, "Check the service and decide what to do", build, expected_steps=[])


def build_sessions(settings: Settings, root: Path, visits: list[Visit]) -> list[Path]:
    from .scenarios import simulate

    return [simulate(visit_scenario(v, f"visit{i:03d}"), settings, root / f"visit{i:03d}") for i, v in enumerate(visits)]


def _drifted(v: Visit) -> str:
    if v.rate >= PAGE_RATE * 1.5:
        return "Page on-call"
    if v.rate >= ROLLBACK_RATE and v.latency >= LATENCY_LIMIT and not v.version_changed:
        return "Roll back"
    return "none"


def domain():
    from .study import Domain

    return Domain(
        "service", make_visits,
        lambda v: {"requests": float(v.requests), "errors": float(v.errors), "latency": float(v.latency), "version": float(v.version)},
        lambda v, drifted: _drifted(v) if drifted else v.outcome,
        ("Roll back", "Page on-call"),
        "the paging rate rises from 5% to 7.5%",
        depends_on_history=lambda v: v.rate >= ROLLBACK_RATE and v.rate < PAGE_RATE and v.latency >= LATENCY_LIMIT,
    )
