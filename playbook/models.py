"""Pydantic schemas shared by recorder, analyzer and generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EventKind = Literal["click", "double_click", "right_click", "drag", "scroll", "type", "key", "hotkey"]
Trigger = Literal["start", "end", "event_before", "event_after", "change", "heartbeat", "scene"]


class Event(BaseModel):
    """A single user input event. Coordinates are relative to the recorded monitor."""

    t: float  # seconds since recording start
    kind: EventKind
    x: int | None = None
    y: int | None = None
    x2: int | None = None  # drag end
    y2: int | None = None
    button: str | None = None
    text: str | None = None  # typed text, key name, or hotkey combo
    dx: int | None = None
    dy: int | None = None

    def describe(self) -> str:
        if self.kind in ("click", "double_click", "right_click"):
            return f"{self.kind.replace('_', ' ')} at ({self.x},{self.y})"
        if self.kind == "drag":
            return f"drag from ({self.x},{self.y}) to ({self.x2},{self.y2})"
        if self.kind == "scroll":
            direction = "down" if (self.dy or 0) < 0 else "up"
            return f"scroll {direction} x{abs(self.dy or 0)} at ({self.x},{self.y})"
        if self.kind == "type":
            return f"typed {json.dumps(self.text or '')}"
        if self.kind == "key":
            return f"pressed {self.text}"
        return f"shortcut {self.text}"


class Keyframe(BaseModel):
    id: int
    t: float
    path: str  # relative to the session directory
    trigger: Trigger
    event_indices: list[int] = Field(default_factory=list)


class Manifest(BaseModel):
    session_id: str
    source: Literal["live", "import"]
    video: str | None = None  # relative to session dir
    duration: float
    width: int  # coordinate space of events (monitor / source video pixels)
    height: int
    fps: float
    created: str
    keyframes: list[Keyframe] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)

    def save(self, session_dir: Path) -> None:
        (session_dir / "manifest.json").write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, session_dir: Path) -> "Manifest":
        return cls.model_validate_json((session_dir / "manifest.json").read_text(encoding="utf-8"))


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


class StepCandidate(BaseModel):
    """A fine-grained step proposed by the vision model for one window of keyframes."""

    id: str = ""
    action: str = "other"
    description: str
    target: str | None = None
    value: str | None = None
    app: str | None = None
    expected_result: str | None = None
    start_keyframe: int = 0  # keyframe ids
    end_keyframe: int = 0
    t_start: float = 0.0
    t_end: float = 0.0
    model_confidence: float = 0.5
    confidence: float = 0.5  # calibrated
    evidence: str = ""
    uncertainty_reason: str | None = None
    calibration_notes: list[str] = Field(default_factory=list)

    @field_validator("model_confidence", "confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return _clamp01(v)


class Step(BaseModel):
    index: int
    title: str
    description: str
    action: str = "other"
    target: str | None = None
    value: str | None = None
    app: str | None = None
    expected_result: str | None = None
    t_start: float
    t_end: float
    keyframe_before: str | None = None
    keyframe_after: str | None = None
    model_confidence: float
    confidence: float
    evidence: str = ""
    uncertainty_reason: str | None = None
    calibration_notes: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    needs_review: bool = False
    verified: bool = False

    @field_validator("model_confidence", "confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return _clamp01(v)


class InputVariable(BaseModel):
    name: str
    example: str | None = None
    description: str | None = None


class Playbook(BaseModel):
    title: str
    goal: str = ""
    summary: str = ""
    apps: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    inputs: list[InputVariable] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)

    session_id: str
    source: Literal["live", "import"]
    video: str | None = None
    duration: float
    model: str
    threshold: float
    generated_at: str
    notes: list[str] = Field(default_factory=list)  # pipeline-level warnings

    @property
    def review_steps(self) -> list[Step]:
        return [s for s in self.steps if s.needs_review and not s.verified]

    def refresh_flags(self) -> None:
        for s in self.steps:
            s.needs_review = s.confidence < self.threshold

    def save(self, session_dir: Path) -> None:
        (session_dir / "playbook.json").write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, session_dir: Path) -> "Playbook":
        return cls.model_validate_json((session_dir / "playbook.json").read_text(encoding="utf-8"))
