"""What kind of knowledge is this? A small rubric for steps and decisions.

Observability classes (what a screen recording can see):
  O1 single-step    one action whose reason is visible on screen
  O2 multi-step     meaning exists only across steps (read a value, switch window, paste it)
  O3 hidden rule    a visible choice among alternatives; the rule behind it is not stated
  O4 non-action     the choice was to do nothing; only dwell time shows it
  O5 cross-session  the reason lies in an earlier session (a change made days before)
  O6 unobservable   off-screen reasons: a chat, a call, memory (needs narration or an interview)

The class chooses the method: record it (O1, O2), pool decisions and fit a rule (O3-O5), or
ask the person (O6, and any decision the fitted rule gets wrong). The classes and the
tacit-vs-explicit framing build on Polanyi (1966) and Nonaka and Takeuchi (1995), see
docs/references.bib. These are heuristics, not measurements: they sort items for review.
"""

from __future__ import annotations

from dataclasses import dataclass

from .decisions import NONE, Decision
from .models import Step

METHOD = {
    "O1": "record", "O2": "record",
    "O3": "pool and fit a rule", "O4": "pool and fit a rule", "O5": "pool and fit a rule",
    "O6": "ask the person",
}


@dataclass
class Classified:
    observability: str
    tacit_score: int  # 0 (explicit) to 4 (needs the person to articulate it)
    reasons: list[str]

    @property
    def method(self) -> str:
        return METHOD[self.observability]


MULTI_STEP_ACTIONS = {"read", "select", "copy", "switch_app", "paste"}
CLASS_NAMES = {
    "O1": "single-step", "O2": "multi-step", "O3": "hidden rule", "O4": "non-action",
    "O5": "cross-session", "O6": "unobservable",
}


def classify_step(step: Step, threshold: float = 0.70) -> Classified:
    """O1 or O2 for a step the recording explains; O6 for one whose reason it could not recover.

    The class rests on evidence the pipeline measured, not on prose the model wrote: small local
    models fill `uncertainty_reason` on every step ("the action is confirmed"), so a non-empty
    reason says nothing. O6 means the calibrated confidence is below the review threshold or the
    model visibly hesitated between targets/values: what the screen shows does not settle why.
    """
    reasons: list[str] = []
    score = 0
    actions = set(step.action.lower().replace("_", " ").replace(" + ", "+").split("+"))
    if len(step.source_ids) > 1 or {a.replace(" ", "_") for a in actions} & MULTI_STEP_ACTIONS:
        cls = "O2"
        reasons.append("meaning depends on neighbouring steps")
    else:
        cls = "O1"
    hesitated = any(n.startswith("The model hesitated") for n in step.calibration_notes)
    if step.confidence < threshold or hesitated:
        cls, score = "O6", score + 2
        reasons.append("the reason for the action could not be recovered from the screen: ask the person")
    if step.review_note:  # a typed value that contradicts the screen, or input the software rejected
        score += 1
        reasons.append("something about this step looks off and is unexplained")
        if cls == "O1":
            cls = "O2"
            reasons.append("the contradiction only shows by comparing it with another moment in the recording")
    return Classified(cls, min(score, 4), reasons)


def annotate_playbook(pb) -> dict[str, int]:
    """Write each step's observability class and tacit score; returns how many steps fall in each class."""
    counts: dict[str, int] = {}
    for s in pb.steps:
        c = classify_step(s, pb.threshold)
        s.observability, s.tacit_score = c.observability, c.tacit_score
        counts[c.observability] = counts.get(c.observability, 0) + 1
    return counts


def classify_decision(d: Decision, rule_features: set[str] | None = None, rule_gets_it_right: bool | None = None) -> Classified:
    """O3/O4/O5 for a decision. `rule_features` are the features of a fitted rule (see induce.py)."""
    reasons: list[str] = []
    cls = "O4" if d.outcome == NONE else "O3"
    reasons.append("outcome was to do nothing; only the pause shows it" if cls == "O4" else "an action was chosen among alternatives")
    score = 2 if cls == "O4" else 1
    if rule_features and any(f.startswith(("changed_", "delta_")) for f in rule_features):
        cls, score = "O5", score + 1
        reasons.append("the fitted rule depends on a change made in an earlier session")
    if rule_gets_it_right is False:
        score += 1
        reasons.append("the fitted rule does not explain this decision: ask the person why")
    return Classified(cls, min(score, 4), reasons)
