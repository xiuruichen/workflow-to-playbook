"""Deterministic compilation of a session's raw capture into typed frames.

A frame is a bounded episode: either `active` (a run of input events in one window) or
`dwell` (the person stayed in a window for a while without acting). Dwell frames are the
only trace of a *non-action*: looking at a chart and deciding to leave it alone produces no
click or keystroke. Every frame points back at the events and keyframes it came from, so
anything derived from it can be audited. No model is involved, so the result is
reproducible and costs nothing.

The idea of compiling captured activity into evidence-linked, model-free episodes follows
Iyamu (2026), "Activity Frames" (see docs/references.bib). This is an adaptation for
decision capture, not a reimplementation of that system.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from .models import Manifest

FrameKind = Literal["active", "dwell"]
DWELL_MIN_S = 8.0  # a pause at least this long between events is a dwell


@dataclass
class Frame:
    kind: FrameKind
    t0: float
    t1: float
    app: str | None
    window: str | None
    event_indices: list[int] = field(default_factory=list)  # indices into manifest.events
    keyframe_ids: list[int] = field(default_factory=list)
    input_events: int = 0  # count of events other than window focus

    @property
    def duration(self) -> float:
        return self.t1 - self.t0

    def to_dict(self) -> dict:
        return asdict(self) | {"duration": round(self.duration, 3)}


def compile_frames(manifest: Manifest, dwell_min_s: float = DWELL_MIN_S) -> list[Frame]:
    """Split a session into active and dwell frames. Frames are ordered and do not overlap."""
    events = manifest.events
    frames: list[Frame] = []

    def keyframes_in(t0: float, t1: float) -> list[int]:
        return [k.id for k in manifest.keyframes if t0 <= k.t <= t1]

    def dwell_keyframes(t0: float, t1: float) -> list[int]:
        """The screen the pause started on (keyframes are only taken on change, so it may predate t0), then any later ones."""
        before = [k.id for k in manifest.keyframes if k.t < t0][-1:]
        return before + keyframes_in(t0, t1)

    def close_active(run: list[int]) -> None:
        if not run:
            return
        first, last = events[run[0]], events[run[-1]]
        frames.append(Frame("active", first.t, last.t, last.app, last.window, list(run), keyframes_in(first.t, last.t),
                            sum(1 for i in run if events[i].kind != "focus")))

    run: list[int] = []
    for i, ev in enumerate(events):
        if run:
            prev = events[run[-1]]
            gap = ev.t - prev.t
            if gap >= dwell_min_s:
                close_active(run)
                run = []
                frames.append(Frame("dwell", prev.t, ev.t, prev.app, prev.window, [], dwell_keyframes(prev.t, ev.t)))
        run.append(i)
    close_active(run)
    if run:  # trailing pause between the last event and the end of the recording
        last = events[run[-1]]
        if manifest.duration - last.t >= dwell_min_s:
            frames.append(Frame("dwell", last.t, manifest.duration, last.app, last.window, [],
                                dwell_keyframes(last.t, manifest.duration)))
    elif manifest.duration >= dwell_min_s:  # no events at all: the whole recording is one dwell
        frames.append(Frame("dwell", 0.0, manifest.duration, None, None, [], dwell_keyframes(0.0, manifest.duration)))
    return frames
